"""Deterministic, dependency-free RC evidence generation."""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from ai_video_platform.build_backend import VERSION as BUILD_VERSION, build_wheel
from ai_video_platform.contracts.business_registry import BUSINESS_ARTIFACT_IDS, BUSINESS_REGISTRY_VERSION
from ai_video_platform.contracts.compatibility import SemVer
from ai_video_platform.contracts.registry import FOUNDATION_CONTRACT_IDS, FOUNDATION_VERSION


_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_AUTHORIZATION = re.compile(r"^FTG-0-\d{8}-\d{3}$")
_REQUIRED_CHECKS = {
    "offline-tests",
    "reproducible-build",
    "ownership-scan",
    "secret-scan",
    "license-scan",
    "rollback-exercise",
}


@dataclass(frozen=True, slots=True)
class RepositoryState:
    head: str
    clean: bool


class RepositoryInspector(Protocol):
    def inspect(self, project_root: Path) -> RepositoryState: ...


class GitRepositoryInspector:
    def inspect(self, project_root: Path) -> RepositoryState:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project_root, check=True, capture_output=True, text=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=project_root, check=True, capture_output=True, text=True
        ).stdout
        return RepositoryState(head=head, clean=not status.strip())


def read_repository_head(project_root: Path) -> str:
    """Resolve HEAD without spawning a process, for offline test evidence."""
    dot_git = project_root / ".git"
    git_dir = dot_git
    if dot_git.is_file():
        prefix, value = dot_git.read_text(encoding="utf-8").strip().split(":", 1)
        if prefix != "gitdir":
            raise ValueError("Unsupported .git file")
        git_dir = (project_root / value.strip()).resolve()
    head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
    if not head.startswith("ref: "):
        return head
    reference = head.removeprefix("ref: ")
    candidates = [git_dir / reference]
    common_file = git_dir / "commondir"
    if common_file.exists():
        candidates.append((git_dir / common_file.read_text(encoding="ascii").strip()).resolve() / reference)
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="ascii").strip()
    raise ValueError(f"Unable to resolve repository HEAD reference: {reference}")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_release_bundle(
    *,
    project_root: Path,
    output_dir: Path,
    source_commit: str,
    version: str,
    authorization_id: str,
    test_evidence: Mapping[str, Mapping[str, str]],
    repository_inspector: RepositoryInspector | None = None,
) -> Mapping[str, bytes]:
    if not _COMMIT.fullmatch(source_commit):
        raise ValueError("source_commit must be a full lowercase Git SHA")
    SemVer.parse(version)
    if not _AUTHORIZATION.fullmatch(authorization_id):
        raise ValueError("A valid FTG-0 authorization reference is required")
    project = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if version != project["version"] or version != BUILD_VERSION:
        raise ValueError("Release version must match project and build metadata")
    dependencies = tuple(project.get("dependencies", ()))
    if dependencies:
        raise ValueError("requirements.lock and release evidence require reviewed dependency entries")
    state = (repository_inspector or GitRepositoryInspector()).inspect(project_root)
    if state.head != source_commit or not state.clean:
        raise ValueError("Release source_commit must be the clean repository HEAD")
    if set(test_evidence) != _REQUIRED_CHECKS or any(
        evidence.get("status") != "PASS" or not _DIGEST.fullmatch(evidence.get("digest", ""))
        for evidence in test_evidence.values()
    ):
        raise ValueError("All required release checks need PASS status and immutable evidence digests")

    with tempfile.TemporaryDirectory() as wheel_directory:
        wheel_name = build_wheel(wheel_directory)
        wheel_bytes = (Path(wheel_directory) / wheel_name).read_bytes()
    wheel_digest = "sha256:" + hashlib.sha256(wheel_bytes).hexdigest()

    manifest = {
        "schema_version": "1.0.0",
        "name": project["name"],
        "version": version,
        "source_commit": source_commit,
        "authorization_id": authorization_id,
        "foundation_schema_version": FOUNDATION_VERSION,
        "foundation_contract_count": len(FOUNDATION_CONTRACT_IDS),
        "business_registry_version": BUSINESS_REGISTRY_VERSION,
        "business_artifact_ids": list(BUSINESS_ARTIFACT_IDS),
        "tests": {name: dict(sorted(value.items())) for name, value in sorted(test_evidence.items())},
        "wheel_filename": wheel_name,
        "wheel_sha256": wheel_digest,
        "provider_smoke": "NOT_AUTHORIZED",
        "release_status": "RC_OFFLINE",
        "rollback_file": "rollback.json",
    }
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{project['name']}-{version}",
        "documentNamespace": f"https://ai-video-platform.invalid/spdx/{source_commit}",
        "packages": [
            {
                "SPDXID": "SPDXRef-Package-ai-video-platform",
                "name": project["name"],
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
            }
        ],
        "relationships": [],
    }
    license_inventory = {
        "schema_version": "1.0.0",
        "project_license": "NOASSERTION",
        "runtime_dependencies": [],
        "review_status": "NO_THIRD_PARTY_RUNTIME_DEPENDENCIES",
    }
    rollback = {
        "schema_version": "1.0.0",
        "source_commit": source_commit,
        "strategy": "revert-release-commit",
        "commands": [f"git revert {source_commit}"],
        "provider_side_effects": "NONE_OFFLINE_RC",
        "data_migration": "NONE",
        "verification": ["python tools/run_offline_tests.py"],
    }
    bundle = {
        "release-manifest.json": _json_bytes(manifest),
        "sbom.spdx.json": _json_bytes(sbom),
        "license-inventory.json": _json_bytes(license_inventory),
        "rollback.json": _json_bytes(rollback),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in bundle.items():
        (output_dir / filename).write_bytes(content)
    return bundle
