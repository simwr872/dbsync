import time
from collections import ChainMap
from typing import Any, Callable, Literal, Optional, Sequence, TypedDict

from .dbapi import Cursor

RowType = dict[str, Any]
MessageTableType = TypedDict("Table", {"modified": list[RowType], "deleted": list[RowType]})
MessageType = TypedDict("Message", {"timestamp": int, "table": dict[str, MessageTableType]})


def row_factory(cursor: Cursor, row: Sequence[Any]) -> RowType:
    """Convert database row to dictionary."""
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


class Table:
    def __init__(
        self,
        name: str,
        primary_columns: list[str],
        schema: dict[str, Any],
        extra_columns: list[str],
        param: str,
    ):
        self._name = name
        self._schema = schema
        self._primary_columns = primary_columns
        self._extra_columns = extra_columns
        self._all_columns = list(schema.keys())
        all_columns = ",".join(self._all_columns)
        extra_conditions = [f"{column}={param}" for column in extra_columns]
        timestamp_conditions = [f"{param}<timestamp", f"timestamp<{param}"]
        modified_conditions = " AND ".join(timestamp_conditions + extra_conditions)
        self._modified_query = f"SELECT {all_columns} FROM {name} WHERE {modified_conditions}"

        insert_columns = self._all_columns + ["timestamp"] + extra_columns
        params = ",".join([param] * len(insert_columns))
        insert_columns = ",".join(insert_columns)
        self._modify_query = f"INSERT OR REPLACE INTO {name}({insert_columns}) VALUES({params})"

        primary_conditions = [f"{column}={param}" for column in primary_columns]
        update_conditions = " AND ".join(primary_conditions + extra_conditions)
        self._delete_query = f"UPDATE {name} SET timestamp={param} WHERE {update_conditions}"

        deleted_columns = ",".join(primary_columns)
        self._deleted_query = f"SELECT {deleted_columns} FROM {name} WHERE {modified_conditions}"

    def graverob(self, cursor: Cursor, timestamp: int) -> None:
        cursor.execute(f"DELETE FROM {self._name} WHERE {timestamp}<timestamp AND timestamp<0")

    def synchronize(
        self,
        cursor: Cursor,
        last_timestamp: int,
        current_timestamp: int,
        table: MessageTableType,
        **extras: Any,
    ) -> MessageTableType:
        extra_values = [extras[column] for column in self._extra_columns]
        cursor.executemany(
            self._modify_query,
            [
                [row[column] for column in self._all_columns] + [current_timestamp] + extra_values
                for row in table["modified"]
            ],
        )
        cursor.executemany(
            self._delete_query,
            [
                [-current_timestamp]
                + [row[column] for column in self._primary_columns]
                + extra_values
                for row in table["deleted"]
            ],
        )
        cursor.execute(self._modified_query, [last_timestamp, current_timestamp] + extra_values)
        modified = [row_factory(cursor, row) for row in cursor.fetchall()]
        cursor.execute(self._deleted_query, [-current_timestamp, -last_timestamp] + extra_values)
        deleted = [row_factory(cursor, row) for row in cursor.fetchall()]
        return {
            "modified": modified,
            "deleted": deleted,
        }

    def schema_definition(self) -> dict[str, Any]:
        return {
            f"{self._name}_deleted": {
                "type": "object",
                "properties": {column: self._schema[column] for column in self._primary_columns},
                "additionalProperties": False,
                "required": self._primary_columns,
            },
            f"{self._name}_modified": {
                "type": "object",
                "properties": self._schema,
                "additionalProperties": False,
                "required": self._all_columns,
            },
        }


class Database:
    _paramstyles = {"qmark": "?", "format": "%s"}

    def __init__(
        self,
        extra_columns: Optional[list[str]] = None,
        counter: Callable[[], int] = lambda: int(time.time()),
        paramstyle: Literal["qmark", "format"] = "qmark",
    ):
        """
        `extra_columns` is a list of extra column names required to identify a row. `counter` is a
        function returning the next timestamp. `paramstyle` is the DBAPI module paramstyle.
        """
        self._param = self._paramstyles[paramstyle]
        if extra_columns is None:
            extra_columns = []
        self._extra_columns = extra_columns
        self._tables: dict[str, Table] = {}
        self._counter = counter

    def add_table(self, name: str, primary_columns: list[str], schema: dict[str, Any]) -> None:
        self._tables[name] = Table(name, primary_columns, schema, self._extra_columns, self._param)

    def graverob(self, cursor: Cursor, delta: int = 2592000) -> None:
        """Commit and rollback must be handled by caller."""
        timestamp = -self._counter() + delta
        for table in self._tables.values():
            table.graverob(cursor, timestamp)

    def synchronize(self, cursor: Cursor, request: MessageType, **extras: Any) -> MessageType:
        """
        Commit and rollback must be handled by caller. `extras` are keyword given by previosuly
        supplied `extra_columns` at Database initialization.
        """
        last_timestamp = request["timestamp"]
        current_timestamp = self._counter()
        response: MessageType = {"timestamp": current_timestamp, "table": {}}
        for name, table in request["table"].items():
            response["table"][name] = self._tables[name].synchronize(
                cursor, last_timestamp, current_timestamp, table, **extras
            )
        return response

    def schema(self) -> dict[str, Any]:
        """Returns the database's jsonschema."""
        return {
            "definitions": {
                **ChainMap(*[table.schema_definition() for table in self._tables.values()]),
                "table": {
                    "type": "object",
                    "properties": {
                        "modified": {"type": "array"},
                        "deleted": {"type": "array"},
                    },
                    "additionalProperties": False,
                    "required": ["modified", "deleted"],
                },
            },
            "type": "object",
            "properties": {
                "timestamp": {"type": "integer", "minimum": 0},
                "table": {
                    "type": "object",
                    "properties": {
                        name: {
                            "allOf": [
                                {"$ref": "#/definitions/table"},
                                {
                                    "properties": {
                                        "modified": {
                                            "items": {"$ref": f"#/definitions/{name}_modified"}
                                        },
                                        "deleted": {
                                            "items": {"$ref": f"#/definitions/{name}_deleted"}
                                        },
                                    }
                                },
                            ]
                        }
                        for name in self._tables.keys()
                    },
                    "additionalProperties": False,
                    "required": list(self._tables.keys()),
                },
            },
            "additionalProperties": False,
            "required": ["timestamp", "table"],
        }
