from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from ai_video_platform.build_backend import build_wheel


class ReleaseReproducibilityTests(unittest.TestCase):
    def test_offline_wheel_build_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_name = build_wheel(first)
            second_name = build_wheel(second)
            first_bytes = (Path(first) / first_name).read_bytes()
            second_bytes = (Path(second) / second_name).read_bytes()

            self.assertEqual(hashlib.sha256(first_bytes).digest(), hashlib.sha256(second_bytes).digest())
            with zipfile.ZipFile(Path(first) / first_name) as wheel:
                names = set(wheel.namelist())
            self.assertIn("ai_video_platform/contracts/registry.py", names)
            self.assertIn("ai_video_platform-0.1.0.dist-info/RECORD", names)


if __name__ == "__main__":
    unittest.main()
