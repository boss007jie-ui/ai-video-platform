"""Run Codex-00 merge ownership and runtime-boundary checks."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.maintenance.codex.merge_guard import (  # noqa: E402
    MergeViolation,
    check_changed_paths,
    scan_runtime_boundaries,
)
from ai_video_platform.core.guards import SecretScanner  # noqa: E402


def _changed_paths(base: str) -> tuple[str, ...]:
    paths: set[str] = set()
    for arguments in (
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "diff", "--name-only"],
    ):
        completed = subprocess.run(
            arguments, cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
        )
        paths.update(line for line in completed.stdout.splitlines() if line)
    return tuple(sorted(paths))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workline", required=True)
    parser.add_argument("--base", default="3bf2c56")
    args = parser.parse_args(argv)
    secret_violations = tuple(
        MergeViolation("SECRET_MATERIAL_FORBIDDEN", finding.source, finding.summary)
        for finding in SecretScanner().scan_tree(PROJECT_ROOT)
    )
    violations = (
        *check_changed_paths(args.workline, _changed_paths(args.base)),
        *scan_runtime_boundaries(PROJECT_ROOT),
        *secret_violations,
    )
    for violation in violations:
        print(f"{violation.rule_id}\t{violation.path}\t{violation.detail}")
    if violations:
        print(f"ownership_violations={len(violations)}")
        return 1
    print("ownership_violations=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
