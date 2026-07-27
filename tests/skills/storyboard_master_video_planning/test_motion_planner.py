from __future__ import annotations

import unittest

from ai_video_platform.skills.storyboard_master_video_planning.motion_planner import (
    _camera_intents,
    _subject_intents,
    plan_motion_annotations,
)


def master_entry(
    *,
    camera_motion: str = "locked close-up",
    subject_motion: str = "fingers hold squeeze, no release",
) -> dict[str, object]:
    return {
        "artifact_name": "VideoGenerationStoryboardMaster",
        "master_panel_entries": [
            {
                "panel_id": "S01-P01",
                "shot_id": "S01",
                "panel_asset_id": "asset://panel/S01-P01",
                "camera_motion": camera_motion,
                "subject_motion": subject_motion,
            }
        ],
        "shots": [
            {
                "shot_id": "S01",
                "motion_path": subject_motion,
                "start_state": "hands approach product",
                "middle_state": "hands act on product",
                "end_state": "product remains visible",
            }
        ],
    }


def observation() -> dict[str, object]:
    return {
        "S01-P01": {
            "confidence": 0.95,
            "objects": [
                {"id": "product", "kind": "product", "bbox": [0.25, 0.3, 0.75, 0.8]},
                {"id": "finger", "kind": "finger", "bbox": [0.65, 0.05, 0.95, 0.45]},
            ],
            "contacts": [
                {"actor_id": "finger", "target_id": "product", "point": [0.64, 0.48]},
            ],
            "motion_candidates": [
                {
                    "role": "subject",
                    "action": "press",
                    "subject_id": "finger",
                    "points": [[0.88, 0.16], [0.64, 0.48]],
                    "confidence": 0.92,
                }
            ],
        }
    }


class MotionPlannerTests(unittest.TestCase):
    def test_camera_intents_separate_locked_frame_from_explicit_movement(self) -> None:
        self.assertEqual(_camera_intents("locked macro, slight push-in"), ("push",))
        self.assertEqual(_camera_intents("locked close-up"), ())
        self.assertEqual(_camera_intents("slow pan left then tilt down"), ("pan_left", "tilt_down"))

    def test_subject_intents_cover_supported_script_actions(self) -> None:
        self.assertEqual(_subject_intents("single fingertip slow press and lift"), ("press", "lift"))
        self.assertEqual(_subject_intents("two hands squeeze, hold, release"), ("squeeze", "hold", "release"))
        self.assertEqual(_subject_intents("wrist rotates product, thumb taps pleats"), ("rotate", "press"))
        self.assertEqual(_subject_intents("hand pushes blind box in from off-frame right, withdraws"), ("enter_left", "exit_right"))

    def test_invalid_normalized_visual_coordinates_are_rejected(self) -> None:
        visual = observation()
        panel = visual["S01-P01"]
        assert isinstance(panel, dict)
        objects = panel["objects"]
        assert isinstance(objects, list)
        objects[0] = {"id": "product", "kind": "product", "bbox": [0.75, 0.3, 0.25, 0.8]}

        with self.assertRaisesRegex(ValueError, "bbox"):
            plan_motion_annotations(master_entry(subject_motion="single finger presses down"), visual)

    def test_low_confidence_panel_produces_no_annotations(self) -> None:
        visual = observation()
        panel = visual["S01-P01"]
        assert isinstance(panel, dict)
        panel["confidence"] = 0.4

        result = plan_motion_annotations(master_entry(subject_motion="single finger presses down"), visual)

        self.assertEqual(result, {"S01-P01": []})


if __name__ == "__main__":
    unittest.main()
