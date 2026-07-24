"""Product-specific production storyboard and panel-plan derivation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ai_video_platform.contracts.envelope import ContractEnvelope, ProducerIdentity, build_envelope, format_utc
from ai_video_platform.contracts.errors import ContractError
from ai_video_platform.contracts.serialization import content_digest, freeze_json, thaw_json
from ai_video_platform.contracts.validation import validate_envelope

from .interface import StoryboardError, safe_field_segment


PRODUCTION_STORYBOARD_VERSION = "1.0.0"
PRODUCTION_STORYBOARD_PLAN_IDENTITY = "avp.contract.production-storyboard-plan"
PRODUCTION_STORYBOARD_PANEL_PLAN_IDENTITY = "avp.contract.production-storyboard-panel-plan"
REFERENCE_STORYBOARD_ANALYSIS_IDENTITY = "avp.contract.reference-storyboard-analysis"
REPLICATION_PATTERN_IDENTITY = "avp.contract.replication-pattern"
STORYBOARD_PRODUCER = {
    "agent": "skill",
    "component_id": "storyboard",
    "component_version": "1.2.0",
}

_FORBIDDEN_CAPABILITY_KEYS = {
    "provider_submission",
    "provider_request",
    "image_generation",
    "video_generation",
    "submit_provider",
    "download_media",
}
_REFERENCE_BOARD_MARKERS = {
    "reference-storyboard-analysis-board",
    "reference-analysis-board",
    "shot-evidence-board",
    "replication-board",
    "storyboard-contact-sheet",
}


@dataclass(frozen=True, slots=True)
class ProductionStoryboardResult:
    production_storyboard_plan: Mapping[str, Any]
    production_storyboard_panel_plan: Mapping[str, Any]
    execution_event: ContractEnvelope
    provider_calls: int = 0
    network_calls: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "production_storyboard_plan", freeze_json(self.production_storyboard_plan))
        object.__setattr__(
            self,
            "production_storyboard_panel_plan",
            freeze_json(self.production_storyboard_panel_plan),
        )


def _validated_foundation(envelope: object, contract_type: str, field_name: str):
    if not isinstance(envelope, ContractEnvelope) or envelope.contract_type != contract_type:
        raise StoryboardError(
            "STORYBOARD_CONTRACT_INVALID",
            "validation",
            "Production storyboard input uses an unexpected Contract type",
            field_paths=(field_name,),
        )
    try:
        return validate_envelope(envelope)
    except ContractError as exc:
        raise StoryboardError(
            exc.code.value,
            exc.category.value,
            exc.message,
            retryable=exc.retryable,
            field_paths=exc.field_paths,
        ) from exc


def _object(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "validation",
            "Production storyboard constraints and artifacts must be objects",
            field_paths=(path,),
        )
    return value


def _text(value: object, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _string_list(value: object, path: str) -> list[str]:
    if value is None:
        return []
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "validation",
            "Asset collections must contain non-empty string references",
            field_paths=(path,),
        )
    return [item.strip() for item in value]


def _reject_forbidden_capabilities(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _FORBIDDEN_CAPABILITY_KEYS:
                raise StoryboardError(
                    "STORYBOARD_CAPABILITY_FORBIDDEN",
                    "authorization",
                    "Storyboard cannot generate media or submit a Provider",
                    field_paths=(f"{path}.{safe_field_segment(key)}",),
                )
            _reject_forbidden_capabilities(nested, f"{path}.{safe_field_segment(key)}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_forbidden_capabilities(nested, f"{path}[{index}]")


def _validated_business_artifact(
    value: object | None,
    *,
    artifact_type: str,
    identity: str,
    task_id: str,
    field_name: str,
) -> Mapping[str, Any] | None:
    if value is None:
        return None
    document = _object(value, field_name)
    if document.get("schema_version") != PRODUCTION_STORYBOARD_VERSION:
        raise StoryboardError(
            "STORYBOARD_ARTIFACT_VERSION_UNSUPPORTED",
            "compatibility",
            "Storyboard supports only business artifact version 1.0.0",
            field_paths=(f"{field_name}.schema_version",),
        )
    if document.get("artifact_type") != artifact_type or document.get("contract_identity") != identity:
        raise StoryboardError(
            "STORYBOARD_CONTRACT_INVALID",
            "validation",
            "Storyboard business artifact identity is not canonical",
            field_paths=(field_name,),
        )
    if document.get("task_id") != task_id:
        raise StoryboardError(
            "STORYBOARD_CONTEXT_INVALID",
            "conflict",
            "Storyboard business artifact belongs to a different task",
            field_paths=(f"{field_name}.task_id",),
        )
    producer = document.get("producer")
    if not isinstance(producer, Mapping) or producer.get("component_id") != "reference-analysis":
        raise StoryboardError(
            "STORYBOARD_PRODUCER_UNAUTHORIZED",
            "authorization",
            "Reference artifacts must be produced by Reference Analysis",
            field_paths=(f"{field_name}.producer",),
        )
    artifact_id = document.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "validation",
            "Business artifact requires artifact_id",
            field_paths=(f"{field_name}.artifact_id",),
        )
    return document


def _reference_beats(reference: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if reference is None:
        return []
    beats = reference.get("beats")
    if (
        not isinstance(beats, Sequence)
        or isinstance(beats, (str, bytes, bytearray))
        or not beats
        or any(not isinstance(item, Mapping) for item in beats)
    ):
        raise StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "validation",
            "ReferenceStoryboardAnalysis requires ordered beats",
            field_paths=("reference_storyboard_analysis.beats",),
        )
    return list(beats)


def _protected_values(reference: Mapping[str, Any] | None) -> tuple[str, ...]:
    if reference is None:
        return ()
    protected = reference.get("protected_identity", {})
    if not isinstance(protected, Mapping):
        return ()
    return tuple(
        item.casefold()
        for collection in protected.values()
        if isinstance(collection, Sequence) and not isinstance(collection, (str, bytes, bytearray))
        for item in collection
        if isinstance(item, str) and item.strip()
    )


def _safe_reference_text(value: object, fallback: str, protected: tuple[str, ...]) -> str:
    selected = _text(value, fallback)
    lowered = selected.casefold()
    if any(item in lowered for item in protected):
        raise StoryboardError(
            "STORYBOARD_REFERENCE_IDENTITY_FORBIDDEN",
            "authorization",
            "Reference identity cannot be copied into a production storyboard",
            field_paths=("reference_storyboard_analysis",),
        )
    return selected


def _panel_count(production_constraints: Mapping[str, Any], reference_beats: Sequence[object]) -> int:
    supplied = production_constraints.get("panel_count")
    count = len(reference_beats) if supplied is None and reference_beats else supplied if supplied is not None else 3
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 500:
        raise StoryboardError(
            "STORYBOARD_BUDGET_EXCEEDED",
            "budget",
            "Production storyboard panel_count must be between 1 and 500",
            field_paths=("production_constraints.panel_count",),
        )
    return count


def _timings(
    count: int,
    duration_ms: int,
    beats: Sequence[Mapping[str, Any]],
) -> list[tuple[int, int]]:
    if len(beats) == count:
        supplied: list[tuple[int, int]] = []
        for index, beat in enumerate(beats):
            start = beat.get("start_ms")
            end = beat.get("end_ms")
            if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or start < 0 or end <= start:
                raise StoryboardError(
                    "STORYBOARD_INPUT_INVALID",
                    "validation",
                    "Reference beat time ranges must be increasing integers",
                    field_paths=(f"reference_storyboard_analysis.beats[{index}]",),
                )
            supplied.append((start, end))
        if supplied[0][0] == 0 and all(supplied[index - 1][1] <= supplied[index][0] for index in range(1, count)):
            reference_duration = supplied[-1][1]
            if reference_duration > 0:
                return [
                    (
                        round(duration_ms * start / reference_duration),
                        round(duration_ms * end / reference_duration),
                    )
                    for start, end in supplied
                ]
    return [
        (round(duration_ms * index / count), round(duration_ms * (index + 1) / count))
        for index in range(count)
    ]


def _replication_by_beat(replication: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if replication is None:
        return {}
    patterns = replication.get("patterns", ())
    if not isinstance(patterns, Sequence) or isinstance(patterns, (str, bytes, bytearray)):
        raise StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "validation",
            "ReplicationPattern patterns must be an array",
            field_paths=("replication_pattern.patterns",),
        )
    return {
        str(item["source_beat_id"]): item
        for item in patterns
        if isinstance(item, Mapping) and isinstance(item.get("source_beat_id"), str)
    }


def _replication_patterns(replication: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if replication is None:
        return []
    patterns = replication.get("patterns", ())
    return [item for item in patterns if isinstance(item, Mapping)]


def _artifact_id(prefix: str, body: Mapping[str, Any]) -> str:
    return f"{prefix}-{content_digest(body).removeprefix('sha256:')[:20]}"


def derive_production_storyboard(
    *,
    task_spec: ContractEnvelope,
    product_context: ContractEnvelope,
    creative_constraints: Mapping[str, Any],
    production_constraints: Mapping[str, Any],
    reference_storyboard_analysis: Mapping[str, Any] | None = None,
    replication_pattern: Mapping[str, Any] | None = None,
) -> ProductionStoryboardResult:
    """Derive canonical production planning artifacts without media or Provider work."""

    validated_task = _validated_foundation(task_spec, "avp.contract.task-spec", "task_spec")
    validated_product = _validated_foundation(
        product_context,
        "avp.contract.product-context-bundle",
        "product_context",
    )
    task_id = validated_task.payload.task_id
    product_id = validated_product.payload.product_id
    if (
        "storyboard" not in validated_task.payload.requested_skills
        or product_context.task_id not in (None, task_id)
    ):
        raise StoryboardError(
            "STORYBOARD_CONTEXT_INVALID",
            "conflict",
            "TaskSpec does not authorize Storyboard for this ProductContextBundle",
            field_paths=("task_spec.payload.requested_skills", "product_context.task_id"),
        )

    creative = _object(creative_constraints, "creative_constraints")
    production = _object(production_constraints, "production_constraints")
    _reject_forbidden_capabilities(creative, "creative_constraints")
    _reject_forbidden_capabilities(production, "production_constraints")

    reference = _validated_business_artifact(
        reference_storyboard_analysis,
        artifact_type="ReferenceStoryboardAnalysis",
        identity=REFERENCE_STORYBOARD_ANALYSIS_IDENTITY,
        task_id=task_id,
        field_name="reference_storyboard_analysis",
    )
    replication = _validated_business_artifact(
        replication_pattern,
        artifact_type="ReplicationPattern",
        identity=REPLICATION_PATTERN_IDENTITY,
        task_id=task_id,
        field_name="replication_pattern",
    )
    beats = _reference_beats(reference)
    protected = _protected_values(reference)
    pattern_by_beat = _replication_by_beat(replication)
    patterns = _replication_patterns(replication)

    approved_assets = set(
        _string_list(
            validated_product.payload.approved_asset_refs,
            "product_context.payload.approved_asset_refs",
        )
    )
    asserted_approved_assets = _string_list(
        production.get("approved_assets"),
        "production_constraints.approved_assets",
    )
    if any(item not in approved_assets for item in asserted_approved_assets):
        raise StoryboardError(
            "STORYBOARD_ASSET_NOT_APPROVED",
            "authorization",
            "Production constraints cannot approve assets absent from ProductContextBundle",
            field_paths=("production_constraints.approved_assets",),
        )
    required_assets = _string_list(creative.get("required_assets"), "creative_constraints.required_assets")
    forbidden_assets = _string_list(creative.get("forbidden_assets"), "creative_constraints.forbidden_assets")
    forbidden_normalized = {item.casefold().replace("_", "-") for item in forbidden_assets}
    if set(required_assets) & set(forbidden_assets) or any(
        any(marker in item for marker in _REFERENCE_BOARD_MARKERS)
        for item in (asset.casefold().replace("_", "-") for asset in required_assets)
    ) or any(asset.casefold().replace("_", "-") in forbidden_normalized for asset in required_assets):
        raise StoryboardError(
            "STORYBOARD_FORBIDDEN_ASSET",
            "authorization",
            "Forbidden or reference-analysis assets cannot become production panel inputs",
            field_paths=("creative_constraints.required_assets",),
        )
    if any(item not in approved_assets for item in required_assets):
        raise StoryboardError(
            "STORYBOARD_ASSET_NOT_APPROVED",
            "authorization",
            "Every required production asset must be approved for the current product",
            field_paths=("creative_constraints.required_assets",),
        )

    count = _panel_count(production, beats or patterns)
    duration_ms = production.get("duration_ms", 4500)
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < count:
        raise StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "validation",
            "production duration_ms must cover every ordered panel",
            field_paths=("production_constraints.duration_ms",),
        )
    timings = _timings(count, duration_ms, beats)
    character_id = _text(creative.get("character_id"), "character-current")
    character_state = _text(creative.get("character_state"), "approved-current-character")
    packaging_state = _text(production.get("packaging_state"), "current-product-packaging")
    container_state = _text(production.get("container_state"), "current-product-container")
    scale_constraints = thaw_json(freeze_json(_object(production.get("scale_constraints", {}), "production_constraints.scale_constraints")))
    narrative_goal = _text(creative.get("narrative_goal"), "Move the audience from product need to confident action")
    visual_constraints = thaw_json(validated_product.payload.visual_constraints or {})
    source_provenance = [
        {
            "contract_identity": task_spec.contract_type,
            "contract_id": str(task_spec.contract_id),
            "payload_digest": task_spec.payload_digest,
        },
        {
            "contract_identity": product_context.contract_type,
            "contract_id": str(product_context.contract_id),
            "payload_digest": product_context.payload_digest,
        },
    ]
    if reference is not None:
        source_provenance.append(
            {
                "contract_identity": REFERENCE_STORYBOARD_ANALYSIS_IDENTITY,
                "artifact_id": reference["artifact_id"],
                "payload_digest": content_digest(reference),
            }
        )
    if replication is not None:
        source_provenance.append(
            {
                "contract_identity": REPLICATION_PATTERN_IDENTITY,
                "artifact_id": replication["artifact_id"],
                "payload_digest": content_digest(replication),
            }
        )

    panels: list[dict[str, Any]] = []
    beat_plan: list[dict[str, Any]] = []
    shot_plan: list[dict[str, Any]] = []
    scene_plan: list[dict[str, Any]] = []
    emotion_arc: list[dict[str, Any]] = []
    psychology_arc: list[dict[str, Any]] = []
    conversion_arc: list[dict[str, Any]] = []
    product_timeline: list[dict[str, Any]] = []
    reference_provenance: list[dict[str, Any]] = []

    for index in range(count):
        beat = beats[index % len(beats)] if beats else {}
        reference_beat_id = beat.get("beat_id") if isinstance(beat.get("beat_id"), str) else None
        pattern = (
            pattern_by_beat.get(reference_beat_id or "", {})
            if beats
            else patterns[index % len(patterns)] if patterns else {}
        )
        pattern_source_beat_id = (
            pattern.get("source_beat_id")
            if isinstance(pattern.get("source_beat_id"), str)
            else reference_beat_id
        )
        mechanism = _safe_reference_text(
            pattern.get("mechanism", beat.get("mechanism")),
            ("hook-current-product" if index == 0 else "prove-current-product" if index < count - 1 else "cta-current-product"),
            protected,
        )
        emotion = _safe_reference_text(beat.get("emotion"), "interest" if index == 0 else "confidence", protected)
        psychology = _safe_reference_text(beat.get("audience_psychology"), "recognition" if index == 0 else "belief", protected)
        conversion = _safe_reference_text(beat.get("conversion_role"), "hook" if index == 0 else "proof" if index < count - 1 else "cta", protected)
        camera = _safe_reference_text(beat.get("camera"), "locked", protected)
        framing = _safe_reference_text(beat.get("framing"), "medium" if index == 0 else "close-up", protected)
        start_ms, end_ms = timings[index]
        scene_id = f"scene-{index + 1:03d}"
        beat_id = f"beat-{index + 1:03d}"
        shot_id = f"shot-{index + 1:03d}"
        panel_id = f"panel-{index + 1:03d}"
        continuity_refs = [
            f"continuity-product-{index + 1:03d}",
            f"continuity-character-{index + 1:03d}",
        ]
        provenance = []
        if reference is not None:
            provenance.append(
                {
                    "artifact_id": reference["artifact_id"],
                    "contract_identity": REFERENCE_STORYBOARD_ANALYSIS_IDENTITY,
                    "content_digest": content_digest(reference),
                    "source_beat_id": pattern_source_beat_id,
                    "transferred_mechanism": mechanism,
                    "identity_transfer": False,
                }
            )
        if replication is not None and pattern:
            provenance.append(
                {
                    "artifact_id": replication["artifact_id"],
                    "contract_identity": REPLICATION_PATTERN_IDENTITY,
                    "content_digest": content_digest(replication),
                    "source_beat_id": reference_beat_id,
                    "transferred_mechanism": mechanism,
                    "identity_transfer": False,
                }
            )
        reference_provenance.extend(item for item in provenance if item not in reference_provenance)
        product_state = {
            "product_id": product_id,
            "sku_id": validated_product.payload.sku_id,
            "visual_constraints": visual_constraints,
            "state": "current-product-featured",
        }
        frozen_moment = f"{mechanism}: show current product {product_id} in the approved production context"
        panels.append(
            {
                "panel_id": panel_id,
                "shot_id": shot_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "frozen_moment": frozen_moment,
                "camera": camera,
                "framing": framing,
                "character_state": {"character_id": character_id, "state": character_state},
                "product_state": product_state,
                "packaging_state": packaging_state,
                "container_state": container_state,
                "emotion": emotion,
                "required_assets": list(required_assets),
                "forbidden_assets": list(forbidden_assets),
                "scale_constraints": scale_constraints,
                "continuity_references": continuity_refs,
                "reference_analysis_provenance": provenance,
            }
        )
        scene_plan.append({"scene_id": scene_id, "order": index + 1, "purpose": mechanism})
        beat_plan.append({"beat_id": beat_id, "scene_id": scene_id, "order": index + 1, "mechanism": mechanism})
        shot_plan.append({"shot_id": shot_id, "beat_id": beat_id, "panel_ids": [panel_id], "order": index + 1, "start_ms": start_ms, "end_ms": end_ms, "camera": camera, "framing": framing})
        emotion_arc.append({"shot_id": shot_id, "emotion": emotion})
        psychology_arc.append({"shot_id": shot_id, "audience_psychology": psychology})
        conversion_arc.append({"shot_id": shot_id, "conversion_role": conversion})
        product_timeline.append({"shot_id": shot_id, "start_ms": start_ms, "end_ms": end_ms, **product_state, "packaging_state": packaging_state, "container_state": container_state})

    plan_body = {
        "artifact_type": "ProductionStoryboardPlan",
        "contract_identity": PRODUCTION_STORYBOARD_PLAN_IDENTITY,
        "schema_version": PRODUCTION_STORYBOARD_VERSION,
        "producer": STORYBOARD_PRODUCER,
        "task_id": task_id,
        "product_id": product_id,
        "NarrativeArc": {"goal": narrative_goal, "ordered_scene_ids": [item["scene_id"] for item in scene_plan]},
        "ScenePlan": scene_plan,
        "BeatPlan": beat_plan,
        "ShotPlan": shot_plan,
        "EmotionArc": emotion_arc,
        "AudiencePsychologyArc": psychology_arc,
        "ConversionArc": conversion_arc,
        "ContinuityBible": {
            "product_id": product_id,
            "character_id": character_id,
            "character_state": character_state,
            "packaging_state": packaging_state,
            "container_state": container_state,
            "scale_constraints": scale_constraints,
            "approved_assets": sorted(approved_assets),
            "forbidden_assets": list(forbidden_assets),
        },
        "ProductStateTimeline": product_timeline,
        "source_provenance": source_provenance,
        "reference_analysis_provenance": reference_provenance,
    }
    plan_body["artifact_id"] = _artifact_id("production-storyboard-plan", plan_body)
    panel_body = {
        "artifact_type": "ProductionStoryboardPanelPlan",
        "contract_identity": PRODUCTION_STORYBOARD_PANEL_PLAN_IDENTITY,
        "schema_version": PRODUCTION_STORYBOARD_VERSION,
        "producer": STORYBOARD_PRODUCER,
        "task_id": task_id,
        "product_id": product_id,
        "production_storyboard_plan_ref": plan_body["artifact_id"],
        "panel_order": [item["panel_id"] for item in panels],
        "panels": panels,
        "source_provenance": source_provenance,
        "reference_analysis_provenance": reference_provenance,
    }
    panel_body["artifact_id"] = _artifact_id("production-storyboard-panel-plan", panel_body)
    source_contract_ids = (str(task_spec.contract_id), str(product_context.contract_id))
    source_hashes = (task_spec.payload_digest, product_context.payload_digest)
    execution_event = build_envelope(
        contract_type="avp.contract.skill-execution-event",
        payload={
            "execution_id": f"execution-{content_digest((plan_body['artifact_id'], panel_body['artifact_id'])).removeprefix('sha256:')[:20]}",
            "task_id": task_id,
            "skill_id": "storyboard",
            "event_type": "completed",
            "sequence": 1,
            "occurred_at": format_utc(task_spec.created_at),
            "status": "completed",
            "input_contract_refs": list(source_contract_ids),
            "output_contract_refs": [plan_body["artifact_id"], panel_body["artifact_id"]],
            "metrics": {"provider_calls": 0, "network_calls": 0},
        },
        producer=ProducerIdentity("skill", "storyboard", STORYBOARD_PRODUCER["component_version"]),
        correlation_id=task_spec.correlation_id,
        idempotency_key=f"derive-production-panels:{plan_body['artifact_id']}:{panel_body['artifact_id']}",
        task_id=task_id,
        source_contract_ids=source_contract_ids,
        source_hashes=source_hashes,
        created_at=task_spec.created_at,
    )
    validate_envelope(execution_event)
    return ProductionStoryboardResult(plan_body, panel_body, execution_event)
