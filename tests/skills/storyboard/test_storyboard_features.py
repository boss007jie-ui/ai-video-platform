from __future__ import annotations

import unittest

from ai_video_platform.skills.storyboard import (
    StoryboardError,
    StoryboardRequest,
    StoryboardService,
    decompose_raw_script,
)
from ai_video_platform.skills.storyboard.cli import run_cli_document

from .fixtures import envelope_document, fixed_clock, product_context, task_context, task_spec


class StoryboardFeatureTests(unittest.TestCase):
    def request(self, plan):
        return StoryboardRequest(
            command="create-storyboard",
            task_spec=task_spec(),
            task_context=task_context(),
            product_context=product_context(),
            plan=plan,
            idempotency_key="feature-case",
            expected_version=0,
        )

    def test_raw_script_entry_point_decomposes_hierarchy_and_plans_six_panels(self) -> None:
        result = StoryboardService(clock=fixed_clock).execute(
            self.request(
                {
                    "raw_script": (
                        "Scene 1: A customer struggles with the old workflow. "
                        "They discover the matte blue product.\n"
                        "Scene 2: The customer uses it and gains confidence."
                    ),
                    "planning_options": {"panel_count": 6},
                }
            )
        )

        story = result.artifact.story
        panels = [
            panel
            for scene in story["scenes"]
            for beat in scene["beats"]
            for shot in beat["shots"]
            for panel in shot["panels"]
        ]
        self.assertEqual(len(panels), 6)
        self.assertEqual(len(story["scenes"]), 2)
        self.assertTrue(all(panel["panel_type"] for panel in panels))
        self.assertTrue(all(panel["layout"] for panel in panels))
        self.assertTrue(all(panel["key_moment"] for panel in panels))
        self.assertIn("continuity_archive", story)

    def test_raw_script_panel_count_is_bounded_to_six_through_twelve(self) -> None:
        service = StoryboardService(clock=fixed_clock)
        with self.assertRaises(StoryboardError) as captured:
            service.execute(
                self.request(
                    {
                        "raw_script": "A short product moment.",
                        "planning_options": {"panel_count": 5},
                    }
                )
            )
        self.assertEqual(captured.exception.code, "STORYBOARD_PLANNING_INVALID")

    def test_raw_script_sentences_become_distinct_key_moments(self) -> None:
        result = StoryboardService(clock=fixed_clock).execute(
            self.request(
                {
                    "raw_script": "First product moment. Second product moment.",
                    "planning_options": {"panel_count": 6},
                }
            )
        )
        key_moments = {
            panel["key_moment"]
            for beat in result.artifact.story["scenes"][0]["beats"]
            for shot in beat["shots"]
            for panel in shot["panels"]
        }
        self.assertEqual(
            key_moments,
            {"First product moment.", "Second product moment."},
        )

    def test_planning_options_must_be_an_object(self) -> None:
        with self.assertRaises(StoryboardError) as captured:
            StoryboardService(clock=fixed_clock).execute(
                self.request(
                    {
                        "raw_script": "A short product moment.",
                        "planning_options": [],
                    }
                )
            )
        self.assertEqual(captured.exception.code, "STORYBOARD_PLANNING_INVALID")

    def test_scene_count_cannot_exceed_requested_panel_capacity(self) -> None:
        raw_script = "\n".join(
            f"Scene {index}: Product moment {index}."
            for index in range(1, 8)
        )
        with self.assertRaises(StoryboardError) as captured:
            StoryboardService(clock=fixed_clock).execute(
                self.request(
                    {
                        "raw_script": raw_script,
                        "planning_options": {"panel_count": 6},
                    }
                )
            )
        self.assertEqual(captured.exception.code, "STORYBOARD_PLANNING_INVALID")

    def test_public_helper_and_cli_script_command_support_twelve_panels(self) -> None:
        plan = decompose_raw_script(
            "Scene 1: Show the product. Scene 2: Resolve with confidence.",
            product_id="product-001",
            visual_constraints={"required_color": "matte blue", "logo_visibility": "front"},
            planning_options={"panel_count": 12},
        )
        self.assertEqual(plan["planning"]["panel_count"], 12)

        exit_code, payload = run_cli_document(
            {
                "command": "create-storyboard-from-script",
                "task_spec": envelope_document(task_spec()),
                "task_context": envelope_document(task_context()),
                "product_context": envelope_document(product_context()),
                "raw_script": "Scene 1: Show the product. Scene 2: Resolve with confidence.",
                "planning_options": {"panel_count": 12},
                "idempotency_key": "cli-script-entry",
                "expected_version": 0,
            },
            service=StoryboardService(clock=fixed_clock),
        )
        panels = [
            panel
            for scene in payload["artifact"]["story"]["scenes"]
            for beat in scene["beats"]
            for shot in beat["shots"]
            for panel in shot["panels"]
        ]
        self.assertEqual((exit_code, len(panels)), (0, 12))

    def test_typed_continuity_archive_preserves_generic_state_and_relationships(self) -> None:
        plan = {
            "title": "Typed continuity",
            "product_id": "product-001",
            "scenes": [
                {
                    "scene_id": "scene-001",
                    "setting": "studio",
                    "emotion": "confidence",
                    "emotion_score": 20,
                    "beats": [
                        {
                            "beat_id": "beat-001",
                            "action": "Hold product",
                            "shots": [
                                {
                                    "shot_id": "shot-001",
                                    "framing": "medium",
                                    "panels": [
                                        {
                                            "panel_id": "panel-001",
                                            "prompt": "Actor holds the matte blue product, logo front",
                                            "product_id": "product-001",
                                            "continuity": {"actor_outfit": "blue-jacket"},
                                            "continuity_entities": ["character-001", "product-001"],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "continuity_archive": {
                "entities": [
                    {
                        "entity_id": "character-001",
                        "entity_type": "character",
                        "name": "Actor",
                        "appearance": "adult presenter",
                        "outfit": "blue-jacket",
                        "relationships": [{"type": "uses", "entity_id": "product-001"}],
                    },
                    {
                        "entity_id": "product-001",
                        "entity_type": "product",
                        "product_id": "product-001",
                        "sku_id": "sku-001",
                        "appearance": "matte blue",
                        "orientation": "front",
                        "relationships": [],
                    },
                ]
            },
        }

        result = StoryboardService(clock=fixed_clock).execute(self.request(plan))
        archive = result.artifact.story["continuity_archive"]
        self.assertEqual({entity["entity_type"] for entity in archive["entities"]}, {"character", "product"})
        self.assertEqual(result.artifact.story["scenes"][0]["beats"][0]["shots"][0]["panels"][0]["continuity_entities"], ("character-001", "product-001"))

    def test_typed_continuity_archive_rejects_missing_type_fields(self) -> None:
        plan = {
            "raw_script": "Scene 1: Show the product.",
            "continuity_archive": {
                "entities": [
                    {
                        "entity_id": "character-001",
                        "entity_type": "character",
                        "name": "Actor",
                        "relationships": [],
                    }
                ],
            },
        }
        with self.assertRaises(StoryboardError) as captured:
            StoryboardService(clock=fixed_clock).execute(self.request(plan))
        self.assertEqual(
            captured.exception.code,
            "STORYBOARD_CONTINUITY_ENTITY_INVALID",
        )

    def test_typed_continuity_archive_rejects_unknown_relationship_target(self) -> None:
        plan = {
            "raw_script": "Scene 1: Show the product.",
            "continuity_archive": {
                "entities": [
                    {
                        "entity_id": "character-001",
                        "entity_type": "character",
                        "name": "Actor",
                        "appearance": "adult",
                        "outfit": "blue-jacket",
                        "relationships": [{"type": "uses", "entity_id": "missing-product"}],
                    }
                ],
            },
        }
        with self.assertRaises(StoryboardError) as captured:
            StoryboardService(clock=fixed_clock).execute(self.request(plan))
        self.assertEqual(captured.exception.code, "STORYBOARD_CONTINUITY_ENTITY_INVALID")


if __name__ == "__main__":
    unittest.main()
