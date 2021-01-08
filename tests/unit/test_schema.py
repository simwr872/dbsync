import json
import unittest
from pathlib import Path
from unittest import TestCase

from sw.dbsync import Database


class TestSchema(TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.database = Database()

    def tearDown(self) -> None:
        name = self.id().split(".")[-1]
        with open(Path(__file__).parent.joinpath(f"fixtures/{name}.json")) as file:
            self.assertEqual(self.database.schema(), json.load(file))

    def test_basic(self) -> None:
        self.database.add_table(
            "item", ["id"], {"id": {"type": "integer"}, "name": {"type": "string"}}
        )

    def test_complex(self) -> None:
        self.database.add_table(
            "thread", ["id"], {"id": {"type": "integer"}, "name": {"type": "string"}}
        )
        self.database.add_table(
            "post",
            ["id", "thread_id"],
            {
                "id": {"type": "integer"},
                "thread_id": {"type": "integer"},
                "text": {"type": "string"},
            },
        )


if __name__ == "__main__":
    unittest.main()
