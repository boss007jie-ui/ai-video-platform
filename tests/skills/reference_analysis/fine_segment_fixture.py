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


def replication_request(
    workspace: Path,
    *,
    profile: str = "HYBRID_REPLICATION",
) -> dict[str, object]:
    request = ten_segment_request(workspace)
    request["analysis_profile"] = profile
    offline = request["offline_analysis"]  # type: ignore[assignment]
    offline["segment_contexts"] = [  # type: ignore[index]
        {
            "start_ms": index * 400,
            "end_ms": (index + 1) * 400,
            "shot_id": f"shot-{index + 1:03d}",
            "scene_id": "scene-001" if index < 5 else "scene-002",
        }
        for index in range(10)
    ]
    offline["motion_actions"] = [  # type: ignore[index]
        {
            "action_id": "action-001",
            "actor": "subject-001",
            "body_part": "right_hand",
            "start_pose": "hand beside torso",
            "end_pose": "hand holding garment",
            "motion_direction": "lower-right to center-up",
            "motion_path": "curved reach then lift",
            "motion_speed": "accelerate then decelerate",
            "joint_or_limb_change": "elbow flexes while shoulder lifts",
            "hand_state": "open to gripping",
            "object_state_before": "garment resting on surface",
            "object_state_after": "garment lifted and held",
            "camera_motion": "static",
            "states": [
                {"state": "ACTION_START", "timestamp_ms": 80, "contact_state": "NO_CONTACT"},
                {"state": "ACTION_ONSET", "timestamp_ms": 280, "contact_state": "APPROACHING"},
                {"state": "PRE_CONTACT", "timestamp_ms": 520, "contact_state": "PRE_CONTACT"},
                {"state": "FIRST_CONTACT", "timestamp_ms": 720, "contact_state": "FIRST_CONTACT"},
                {"state": "CONTROL_OR_GRIP", "timestamp_ms": 920, "contact_state": "GRIPPING"},
                {"state": "ACTION_APEX", "timestamp_ms": 1240, "contact_state": "HOLDING"},
                {"state": "ACTION_END", "timestamp_ms": 1480, "contact_state": "HOLDING"},
                {"state": "FINAL_HOLD", "timestamp_ms": 1560, "contact_state": "HOLDING"},
            ],
        },
        {
            "action_id": "action-002",
            "actor": "subject-001",
            "body_part": "whole_body",
            "start_pose": "front-facing recline",
            "end_pose": "side-facing recline",
            "motion_direction": "roll toward camera-right",
            "motion_path": "torso rotation around body axis",
            "motion_speed": "slow continuous turn",
            "joint_or_limb_change": "hips and shoulders rotate together",
            "hand_state": "relaxed",
            "object_state_before": "garment front visible",
            "object_state_after": "garment back visible",
            "camera_motion": "static",
            "states": [
                {"state": "ACTION_START", "timestamp_ms": 1680, "contact_state": "NO_CONTACT"},
                {"state": "ACTION_ONSET", "timestamp_ms": 1920, "contact_state": "NO_CONTACT"},
                {"state": "ACTION_APEX", "timestamp_ms": 2240, "contact_state": "NO_CONTACT"},
                {"state": "ACTION_END", "timestamp_ms": 2640, "contact_state": "NO_CONTACT"},
            ],
        },
        {
            "action_id": "action-003",
            "actor": "subject-001",
            "body_part": "left_hand",
            "start_pose": "hand above garment hem",
            "end_pose": "hem held in reveal position",
            "motion_direction": "bottom to top",
            "motion_path": "short vertical pull",
            "motion_speed": "quick pull then hold",
            "joint_or_limb_change": "wrist closes and elbow lifts",
            "hand_state": "open to pinching",
            "object_state_before": "garment hem lowered",
            "object_state_after": "garment detail fully revealed",
            "camera_motion": "short controlled move",
            "states": [
                {"state": "ACTION_START", "timestamp_ms": 2880, "contact_state": "APPROACHING"},
                {"state": "FIRST_CONTACT", "timestamp_ms": 3080, "contact_state": "FIRST_CONTACT"},
                {"state": "CONTROL_OR_GRIP", "timestamp_ms": 3240, "contact_state": "GRIPPING"},
                {"state": "ACTION_APEX", "timestamp_ms": 3440, "contact_state": "MANIPULATING"},
                {"state": "FINAL_HOLD", "timestamp_ms": 3560, "contact_state": "HOLDING"},
            ],
        },
    ]
    repeated_actions = (
        "establish wearing state",
        "adjust garment structure",
        "show front silhouette",
        "reveal construction detail",
        "turn body to show back",
    )
    offline["narrative_facts"] = [  # type: ignore[index]
        {
            "fact_id": f"fact-{index + 1:03d}",
            "start_ms": index * 400,
            "end_ms": (index + 1) * 400,
            "actor": "subject-001",
            "action": repeated_actions[index % len(repeated_actions)],
            "object": "garment",
            "location": "bed surface" if index < 5 else "living-room surface",
            "start_state": f"state-{index:02d}",
            "end_state": f"state-{index + 1:02d}",
            "trigger": "prior verified step" if index else "video start",
            "result": f"visible result {index + 1}",
            "information_revealed": "garment construction detail" if index in {3, 7} else "UNAVAILABLE",
            "spoken_text": "UNAVAILABLE",
            "subtitle_text": f"Proof step {index + 1}",
        }
        for index in range(10)
    ]
    offline["scene_annotations"] = [  # type: ignore[index]
        {
            "scene_id": "scene-001",
            "start_ms": 0,
            "end_ms": 2000,
            "scene_type": "bed demonstration",
            "camera_position": "foot-side centered",
            "camera_height": "slightly elevated",
            "camera_direction": "toward subject center",
            "framing": "medium full body",
            "large_object_layout": "bed fills lower frame",
            "subject_position": "center",
            "subject_scale_in_frame": "0.62 frame height",
            "subject_orientation": "front-facing",
            "entry_direction": "UNAVAILABLE",
            "exit_direction": "UNAVAILABLE",
            "movement_route": "center roll toward camera-right",
            "light_direction": "upper-left",
            "major_spatial_relationships": "subject centered on bed; garment follows torso",
        },
        {
            "scene_id": "scene-002",
            "start_ms": 2000,
            "end_ms": 4000,
            "scene_type": "living-room demonstration",
            "camera_position": "front centered",
            "camera_height": "eye-level to seated subject",
            "camera_direction": "toward subject center",
            "framing": "medium",
            "large_object_layout": "sofa behind subject",
            "subject_position": "center",
            "subject_scale_in_frame": "0.58 frame height",
            "subject_orientation": "side then front-facing",
            "entry_direction": "UNAVAILABLE",
            "exit_direction": "UNAVAILABLE",
            "movement_route": "small center-zone movement",
            "light_direction": "camera-left",
            "major_spatial_relationships": "subject remains in front of sofa; garment stays foreground",
        },
    ]
    return request
