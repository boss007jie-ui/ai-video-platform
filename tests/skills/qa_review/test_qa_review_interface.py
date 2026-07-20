from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.qa_review import QAError, QAErrorCode, ReviewOutcome, ReviewRequest, review
from ai_video_platform.skills.qa_review.cli import main as cli_main


def valid_request() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "criteria_version": "qa-criteria-v1",
        "evaluation_set_version": "qa-eval-v1",
        "command": "review-asset",
        "task_id": "task-qa-001",
        "execution_id": "exec-qa-001",
        "subject": {
            "artifact_id": "asset-001",
            "artifact_type": "image",
            "schema_version": "1.0.0",
            "revision": 2,
            "contract_valid": True,
            "assets": [{"role": "primary", "approved": True}],
            "product_id": "product-001",
            "sku_id": "sku-001",
            "continuity": {"hero_color": "navy"},
            "drift": {"layout": 0.02},
            "quality": {"sharpness": 0.92, "artifact_score": 0.04},
        },
        "criteria": {
            "expected_revision": 2,
            "required_asset_roles": ["primary"],
            "expected_product_id": "product-001",
            "expected_sku_id": "sku-001",
            "continuity": {"hero_color": "navy"},
            "max_drift": {"layout": 0.10},
            "quality": {
                "sharpness": {"min": 0.80},
                "artifact_score": {"max": 0.10},
            },
        },
        "context": {
            "product_context_revision": 3,
            "expected_product_context_revision": 3,
        },
        "evidence_refs": ["fixture:qa/pass-asset"],
    }


class QAReviewInterfaceTests(unittest.TestCase):
    def test_review_asset_passes_and_emits_only_owned_contracts(self) -> None:
        result = review(ReviewRequest.from_mapping(valid_request()))

        self.assertEqual(result.outcome, ReviewOutcome.PASS)
        self.assertEqual(result.review_decision["decision"], "approve")
        self.assertEqual(result.review_decision["subject_ref"]["artifact_id"], "asset-001")
        self.assertEqual(result.feedback_events, ())
        self.assertEqual(result.skill_execution_event["status"], "completed")
        self.assertEqual(result.human_review_package["schema_version"], "1.0.0")

    def test_contract_and_product_identity_failures_reject_with_feedback(self) -> None:
        request = deepcopy(valid_request())
        request["subject"]["contract_valid"] = False
        request["subject"]["product_id"] = "product-wrong"

        result = review(ReviewRequest.from_mapping(request))

        self.assertEqual(result.outcome, ReviewOutcome.FAIL)
        self.assertEqual(result.review_decision["decision"], "reject")
        self.assertEqual(len(result.feedback_events), 1)
        codes = {item["code"] for item in result.human_review_package["issues"]}
        self.assertEqual(codes, {"QA_CONTRACT_INVALID", "QA_PRODUCT_IDENTITY_MISMATCH"})

    def test_stale_subject_and_missing_quality_metric_need_human_review(self) -> None:
        request = deepcopy(valid_request())
        request["criteria"]["expected_revision"] = 3
        del request["subject"]["quality"]["sharpness"]

        result = review(ReviewRequest.from_mapping(request))

        self.assertEqual(result.outcome, ReviewOutcome.NEEDS_REVIEW)
        self.assertEqual(result.review_decision["decision"], "defer")
        codes = {item["code"] for item in result.human_review_package["issues"]}
        self.assertEqual(codes, {"QA_STALE_SUBJECT", "QA_QUALITY_EVIDENCE_MISSING"})

    def test_unsupported_request_major_version_is_a_stable_error(self) -> None:
        request = deepcopy(valid_request())
        request["schema_version"] = "2.0.0"

        with self.assertRaises(QAError) as captured:
            ReviewRequest.from_mapping(request)

        self.assertEqual(captured.exception.code, QAErrorCode.QA_SCHEMA_UNSUPPORTED)
        self.assertEqual(captured.exception.to_dict()["category"], "compatibility")

    def test_cli_writes_only_versioned_qa_outputs_and_returns_outcome_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            output_dir = root / "qa-output"
            request_path.write_text(json.dumps(valid_request()), encoding="utf-8")

            exit_code = cli_main(
                ["review-asset", "--request", str(request_path), "--output-dir", str(output_dir)]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                {path.name for path in output_dir.iterdir()},
                {
                    "feedback-events.json",
                    "human-review-package.json",
                    "result.json",
                    "review-decision.json",
                    "skill-execution-event.json",
                },
            )
            result = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["outcome"], "pass")
            self.assertEqual(result["interface_version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
