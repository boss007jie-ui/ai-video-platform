"""Offline QA acceptance for the canonical storyboard artifact chain."""

from __future__ import annotations

import re
from typing import Any, Mapping

from ai_video_platform.contracts.business_registry import BUSINESS_REGISTRY

from .models import ReviewOutcome, ReviewRequest


CANONICAL_VERSION = "1.0.0"
CHAIN_TYPES = {
    "avp.contract.reference-storyboard-analysis",
    "avp.contract.reference-beat",
    "avp.contract.reference-shot-evidence",
    "avp.contract.replication-pattern",
    "avp.contract.reference-analysis-board-manifest",
    "avp.contract.production-storyboard-plan",
    "avp.contract.production-storyboard-panel-plan",
    "avp.contract.production-storyboard-panel-set",
    "avp.contract.video-generation-storyboard-master",
    "avp.contract.shot-motion-plan",
    "avp.contract.video-execution-package",
    "avp.contract.first-frame-mapping",
    "avp.contract.reference-role-mapping",
}
REQUIRED_COMPOSITION_TYPES = CHAIN_TYPES
FORBIDDEN_EXECUTION_KINDS = {
    "reference_analysis_board", "shot_evidence_board", "replication_board", "contact_sheet",
}
PERMITTED_REFERENCE_ROLES = {
    "global_structure_reference", "character_reference", "product_reference",
    "packaging_reference", "scene_reference", "style_reference",
}
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _result(family: str, failures: list[dict[str, str]]) -> tuple[dict[str, str], list[dict[str, str]]]:
    if not failures:
        return {"criterion_id": family, "outcome": ReviewOutcome.PASS.value}, []
    result = {
        "criterion_id": family,
        "outcome": ReviewOutcome.FAIL.value,
        "code": failures[0]["code"],
    }
    return result, failures


def _failure(
    family: str,
    code: str,
    message: str,
    artifact: Mapping[str, Any] | None,
    *,
    owner: str = "unknown",
) -> dict[str, str]:
    artifact = artifact or {}
    artifact_type = str(artifact.get("artifact_type", "missing"))
    definition = BUSINESS_REGISTRY.get(artifact_type)
    canonical_owner = definition.owner if definition is not None else "unregistered"
    return {
        "code": code,
        "message": message,
        "criterion_id": family,
        "outcome": ReviewOutcome.FAIL.value,
        "offending_artifact": str(artifact.get("artifact_id", artifact.get("artifact_type", "missing"))),
        "artifact_type": artifact_type,
        "owning_producer": owner if owner != "unknown" else canonical_owner,
    }


