"""Partial stub for PEP 249 (Python Database API Specification v2.0)."""
from collections.abc import Sequence
from typing import Any, Optional, Protocol


class Module(Protocol):
    paramstyle: str


class Cursor(Protocol):
    @property
    def description(
        self,
    ) -> Sequence[tuple[str, int, Optional[int], Optional[int], Optional[int], Optional[bool]]]:
        ...

    def close(self) -> None:
        ...

    def execute(self, operation: str, parameters: Sequence[Any] = ...) -> Any:
        ...

    def executemany(self, operation: str, seq_of_parameters: Sequence[Sequence[Any]]) -> Any:
        ...

    def fetchall(self) -> Sequence[Sequence[Any]]:
        ...


class Connection(Protocol):
    def cursor(self) -> Cursor:
        ...

    def close(self) -> None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...
