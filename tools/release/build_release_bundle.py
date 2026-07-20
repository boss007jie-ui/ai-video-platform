"""CLI for deterministic release evidence generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ai_video_platform.maintenance.codex.release import build_release_bundle  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--test-evidence", required=True, help="Path to a JSON object of test summaries")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    evidence = json.loads(Path(args.test_evidence).read_text(encoding="utf-8"))
    if not isinstance(evidence, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in evidence.items()):
        raise ValueError("test evidence must be a JSON object of string values")
    build_release_bundle(
        project_root=PROJECT_ROOT,
        output_dir=Path(args.output),
        source_commit=args.source_commit,
        version=args.version,
        authorization_id=args.authorization_id,
        test_evidence=evidence,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
