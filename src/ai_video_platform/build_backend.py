"""Minimal offline build backend for the dependency-free foundation package."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import pathlib
import zipfile


NAME = "ai_video_platform"
VERSION = "0.1.0"
DIST_INFO = f"{NAME}-{VERSION}.dist-info"


def _metadata() -> bytes:
    return (
        "Metadata-Version: 2.3\n"
        "Name: ai-video-platform\n"
        f"Version: {VERSION}\n"
        "Requires-Python: >=3.12\n"
        "Summary: Clean-room AI Video Platform foundation\n"
    ).encode("utf-8")


def _wheel() -> bytes:
    return (
        "Wheel-Version: 1.0\n"
        "Generator: ai_video_platform.build_backend\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("utf-8")


def _record_value(data: bytes) -> tuple[str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
    return f"sha256={digest}", str(len(data))


def _project_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def _wheel_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    package_root = _project_root() / "src" / NAME
    for path in sorted(package_root.rglob("*.py")):
        archive_path = path.relative_to(package_root.parent).as_posix()
        files[archive_path] = path.read_bytes()
    files[f"{DIST_INFO}/METADATA"] = _metadata()
    files[f"{DIST_INFO}/WHEEL"] = _wheel()
    return files


def build_wheel(wheel_directory: str, config_settings=None, metadata_directory=None) -> str:
    del config_settings, metadata_directory
    filename = f"{NAME}-{VERSION}-py3-none-any.whl"
    output = pathlib.Path(wheel_directory) / filename
    files = _wheel_files()
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for archive_path, data in files.items():
        digest, size = _record_value(data)
        writer.writerow((archive_path, digest, size))
    writer.writerow((f"{DIST_INFO}/RECORD", "", ""))
    files[f"{DIST_INFO}/RECORD"] = record.getvalue().encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for archive_path, data in files.items():
            info = zipfile.ZipInfo(archive_path, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            wheel.writestr(info, data)
    return filename


def build_sdist(sdist_directory: str, config_settings=None) -> str:
    raise RuntimeError("Source distribution is not part of the IR-1/IR-2 baseline")


def get_requires_for_build_wheel(config_settings=None) -> list[str]:
    del config_settings
    return []


def prepare_metadata_for_build_wheel(metadata_directory: str, config_settings=None) -> str:
    del config_settings
    destination = pathlib.Path(metadata_directory) / DIST_INFO
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "METADATA").write_bytes(_metadata())
    (destination / "WHEEL").write_bytes(_wheel())
    return DIST_INFO
