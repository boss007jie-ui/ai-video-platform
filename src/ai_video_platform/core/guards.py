"""Fail-closed offline, legacy-path, secret, and Provider guardrails."""

from __future__ import annotations

import os
import re
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Callable, Iterable

from ai_video_platform.contracts.errors import ContractError, ErrorCategory, ErrorCode


def _network_forbidden(*args, **kwargs):
    del args, kwargs
    raise ContractError(
        ErrorCode.NETWORK_ACCESS_FORBIDDEN,
        ErrorCategory.AUTHORIZATION,
        "Network access is disabled for the IR-1/IR-2 offline baseline",
    )


class NetworkDenyGuard:
    """Temporarily blocks the standard-library DNS and socket entry points."""

    def __init__(self) -> None:
        self._originals: list[tuple[object, str, Callable]] = []

    def __enter__(self) -> "NetworkDenyGuard":
        targets = [
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (socket.socket, "connect"),
            (socket.socket, "connect_ex"),
            (socket.socket, "send"),
            (socket.socket, "sendall"),
            (socket.socket, "sendto"),
            (subprocess, "Popen"),
        ]
        if hasattr(socket.socket, "sendmsg"):
            targets.append((socket.socket, "sendmsg"))
        for owner, attribute in targets:
            original = getattr(owner, attribute)
            self._originals.append((owner, attribute, original))
            setattr(owner, attribute, _network_forbidden)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        for owner, attribute, original in reversed(self._originals):
            setattr(owner, attribute, original)
        self._originals.clear()


class LegacyPathGuard:
    """Rejects paths under the registered legacy source root without reading it."""

    def __init__(self, legacy_root: Path | None = None) -> None:
        self.legacy_root = legacy_root or (Path.home() / "Desktop" / ("04-" + "视频"))

    @staticmethod
    def _normalized(path: Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    def assert_allowed(self, path: Path | str) -> Path:
        candidate = Path(path)
        root_text = self._normalized(self.legacy_root)
        candidate_text = self._normalized(candidate)
        try:
            common = os.path.commonpath((root_text, candidate_text))
        except ValueError:
            common = ""
        if common == root_text:
            raise ContractError(
                ErrorCode.LEGACY_PATH_ACCESS_FORBIDDEN,
                ErrorCategory.AUTHORIZATION,
                "Legacy Source Library access requires separate Direct Verification authorization",
                field_paths=("path",),
            )
        return candidate


@dataclass(frozen=True, slots=True)
class SecretFinding:
    source: str
    rule_id: str
    line_number: int
    summary: str


class SecretScanner:
    """Small dependency-free scanner for common credential material."""

    _RULES = (
        ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
        ("token-prefix", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b")),
        (
            "assigned-secret",
            re.compile(
                r"(?i)\b(?:api[_-]?key|access[_-]?token|secret[_-]?key|authorization)\b"
                r"\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{20,}"
            ),
        ),
    )
    _TEXT_SUFFIXES = {".py", ".json", ".toml", ".md", ".txt", ".yaml", ".yml"}
    _SKIP_PARTS = {".git", "__pycache__", ".venv", "venv", "build", "dist"}

    def scan_text(self, text: str, *, source: str) -> tuple[SecretFinding, ...]:
        findings: list[SecretFinding] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            for rule_id, pattern in self._RULES:
                if pattern.search(line):
                    findings.append(
                        SecretFinding(
                            source=source,
                            rule_id=rule_id,
                            line_number=line_number,
                            summary=f"Potential secret matched rule {rule_id}; value redacted",
                        )
                    )
        return tuple(findings)

    def scan_tree(self, root: Path) -> tuple[SecretFinding, ...]:
        findings: list[SecretFinding] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in self._TEXT_SUFFIXES:
                continue
            if any(part in self._SKIP_PARTS for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            findings.extend(self.scan_text(text, source=path.relative_to(root).as_posix()))
        return tuple(findings)


class RejectingProviderAdapter:
    """Provider-shaped boundary that always rejects before network activity."""

    def __init__(self) -> None:
        self.attempt_count = 0

    def submit(self, request: object) -> None:
        del request
        self.attempt_count += 1
        _network_forbidden()
