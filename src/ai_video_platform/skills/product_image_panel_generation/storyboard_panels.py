"""Canonical production-storyboard panel artifact chain."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Iterable

from ai_video_platform.contracts.serialization import canonical_json, content_digest, freeze_json, thaw_json

from .adapters import ImageProviderAdapter, ProviderAsset, ProviderInvocation
from .codec import generation_request_from_mapping
from .errors import ImagePanelError, ImagePanelErrorCode
from .models import GenerationOutcome, GenerationRequest, GenerationStatus, ItemStatus, ModelProfile
from .png import deterministic_png
from .prompting import compile_prompt
from .service import ImagePanelService


PANEL_PLAN_ARTIFACT = "ProductionStoryboardPanelPlan"
PANEL_PLAN_CONTRACT_ID = "avp.contract.production-storyboard-panel-plan"
PANEL_SET_ARTIFACT = "ProductionStoryboardPanelSet"
PANEL_SET_CONTRACT_ID = "avp.contract.production-storyboard-panel-set"
STORYBOARD_SCHEMA_VERSION = "1.0.0"
PANEL_SET_CONTRACT_STATUS = "IDENTITY_REGISTERED_SCHEMA_PENDING"
PROVIDER_STATE = "RC_PROVIDER_PENDING / NOT_AUTHORIZED"
REQUIRED_ANCHOR_CATEGORIES = (
    "product",
    "character",
    "wardrobe",
    "scene",
    "packaging",
    "container",
)
REQUIRED_CONTINUITY_FIELDS = (
    "character_anchor_id",
    "wardrobe_anchor_id",
    "scene_anchor_id",
    "product_state",
    "packaging_state",
    "container_state",
    "relative_scale",
)
FORBIDDEN_BOARD_IDENTITIES = frozenset(
    {
        "referencestoryboardanalysisboard",
        "shotevidenceboard",
        "replicationboard",
        "storyboardcontactsheet",
    }
)


@dataclass(frozen=True, slots=True)
class StoryboardPanelRequest:
    panel_plan: Mapping[str, Any]
    anchor_set: Mapping[str, Any]
    generation_request: GenerationRequest


def _fail(code: ImagePanelErrorCode, message: str, *field_paths: str) -> None:
    raise ImagePanelError(code, message, field_paths=tuple(field_paths))


def _object(value: object, field_path: str, code: ImagePanelErrorCode) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(code, "Storyboard panel input must be an object", field_path)
    return value


def _array(value: object, field_path: str, code: ImagePanelErrorCode) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or not value:
        _fail(code, "Storyboard panel input must be a non-empty array", field_path)
    return value


def _text(value: object, field_path: str, code: ImagePanelErrorCode) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(code, "Storyboard panel identity or text is missing", field_path)
    return value.strip()


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def storyboard_panel_request_from_mapping(value: object) -> StoryboardPanelRequest:
    if not isinstance(value, Mapping):
        _fail(ImagePanelErrorCode.CONTRACT_INVALID, "generate-panels input must be an object", "input")
    try:
        panel_plan = _object(value["panel_plan"], "panel_plan", ImagePanelErrorCode.PANEL_PLAN_INVALID)
        anchor_set = _object(value["anchor_set"], "anchor_set", ImagePanelErrorCode.ANCHOR_MISMATCH)
        generation_request = generation_request_from_mapping(value.get("request"))
    except ImagePanelError:
        raise
    except KeyError as exc:
        _fail(ImagePanelErrorCode.CONTRACT_INVALID, "generate-panels input is incomplete", str(exc.args[0]))
    return StoryboardPanelRequest(
        panel_plan=freeze_json(panel_plan),
        anchor_set=freeze_json(anchor_set),
        generation_request=generation_request,
    )


def _normalized_identity(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())


def _contains_forbidden_board(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_forbidden_board(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_forbidden_board(item) for item in value)
    return _normalized_identity(value) in FORBIDDEN_BOARD_IDENTITIES


def _manifest_assets(request: GenerationRequest) -> dict[str, Mapping[str, Any]]:
    assets: dict[str, Mapping[str, Any]] = {}
    for manifest in request.input_asset_manifests:
        payload = manifest.payload
        raw_assets = payload.get("assets", ()) if isinstance(payload, Mapping) else ()
        if isinstance(raw_assets, Sequence) and not isinstance(raw_assets, (str, bytes, bytearray)):
            for asset in raw_assets:
                if isinstance(asset, Mapping) and isinstance(asset.get("asset_id"), str):
                    assets[asset["asset_id"]] = asset
    return assets


def _approved_asset_ids(request: GenerationRequest) -> set[str]:
    context = request.product_context
    if context is None or not isinstance(context.payload, Mapping):
        return set()
    raw = context.payload.get("approved_asset_refs", context.payload.get("approved_asset_ids", ()))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return set()
    return {item for item in raw if isinstance(item, str)}


def _validate_plan_identity(plan: Mapping[str, Any], request: GenerationRequest) -> Sequence[Any]:
    expected = {
        "artifact_type": PANEL_PLAN_ARTIFACT,
        "contract_id": PANEL_PLAN_CONTRACT_ID,
        "schema_version": STORYBOARD_SCHEMA_VERSION,
    }
    for field, expected_value in expected.items():
        if plan.get(field) != expected_value:
            _fail(ImagePanelErrorCode.PANEL_PLAN_INVALID, "Production storyboard panel plan identity is invalid", f"panel_plan.{field}")
    producer = _object(plan.get("producer"), "panel_plan.producer", ImagePanelErrorCode.PANEL_PLAN_INVALID)
    if producer.get("skill_id") != "storyboard":
        _fail(ImagePanelErrorCode.PANEL_PLAN_INVALID, "Production storyboard panel plan producer is invalid", "panel_plan.producer.skill_id")
    approval = _object(plan.get("approval"), "panel_plan.approval", ImagePanelErrorCode.PANEL_PLAN_INVALID)
    if approval.get("status") != "approved" or not isinstance(approval.get("approval_ref"), str):
        _fail(ImagePanelErrorCode.PANEL_PLAN_INVALID, "Production storyboard panel plan is not approved", "panel_plan.approval")
    if plan.get("product_id") != request.product_id or plan.get("sku_id") != request.sku_id:
        _fail(ImagePanelErrorCode.PANEL_PLAN_INVALID, "Panel plan product identity does not match the generation request", "panel_plan.product_id", "panel_plan.sku_id")
    panels = _array(plan.get("panels"), "panel_plan.panels", ImagePanelErrorCode.PANEL_PLAN_INVALID)
    return panels


def _validate_reference_board_boundary(request: StoryboardPanelRequest) -> None:
    generation = request.generation_request
    candidates: list[object] = [request.panel_plan.get("production_master"), generation.reference_manifest.payload if generation.reference_manifest else None]
    candidates.extend(
        {
            "role": item.role,
            "input_asset_ids": item.input_asset_ids,
        }
        for item in generation.items
    )
    for manifest in generation.input_asset_manifests:
        candidates.append(manifest.payload)
    if _contains_forbidden_board(candidates):
        _fail(
            ImagePanelErrorCode.REFERENCE_BOARD_MISUSE,
            "Reference analysis boards and contact sheets cannot be production panel or Provider inputs",
            "panel_inputs",
        )


def _validate_anchors(
    anchor_set: Mapping[str, Any],
    request: GenerationRequest,
    manifest_assets: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    if anchor_set.get("product_id") != request.product_id or anchor_set.get("sku_id") != request.sku_id:
        _fail(ImagePanelErrorCode.ANCHOR_MISMATCH, "AnchorSet product identity does not match the generation request", "anchor_set.product_id", "anchor_set.sku_id")
    anchors = _object(anchor_set.get("anchors"), "anchor_set.anchors", ImagePanelErrorCode.ANCHOR_MISMATCH)
    approved = _approved_asset_ids(request)
    validated: dict[str, Mapping[str, Any]] = {}
    asset_roles: dict[str, str] = {}
    for category in REQUIRED_ANCHOR_CATEGORIES:
        anchor = _object(anchors.get(category), f"anchor_set.anchors.{category}", ImagePanelErrorCode.ANCHOR_MISMATCH)
        _text(anchor.get("anchor_id"), f"anchor_set.anchors.{category}.anchor_id", ImagePanelErrorCode.ANCHOR_MISMATCH)
        asset_ids = _array(anchor.get("asset_ids"), f"anchor_set.anchors.{category}.asset_ids", ImagePanelErrorCode.ANCHOR_MISMATCH)
        for index, asset_id in enumerate(asset_ids):
            if not isinstance(asset_id, str) or asset_id not in approved:
                _fail(ImagePanelErrorCode.ANCHOR_MISMATCH, "Anchor asset is not approved by ProductContextBundle", f"anchor_set.anchors.{category}.asset_ids[{index}]")
            asset = manifest_assets.get(asset_id)
            if not isinstance(asset, Mapping) or not asset.get("approval_ref") or asset.get("role") != category:
                _fail(ImagePanelErrorCode.ANCHOR_MISMATCH, "Anchor asset role or approval does not match", f"anchor_set.anchors.{category}.asset_ids[{index}]")
            existing_role = asset_roles.setdefault(asset_id, category)
            if existing_role != category:
                _fail(ImagePanelErrorCode.ANCHOR_MISMATCH, "One approved asset cannot satisfy multiple anchor categories", f"anchor_set.anchors.{category}.asset_ids[{index}]")
        validated[category] = anchor
    return validated, asset_roles


def _validate_scale(
    continuity: Mapping[str, Any],
    constraints: Mapping[str, Any],
    panel_path: str,
) -> None:
    scales = _object(continuity.get("relative_scale"), f"{panel_path}.continuity.relative_scale", ImagePanelErrorCode.CONTINUITY_INVALID)
    if not constraints:
        _fail(ImagePanelErrorCode.CONTINUITY_INVALID, "Relative scale constraints are required", "anchor_set.relative_scale_constraints")
    for name, raw_constraint in constraints.items():
        constraint = _object(raw_constraint, f"anchor_set.relative_scale_constraints.{name}", ImagePanelErrorCode.CONTINUITY_INVALID)
        value = scales.get(name)
        minimum = constraint.get("minimum")
        maximum = constraint.get("maximum")
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        bounds = isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and isinstance(maximum, (int, float)) and not isinstance(maximum, bool)
        if not numeric or not bounds or minimum > maximum or not minimum <= value <= maximum:
            _fail(ImagePanelErrorCode.CONTINUITY_INVALID, "Panel relative scale is outside approved constraints", f"{panel_path}.continuity.relative_scale.{name}")


def _validate_continuity_change(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    changes: object,
    panel_path: str,
) -> None:
    changes_map = _object(changes, f"{panel_path}.continuity_changes", ImagePanelErrorCode.CONTINUITY_INVALID)
    changed_keys = {key for key in previous if previous.get(key) != current.get(key)}
    if set(changes_map) != changed_keys:
        _fail(ImagePanelErrorCode.CONTINUITY_INVALID, "Continuity changes must exactly declare every changed field", f"{panel_path}.continuity_changes")
    for key in changed_keys:
        declaration = _object(changes_map.get(key), f"{panel_path}.continuity_changes.{key}", ImagePanelErrorCode.CONTINUITY_INVALID)
        reason = declaration.get("reason")
        if declaration.get("from") != previous.get(key) or declaration.get("to") != current.get(key) or not isinstance(reason, str) or not reason.strip():
            _fail(ImagePanelErrorCode.CONTINUITY_INVALID, "Continuity transition must bind exact from/to values and a reason", f"{panel_path}.continuity_changes.{key}")


def _validate_panel_coverage(
    panels: Sequence[Any],
    anchor_set: Mapping[str, Any],
    anchors: Mapping[str, Mapping[str, Any]],
    asset_roles: Mapping[str, str],
    request: GenerationRequest,
) -> list[Mapping[str, Any]]:
    plan_panels: list[Mapping[str, Any]] = []
    seen_panel_ids: set[str] = set()
    expected_sequences = list(range(1, len(panels) + 1))
    actual_sequences: list[int] = []
    previous_continuity: Mapping[str, Any] | None = None
    constraints = _object(anchor_set.get("relative_scale_constraints"), "anchor_set.relative_scale_constraints", ImagePanelErrorCode.CONTINUITY_INVALID)
    aspect_ratio = _text(anchor_set.get("aspect_ratio", ""), "anchor_set.aspect_ratio", ImagePanelErrorCode.PANEL_PLAN_INVALID) if "aspect_ratio" in anchor_set else _text(requested_aspect_ratio := "", "unused", ImagePanelErrorCode.PANEL_PLAN_INVALID)
    del aspect_ratio, requested_aspect_ratio

    for index, raw_panel in enumerate(panels):
        panel_path = f"panel_plan.panels[{index}]"
        panel = _object(raw_panel, panel_path, ImagePanelErrorCode.PANEL_PLAN_INVALID)
        panel_id = _text(panel.get("panel_id"), f"{panel_path}.panel_id", ImagePanelErrorCode.PANEL_PLAN_INVALID)
        _text(panel.get("shot_id"), f"{panel_path}.shot_id", ImagePanelErrorCode.PANEL_PLAN_INVALID)
        _text(panel.get("prompt"), f"{panel_path}.prompt", ImagePanelErrorCode.PANEL_PLAN_INVALID)
        if panel_id in seen_panel_ids:
            _fail(ImagePanelErrorCode.PANEL_PLAN_COVERAGE_INVALID, "Panel identities must be unique", f"{panel_path}.panel_id")
        seen_panel_ids.add(panel_id)
        sequence = panel.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            _fail(ImagePanelErrorCode.PANEL_PLAN_INVALID, "Panel sequence must be an integer", f"{panel_path}.sequence")
        actual_sequences.append(sequence)
        width = panel.get("width")
        height = panel.get("height")
        if not isinstance(width, int) or isinstance(width, bool) or not isinstance(height, int) or isinstance(height, bool) or width < 1 or height < 1:
            _fail(ImagePanelErrorCode.PANEL_PLAN_INVALID, "Panel dimensions must be positive integers", f"{panel_path}.width", f"{panel_path}.height")
        approved_ids = _array(panel.get("approved_asset_ids"), f"{panel_path}.approved_asset_ids", ImagePanelErrorCode.PANEL_PLAN_INVALID)
        if any(not isinstance(asset_id, str) or asset_id not in asset_roles for asset_id in approved_ids):
            _fail(ImagePanelErrorCode.ANCHOR_MISMATCH, "Panel source assets must come from the approved AnchorSet", f"{panel_path}.approved_asset_ids")
        panel_roles = {asset_roles[asset_id] for asset_id in approved_ids}
        if panel_roles != set(REQUIRED_ANCHOR_CATEGORIES):
            _fail(ImagePanelErrorCode.ANCHOR_MISMATCH, "Every panel requires all six approved anchor categories", f"{panel_path}.approved_asset_ids")
        continuity = _object(panel.get("continuity"), f"{panel_path}.continuity", ImagePanelErrorCode.CONTINUITY_INVALID)
        for field in REQUIRED_CONTINUITY_FIELDS:
            if field not in continuity:
                _fail(ImagePanelErrorCode.CONTINUITY_INVALID, "Panel continuity state is incomplete", f"{panel_path}.continuity.{field}")
        anchor_bindings = {
            "character_anchor_id": anchors["character"]["anchor_id"],
            "wardrobe_anchor_id": anchors["wardrobe"]["anchor_id"],
            "scene_anchor_id": anchors["scene"]["anchor_id"],
        }
        for field, expected in anchor_bindings.items():
            if continuity.get(field) != expected:
                _fail(ImagePanelErrorCode.CONTINUITY_INVALID, "Panel continuity references an unapproved anchor", f"{panel_path}.continuity.{field}")
        _validate_scale(continuity, constraints, panel_path)
        if previous_continuity is not None:
            _validate_continuity_change(previous_continuity, continuity, panel.get("continuity_changes", {}), panel_path)
        elif panel.get("continuity_changes") not in ({}, None):
            _fail(ImagePanelErrorCode.CONTINUITY_INVALID, "The first panel cannot declare a prior continuity transition", f"{panel_path}.continuity_changes")
        previous_continuity = continuity
        plan_panels.append(panel)

    if actual_sequences != expected_sequences:
        _fail(ImagePanelErrorCode.PANEL_PLAN_COVERAGE_INVALID, "Panel sequence must be contiguous and ordered", "panel_plan.panels.sequence")
    items = request.items
    if len(items) != len(plan_panels) or [item.item_id for item in items] != [panel["panel_id"] for panel in plan_panels]:
        _fail(ImagePanelErrorCode.PANEL_PLAN_COVERAGE_INVALID, "Generation request does not cover the full panel plan in order", "request.items")
    for index, (item, panel) in enumerate(zip(items, plan_panels, strict=True)):
        if (
            item.role != "production-storyboard-panel"
            or item.prompt != panel["prompt"]
            or item.width != panel["width"]
            or item.height != panel["height"]
            or item.input_asset_ids != tuple(panel["approved_asset_ids"])
        ):
            _fail(ImagePanelErrorCode.PANEL_PLAN_COVERAGE_INVALID, "Generation item does not exactly bind its planned panel", f"request.items[{index}]")
    return plan_panels


def _validate_aspect_ratio(plan: Mapping[str, Any], panels: Sequence[Mapping[str, Any]]) -> None:
    value = _text(plan.get("aspect_ratio"), "panel_plan.aspect_ratio", ImagePanelErrorCode.PANEL_PLAN_INVALID)
    try:
        width_text, height_text = value.split(":", 1)
        ratio_width = int(width_text)
        ratio_height = int(height_text)
    except (ValueError, AttributeError) as exc:
        raise ImagePanelError(ImagePanelErrorCode.PANEL_PLAN_INVALID, "Panel plan aspect ratio is invalid", field_paths=("panel_plan.aspect_ratio",)) from exc
    if ratio_width < 1 or ratio_height < 1:
        _fail(ImagePanelErrorCode.PANEL_PLAN_INVALID, "Panel plan aspect ratio is invalid", "panel_plan.aspect_ratio")
    for index, panel in enumerate(panels):
        if panel["width"] * ratio_height != panel["height"] * ratio_width:
            _fail(ImagePanelErrorCode.PANEL_PLAN_INVALID, "Panel dimensions do not match the declared aspect ratio", f"panel_plan.panels[{index}].width", f"panel_plan.panels[{index}].height")


def _write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(value))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _panel_asset_by_item(outcome: GenerationOutcome) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    assets = outcome.asset_manifest.payload.get("assets", ())
    for asset in assets:
        if isinstance(asset, Mapping):
            asset_id = asset.get("asset_id")
            if isinstance(asset_id, str):
                for record in outcome.generation_record.items:
                    if record.asset_id == asset_id:
                        result[record.item_id] = asset
                        break
    return result


class ProductionStoryboardPanelService:
    """Validate a canonical panel plan and persist its task-local artifact chain."""

    def __init__(
        self,
        *,
        provider: ImageProviderAdapter,
        profiles: Iterable[ModelProfile],
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        max_concurrency: int = 1,
    ) -> None:
        self._provider = provider
        self._profiles = tuple(profiles)
        self._profile_by_id = {profile.profile_id: profile for profile in self._profiles}
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        self._max_concurrency = max_concurrency

    def generate_panels(self, request: StoryboardPanelRequest, *, output_root: Path) -> GenerationOutcome:
        if not isinstance(request, StoryboardPanelRequest):
            raise TypeError("request must be StoryboardPanelRequest")
        plan = request.panel_plan
        generation = request.generation_request
        panels = _validate_plan_identity(plan, generation)
        _validate_reference_board_boundary(request)
        manifest_assets = _manifest_assets(generation)
        anchors, asset_roles = _validate_anchors(request.anchor_set, generation, manifest_assets)
        validated_panels = _validate_panel_coverage(panels, request.anchor_set, anchors, asset_roles, generation)
        _validate_aspect_ratio(plan, validated_panels)
        if output_root.exists():
            _fail(ImagePanelErrorCode.CONTRACT_INVALID, "Production storyboard panel output already exists", "output_root")

        captured_assets: dict[str, ProviderAsset] = {}

        def capture(invocation: ProviderInvocation, asset: ProviderAsset) -> None:
            captured_assets[invocation.item.item_id] = asset

        service = ImagePanelService(
            provider=self._provider,
            profiles=self._profiles,
            now=self._now,
            sleep=self._sleep,
            max_concurrency=self._max_concurrency,
            asset_sink=capture,
        )
        outcome = service.generate_panel(generation)
        self._persist_artifacts(
            request,
            validated_panels,
            outcome,
            captured_assets,
            output_root=output_root,
        )
        return outcome

    def _persist_artifacts(
        self,
        request: StoryboardPanelRequest,
        panels: Sequence[Mapping[str, Any]],
        outcome: GenerationOutcome,
        captured_assets: Mapping[str, ProviderAsset],
        *,
        output_root: Path,
    ) -> None:
        parent = output_root.parent
        staging = parent / f".{output_root.name}.{os.getpid()}.tmp"
        if staging.exists():
            raise ImagePanelError(ImagePanelErrorCode.CONTRACT_INVALID, "Storyboard artifact staging path already exists", field_paths=("output_root",))
        try:
            (staging / "panel_images").mkdir(parents=True)
            profile = self._profile_by_id[request.generation_request.model_profile_id]
            generated_at = _utc_text(self._now())
            asset_metadata = _panel_asset_by_item(outcome)
            records = {record.item_id: record for record in outcome.generation_record.items}
            prompt_records: list[dict[str, Any]] = []
            panel_records: list[dict[str, Any]] = []
            qa_panels: list[dict[str, Any]] = []

            for panel, item in zip(panels, request.generation_request.items, strict=True):
                record = records[item.item_id]
                prompt_records.append(
                    {
                        "panel_id": panel["panel_id"],
                        "shot_id": panel["shot_id"],
                        "prompt": panel["prompt"],
                        "compiled_prompt": compile_prompt(request.generation_request, item),
                        "request_hash": request.generation_request.request_hash,
                        "model_profile_id": profile.profile_id,
                        "model_profile_digest": request.generation_request.model_profile_digest,
                        "provider_id": profile.provider_id,
                        "model_id": profile.model_id,
                        "model_version": profile.version,
                        "width": panel["width"],
                        "height": panel["height"],
                        "approved_source_asset_ids": list(panel["approved_asset_ids"]),
                    }
                )
                asset_record: dict[str, Any] | None = None
                qa_status = "failed_generation"
                if record.status is ItemStatus.COMPLETED:
                    captured = captured_assets[item.item_id]
                    image_bytes = bytes(captured.content)
                    image_path = staging / "panel_images" / f"{panel['panel_id']}.png"
                    with image_path.open("xb") as stream:
                        stream.write(image_bytes)
                        stream.flush()
                        os.fsync(stream.fileno())
                    digest = hashlib.sha256(image_bytes).hexdigest()
                    metadata = asset_metadata[item.item_id]
                    dimensions = thaw_json(metadata["dimensions"])
                    asset_record = {
                        "asset_id": record.asset_id,
                        "role": "production-storyboard-panel",
                        "relative_path": f"panel_images/{panel['panel_id']}.png",
                        "content_type": captured.content_type,
                        "byte_size": len(image_bytes),
                        "sha256": digest,
                        "dimensions": dimensions,
                        "provider_asset_id": captured.provider_asset_id,
                        "individual_panel": True,
                        "first_frame_eligible": True,
                        "provider_execution_input": True,
                    }
                    qa_status = "pass"
                panel_records.append(
                    {
                        "panel_id": panel["panel_id"],
                        "shot_id": panel["shot_id"],
                        "sequence": panel["sequence"],
                        "generation_status": record.status.value,
                        "qa_status": qa_status,
                        "asset": asset_record,
                        "prompt_ref": f"panel_prompts.json#{panel['panel_id']}",
                        "approved_source_asset_ids": list(panel["approved_asset_ids"]),
                        "continuity": thaw_json(panel["continuity"]),
                        "continuity_changes": thaw_json(panel.get("continuity_changes", {})),
                        "error": thaw_json(record.error) if record.error is not None else None,
                    }
                )
                qa_panels.append(
                    {
                        "panel_id": panel["panel_id"],
                        "shot_id": panel["shot_id"],
                        "generation_status": record.status.value,
                        "qa_status": qa_status,
                        "checks": {
                            "product_identity": "pass" if qa_status == "pass" else "not_run",
                            "approved_anchor_coverage": "pass" if qa_status == "pass" else "not_run",
                            "relative_scale": "pass" if qa_status == "pass" else "not_run",
                        },
                    }
                )

            contact_sheet_bytes = deterministic_png(
                max(panel["width"] for panel in panels),
                max(panel["height"] for panel in panels),
                seed=":".join(f"{record['panel_id']}:{record['generation_status']}" for record in panel_records),
            )
            contact_sheet_path = staging / "storyboard_contact_sheet.png"
            with contact_sheet_path.open("xb") as stream:
                stream.write(contact_sheet_bytes)
                stream.flush()
                os.fsync(stream.fileno())

            plan_digest = content_digest(request.panel_plan)
            panel_set = {
                "artifact_type": PANEL_SET_ARTIFACT,
                "contract_id": PANEL_SET_CONTRACT_ID,
                "schema_version": STORYBOARD_SCHEMA_VERSION,
                "contract_status": PANEL_SET_CONTRACT_STATUS,
                "artifact_id": f"production-storyboard-panel-set:{request.generation_request.request_id}",
                "producer": {"skill_id": "product-image-panel-generation", "workline_id": "codex-04"},
                "product_id": request.generation_request.product_id,
                "sku_id": request.generation_request.sku_id,
                "status": outcome.status.value,
                "panel_plan": {
                    "artifact_id": request.panel_plan.get("artifact_id"),
                    "contract_id": PANEL_PLAN_CONTRACT_ID,
                    "schema_version": STORYBOARD_SCHEMA_VERSION,
                    "content_digest": plan_digest,
                    "approval_ref": request.panel_plan["approval"]["approval_ref"],
                },
                "request_hash": request.generation_request.request_hash,
                "panels": panel_records,
                "contact_sheet": {
                    "relative_path": "storyboard_contact_sheet.png",
                    "sha256": hashlib.sha256(contact_sheet_bytes).hexdigest(),
                    "byte_size": len(contact_sheet_bytes),
                    "role": "human_review_only",
                    "individual_panel": False,
                    "first_frame_eligible": False,
                    "provider_execution_input": False,
                },
                "generated_at": generated_at,
            }
            all_completed = outcome.status is GenerationStatus.COMPLETED
            qa_report = {
                "artifact_type": "ProductionStoryboardPanelQAReport",
                "schema_version": STORYBOARD_SCHEMA_VERSION,
                "panel_set_ref": panel_set["artifact_id"],
                "overall_status": "pass" if all_completed else "fail",
                "set_checks": {
                    "panel_plan_coverage": "pass",
                    "product_identity": "pass",
                    "approved_anchor_coverage": "pass",
                    "relative_scale": "pass",
                    "cross_panel_continuity": "pass",
                    "contact_sheet_non_executable": "pass",
                },
                "panels": qa_panels,
                "generated_at": generated_at,
            }
            prompts = {
                "artifact_type": "ProductionStoryboardPanelPromptSet",
                "schema_version": STORYBOARD_SCHEMA_VERSION,
                "request_hash": request.generation_request.request_hash,
                "panels": prompt_records,
            }
            provenance = {
                "artifact_type": "ProductionStoryboardPanelGenerationProvenance",
                "schema_version": STORYBOARD_SCHEMA_VERSION,
                "panel_set_ref": panel_set["artifact_id"],
                "panel_plan_digest": plan_digest,
                "request_hash": request.generation_request.request_hash,
                "product_context_contract_id": str(request.generation_request.product_context.contract_id),
                "input_asset_manifest_contract_ids": [str(item.contract_id) for item in request.generation_request.input_asset_manifests],
                "model_profile": {
                    "profile_id": profile.profile_id,
                    "digest": request.generation_request.model_profile_digest,
                    "provider_id": profile.provider_id,
                    "model_id": profile.model_id,
                    "model_version": profile.version,
                },
                "provider_network_performed": False,
                "provider_state": PROVIDER_STATE,
                "provider_smoke": "NOT_REQUIRED",
                "generated_at": generated_at,
            }

            _write_json(staging / "panel_plan.json", thaw_json(request.panel_plan))
            _write_json(staging / "panel_prompts.json", prompts)
            _write_json(staging / "production_storyboard_panel_set.json", panel_set)
            _write_json(staging / "panel_qa_report.json", qa_report)
            _write_json(staging / "panel_generation_provenance.json", provenance)
            os.replace(staging, output_root)
        except ImagePanelError:
            raise
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ImagePanelError(
                ImagePanelErrorCode.CONTRACT_INVALID,
                "Production storyboard panel artifacts could not be persisted",
                field_paths=("output_root",),
                details={"cause_type": type(exc).__name__},
            ) from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging)
