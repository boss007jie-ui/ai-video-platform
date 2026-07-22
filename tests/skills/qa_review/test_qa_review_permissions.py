from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.contracts.errors import ContractError, ErrorCode
from ai_video_platform.contracts.validation import validate_payload
from ai_video_platform.skills.qa_review import QAError, QAErrorCode, ReviewArtifacts, ReviewRequest, review
from ai_video_platform.skills.qa_review.cli import QAOutputWriter
from tests.skills.qa_review.test_qa_review_interface import valid_request


class QAReviewPermissionTests(unittest.TestCase):
    def test_public_result_has_only_qa_owned_outputs(self) -> None:
        names = {item.name for item in fields(ReviewArtifacts)}

        self.assertEqual(
            names,
            {
                "outcome", "review_decision", "feedback_events",
                "human_review_package", "skill_execution_event",
            },
        )
        self.assertNotIn("approval_record", names)
        self.assertNotIn("product_context_bundle", names)
        self.assertNotIn("product_review_context", names)

    def test_shared_contract_guard_rejects_qa_approval_publication(self) -> None:
        payload = {
            "approval_id": "approval-forbidden",
            "subject_ref": {"artifact_id": "asset-001"},
            "approval_type": "release",
            "outcome": "approved",
            "authority": {"actor": "qa-review"},
            "decided_at": "2026-07-20T00:00:00Z",
            "decision_ref": "review-exec-qa-001",
        }

        with self.assertRaises(ContractError) as captured:
            validate_payload(
                "avp.contract.approval-record",
                payload,
                producer_component_id="qa-review",
                producer_agent="skill",
            )

        self.assertEqual(captured.exception.code, ErrorCode.APPROVAL_AUTHORITY_INVALID)

    def test_reference_analysis_semantic_comparison_criterion_is_forbidden(self) -> None:
        request = deepcopy(valid_request())
        request["criteria"]["semantic_reference_comparison"] = {"target": "reference-001"}

        with self.assertRaises(QAError) as captured:
            review(ReviewRequest.from_mapping(request))

        self.assertEqual(captured.exception.code, QAErrorCode.QA_CRITERION_FORBIDDEN)

    def test_review_feedback_cannot_write_product_context(self) -> None:
        request = deepcopy(valid_request())
        request["subject"]["contract_valid"] = False

        result = review(ReviewRequest.from_mapping(request))

        feedback = result.feedback_events[0]
        self.assertEqual(feedback["source_skill_id"], "qa-review")
        self.assertNotIn("product_context_bundle", feedback)
        self.assertNotIn("product_review_context", feedback)
        self.assertNotIn("approval_id", feedback)

    def test_output_writer_rejects_product_library_target_before_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "AI Video Product Library" / "qa-output"

            with self.assertRaises(QAError) as captured:
                QAOutputWriter(target)

            self.assertEqual(captured.exception.code, QAErrorCode.QA_OUTPUT_PATH_FORBIDDEN)
            self.assertFalse(target.exists())
            self.assertNotIn("approval-record.json", QAOutputWriter.ALLOWED_FILENAMES)
            self.assertNotIn("product-context-bundle.json", QAOutputWriter.ALLOWED_FILENAMES)
            self.assertNotIn("product-review-context.json", QAOutputWriter.ALLOWED_FILENAMES)

    def test_public_qa_error_redacts_sensitive_detail_keys(self) -> None:
        error = QAError(
            QAErrorCode.QA_INPUT_INVALID,
            "validation",
            "Synthetic validation failure",
            details={"credential_reference": "must-not-appear", "safe_detail": "visible"},
        )

        document = error.to_dict()

        self.assertEqual(document["details"]["credential_reference"], "[REDACTED]")
        self.assertEqual(document["details"]["safe_detail"], "visible")
        self.assertNotIn("must-not-appear", str(document))


if __name__ == "__main__":
    unittest.main()
