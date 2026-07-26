from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_video_platform.cli.root.dispatcher import dispatch, main


class RootCliRoutingTests(unittest.TestCase):
    def test_seedance_routes_forward_to_owner_public_clis(self) -> None:
        image_cases = (
            "generate-product-image",
            "generate-panel",
            "inspect-generation-request",
        )
        for command in image_cases:
            with self.subTest(command=command), patch(
                "ai_video_platform.skills.product_image_panel_generation.cli.main", return_value=11
            ) as owner_main:
                result = dispatch("seedance-nz-image", command, ["--input", "request.json", "--adapter", "seedance-nz-image"])
            self.assertEqual(result, 11)
            owner_main.assert_called_once_with([command, "--input", "request.json", "--adapter", "seedance-nz-image"])

        with patch("ai_video_platform.skills.video_generation.cli.main", return_value=12) as owner_main:
            result = dispatch("seedance-nz-video", "execute-seedance-nz", ["request.json", "--output-dir", "out"])
        self.assertEqual(result, 12)
        owner_main.assert_called_once_with(["execute-seedance-nz", "request.json", "--output-dir", "out"])

    def test_seedance_video_rejects_unsupported_command(self) -> None:
        self.assertEqual(main(["seedance-nz-video", "run", "request.json"]), 2)

    def test_seedance_image_missing_key_fails_closed_before_transport(self) -> None:
        from ai_video_platform.skills.product_image_panel_generation import generation_request_to_mapping, model_profile_to_mapping
        from tests.skills.product_image_panel_generation._support import make_request, profile

        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"SEEDANCE_NZ_API_KEY": ""}):
            request_path = Path(directory) / "request.json"
            request_path.write_text(
                json.dumps({"request": generation_request_to_mapping(make_request()), "model_profile": model_profile_to_mapping(profile())}),
                encoding="utf-8",
            )
            exit_code = main([
                "seedance-nz-image",
                "generate-product-image",
                "--input",
                str(request_path),
                "--adapter",
                "seedance-nz-image",
            ])
        self.assertEqual(exit_code, 2)

    def test_seedance_image_default_remains_rejecting(self) -> None:
        from ai_video_platform.skills.product_image_panel_generation import generation_request_to_mapping, model_profile_to_mapping
        from tests.skills.product_image_panel_generation._support import make_request, profile

        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(
                json.dumps({"request": generation_request_to_mapping(make_request()), "model_profile": model_profile_to_mapping(profile())}),
                encoding="utf-8",
            )
            exit_code = main(["seedance-nz-image", "generate-product-image", "--input", str(request_path)])
        self.assertEqual(exit_code, 2)

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

    def test_viral_research_routes_to_owner_with_fake_fixture(self) -> None:
        fixture_path = (
            Path(__file__).parents[1]
            / "skills"
            / "viral_research_asset_collection"
            / "fixtures"
            / "viral-research-pack-v1.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            provider_fixture_path = Path(directory) / "provider-fixture.json"
            request_path.write_text(json.dumps(fixture["request"]), encoding="utf-8")
            provider_fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            with patch(
                "ai_video_platform.skills.viral_research_asset_collection.cli.main",
                return_value=0,
            ) as owner_main:
                result = dispatch(
                    "viral-research",
                    "search",
                    [
                        "--input",
                        str(request_path),
                        "--fixture",
                        str(provider_fixture_path),
                    ],
                )
            self.assertEqual(result, 0)
            owner_main.assert_called_once_with(
                [
                    "research-viral",
                    "--input",
                    str(request_path),
                    "--provider",
                    "fake",
                    "--provider-fixture",
                    str(provider_fixture_path),
                ]
            )

    def test_reference_analysis_routes_to_owner(self) -> None:
        fixture_path = (
            Path(__file__).parents[1]
            / "skills"
            / "reference_analysis"
            / "fixtures"
            / "storyboard-analysis-v1.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            workspace_path = Path(directory) / "workspace"
            workspace_path.mkdir()
            request_path.write_text(json.dumps(fixture["request"]), encoding="utf-8")
            with patch(
                "ai_video_platform.skills.reference_analysis.cli.main",
                return_value=0,
            ) as owner_main:
                result = dispatch(
                    "reference-analysis",
                    "analyze-storyboard",
                    [
                        "--input",
                        str(request_path),
                        "--workspace",
                        str(workspace_path),
                    ],
                )
            self.assertEqual(result, 0)
            owner_main.assert_called_once_with(
                [
                    "analyze-storyboard",
                    "--input",
                    str(request_path),
                    "--workspace",
                    str(workspace_path),
                ]
            )
            self.assertNotIn("--output", owner_main.call_args.args[0])

    def test_viral_research_search_defaults_to_rejecting_without_fixture(self) -> None:
        fixture_path = (
            Path(__file__).parents[1]
            / "skills"
            / "viral_research_asset_collection"
            / "fixtures"
            / "viral-research-pack-v1.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(json.dumps(fixture["request"]), encoding="utf-8")
            exit_code = main(["viral-research", "search", "--input", str(request_path)])
            self.assertNotEqual(exit_code, 0)

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
