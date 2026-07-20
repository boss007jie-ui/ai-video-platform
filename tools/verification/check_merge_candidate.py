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
    check_changed_paths,
    scan_runtime_boundaries,
)


def _changed_paths(base: str) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in completed.stdout.splitlines() if line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workline", required=True)
    parser.add_argument("--base", default="3bf2c56")
    args = parser.parse_args(argv)
    violations = (
        *check_changed_paths(args.workline, _changed_paths(args.base)),
        *scan_runtime_boundaries(PROJECT_ROOT),
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
