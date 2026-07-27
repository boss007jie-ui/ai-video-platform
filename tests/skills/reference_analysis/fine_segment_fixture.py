from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Iterable


FIXTURE = Path(__file__).parent / "fixtures" / "local-draft-v1.mp4"

OBSERVATION_FIELDS = (
    "scene",
    "shot_scale_and_camera_position",
    "camera_motion",
    "subject_motion",
    "primary_subject_action",
    "product_action_and_state",
    "package_container_prop_state",
    "subtitle_and_visible_text",
    "speech_music_sound_effect",
    "emotion_change",
    "attention_target",
    "audience_psychology",
    "narrative_function",
    "viral_mechanism",
    "conversion_function",
)

STAGES = (
    ("Problem Hook", "Recognize a familiar problem", "Visual Hook"),
    ("Product Reveal", "Resolve initial curiosity", "Reveal"),
    ("Use Demo", "Understand how the product works", "Product Proof"),
    ("Result Proof", "Believe the visible result", "Detail Proof"),
    ("Natural Close", "Accept a low-pressure ending", "Natural Close"),
)


def materialize_video(workspace: Path) -> tuple[Path, str]:
    media = workspace / "inputs" / "reference.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, media)
    return media, hashlib.sha256(media.read_bytes()).hexdigest()


def fine_segment_request(media_sha256: str, *, boundaries: Iterable[int]) -> dict[str, object]:
    return {
        "analysis_version": "1.0.0",
        "mode": "local_fine_segments_v1",
        "selected_reference_video": {
            "reference_id": "fine-reference-001",
            "media_path": "inputs/reference.mp4",
            "sha256": media_sha256,
            "source_platform": "local",
            "source_url": "urn:local:synthetic-fixture:local-draft-v1",
            "source_id": "local-draft-v1",
            "published_at": "2026-07-27T00:00:00Z",
            "collected_at": "2026-07-27T00:00:00Z",
            "category": "synthetic product demonstration",
            "reference_brand": "Synthetic Reference Brand",
            "reference_product": "Synthetic Reference Product",
            "reference_people": [],
            "provenance": {
                "fixture_id": "local-fine-segments-v1",
                "fixture_kind": "VERSIONED_SYNTHETIC_MEDIA",
            },
        },
        "video_metadata": {
            "duration_ms": 4000,
            "width": 64,
            "height": 96,
            "aspect_ratio": "2:3",
            "media_type": "video/mp4",
            "codec": "h264",
        },
        "segmentation_policy": {
            "sampling_fps": 4,
            "visual_change_threshold": 1.0,
            "min_segment_ms": 200,
            "enable_audio_boundaries": False,
        },
        "offline_analysis": {
            "analyzer_id": "fake-offline-multimodal-v1",
            "boundary_signals": [
                {
                    "timestamp_ms": timestamp,
                    "reasons": ["offline_semantic_change"],
                    "evidence": "fixture:local-fine-segments-v1",
                }
                for timestamp in boundaries
            ],
            "segment_annotations": [],
        },
    }


def ten_segment_request(workspace: Path) -> dict[str, object]:
    _, digest = materialize_video(workspace)
    request = fine_segment_request(
        digest,
        boundaries=(400, 800, 1200, 1600, 2000, 2400, 2800, 3200, 3600),
    )
    annotations: list[dict[str, object]] = []
    for index in range(10):
        title, psychology, function = STAGES[index // 2]
        values = {
            "scene": f"Synthetic scene {index // 2 + 1}",
            "shot_scale_and_camera_position": "Close product view",
            "camera_motion": "Short controlled move",
            "subject_motion": f"Subject action stage {index // 2 + 1}",
            "primary_subject_action": f"Complete action for {title}",
            "product_action_and_state": f"Product state for {title}",
            "package_container_prop_state": "Props remain visibly traceable",
            "subtitle_and_visible_text": f"Stage label {title}",
            "speech_music_sound_effect": "Synthetic local audio evidence",
            "emotion_change": f"Emotion supports {title}",
            "attention_target": "Reference product and action",
            "audience_psychology": psychology,
            "narrative_function": title,
            "viral_mechanism": function,
            "conversion_function": function,
        }
        annotations.append({
            "start_ms": index * 400,
            "end_ms": (index + 1) * 400,
            "stage_title": title,
            "observations": {field: values[field] for field in OBSERVATION_FIELDS},
        })
    request["offline_analysis"]["segment_annotations"] = annotations  # type: ignore[index]
    return request
