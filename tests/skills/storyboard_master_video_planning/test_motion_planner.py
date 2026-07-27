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

    def test_press_uses_visual_candidate_that_matches_script_action(self) -> None:
        result = plan_motion_annotations(
            master_entry(subject_motion="single finger presses down and holds"),
            observation(),
        )

        self.assertEqual(
            result["S01-P01"],
            [{"role": "subject", "points": [[0.88, 0.16], [0.64, 0.48]]}],
        )

    def test_press_falls_back_to_observed_actor_and_contact(self) -> None:
        visual = observation()
        panel = visual["S01-P01"]
        assert isinstance(panel, dict)
        panel["motion_candidates"] = []

        result = plan_motion_annotations(
            master_entry(subject_motion="single finger presses down"),
            visual,
        )

        self.assertEqual(
            result["S01-P01"],
            [{"role": "subject", "points": [[0.8, 0.25], [0.64, 0.48]]}],
        )

    def test_squeeze_paths_run_from_observed_hands_toward_product_center(self) -> None:
        visual = {
            "S01-P01": {
                "confidence": 0.94,
                "objects": [
                    {"id": "product", "kind": "product", "bbox": [0.25, 0.3, 0.75, 0.8]},
                    {"id": "left-hand", "kind": "hand", "bbox": [0.02, 0.35, 0.25, 0.7]},
                    {"id": "right-hand", "kind": "hand", "bbox": [0.75, 0.35, 0.98, 0.7]},
                ],
                "contacts": [],
                "motion_candidates": [],
            }
        }

        result = plan_motion_annotations(master_entry(subject_motion="two hands squeeze, hold, release"), visual)

        self.assertEqual(
            result["S01-P01"],
            [
                {"role": "subject", "points": [[0.25, 0.525], [0.4, 0.55]]},
                {"role": "subject", "points": [[0.75, 0.525], [0.6, 0.55]]},
            ],
        )

    def test_rotate_and_thumb_press_keep_separate_visual_paths(self) -> None:
        visual = observation()
        panel = visual["S01-P01"]
        assert isinstance(panel, dict)
        panel["motion_candidates"] = [
            {
                "role": "subject", "action": "rotate", "subject_id": "product",
                "points": [[0.24, 0.55], [0.3, 0.35], [0.5, 0.3], [0.74, 0.45]], "confidence": 0.91,
            },
            {
                "role": "subject", "action": "press", "subject_id": "finger",
                "points": [[0.53, 0.24], [0.48, 0.39]], "confidence": 0.9,
            },
        ]

        result = plan_motion_annotations(
            master_entry(subject_motion="wrist rotates product, thumb taps pleats"),
            visual,
        )

        self.assertEqual(
            result["S01-P01"],
            [
                {"role": "subject", "points": [[0.24, 0.55], [0.3, 0.35], [0.5, 0.3], [0.74, 0.45]]},
                {"role": "subject", "points": [[0.53, 0.24], [0.48, 0.39]]},
            ],
        )

    def test_packaging_entering_from_right_gets_leftward_path(self) -> None:
        visual = {
            "S01-P01": {
                "confidence": 0.9,
                "objects": [
                    {"id": "product", "kind": "product", "bbox": [0.12, 0.5, 0.38, 0.75]},
                    {"id": "box", "kind": "packaging", "bbox": [0.55, 0.35, 0.85, 0.75]},
                ],
                "contacts": [],
                "motion_candidates": [],
            }
        }

        result = plan_motion_annotations(
            master_entry(subject_motion="hand pushes blind box in from off-frame right, withdraws"),
            visual,
        )

        self.assertEqual(
            result["S01-P01"],
            [{"role": "subject", "points": [[0.91, 0.55], [0.7, 0.55]]}],
        )

    def test_camera_push_is_planned_independently_around_observed_product(self) -> None:
        result = plan_motion_annotations(
            master_entry(camera_motion="locked macro, slight push-in", subject_motion="hold still"),
            observation(),
        )

        self.assertEqual(
            result["S01-P01"],
            [
                {"role": "camera", "points": [[0.08, 0.18], [0.36, 0.26]]},
                {"role": "camera", "points": [[0.92, 0.18], [0.64, 0.26]]},
            ],
        )

    def test_incompatible_or_ambiguous_visual_evidence_does_not_guess(self) -> None:
        visual = observation()
        panel = visual["S01-P01"]
        assert isinstance(panel, dict)
        panel["motion_candidates"] = [
            {
                "role": "subject", "action": "press", "subject_id": "finger",
                "points": [[0.88, 0.16], [0.64, 0.48]], "confidence": 0.92,
            }
        ]

        rotate = plan_motion_annotations(master_entry(subject_motion="rotate product"), visual)
        missing_product = plan_motion_annotations(
            master_entry(camera_motion="slow push-in", subject_motion="hold"),
            {"S01-P01": {"confidence": 0.9, "objects": [], "contacts": [], "motion_candidates": []}},
        )

        self.assertEqual(rotate, {"S01-P01": []})
        self.assertEqual(missing_product, {"S01-P01": []})


if __name__ == "__main__":
    unittest.main()
