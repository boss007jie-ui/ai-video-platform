from __future__ import annotations

import json
from pathlib import Path
import unittest

from ai_video_platform.contracts.business_registry import BUSINESS_REGISTRY
from ai_video_platform.skills.qa_review import ReviewOutcome, ReviewRequest, review
from tests.skills.qa_review.test_storyboard_artifact_chain import valid_composition_request


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALIGNMENT_FIXTURE = PROJECT_ROOT / "fixtures" / "integration" / "storyboard-artifact-chain-v1.json"


class StoryboardArtifactChainIntegrationTests(unittest.TestCase):
    def test_synthetic_no_provider_chain_matches_registered_identities_and_passes_qa(self) -> None:
        alignment = json.loads(ALIGNMENT_FIXTURE.read_text(encoding="utf-8"))
        request = valid_composition_request()
        reviewed_types = {
            artifact["artifact_type"]
            for artifact in request["subject"]["artifacts"]
        }
        reviewed_names = {BUSINESS_REGISTRY[artifact_type].name for artifact_type in reviewed_types}

        result = review(ReviewRequest.from_mapping(request))

        self.assertEqual(reviewed_names, set(alignment["registered_artifacts"]))
        self.assertEqual(result.outcome, ReviewOutcome.PASS)
        self.assertEqual(alignment["provider_calls"], 0)
        self.assertNotIn("approval_record", result.human_review_package)
        self.assertNotIn("production_storyboard_plan", result.human_review_package)
        self.assertNotIn("video_execution_package", result.human_review_package)


if __name__ == "__main__":
    unittest.main()
