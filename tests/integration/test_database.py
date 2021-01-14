import sqlite3
import unittest
from typing import Callable
from unittest import TestCase

from sw.dbsync import Database


def counter() -> Callable[[], int]:
    value = 0

    def increment() -> int:
        nonlocal value
        value += 1
        return value

    return increment


class TestSQLite3(TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()

    def tearDown(self) -> None:
        self.cursor.close()
        self.connection.close()

    def test_graverob(self) -> None:
        self.cursor.execute("CREATE TABLE item(id INTEGER, timestamp INTEGER)")
        database = Database(counter=lambda: 5)
        database.add_table("item", ["id"], {"id": {"type": "integer"}})
        self.cursor.executemany(
            "INSERT INTO item VALUES(?,?)", [(1, 1), (2, 3), (3, -1), (4, -2), (5, -3), (6, -4)]
        )
        database.graverob(self.cursor, 2)

        self.assertEqual(
            self.cursor.execute("SELECT * FROM item ORDER BY id").fetchall(),
            [(1, 1), (2, 3), (5, -3), (6, -4)],
        )

    def test_basic(self) -> None:
        self.cursor.execute(
            "CREATE TABLE item(id INTEGER PRIMARY KEY, name TEXT, timestamp INTEGER)"
        )
        database = Database(counter=counter())
        database.add_table("item", ["id"], {"id": {"type": "integer"}, "name": {"type": "string"}})
        # Client A adds item 1
        self.assertEqual(
            database.synchronize(
                self.cursor,
                {
                    "timestamp": 0,
                    "table": {"item": {"modified": [{"id": 1, "name": "Item 1"}], "deleted": []}},
                },
            ),
            {
                "timestamp": 1,
                "table": {"item": {"modified": [], "deleted": []}},
            },
        )
        # Client B adds item 2
        self.assertEqual(
            database.synchronize(
                self.cursor,
                {
                    "timestamp": 0,
                    "table": {"item": {"modified": [{"id": 2, "name": "Item 2"}], "deleted": []}},
                },
            ),
            {
                "timestamp": 2,
                "table": {"item": {"modified": [{"id": 1, "name": "Item 1"}], "deleted": []}},
            },
        )
        # Client A deletes item 1
        self.assertEqual(
            database.synchronize(
                self.cursor,
                {
                    "timestamp": 1,
                    "table": {"item": {"modified": [], "deleted": [{"id": 1}]}},
                },
            ),
            {
                "timestamp": 3,
                "table": {"item": {"modified": [{"id": 2, "name": "Item 2"}], "deleted": []}},
            },
        )
        # Client B synchronizes
        self.assertEqual(
            database.synchronize(
                self.cursor,
                {
                    "timestamp": 2,
                    "table": {"item": {"modified": [], "deleted": []}},
                },
            ),
            {
                "timestamp": 4,
                "table": {"item": {"modified": [], "deleted": [{"id": 1}]}},
            },
        )

        self.assertEqual(
            self.cursor.execute("SELECT * FROM item ORDER BY id").fetchall(),
            [(1, "Item 1", -3), (2, "Item 2", 2)],
        )

    def test_complex(self) -> None:
        self.cursor.execute(
            "CREATE TABLE thread(id INTEGER, name TEXT, user INTEGER, timestamp INTEGER, PRIMARY KEY (id, user))"
        )
        self.cursor.execute(
            "CREATE TABLE post(id INTEGER, thread_id INTEGER, text TEXT, user INTEGER, timestamp INTEGER, PRIMARY KEY (id, thread_id, user))"
        )
        database = Database(extra_columns=["user"], counter=counter())
        database.add_table(
            "thread", ["id"], {"id": {"type": "integer"}, "name": {"type": "string"}}
        )
        database.add_table(
            "post",
            ["id", "thread_id"],
            {
                "id": {"type": "integer"},
                "thread_id": {"type": "integer"},
                "text": {"type": "string"},
            },
        )

        # User 1 client A adds thread 1 and post 1
        self.assertEqual(
            database.synchronize(
                self.cursor,
                {
                    "timestamp": 0,
                    "table": {
                        "thread": {"modified": [{"id": 1, "name": "Thread 1"}], "deleted": []},
                        "post": {
                            "modified": [{"id": 1, "thread_id": 1, "text": "Post 1"}],
                            "deleted": [],
                        },
                    },
                },
                user=1,
            ),
            {
                "timestamp": 1,
                "table": {
                    "thread": {"modified": [], "deleted": []},
                    "post": {"modified": [], "deleted": []},
                },
            },
        )
        # User 2 client A adds thread 1 and post 1
        self.assertEqual(
            database.synchronize(
                self.cursor,
                {
                    "timestamp": 0,
                    "table": {
                        "thread": {"modified": [{"id": 1, "name": "Thread 1"}], "deleted": []},
                        "post": {
                            "modified": [{"id": 1, "thread_id": 1, "text": "Post 1"}],
                            "deleted": [],
                        },
                    },
                },
                user=2,
            ),
            {
                "timestamp": 2,
                "table": {
                    "thread": {"modified": [], "deleted": []},
                    "post": {"modified": [], "deleted": []},
                },
            },
        )
        # User 1 client A edits post 1 and adds post 2
        self.assertEqual(
            database.synchronize(
                self.cursor,
                {
                    "timestamp": 1,
                    "table": {
                        "thread": {"modified": [], "deleted": []},
                        "post": {
                            "modified": [
                                {"id": 1, "thread_id": 1, "text": "Post 1 edit"},
                                {"id": 2, "thread_id": 1, "text": "Post 2"},
                            ],
                            "deleted": [],
                        },
                    },
                },
                user=1,
            ),
            {
                "timestamp": 3,
                "table": {
                    "thread": {"modified": [], "deleted": []},
                    "post": {"modified": [], "deleted": []},
                },
            },
        )
        # User 1 client B deletes thread 1
        self.assertEqual(
            database.synchronize(
                self.cursor,
                {
                    "timestamp": 0,
                    "table": {
                        "thread": {"modified": [], "deleted": [{"id": 1}]},
                        "post": {"modified": [], "deleted": []},
                    },
                },
                user=1,
            ),
            {
                "timestamp": 4,
                "table": {
                    "thread": {"modified": [], "deleted": []},
                    "post": {
                        "modified": [
                            {"id": 1, "thread_id": 1, "text": "Post 1 edit"},
                            {"id": 2, "thread_id": 1, "text": "Post 2"},
                        ],
                        "deleted": [],
                    },
                },
            },
        )

        self.assertEqual(
            self.cursor.execute("SELECT * FROM thread ORDER BY user,id").fetchall(),
            [(1, "Thread 1", 1, -4), (1, "Thread 1", 2, 2)],
        )
        self.assertEqual(
            self.cursor.execute("SELECT * FROM post ORDER BY user,id").fetchall(),
            [(1, 1, "Post 1 edit", 1, 3), (2, 1, "Post 2", 1, 3), (1, 1, "Post 1", 2, 2)],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
