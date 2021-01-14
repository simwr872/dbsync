"""Partial stub for PEP 249 (Python Database API Specification v2.0)."""
from collections.abc import Sequence
from typing import Any, Optional, Protocol


class Cursor(Protocol):
    @property
    def description(
        self,
    ) -> Sequence[tuple[str, int, Optional[int], Optional[int], Optional[int], Optional[bool]]]:
        ...

    def execute(self, operation: str, parameters: Sequence[Any] = ...) -> Any:
        ...

    def executemany(self, operation: str, seq_of_parameters: Sequence[Sequence[Any]]) -> Any:
        ...

    def fetchall(self) -> Sequence[Sequence[Any]]:
        ...
