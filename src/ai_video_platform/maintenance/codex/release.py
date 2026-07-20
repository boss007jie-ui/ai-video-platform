"""Deterministic, dependency-free RC evidence generation."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Mapping

from ai_video_platform.contracts.business_registry import BUSINESS_ARTIFACT_IDS, BUSINESS_REGISTRY_VERSION
from ai_video_platform.contracts.compatibility import SemVer
from ai_video_platform.contracts.registry import FOUNDATION_CONTRACT_IDS, FOUNDATION_VERSION


_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_release_bundle(
    *,
    project_root: Path,
    output_dir: Path,
    source_commit: str,
    version: str,
    authorization_id: str,
    test_evidence: Mapping[str, str],
) -> Mapping[str, bytes]:
    if not _COMMIT.fullmatch(source_commit):
        raise ValueError("source_commit must be a full lowercase Git SHA")
    SemVer.parse(version)
    if not authorization_id.startswith("FTG-"):
        raise ValueError("Fast Track authorization reference is required")
    project = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = tuple(project.get("dependencies", ()))
    if dependencies:
        raise ValueError("requirements.lock and release evidence require reviewed dependency entries")

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
        "tests": dict(sorted(test_evidence.items())),
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
        "commands": ["git revert <release-commit>"],
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
