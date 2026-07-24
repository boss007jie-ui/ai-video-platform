from __future__ import annotations

from copy import deepcopy
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


SHOT_REQUIRED_FIELDS = {
    "start_state",
    "action_path",
    "end_state",
    "emotion_transition",
    "audience_psychology",
    "conversion_function",
    "dialogue_or_voiceover",
    "subtitle",
    "sound_design",
    "transition",
    "required_assets",
    "forbidden_assets",
    "first_frame_role",
    "provider_reference_role",
}


def structured_plan() -> dict:
    shots = []
    beats = []
    for index in range(1, 6):
        start_ms = (index - 1) * 1000
        end_ms = index * 1000
        beat_id = f"B{index:02d}"
        shot_id = f"S{index:02d}"
        panel_id = f"{shot_id}-P01"
        beats.append({"beat_id": beat_id, "beat_sequence": index, "shot_ids": [shot_id]})
        shots.append(
            {
                "beat_id": beat_id,
                "shot_id": shot_id,
                "shot_sequence": index,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": 1000,
                "start_state": f"state-{index}-start",
                "action_path": f"action-{index}",
                "end_state": f"state-{index}-end",
                "emotion_transition": "interest-to-confidence",
                "audience_psychology": "belief",
                "conversion_function": "proof" if index < 5 else "cta",
                "dialogue_or_voiceover": "Approved synthetic narration",
                "subtitle": "Approved synthetic subtitle",
                "sound_design": "soft product cue",
                "transition": {"kind": "none", "duration_ms": 0, "timing_policy": "none"},
                "required_assets": ["asset-product-front", "asset-character-current"],
                "forbidden_assets": ["asset-reference-person", "asset-reference-brand"],
                "first_frame_role": "clean_panel" if index == 1 else "not_first_frame",
                "provider_reference_role": "product_reference",
                "camera_motion": {
                    "structured_definition": "locked camera",
                    "visual_annotation": {"label": "CAMERA", "line_style": "solid", "marker": "triangle", "color": "blue"},
                },
                "subject_motion": {
                    "structured_definition": "presenter lifts product",
                    "visual_annotation": {"label": "SUBJECT", "line_style": "dashed", "marker": "circle", "color": "blue"},
                },
                "active_product_id": "product-001",
                "active_sku_id": "sku-001",
                "visible_sku_ids": ["sku-001"],
                "forbidden_sku_ids": [],
                "product_state": "sealed",
                "package_state": "current-matte-blue-carton",
                "container_state": "sealed-then-open",
                "scale_constraints": {"product_to_hand": "true-to-current-product"},
                "character_state": "character-current-001",
                "wardrobe_state": "blue-jacket-presenter",
                "scene_state": "approved-studio",
                "panels": [
                    {
                        "beat_id": beat_id,
                        "shot_id": shot_id,
                        "panel_id": panel_id,
                        "panel_sequence": 1,
                        "panel_timing_mode": "TEMPORAL_SEGMENT",
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "duration_ms": 1000,
                    }
                ],
            }
        )
    return {
        "workflow_profile": "short_form",
        "total_duration_ms": 5000,
        "product_scope": {
            "mode": "single_sku",
            "active_product_id": "product-001",
            "active_sku_id": "sku-001",
            "allowed_sku_ids": ["sku-001"],
        },
        "beats": beats,
        "shots": shots,
    }


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

    def test_frozen_structured_plan_is_validated_and_projected(self) -> None:
        creative, production = constraints()
        result = self.derive(
            creative_constraints=creative,
            production_constraints={**production, "structured_plan": structured_plan()},
        )

        shots = result.production_storyboard_plan["ShotPlan"]
        panels = result.production_storyboard_panel_plan["panels"]
        self.assertEqual([shot["shot_id"] for shot in shots], ["S01", "S02", "S03", "S04", "S05"])
        self.assertTrue(all(SHOT_REQUIRED_FIELDS.issubset(shot) for shot in shots))
        self.assertEqual([panel["panel_id"] for panel in panels], [f"S{index:02d}-P01" for index in range(1, 6)])
        self.assertTrue(all(panel["panel_timing_mode"] == "TEMPORAL_SEGMENT" for panel in panels))
        self.assertEqual(result.production_storyboard_plan["total_duration_ms"], 5000)
        self.assertEqual(result.production_storyboard_plan["workflow_profile"], "short_form")

    def test_duration_mismatch_and_missing_shot_fail_closed(self) -> None:
        creative, production = constraints()
        mismatched = structured_plan()
        mismatched["total_duration_ms"] = 15000
        with self.assertRaises(StoryboardError) as duration:
            self.derive(
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": mismatched},
            )
        self.assertEqual(duration.exception.code, "STORYBOARD_DURATION_MISMATCH")

        missing = structured_plan()
        missing["shots"][4]["shot_id"] = "S06"
        missing["shots"][4]["panels"][0]["shot_id"] = "S06"
        missing["shots"][4]["panels"][0]["panel_id"] = "S06-P01"
        missing["beats"][4]["shot_ids"] = ["S06"]
        with self.assertRaises(StoryboardError) as sequence:
            self.derive(
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": missing},
            )
        self.assertEqual(sequence.exception.code, "STORYBOARD_SEQUENCE_INVALID")

    def test_panel_timing_modes_and_beat_binding_fail_closed(self) -> None:
        creative, production = constraints()
        gap = structured_plan()
        gap["shots"][0]["panels"][0]["end_ms"] = 900
        gap["shots"][0]["panels"][0]["duration_ms"] = 900
        with self.assertRaises(StoryboardError) as segment:
            self.derive(
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": gap},
            )
        self.assertEqual(segment.exception.code, "STORYBOARD_PANEL_TIMING_INVALID")

        anchor = structured_plan()
        anchor["shots"][0]["panels"][0] = {
            "beat_id": "B01",
            "shot_id": "S01",
            "panel_id": "S01-P01",
            "panel_sequence": 1,
            "panel_timing_mode": "KEYFRAME_ANCHOR",
            "anchor_time_ms": 500,
            "anchor_role": "opening_product_anchor",
            "duration_ms": 10,
        }
        with self.assertRaises(StoryboardError) as keyframe:
            self.derive(
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": anchor},
            )
        self.assertEqual(keyframe.exception.code, "STORYBOARD_PANEL_TIMING_INVALID")

        wrong_beat = structured_plan()
        wrong_beat["shots"][0]["panels"][0]["beat_id"] = "B02"
        with self.assertRaises(StoryboardError) as hierarchy:
            self.derive(
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": wrong_beat},
            )
        self.assertEqual(hierarchy.exception.code, "STORYBOARD_HIERARCHY_INVALID")

    def test_multisku_motion_and_required_semantics_fail_closed(self) -> None:
        creative, production = constraints()
        multiple = structured_plan()
        multiple["product_scope"] = {
            "mode": "multi_sku",
            "active_product_id": "product-001",
            "active_sku_id": "sku-001",
            "allowed_sku_ids": ["sku-001", "sku-002", "sku-003"],
        }
        multiple["shots"][2]["visible_sku_ids"] = ["sku-001", "sku-002", "sku-003"]
        with self.assertRaises(StoryboardError) as sku:
            self.derive(
                task_spec=task_spec(),
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": multiple},
            )
        self.assertEqual(sku.exception.code, "STORYBOARD_SKU_SCOPE_UNAUTHORIZED")

        motion = structured_plan()
        motion["shots"][0]["subject_motion"]["visual_annotation"] = deepcopy(
            motion["shots"][0]["camera_motion"]["visual_annotation"]
        )
        with self.assertRaises(StoryboardError) as arrows:
            self.derive(
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": motion},
            )
        self.assertEqual(arrows.exception.code, "STORYBOARD_MOTION_ANNOTATION_INVALID")

        incomplete = structured_plan()
        del incomplete["shots"][0]["sound_design"]
        with self.assertRaises(StoryboardError) as fields:
            self.derive(
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": incomplete},
            )
        self.assertEqual(fields.exception.code, "STORYBOARD_SHOT_FIELDS_MISSING")

    def test_every_required_shot_field_and_exact_timeline_are_enforced(self) -> None:
        creative, production = constraints()
        for field in sorted(SHOT_REQUIRED_FIELDS):
            with self.subTest(field=field):
                incomplete = structured_plan()
                del incomplete["shots"][0][field]
                with self.assertRaises(StoryboardError) as captured:
                    self.derive(
                        creative_constraints=creative,
                        production_constraints={**production, "structured_plan": incomplete},
                    )
                self.assertEqual(captured.exception.code, "STORYBOARD_SHOT_FIELDS_MISSING")
                self.assertIn(f"shots[0].{field}", captured.exception.field_paths)

        missing_time = structured_plan()
        del missing_time["shots"][0]["start_ms"]
        with self.assertRaises(StoryboardError) as captured:
            self.derive(
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": missing_time},
            )
        self.assertEqual(captured.exception.code, "STORYBOARD_DURATION_MISMATCH")

    def test_profile_transition_authorized_multisku_and_input_snapshot(self) -> None:
        creative, production = constraints()
        too_short = structured_plan()
        too_short["shots"] = too_short["shots"][:4]
        too_short["beats"] = too_short["beats"][:4]
        too_short["total_duration_ms"] = 4000
        with self.assertRaises(StoryboardError) as profile:
            self.derive(
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": too_short},
            )
        self.assertEqual(profile.exception.code, "STORYBOARD_PROFILE_INVALID")

        overlap = structured_plan()
        overlap["shots"][0]["transition"] = {
            "kind": "cross_dissolve",
            "duration_ms": 200,
            "timing_policy": "overlap_next_shot",
        }
        with self.assertRaises(StoryboardError) as transition:
            self.derive(
                creative_constraints=creative,
                production_constraints={**production, "structured_plan": overlap},
            )
        self.assertEqual(transition.exception.code, "STORYBOARD_TRANSITION_INVALID")

        authorized = structured_plan()
        authorized["product_scope"] = {
            "mode": "multi_sku",
            "active_product_id": "product-001",
            "active_sku_id": "sku-001",
            "allowed_sku_ids": ["sku-001", "sku-002"],
        }
        authorized["shots"][2]["visible_sku_ids"] = ["sku-001", "sku-002"]
        original = deepcopy(authorized)
        result = self.derive(
            task_spec=task_spec(
                constraints={
                    "storyboard": {
                        "product_scope": {
                            "mode": "multi_sku",
                            "allowed_sku_ids": ["sku-001", "sku-002"],
                        }
                    }
                }
            ),
            creative_constraints=creative,
            production_constraints={**production, "structured_plan": authorized},
        )
        self.assertEqual(result.production_storyboard_plan["product_scope"]["mode"], "multi_sku")
        self.assertEqual(authorized, original)

    def test_valid_keyframe_anchor_is_projected_without_duration(self) -> None:
        creative, production = constraints()
        anchored = structured_plan()
        anchored["shots"][0]["panels"][0] = {
            "beat_id": "B01",
            "shot_id": "S01",
            "panel_id": "S01-P01",
            "panel_sequence": 1,
            "panel_timing_mode": "KEYFRAME_ANCHOR",
            "anchor_time_ms": 0,
            "anchor_role": "clean_opening_frame",
        }
        result = self.derive(
            creative_constraints=creative,
            production_constraints={**production, "structured_plan": anchored},
        )
        panel = result.production_storyboard_panel_plan["panels"][0]
        self.assertEqual(panel["panel_timing_mode"], "KEYFRAME_ANCHOR")
        self.assertEqual(panel["anchor_role"], "clean_opening_frame")
        self.assertNotIn("duration_ms", panel)

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
