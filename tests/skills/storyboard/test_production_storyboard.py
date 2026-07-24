from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_video_platform.skills.storyboard import StoryboardError, derive_production_storyboard
from ai_video_platform.skills.storyboard.cli import run_cli_document
from ai_video_platform.contracts.serialization import thaw_json
from ai_video_platform.contracts.validation import validate_envelope

from .fixtures import envelope_document, product_context, task_spec


def reference_analysis(*, version: str = "1.0.0") -> dict:
    return {
        "artifact_type": "ReferenceStoryboardAnalysis",
        "contract_identity": "avp.contract.reference-storyboard-analysis",
        "schema_version": version,
        "artifact_id": "reference-analysis-synthetic-v1",
        "task_id": "task-storyboard-001",
        "producer": {"component_id": "reference-analysis"},
        "beats": [
            {
                "beat_id": "reference-beat-001",
                "start_ms": 0,
                "end_ms": 1200,
                "mechanism": "show-friction-fast",
                "emotion": "friction",
                "audience_psychology": "recognition",
                "conversion_role": "hook",
                "camera": "locked",
                "framing": "medium",
            },
            {
                "beat_id": "reference-beat-002",
                "start_ms": 1200,
                "end_ms": 3000,
                "mechanism": "demonstrate-proof",
                "emotion": "confidence",
                "audience_psychology": "belief",
                "conversion_role": "proof",
                "camera": "push-in",
                "framing": "close-up",
            },
            {
                "beat_id": "reference-beat-003",
                "start_ms": 3000,
                "end_ms": 4500,
                "mechanism": "resolve-with-cta",
                "emotion": "desire",
                "audience_psychology": "action",
                "conversion_role": "cta",
                "camera": "locked",
                "framing": "hero",
            },
        ],
        "protected_identity": {
            "people": ["Reference Person"],
            "brands": ["Reference Brand"],
            "products": ["Reference Product"],
            "packaging": ["Reference Red Box"],
        },
    }


def replication_pattern(*, version: str = "1.0.0") -> dict:
    return {
        "artifact_type": "ReplicationPattern",
        "contract_identity": "avp.contract.replication-pattern",
        "schema_version": version,
        "artifact_id": "replication-pattern-synthetic-v1",
        "task_id": "task-storyboard-001",
        "producer": {"component_id": "reference-analysis"},
        "patterns": [
            {"source_beat_id": "reference-beat-001", "mechanism": "compressed-hook"},
            {"source_beat_id": "reference-beat-002", "mechanism": "visible-proof"},
        ],
    }


def constraints() -> tuple[dict, dict]:
    creative = {
        "narrative_goal": "Turn setup friction into a confident product payoff",
        "character_id": "character-current-001",
        "character_state": "blue-jacket-presenter",
        "required_assets": ["asset-product-front", "asset-character-current"],
        "forbidden_assets": ["asset-reference-person", "asset-reference-brand"],
    }
    production = {
        "duration_ms": 4500,
        "aspect_ratio": "9:16",
        "packaging_state": "current-matte-blue-carton",
        "container_state": "sealed-then-open",
        "scale_constraints": {"product_to_hand": "true-to-current-product"},
        "approved_assets": ["asset-product-front", "asset-character-current"],
    }
    return creative, production


