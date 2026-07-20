"""Strict SemVer parsing and foundation reader/writer compatibility."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


@dataclass(frozen=True, order=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build: str | None = None

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        match = _SEMVER.fullmatch(value)
        if match is None:
            raise ValueError(f"Invalid SemVer: {value}")
        major, minor, patch, prerelease, build = match.groups()
        if prerelease is not None:
            for identifier in prerelease.split("."):
                if identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0"):
                    raise ValueError(f"Invalid SemVer: {value}")
        return cls(int(major), int(minor), int(patch), prerelease, build)


class Compatibility(str, Enum):
    COMPATIBLE = "compatible"
    READER_TOO_OLD = "reader_too_old"
    MAJOR_MISMATCH = "major_mismatch"


def evaluate_compatibility(reader_version: str, writer_version: str) -> Compatibility:
    reader = SemVer.parse(reader_version)
    writer = SemVer.parse(writer_version)
    if reader.major != writer.major:
        return Compatibility.MAJOR_MISMATCH
    if reader.minor < writer.minor:
        return Compatibility.READER_TOO_OLD
    return Compatibility.COMPATIBLE
