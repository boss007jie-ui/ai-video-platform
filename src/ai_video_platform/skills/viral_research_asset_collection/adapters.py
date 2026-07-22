"""Offline fake and fail-closed Provider/Download adapters."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Iterable, Mapping

from .errors import ErrorCode, SkillError


class FakeCollectionAdapter:
    def __init__(
        self,
        rows: Iterable[Mapping[str, object]],
        *,
        failures: int = 0,
        terminal_error: Exception | None = None,
        iterator_error: Exception | None = None,
    ) -> None:
        self._rows = tuple(deepcopy(dict(row)) for row in rows)
        self._failures = failures
        self._terminal_error = terminal_error
        self._iterator_error = iterator_error
        self.attempt_count = 0

    def fetch(self, query: str, *, limit: int, timeout_seconds: int):
        del query, timeout_seconds
        self.attempt_count += 1
        if self.attempt_count <= self._failures:
            raise SkillError(ErrorCode.PROVIDER_FAILURE, "Synthetic offline failure", retryable=True)
        if self._terminal_error is not None:
            raise self._terminal_error
        rows = tuple(deepcopy(row) for row in self._rows[:limit])
        if self._iterator_error is None:
            return rows

        def failing_rows():
            yield from rows
            raise self._iterator_error

        return failing_rows()


class RejectingCollectionAdapter:
    def __init__(self) -> None:
        self.attempt_count = 0

    def fetch(self, query: str, *, limit: int, timeout_seconds: int):
        del query, limit, timeout_seconds
        self.attempt_count += 1
        raise SkillError(
            ErrorCode.PROVIDER_FORBIDDEN,
            "A real collection Provider requires separate authorization",
        )


class FakeDownloadAdapter:
    def __init__(self) -> None:
        self.attempt_count = 0

    def download(self, candidate: Mapping[str, object]) -> dict[str, object]:
        self.attempt_count += 1
        source_id = str(candidate.get("source_id", ""))
        payload = f"offline-fake:{source_id}".encode("utf-8")
        return {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "byte_size": len(payload),
            "method": "OFFLINE_FAKE",
        }


class RejectingDownloadAdapter:
    def __init__(self) -> None:
        self.attempt_count = 0

    def download(self, candidate: Mapping[str, object]):
        del candidate
        self.attempt_count += 1
        raise SkillError(
            ErrorCode.DOWNLOAD_FORBIDDEN,
            "Media download requires separate authorization",
        )