class ProductionStoryboardTests(unittest.TestCase):
    def derive(self, **overrides):
        creative, production = constraints()
        values = {
            "task_spec": task_spec(),
            "product_context": product_context(
                approved_asset_refs=["asset-product-front", "asset-character-current"]
            ),
            "creative_constraints": creative,
            "production_constraints": production,
            "reference_storyboard_analysis": reference_analysis(),
            "replication_pattern": replication_pattern(),
        }
        values.update(overrides)
        return derive_production_storyboard(**values)

    def test_reference_optional_derivation_publishes_two_canonical_artifacts(self) -> None:
        creative, production = constraints()
        result = self.derive(
            creative_constraints=creative,
            production_constraints={**production, "panel_count": 3},
            reference_storyboard_analysis=None,
            replication_pattern=None,
        )

        self.assertEqual(result.production_storyboard_plan["contract_identity"], "avp.contract.production-storyboard-plan")
        self.assertEqual(result.production_storyboard_panel_plan["contract_identity"], "avp.contract.production-storyboard-panel-plan")
        self.assertEqual(result.production_storyboard_plan["schema_version"], "1.0.0")
        self.assertEqual(result.production_storyboard_panel_plan["schema_version"], "1.0.0")
        self.assertEqual(
            result.production_storyboard_plan["producer"],
            {"agent": "skill", "component_id": "storyboard", "component_version": "1.2.0"},
        )
        self.assertEqual(
            result.production_storyboard_panel_plan["producer"],
            {"agent": "skill", "component_id": "storyboard", "component_version": "1.2.0"},
        )
        self.assertEqual(
            [item["contract_identity"] for item in result.production_storyboard_plan["source_provenance"]],
            ["avp.contract.task-spec", "avp.contract.product-context-bundle"],
        )
        self.assertEqual(result.production_storyboard_plan["reference_analysis_provenance"], ())
        self.assertEqual(len(result.production_storyboard_panel_plan["panels"]), 3)
        event = validate_envelope(result.execution_event).payload
        self.assertEqual(event.skill_id, "storyboard")
        self.assertEqual(
            tuple(event.output_contract_refs),
            (
                result.production_storyboard_plan["artifact_id"],
                result.production_storyboard_panel_plan["artifact_id"],
            ),
        )
        self.assertEqual(result.provider_calls, 0)
        self.assertEqual(result.network_calls, 0)

    def test_reference_mechanics_shape_order_without_copying_reference_identity(self) -> None:
        result = self.derive()
        plan = result.production_storyboard_plan
        panel_plan = result.production_storyboard_panel_plan

        self.assertEqual([item["shot_id"] for item in plan["ShotPlan"]], ["shot-001", "shot-002", "shot-003"])
        self.assertEqual([item["panel_id"] for item in panel_plan["panels"]], ["panel-001", "panel-002", "panel-003"])
        self.assertEqual([item["conversion_role"] for item in plan["ConversionArc"]], ["hook", "proof", "cta"])
        serialized = json.dumps(
            {
                "plan": thaw_json(plan),
                "panel_plan": thaw_json(panel_plan),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for protected_value in ("Reference Person", "Reference Brand", "Reference Product", "Reference Red Box"):
            self.assertNotIn(protected_value, serialized)
        self.assertIn("product-001", serialized)
        self.assertIn("character-current-001", serialized)

    def test_user_constraints_cannot_reintroduce_a_protected_reference_identity(self) -> None:
        creative, production = constraints()

        with self.assertRaises(StoryboardError) as captured:
            self.derive(
                creative_constraints={
                    **creative,
                    "narrative_goal": "Copy the Reference Brand payoff",
                },
                production_constraints=production,
            )

        self.assertEqual(captured.exception.code, "STORYBOARD_REFERENCE_IDENTITY_FORBIDDEN")

    def test_replication_pattern_is_independently_optional_and_reference_pacing_scales(self) -> None:
        replication_only = self.derive(reference_storyboard_analysis=None)
        self.assertEqual(
            [item["mechanism"] for item in replication_only.production_storyboard_plan["BeatPlan"]],
            ["compressed-hook", "visible-proof"],
        )

        creative, production = constraints()
        scaled = self.derive(
            creative_constraints=creative,
            production_constraints={**production, "duration_ms": 9000},
        )
        self.assertEqual(
            [(item["start_ms"], item["end_ms"]) for item in scaled.production_storyboard_plan["ShotPlan"]],
            [(0, 2400), (2400, 6000), (6000, 9000)],
        )

    def test_product_context_is_the_only_product_identity_source(self) -> None:
        result = self.derive(
            product_context=product_context(
                product_id="product-current-002",
                approved_asset_refs=["asset-product-front", "asset-character-current"],
            )
        )
        serialized = json.dumps(
            {
                "plan": thaw_json(result.production_storyboard_plan),
                "panel_plan": thaw_json(result.production_storyboard_panel_plan),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        self.assertIn("product-current-002", serialized)
        self.assertNotIn("Reference Product", serialized)
        self.assertNotIn('"product_id": "product-001"', serialized)

    def test_plan_and_panels_have_complete_production_fields_and_propagated_state(self) -> None:
        result = self.derive()
        plan = result.production_storyboard_plan

        for field in (
            "NarrativeArc",
            "ScenePlan",
            "BeatPlan",
            "ShotPlan",
            "EmotionArc",
            "AudiencePsychologyArc",
            "ConversionArc",
            "ContinuityBible",
            "ProductStateTimeline",
        ):
            self.assertIn(field, plan)

        required_panel_fields = {
            "panel_id",
            "shot_id",
            "start_ms",
            "end_ms",
            "frozen_moment",
            "camera",
            "framing",
            "character_state",
            "product_state",
            "packaging_state",
            "container_state",
            "emotion",
            "required_assets",
            "forbidden_assets",
            "scale_constraints",
            "continuity_references",
            "reference_analysis_provenance",
        }
        panels = result.production_storyboard_panel_plan["panels"]
        self.assertTrue(panels)
        for index, panel in enumerate(panels, start=1):
            self.assertTrue(required_panel_fields.issubset(panel))
            self.assertEqual(panel["product_state"]["product_id"], "product-001")
            self.assertEqual(panel["packaging_state"], "current-matte-blue-carton")
            self.assertEqual(panel["container_state"], "sealed-then-open")
            self.assertIn(f"continuity-product-{index:03d}", panel["continuity_references"])
        self.assertEqual(
            [item["product_id"] for item in plan["ProductStateTimeline"]],
            ["product-001", "product-001", "product-001"],
        )

    def test_stale_reference_versions_and_forbidden_assets_fail_closed(self) -> None:
        with self.assertRaises(StoryboardError) as stale:
            self.derive(reference_storyboard_analysis=reference_analysis(version="1.1.0"))
        self.assertEqual(stale.exception.code, "STORYBOARD_ARTIFACT_VERSION_UNSUPPORTED")

        with self.assertRaises(StoryboardError) as stale_pattern:
            self.derive(replication_pattern=replication_pattern(version="0.9.0"))
        self.assertEqual(stale_pattern.exception.code, "STORYBOARD_ARTIFACT_VERSION_UNSUPPORTED")

        creative, production = constraints()
        with self.assertRaises(StoryboardError) as forbidden:
            self.derive(
                creative_constraints={**creative, "required_assets": ["asset-reference-person"]},
                production_constraints=production,
            )
        self.assertEqual(forbidden.exception.code, "STORYBOARD_FORBIDDEN_ASSET")

        with self.assertRaises(StoryboardError) as self_approved:
            self.derive(
                product_context=product_context(),
                creative_constraints=creative,
                production_constraints=production,
            )
        self.assertEqual(self_approved.exception.code, "STORYBOARD_ASSET_NOT_APPROVED")

    def test_provider_shaped_capabilities_fail_before_any_artifact(self) -> None:
        creative, production = constraints()
        with self.assertRaises(StoryboardError) as captured:
            self.derive(
                creative_constraints={**creative, "provider_submission": {"model": "forbidden"}},
                production_constraints=production,
            )
        self.assertEqual(captured.exception.code, "STORYBOARD_CAPABILITY_FORBIDDEN")

    def test_cli_writes_exact_output_root_files_and_returns_machine_artifacts(self) -> None:
        creative, production = constraints()
        with TemporaryDirectory() as directory:
            exit_code, payload = run_cli_document(
                {
                    "command": "derive-production-panels",
                    "task_spec": envelope_document(task_spec()),
                    "product_context": envelope_document(
                        product_context(
                            approved_asset_refs=["asset-product-front", "asset-character-current"]
                        )
                    ),
                    "reference_storyboard_analysis": reference_analysis(),
                    "replication_pattern": replication_pattern(),
                    "creative_constraints": creative,
                    "production_constraints": production,
                    "output_root": directory,
                }
            )
            output = Path(directory) / "production_storyboard_plan"
            plan_path = output / "production_storyboard_plan.json"
            panel_path = output / "production_storyboard_panel_plan.json"

            self.assertEqual(exit_code, 0, payload)
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["metrics"], {"provider_calls": 0, "network_calls": 0})
            event = payload["execution_event"]["payload"]
            self.assertEqual(event["skill_id"], "storyboard")
            self.assertEqual(event["event_type"], "completed")
            self.assertEqual(
                tuple(event["output_contract_refs"]),
                (
                    payload["production_storyboard_plan"]["artifact_id"],
                    payload["production_storyboard_panel_plan"]["artifact_id"],
                ),
            )
            self.assertEqual(event["metrics"], {"provider_calls": 0, "network_calls": 0})
            self.assertEqual(json.loads(plan_path.read_text(encoding="utf-8")), payload["production_storyboard_plan"])
            self.assertEqual(json.loads(panel_path.read_text(encoding="utf-8")), payload["production_storyboard_panel_plan"])
            self.assertEqual(payload["output_files"], [str(plan_path), str(panel_path)])


if __name__ == "__main__":
    unittest.main()
