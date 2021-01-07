import sqlite3
import time
import typing
from collections import ChainMap
from typing import Any, Callable, ModuleType, Optional, Sequence, TypedDict

from .dbapi import Connection, Cursor, Module

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
        cursor.execute(self._delete_query, [-current_timestamp, -last_timestamp] + extra_values)
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
    def __init__(
        self,
        extra_columns: Optional[list[str]] = None,
        module: ModuleType = sqlite3,
        counter: Callable[[], int] = lambda: int(time.time()),
    ):
        # No type checkers support modules as implementations of protocols (January 2021)
        paramstyle = typing.cast(Module, module).paramstyle
        paramstyles = {"qmark": "?", "format": "%s"}
        if paramstyle not in paramstyles:
            raise ValueError(
                f"Provided module's global attribute paramstyle must be one of {paramstyles.keys()}"
            )
        self._param = paramstyle
        if extra_columns is None:
            extra_columns = []
        self._extra_columns = extra_columns
        self._tables: dict[str, Table] = {}
        self._counter = counter

    def add_table(self, name: str, primary_columns: list[str], schema: dict[str, Any]):
        self._tables[name] = Table(name, primary_columns, schema, self._extra_columns, self._param)

    def synchronize(
        self, connection: Connection, request: MessageType, **extras: Any
    ) -> MessageType:
        last_timestamp = max(0, request["timestamp"])
        current_timestamp = self._counter()
        cursor = connection.cursor()
        response: MessageType = {"timestamp": current_timestamp, "table": {}}
        try:
            for name, table in request["table"].items():
                response["table"][name] = self._tables[name].synchronize(
                    cursor, last_timestamp, current_timestamp, table, **extras
                )
            connection.commit()
        except Exception as exception:
            connection.rollback()
            raise exception
        finally:
            cursor.close()
        return response

    def schema(self) -> dict[str, Any]:
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
