from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_video_platform.cli.root import ROOT_CLI_TARGETS
from ai_video_platform.contracts.business_registry import BUSINESS_REGISTRY


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "fixtures" / "integration" / "storyboard-artifact-chain-v1.json"


class StoryboardArtifactChainTests(unittest.TestCase):
    def test_root_cli_declares_the_eight_public_chain_targets(self) -> None:
        self.assertEqual(
            [(target.namespace, target.command) for target in ROOT_CLI_TARGETS],
            [
                ("viral-research", "search"),
                ("reference-analysis", "analyze-storyboard"),
                ("storyboard", "derive-production-panels"),
                ("image-panel", "generate-panels"),
                ("video-planning", "build-storyboard-master"),
                ("video-generation", "run"),
                ("qa-review", "review-artifact"),
                ("qa-review", "review-composition"),
            ],
        )
        targets = {(target.namespace, target.command): target for target in ROOT_CLI_TARGETS}
        routed = {
            ("storyboard", "derive-production-panels"),
            ("image-panel", "generate-panels"),
            ("video-planning", "build-storyboard-master"),
            ("video-generation", "run"),
            ("qa-review", "review-artifact"),
            ("qa-review", "review-composition"),
        }
        self.assertEqual({key for key, target in targets.items() if target.status == "ROUTED"}, routed)

        reference_analysis = targets[("reference-analysis", "analyze-storyboard")]
        self.assertEqual(
            reference_analysis.required_inputs,
            ("selected-reference-video", "video-metadata", "analysis-config"),
        )
        self.assertEqual(reference_analysis.optional_inputs, ("ViralResearchPack", "popular-comments"))

        video_generation = targets[("video-generation", "run")]
        self.assertIn("ReferenceRoleMapping", video_generation.required_inputs)
        self.assertEqual(video_generation.optional_inputs, ())

    def test_synthetic_fixture_matches_registry_and_production_order(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        expected_chain = [
            "ViralResearchPack",
            "ReferenceStoryboardAnalysis",
            "ProductionStoryboardPlan",
            "ProductionStoryboardPanelPlan",
            "ProductionStoryboardPanelSet",
            "VideoGenerationStoryboardMaster",
            "ShotMotionPlan",
            "VideoExecutionPackage",
            "VideoResult",
        ]
        registered_chain_names = {
            definition.name
            for definition in BUSINESS_REGISTRY.values()
            if definition.name
            not in {"ViralResearchRequest", "ViralResearchPack", "ReferenceCollectionManifest"}
        }

        self.assertEqual(fixture["authorization_id"], "FTG-0-20260720-001")
        self.assertEqual(fixture["fixture_kind"], "VERSIONED_SYNTHETIC_NO_PROVIDER")
        self.assertEqual(fixture["production_chain"], expected_chain)
        self.assertEqual(set(fixture["registered_artifacts"]), registered_chain_names)

    def test_fixture_prevents_board_and_contact_sheet_first_frame_misuse(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        first_frame = fixture["examples"]["FirstFrameMapping"]
        role_mapping = fixture["examples"]["ReferenceRoleMapping"]

        self.assertEqual(first_frame["asset_role"], "clean_full_frame_panel")
        self.assertEqual(
            first_frame["asset_ref"],
            "asset://production-panel/panel-001-clean",
        )
        self.assertNotIn(first_frame["asset_ref"], fixture["forbidden_first_frame_refs"])
        self.assertEqual(
            role_mapping["reference_analysis_board"]["role"],
            "global_structure_reference",
        )
        self.assertFalse(role_mapping["reference_analysis_board"]["provider_execution_input"])


if __name__ == "__main__":
    unittest.main()
