"""Public Video Generation interface; preflight only until adapter task."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from .preflight import GenerationPreflight


class VideoGenerationInterface:
    def __init__(self, *, adapter: object | None = None, ledger: object | None = None) -> None:
        self._preflight = GenerationPreflight()
        self._adapter = adapter
        self._ledger = ledger

    def inspect_video_request(
        self,
        request: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        return self._preflight.inspect(request, now=now)
