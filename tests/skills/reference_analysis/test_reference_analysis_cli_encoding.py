from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_video_platform.skills.reference_analysis import cli


class _UnicodeResult:
    def to_dict(self) -> dict[str, str]:
        return {"visible_text": "99¢ 中文"}


class ReferenceAnalysisCliEncodingTests(unittest.TestCase):
    def test_cli_result_is_machine_readable_on_a_gbk_console(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request_path = workspace / "request.json"
            request_path.write_text("{}", encoding="utf-8")
            raw_stdout = io.BytesIO()
            console = io.TextIOWrapper(raw_stdout, encoding="gbk")

            with patch.object(cli, "analyze_storyboard", return_value=_UnicodeResult()):
                with redirect_stdout(console):
                    code = cli.main([
                        "finalize-reference-analysis",
                        "--input",
                        str(request_path),
                        "--workspace",
                        str(workspace),
                    ])
            console.flush()

            self.assertEqual(code, 0)
            payload = json.loads(raw_stdout.getvalue().decode("gbk"))
            self.assertEqual(payload["visible_text"], "99¢ 中文")


if __name__ == "__main__":
    unittest.main()
