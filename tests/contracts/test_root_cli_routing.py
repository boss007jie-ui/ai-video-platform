from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_video_platform.cli.root.dispatcher import dispatch, main


class RootCliRoutingTests(unittest.TestCase):
    def test_owner_routes_forward_only_to_public_cli(self) -> None:
        cases = (
            ("storyboard", "derive-production-panels", "ai_video_platform.skills.storyboard.cli", ["derive-production-panels", "--input", "request.json"]),
            ("image-panel", "generate-panels", "ai_video_platform.skills.product_image_panel_generation.cli", ["generate-panels", "--input", "request.json", "--adapter", "fake"]),
        )
        for namespace, command, module, expected in cases:
            with self.subTest(command=command), patch(f"{module}.main", return_value=7) as owner_main:
                result = dispatch(namespace, command, expected[1:])
                self.assertEqual(result, 7)
                owner_main.assert_called_once_with(expected)

        with patch("ai_video_platform.skills.storyboard_master_video_planning.cli.main", return_value=8) as owner_main:
            self.assertEqual(dispatch("video-planning", "build-storyboard-master", ["--input", "request.json"]), 8)
            owner_main.assert_called_once_with(["build-storyboard-master", "request.json"])

        with patch("ai_video_platform.skills.qa_review.cli.main", return_value=9) as owner_main:
            args = ["--input", "request.json", "--output-dir", "qa-out"]
            self.assertEqual(dispatch("qa-review", "review-artifact", args), 9)
            owner_main.assert_called_once_with(["review-artifact", "--request", "request.json", "--output-dir", "qa-out"])

    def test_video_generation_defaults_to_rejecting_without_network(self) -> None:
        from tests.skills.video_generation.test_video_generation_interface import generation_request

        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request = generation_request()
            request["approval_record"]["valid_until"] = "2099-01-01T00:00:00Z"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            exit_code = main(["video-generation", "run", "--input", str(request_path)])
            self.assertEqual(exit_code, 2)

    def test_video_generation_fake_route_is_available_offline(self) -> None:
        from tests.skills.video_generation.test_video_generation_interface import generation_request

        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request = generation_request()
            request["approval_record"]["valid_until"] = "2099-01-01T00:00:00Z"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            exit_code = main(["video-generation", "run", "--input", str(request_path), "--adapter", "fake"])
            self.assertEqual(exit_code, 0)

    def test_root_module_dispatches_video_generation(self) -> None:
        from ai_video_platform.cli import main as root_main

        self.assertIs(root_main, main)


if __name__ == "__main__":
    unittest.main()
