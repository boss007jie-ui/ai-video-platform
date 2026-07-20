from __future__ import annotations

import ast
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import traceback
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ai_video_platform.skills.video_generation import GenerationError, GenerationErrorCode, VideoGenerationInterface
from ai_video_platform.skills.video_generation.cli import main, run_cli
from tests.skills.video_generation.test_video_generation_interface import NOW, digest, generation_request


class VideoGenerationSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.interface = VideoGenerationInterface()

    def assert_code(self, request: dict[str, object], code: GenerationErrorCode) -> GenerationError:
        with self.assertRaises(GenerationError) as captured:
            self.interface.inspect_video_request(request, now=NOW)
        self.assertEqual(captured.exception.code, code)
        return captured.exception

    def test_approval_must_be_effective_and_match_package(self) -> None:
        request = generation_request()
        request.pop("approval_record")
        self.assert_code(request, GenerationErrorCode.APPROVAL_REQUIRED)
        for field, value in (("outcome", "revoked"), ("valid_until", "2026-07-20T11:59:59Z")):
            with self.subTest(field=field):
                request = generation_request()
                request["approval_record"][field] = value
                self.assert_code(request, GenerationErrorCode.APPROVAL_NOT_EFFECTIVE)
        request = generation_request()
        request["approval_record"]["subject_ref"]["digest"] = "sha256:" + "0" * 64
        self.assert_code(request, GenerationErrorCode.APPROVAL_SUBJECT_MISMATCH)

    def test_future_or_unauthorized_approval_boundary_is_rejected(self) -> None:
        request = generation_request()
        request["approval_record"]["decided_at"] = "2026-07-20T12:00:01Z"
        self.assert_code(request, GenerationErrorCode.APPROVAL_NOT_EFFECTIVE)

        request = generation_request()
        request["approval_record"]["authority"]["boundary_id"] = "qa-review"
        self.assert_code(request, GenerationErrorCode.APPROVAL_NOT_EFFECTIVE)

        raw_value = "Bearer " + "synthetic" + "G" * 24
        request = generation_request()
        request["approval_record"]["decided_at"] = raw_value
        error = self.assert_code(request, GenerationErrorCode.APPROVAL_NOT_EFFECTIVE)
        self.assertIsNone(error.__cause__)
        self.assertNotIn(raw_value, "".join(traceback.format_exception(error)))

    def test_budget_and_limits_fail_closed(self) -> None:
        request = generation_request()
        request["budget"]["estimated_cost_units"] = 21
        self.assert_code(request, GenerationErrorCode.BUDGET_EXCEEDED)
        for field in ("max_cost_units", "max_requests", "max_concurrency", "max_attempts", "timeout_seconds"):
            with self.subTest(field=field):
                request = generation_request()
                request["budget"][field] = 0
                self.assert_code(request, GenerationErrorCode.BUDGET_INVALID)

    def test_provider_binding_and_credential_reference_fail_closed_without_echo(self) -> None:
        request = generation_request()
        request["provider_binding"]["provider_id"] = ""
        self.assert_code(request, GenerationErrorCode.PROVIDER_BINDING_INVALID)
        raw_value = "sk" + "-" + "synthetic" + "A" * 24
        request = generation_request()
        request["provider_binding"]["credential_ref"] = raw_value
        error = self.assert_code(request, GenerationErrorCode.CREDENTIAL_REFERENCE_INVALID)
        self.assertNotIn(raw_value, str(error.to_dict()))
        request = generation_request()
        request["provider_binding"].pop("credential_ref")
        self.assert_code(request, GenerationErrorCode.CREDENTIAL_REFERENCE_INVALID)
        request = generation_request()
        request["provider_binding"]["api_key"] = "Bearer " + "synthetic" + "F" * 24
        self.assert_code(request, GenerationErrorCode.PROVIDER_BINDING_INVALID)

    def test_package_version_digest_and_provider_marker_fail_closed(self) -> None:
        request = generation_request()
        request["execution_package"]["schema_version"] = "9.0.0"
        self.assert_code(request, GenerationErrorCode.PACKAGE_VERSION_UNSUPPORTED)
        request = generation_request()
        request["execution_package"]["motion_plan"][0]["motion"]["kind"] = "tampered"
        self.assert_code(request, GenerationErrorCode.PACKAGE_TAMPERED)
        request = generation_request()
        package = request["execution_package"]
        package["planning_provider_submission_performed"] = True
        package["package_digest"] = digest({key: value for key, value in package.items() if key != "package_digest"})
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

    def test_outer_rehash_cannot_hide_nested_master_tampering(self) -> None:
        request = generation_request()
        package = request["execution_package"]
        package["storyboard_master"]["motion_plan"][0]["motion"]["kind"] = "tampered"
        package["package_digest"] = digest({key: value for key, value in package.items() if key != "package_digest"})
        request["approval_record"]["subject_ref"]["digest"] = package["package_digest"]
        self.assert_code(request, GenerationErrorCode.PACKAGE_TAMPERED)

    def test_recomputed_hashes_cannot_hide_malformed_source_or_task(self) -> None:
        request = generation_request()
        package = request["execution_package"]
        package["source"] = {}
        package["storyboard_master"]["source"] = {}
        package["package_id"] = "vep-" + digest({}).removeprefix("sha256:")[:20]
        master = package["storyboard_master"]
        master["master_digest"] = digest({key: value for key, value in master.items() if key != "master_digest"})
        package["package_digest"] = digest({key: value for key, value in package.items() if key != "package_digest"})
        request["approval_record"]["subject_ref"]["digest"] = package["package_digest"]
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

        request = generation_request()
        package = request["execution_package"]
        package["task_id"] = "different-task"
        package["package_digest"] = digest({key: value for key, value in package.items() if key != "package_digest"})
        request["approval_record"]["subject_ref"]["digest"] = package["package_digest"]
        self.assert_code(request, GenerationErrorCode.PACKAGE_TAMPERED)

        request = generation_request()
        package = request["execution_package"]
        master = package["storyboard_master"]
        master["shots"][0]["required_asset_roles"] = []
        master["master_digest"] = digest({key: value for key, value in master.items() if key != "master_digest"})
        package["package_digest"] = digest({key: value for key, value in package.items() if key != "package_digest"})
        request["approval_record"]["subject_ref"]["digest"] = package["package_digest"]
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

        request = generation_request()
        package = request["execution_package"]
        package["motion_plan"][0]["motion"] = {"kind": "different-copy"}
        package["package_digest"] = digest({key: value for key, value in package.items() if key != "package_digest"})
        request["approval_record"]["subject_ref"]["digest"] = package["package_digest"]
        self.assert_code(request, GenerationErrorCode.PACKAGE_TAMPERED)

        request = generation_request()
        package = request["execution_package"]
        master = package["storyboard_master"]
        master["shots"][0]["motion"] = {"kind": "different-shot-motion"}
        master["master_digest"] = digest({key: value for key, value in master.items() if key != "master_digest"})
        package["package_digest"] = digest({key: value for key, value in package.items() if key != "package_digest"})
        request["approval_record"]["subject_ref"]["digest"] = package["package_digest"]
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

        request = generation_request()
        package = request["execution_package"]
        master = package["storyboard_master"]
        master["shots"][0]["visual_anchor"] = {"angle": "different-shot-anchor"}
        master["master_digest"] = digest({key: value for key, value in master.items() if key != "master_digest"})
        package["package_digest"] = digest({key: value for key, value in package.items() if key != "package_digest"})
        request["approval_record"]["subject_ref"]["digest"] = package["package_digest"]
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

        request = generation_request()
        package = request["execution_package"]
        master = package["storyboard_master"]
        master["shots"].append({
            "shot_id": "shot-002", "sequence": 2, "required_asset_roles": ["hero"],
            "continuity_group": "product", "visual_anchor": {"angle": "side"},
            "motion": {"kind": "hold"},
        })
        master["asset_mapping"].append({
            "shot_id": "shot-002", "role": "hero", "asset_id": "asset-001",
            "uri": "memory://asset.png", "sha256": "sha256:" + "3" * 64,
        })
        master["motion_plan"].append({"shot_id": "shot-002", "sequence": 2, "motion": {"kind": "hold"}})
        package["asset_mapping"] = master["asset_mapping"]
        package["motion_plan"] = master["motion_plan"]
        master["master_digest"] = digest({key: value for key, value in master.items() if key != "master_digest"})
        package["package_digest"] = digest({key: value for key, value in package.items() if key != "package_digest"})
        request["approval_record"]["subject_ref"]["digest"] = package["package_digest"]
        self.assert_code(request, GenerationErrorCode.PACKAGE_INVALID)

    def test_sensitive_output_configuration_is_rejected_without_echo(self) -> None:
        raw_value = "sk" + "-" + "synthetic" + "C" * 24
        request = generation_request()
        request["output"]["api_key"] = raw_value
        error = self.assert_code(request, GenerationErrorCode.INVALID_INPUT)
        self.assertNotIn(raw_value, str(error.to_dict()))

        bearer = "Bearer " + "synthetic" + "D" * 24
        request = generation_request()
        request["output"]["note"] = bearer
        error = self.assert_code(request, GenerationErrorCode.INVALID_INPUT)
        self.assertNotIn(bearer, str(error.to_dict()))

        request = generation_request()
        request["budget"]["api_key"] = bearer
        error = self.assert_code(request, GenerationErrorCode.BUDGET_INVALID)
        self.assertNotIn(bearer, str(error.to_dict()))

    def test_redaction_covers_message_and_field_paths(self) -> None:
        bearer = "Bearer " + "synthetic" + "E" * 24
        error = GenerationError(GenerationErrorCode.PACKAGE_INVALID, bearer, field_paths=(bearer,))
        self.assertNotIn(bearer, str(error.to_dict()))
        self.assertNotIn(bearer, str(error))
        self.assertNotIn(bearer, str(error.args))

    def test_missing_idempotency_key_is_rejected(self) -> None:
        request = generation_request()
        request["idempotency_key"] = ""
        self.assert_code(request, GenerationErrorCode.IDEMPOTENCY_KEY_REQUIRED)

    def test_error_redacts_sensitive_nested_fields_and_values(self) -> None:
        raw_value = "sk" + "-" + "synthetic" + "B" * 24
        error = GenerationError(
            GenerationErrorCode.PACKAGE_INVALID,
            "Synthetic",
            details={"credential_ref": raw_value, "nested": {"safe": "visible", "message": raw_value}},
        )
        serialized = error.to_dict()
        self.assertNotIn(raw_value, str(serialized))
        self.assertEqual(serialized["details"]["credential_ref"], "[REDACTED]")
        self.assertEqual(serialized["details"]["nested"]["safe"], "visible")

    def test_generation_source_has_no_private_planning_import(self) -> None:
        root = SOURCE_ROOT / "ai_video_platform" / "skills" / "video_generation"
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn("storyboard_master_video_planning", node.module, path)
                if isinstance(node, ast.Import):
                    self.assertTrue(all("storyboard_master_video_planning" not in item.name for item in node.names), path)

    def test_cli_argument_and_validation_errors_are_machine_readable(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main([])
        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "INVALID_INPUT")
        request = generation_request()
        request["budget"]["estimated_cost_units"] = 99
        result = run_cli("inspect-video-request", request, now=NOW)
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["error"]["code"], "BUDGET_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
