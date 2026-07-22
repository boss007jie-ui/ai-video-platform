from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = PROJECT_ROOT / "fixtures" / "integration" / "skill-rc-candidates-v1.json"
EXPECTED_SKILLS = {
    "product-knowledge",
    "viral-research-asset-collection",
    "reference-analysis",
    "storyboard",
    "product-image-panel-generation",
    "storyboard-master-video-planning",
    "video-generation",
    "qa-review",
}
REQUIRED_EVIDENCE = {
    "owned_tests",
    "contract_tests",
    "permission_tests",
    "security_tests",
    "coverage",
    "performance_budget",
    "sbom_license",
    "rollback",
}


def acceptance_verdict(candidate: dict[str, object], evidence_defaults: dict[str, str]) -> str:
    interface = candidate.get("public_interface")
    evidence = {**evidence_defaults, **candidate.get("evidence_overrides", {})}
    if not isinstance(interface, dict):
        return "REJECTED_INTERFACE_MISSING"
    if not interface.get("version") or not interface.get("commands"):
        return "REJECTED_INTERFACE_MISSING"
    if set(evidence) != REQUIRED_EVIDENCE:
        return "REJECTED_RC_BUNDLE_INCOMPLETE"
    if any(value != "pass" for value in evidence.values()):
        return "REJECTED_RC_EVIDENCE_FAILED"
    return "ACCEPTED_RC_OFFLINE"


class SkillRCAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_all_eight_public_interfaces_receive_independent_verdicts(self) -> None:
        candidates = self.fixture["candidates"]
        self.assertEqual({item["skill_id"] for item in candidates}, EXPECTED_SKILLS)
        self.assertEqual(len(candidates), 8)

        verdicts = {
            item["skill_id"]: acceptance_verdict(item, self.fixture["evidence_defaults"])
            for item in candidates
        }

        self.assertEqual(set(verdicts.values()), {"ACCEPTED_RC_OFFLINE"})
        self.assertEqual(set(verdicts), EXPECTED_SKILLS)

    def test_composition_pass_cannot_promote_a_failing_skill(self) -> None:
        candidate = deepcopy(self.fixture["candidates"][0])
        candidate["evidence_overrides"] = {"security_tests": "fail"}
        composition_result = "pass"

        verdict = acceptance_verdict(candidate, self.fixture["evidence_defaults"])

        self.assertEqual(composition_result, "pass")
        self.assertEqual(verdict, "REJECTED_RC_EVIDENCE_FAILED")
        self.assertNotEqual(verdict, "ACCEPTED_RC_OFFLINE")


if __name__ == "__main__":
    unittest.main()
