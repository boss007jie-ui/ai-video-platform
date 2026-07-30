from __future__ import annotations

import unittest

from ai_video_platform.skills.reference_analysis.storyboard_boards import (
    decode_png,
    render_analysis_board,
    render_replication_board,
)


def _pixel_at(image: tuple[int, int, bytes], x: int, y: int) -> tuple[int, int, int]:
    width, _, pixels = image
    offset = (y * width + x) * 3
    return tuple(pixels[offset : offset + 3])  # type: ignore[return-value]


class StoryboardBoardRenderingTests(unittest.TestCase):
    def test_analysis_board_preserves_vertical_keyframe_aspect_ratio(self) -> None:
        red = (237, 24, 36)
        source_frame = (2, 4, bytes(red) * 8)
        payload = render_analysis_board(
            {"category": "TEST", "source_platform": "LOCAL"},
            {"aspect_ratio": "9:16", "duration_ms": 1000},
            [],
            {"frame-001": source_frame},
            {"value": "TEST"},
            core_beats=[
                {
                    "beat_id": "beat-001",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "representative_frame_id": "frame-001",
                    "stage_title": "TEST",
                    "visual_summary": "TEST",
                    "key_action": "TEST",
                    "audience_psychology": "TEST",
                    "viral_or_conversion_function": "TEST",
                    "function_label": "TEST",
                }
            ],
        )

        image = decode_png(payload)
        self.assertEqual(_pixel_at(image, 1500, 520), red)
        self.assertNotEqual(
            _pixel_at(image, 80, 520),
            red,
            "the vertical source frame was stretched across the horizontal image slot",
        )

    def test_replication_board_renders_chinese_instead_of_question_marks(self) -> None:
        def render(actual: str, reusable: str) -> tuple[int, int, bytes]:
            return decode_png(
                render_replication_board(
                    [
                        {
                            "pattern_id": "pattern-001",
                            "interval": {"start_ms": 0, "end_ms": 1000},
                            "actual_reference_behavior": {"value": actual},
                            "reusable_mechanism": {"value": reusable},
                        }
                    ]
                )
            )

        chinese = render("真实动作", "故事复刻")
        question_marks = render("????", "????")
        self.assertNotEqual(
            chinese[2],
            question_marks[2],
            "Chinese text was replaced by question-mark glyphs",
        )


if __name__ == "__main__":
    unittest.main()