def _as_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def evaluate_storyboard_chain(
    request: ReviewRequest,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    subject = request.subject
    raw_artifacts = subject.get("artifacts")
    artifacts = _as_mappings(raw_artifacts) if raw_artifacts is not None else [subject]
    by_type = {str(item.get("artifact_type")): item for item in artifacts}
    failures: dict[str, list[dict[str, str]]] = {
        family: []
        for family in (
            "reference-analysis-evidence",
            "reference-to-production-translation",
            "production-panel-identity-continuity",
            "video-storyboard-master-completeness",
            "first-frame-correctness",
            "reference-role-mapping",
            "artifact-misuse-prevention",
            "end-to-end-provenance",
        )
    }

    def fail(family: str, code: str, message: str, artifact: Mapping[str, Any] | None, owner: str = "unknown") -> None:
        failures[family].append(_failure(family, code, message, artifact, owner=owner))

    if request.command == "review-composition":
        for artifact_type in sorted(REQUIRED_COMPOSITION_TYPES - set(by_type)):
            definition = BUSINESS_REGISTRY[artifact_type]
            fail(
                "end-to-end-provenance", "QA_CHAIN_ARTIFACT_MISSING",
                "Required storyboard-chain artifact is missing",
                {"artifact_type": artifact_type}, definition.owner,
            )

    analysis = by_type.get("avp.contract.reference-storyboard-analysis")
    if analysis:
        metadata = analysis.get("source_metadata")
        evidence = _as_mappings(analysis.get("shot_evidence"))
        beats = _as_mappings(analysis.get("beats"))
        valid_ranges = bool(beats) and all(
            isinstance(item.get("start_ms"), int)
            and isinstance(item.get("end_ms"), int)
            and item["end_ms"] > item["start_ms"] >= 0
            for item in beats
        )
        valid_evidence = bool(evidence) and all(
            isinstance(item.get("start_ms"), int)
            and isinstance(item.get("end_ms"), int)
            and item["end_ms"] > item["start_ms"] >= 0
            and item.get("keyframe_refs")
            and item.get("source_metadata_ref")
            and isinstance(item.get("comment_provenance"), (list, tuple))
            for item in evidence
        )
        if not isinstance(metadata, Mapping) or not metadata.get("source_ref") or not valid_ranges or not valid_evidence:
            fail("reference-analysis-evidence", "QA_REFERENCE_EVIDENCE_INCOMPLETE", "Reference evidence lacks real ranges, keyframes, source metadata, or comment provenance", analysis)
        if analysis.get("invented_content") is not False:
            fail("reference-analysis-evidence", "QA_REFERENCE_CONTENT_INVENTED", "Reference analysis contains invented or unverified content", analysis)

    product_context = subject.get("product_context_bundle")
    plan = by_type.get("avp.contract.production-storyboard-plan")
    if plan:
        if not isinstance(product_context, Mapping) or not plan.get("product_context_ref"):
            fail("reference-to-production-translation", "QA_PRODUCT_CONTEXT_MISSING", "Production translation requires ProductContextBundle", plan)
        if plan.get("copied_reference_identity") is not False or plan.get("copied_reference_fields"):
            fail("reference-to-production-translation", "QA_REFERENCE_IDENTITY_COPIED", "Reference people, brand, product, or packaging identity was copied", plan)
        if not plan.get("adapted_mechanisms"):
            fail("reference-to-production-translation", "QA_REPLICATION_MECHANISM_MISSING", "No reusable mechanism was adapted into the production plan", plan)

    panel_set = by_type.get("avp.contract.production-storyboard-panel-set")
    panels = _as_mappings(panel_set.get("panels")) if panel_set else []
    panel_by_id = {str(item.get("panel_id")): item for item in panels}
    panel_by_ref = {str(item.get("asset_ref")): item for item in panels}
    if panel_set:
        context_product = product_context.get("product_id") if isinstance(product_context, Mapping) else None
        context_sku = product_context.get("sku_id") if isinstance(product_context, Mapping) else None
        if not isinstance(product_context, Mapping) or not panel_set.get("product_context_ref"):
            fail("production-panel-identity-continuity", "QA_PRODUCT_CONTEXT_MISSING", "Production panels require ProductContextBundle", panel_set)
        if panel_set.get("product_id") != context_product or panel_set.get("sku_id") != context_sku:
            fail("production-panel-identity-continuity", "QA_PANEL_PRODUCT_MISMATCH", "Panel set product or SKU does not match ProductContextBundle", panel_set)
        required_continuity = {"scale", "character", "wardrobe", "product", "packaging", "container", "scene"}
        continuity = panel_set.get("continuity")
        if not isinstance(continuity, Mapping) or any(not continuity.get(key) for key in required_continuity):
            fail("production-panel-identity-continuity", "QA_PANEL_CONTINUITY_INCOMPLETE", "Panel continuity anchors are incomplete", panel_set)
        if not panels or any(item.get("approved") is not True or item.get("product_id") != context_product for item in panels):
            fail("production-panel-identity-continuity", "QA_PANEL_UNAPPROVED_OR_MISMATCHED", "A production panel is unapproved or belongs to another product", panel_set)
        approved_assets = set(product_context.get("approved_asset_refs", ())) if isinstance(product_context, Mapping) else set()
        if any(
            not item.get("source_asset_refs")
            or not set(item.get("source_asset_refs", ())).issubset(approved_assets)
            for item in panels
        ):
            fail("production-panel-identity-continuity", "QA_PANEL_SOURCE_ASSET_UNAPPROVED", "A production panel is not traced exclusively to approved product assets", panel_set)

    master = by_type.get("avp.contract.video-generation-storyboard-master")
    motion_plan = by_type.get("avp.contract.shot-motion-plan")
    shots = _as_mappings(master.get("shots")) if master else []
    if master:
        required_shot_fields = {
            "shot_id", "panel_id", "duration_ms", "start_state", "middle_state", "end_state",
            "motion", "emotion", "camera", "transition", "voiceover", "captions", "sound", "cta",
        }
        shot_order = [str(item.get("shot_id")) for item in shots]
        if not shots or master.get("shot_order") != tuple(shot_order) and master.get("shot_order") != shot_order:
            fail("video-storyboard-master-completeness", "QA_MASTER_SHOT_ORDER_MISMATCH", "Master shot order does not match ordered shots", master)
        if any(any(item.get(field) in (None, "") for field in required_shot_fields) for item in shots):
            fail("video-storyboard-master-completeness", "QA_MASTER_FIELD_MISSING", "Master duration, state, motion, audiovisual, or CTA data is incomplete", master)
        motions = _as_mappings(motion_plan.get("motions")) if motion_plan else []
        motion_shots = {str(item.get("shot_id")) for item in motions if item.get("motion")}
        if not motion_plan or motion_shots != set(shot_order):
            fail("video-storyboard-master-completeness", "QA_MOTION_PLAN_INCOMPLETE", "ShotMotionPlan does not cover every ordered shot", motion_plan or master, "storyboard-master-video-planning")

    first_frame = by_type.get("avp.contract.first-frame-mapping")
    if first_frame:
        first_shot = shots[0] if shots else {}
        panel = panel_by_id.get(str(first_frame.get("panel_id")))
        clean = (
            first_frame.get("asset_role") == "clean_full_frame_panel"
            and first_frame.get("approved") is True
            and not first_frame.get("contains_grid")
            and not first_frame.get("contains_numbering")
            and not first_frame.get("contains_label")
            and not first_frame.get("contains_text_overlay")
        )
        if not panel or panel.get("approved") is not True or first_frame.get("asset_ref") != panel.get("asset_ref"):
            fail("first-frame-correctness", "QA_FIRST_FRAME_PANEL_INVALID", "First frame is not an approved ProductionStoryboardPanelSet panel", first_frame)
        if first_frame.get("shot_id") != first_shot.get("shot_id") or first_frame.get("panel_id") != first_shot.get("panel_id"):
            fail("first-frame-correctness", "QA_FIRST_FRAME_SHOT_MISMATCH", "First frame does not map to the first ordered shot and panel", first_frame)
        if not clean or first_frame.get("aspect_ratio") != (master or {}).get("aspect_ratio"):
            fail("first-frame-correctness", "QA_FIRST_FRAME_NOT_CLEAN", "First frame is not one clean full-frame panel at the target aspect ratio", first_frame)

    role_map = by_type.get("avp.contract.reference-role-mapping")
    if role_map:
        mappings = _as_mappings(role_map.get("mappings"))
        refs = [str(item.get("asset_ref")) for item in mappings]
        invalid = not mappings or len(refs) != len(set(refs))
        for item in mappings:
            role = item.get("role")
            if role not in PERMITTED_REFERENCE_ROLES:
                invalid = True
            if item.get("asset_kind") in {"reference_analysis_board", "shot_evidence_board", "replication_board"}:
                invalid = invalid or role != "global_structure_reference" or item.get("provider_execution_input") is not False or item.get("first_frame_eligible") is not False
        if invalid:
            fail("reference-role-mapping", "QA_REFERENCE_ROLE_INVALID", "A reference has a duplicate, unsupported, or executable structural role", role_map)

    execution = by_type.get("avp.contract.video-execution-package")
    if execution:
        shot_order = list(execution.get("shot_order", ()))
        panel_order = list(execution.get("panel_order", ()))
        expected_panel_order = [str(item.get("panel_id")) for item in shots]
        if shot_order != list((master or {}).get("shot_order", ())) or panel_order != expected_panel_order:
            fail("artifact-misuse-prevention", "QA_EXECUTION_ORDER_MISMATCH", "Execution shot or panel order diverges from the master", execution)
        if any(ref not in panel_by_ref or panel_by_ref[ref].get("approved") is not True for ref in execution.get("panel_refs", ())):
            fail("artifact-misuse-prevention", "QA_EXECUTION_PANEL_UNAPPROVED", "Execution package contains an unapproved or foreign panel", execution)

    for artifact in artifacts:
        if artifact.get("artifact_type") == "avp.contract.production-storyboard-panel-set":
            if any(item.get("asset_kind") in FORBIDDEN_EXECUTION_KINDS for item in _as_mappings(artifact.get("panels"))):
                fail("artifact-misuse-prevention", "QA_ANALYSIS_BOARD_USED_AS_PANEL", "Analysis/evidence/replication board or contact sheet was used as a production panel", artifact)
    if first_frame and (
        first_frame.get("asset_kind") in FORBIDDEN_EXECUTION_KINDS
        or any(token in str(first_frame.get("asset_ref", "")) for token in ("analysis-board", "evidence-board", "replication-board", "contact-sheet", "contact_sheet"))
    ):
        fail("artifact-misuse-prevention", "QA_FORBIDDEN_FIRST_FRAME_ASSET", "Analysis board or contact sheet was used as the video first frame", first_frame)

    expected_revision = request.criteria.get("expected_revision", subject.get("revision"))
    artifact_ids = {str(item.get("artifact_id")) for item in artifacts if item.get("artifact_id")}
    external_refs: set[str] = set()
    if isinstance(product_context, Mapping):
        external_refs.add(str(product_context.get("artifact_ref", "")))
        external_refs.update(str(item) for item in product_context.get("approved_asset_refs", ()))
    if analysis and isinstance(analysis.get("source_metadata"), Mapping):
        external_refs.add(str(analysis["source_metadata"].get("source_ref", "")))
    external_refs.update(str(item) for item in request.context.get("available_artifact_refs", ()))
    external_refs.discard("")
    for artifact in artifacts:
        artifact_type = str(artifact.get("artifact_type", ""))
        definition = BUSINESS_REGISTRY.get(artifact_type)
        if artifact_type not in CHAIN_TYPES or definition is None:
            fail("end-to-end-provenance", "QA_ARTIFACT_IDENTITY_UNSUPPORTED", "Artifact identity is not canonical for the storyboard chain", artifact)
            continue
        if artifact.get("schema_version") != CANONICAL_VERSION:
            fail("end-to-end-provenance", "QA_ARTIFACT_VERSION_UNSUPPORTED", "Artifact version is not the canonical 1.0.0", artifact, definition.owner)
        if artifact.get("producer_component_id") != definition.owner:
            fail("end-to-end-provenance", "QA_ARTIFACT_PRODUCER_MISMATCH", "Artifact producer does not match the sole registered owner", artifact, definition.owner)
        if artifact.get("revision") != expected_revision:
            fail("end-to-end-provenance", "QA_ARTIFACT_REVISION_MISMATCH", "Artifact revision does not match the reviewed chain revision", artifact, definition.owner)
        if not HASH_PATTERN.fullmatch(str(artifact.get("immutable_hash", ""))):
            fail("end-to-end-provenance", "QA_ARTIFACT_HASH_INVALID", "Artifact immutable SHA-256 hash is missing or invalid", artifact, definition.owner)
        upstream_refs = tuple(str(item) for item in artifact.get("upstream_refs", ()))
        if not upstream_refs:
            fail("end-to-end-provenance", "QA_ARTIFACT_PROVENANCE_BROKEN", "Artifact has no immutable upstream provenance references", artifact, definition.owner)
        elif any(ref not in artifact_ids and ref not in external_refs for ref in upstream_refs):
            fail("end-to-end-provenance", "QA_ARTIFACT_PROVENANCE_BROKEN", "Artifact upstream provenance reference cannot be resolved within the reviewed chain", artifact, definition.owner)

    results: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []
    for family, family_failures in failures.items():
        result, emitted = _result(family, family_failures)
        results.append(result)
        issues.extend(emitted)
    return results, issues
