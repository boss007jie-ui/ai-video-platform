from __future__ import annotations

import unittest

from ai_video_platform.skills.storyboard import StoryboardError, StoryboardRequest, StoryboardService

from .fixtures import fixed_clock, product_context, task_context, task_spec, valid_plan


class StoryboardContinuityTests(unittest.TestCase):
    def execute(self, plan):
        return StoryboardService(clock=fixed_clock).execute(
            StoryboardRequest(
                command="create-storyboard",
                task_spec=task_spec(),
                task_context=task_context(),
                product_context=product_context(),
                plan=plan,
                idempotency_key="continuity-case",
                expected_version=0,
            )
        )

    def test_valid_story_scene_beat_shot_panel_hierarchy_and_continuity(self) -> None:
        result = self.execute(valid_plan())

        StoryboardService(clock=fixed_clock).validate_continuity(result.artifact)
        scene = result.artifact.story["scenes"][0]
        self.assertEqual(scene["scene_id"], "scene-001")
        self.assertEqual(scene["beats"][0]["shots"][0]["panels"][0]["panel_id"], "panel-001")

    def test_undeclared_continuity_change_is_rejected(self) -> None:
        plan = valid_plan()
        plan["scenes"][0]["beats"][0]["shots"][0]["panels"][1]["continuity"]["actor_outfit"] = "red-shirt"

        with self.assertRaises(StoryboardError) as captured:
            self.execute(plan)

        self.assertEqual(captured.exception.code, "STORYBOARD_CONTINUITY_CONFLICT")
        self.assertIn("actor_outfit", captured.exception.field_paths[0])

    def test_declared_continuity_transition_is_auditable(self) -> None:
        plan = valid_plan()
        panel = plan["scenes"][0]["beats"][0]["shots"][0]["panels"][1]
        panel["continuity"]["actor_outfit"] = "red-shirt"
        panel["continuity_changes"] = {
            "actor_outfit": {
                "from": "blue-jacket",
                "to": "red-shirt",
                "reason": "On-screen wardrobe transition",
            }
        }
        later_panel = plan["scenes"][1]["beats"][0]["shots"][0]["panels"][0]
        later_panel["continuity_changes"] = {
            "actor_outfit": {
                "from": "red-shirt",
                "to": "blue-jacket",
                "reason": "On-screen wardrobe reset",
            }
        }

        result = self.execute(plan)

        self.assertEqual(
            result.artifact.story["scenes"][0]["beats"][0]["shots"][0]["panels"][1]["continuity_changes"]["actor_outfit"]["reason"],
            "On-screen wardrobe transition",
        )

    def test_emotional_progression_must_not_regress(self) -> None:
        plan = valid_plan()
        plan["scenes"][1]["emotion_score"] = 10

        with self.assertRaises(StoryboardError) as captured:
            self.execute(plan)

        self.assertEqual(captured.exception.code, "STORYBOARD_EMOTIONAL_PROGRESSION_INVALID")


if __name__ == "__main__":
    unittest.main()
