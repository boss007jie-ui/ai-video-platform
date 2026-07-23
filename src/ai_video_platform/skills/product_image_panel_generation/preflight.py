"""Fail-closed validation before image/panel generation side effects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from ai_video_platform.contracts import ContractError, ContractEnvelope, validate_envelope

from .errors import ImagePanelError, ImagePanelErrorCode
from .models import (
    GenerationCommand,
    GenerationRequest,
    ModelProfile,
    PreflightInspection,
    calculate_model_profile_digest,
    calculate_request_hash,
)
from .product_data import to_product_facts


SKILL_ID = "product-image-panel-generation"


def _fail(code: ImagePanelErrorCode, message: str, *field_paths: str, category: str = "validation") -> None:
    raise ImagePanelError(code, message, category=category, field_paths=tuple(field_paths))


def _validated(envelope: ContractEnvelope, expected_type: str):
    if envelope.contract_type != expected_type:
        _fail(ImagePanelErrorCode.CONTRACT_INVALID, "Unexpected foundation contract type", "contract_type")
    try:
        return validate_envelope(envelope).payload
    except (ContractError, KeyError, ValueError) as exc:
        raise ImagePanelError(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "Foundation contract validation failed",
            field_paths=("contract",),
            details={"cause_type": type(exc).__name__},
        ) from exc


def _parse_utc(value: object, field_path: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail(ImagePanelErrorCode.APPROVAL_NOT_EFFECTIVE, "Approval timestamp must use UTC Z form", field_path)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ImagePanelError(
            ImagePanelErrorCode.APPROVAL_NOT_EFFECTIVE,
            "Approval timestamp is invalid",
            field_paths=(field_path,),
        ) from exc
    return parsed


def _assert_task_relation(
    envelope: ContractEnvelope,
    *,
    task_id: str,
    correlation_id: str,
    field_path: str,
) -> None:
    if envelope.task_id is not None and envelope.task_id != task_id:
        _fail(ImagePanelErrorCode.CONTRACT_INVALID, "Input contract task_id is unrelated", f"{field_path}.task_id")
    if envelope.correlation_id != correlation_id and not envelope.extensions.get("external_relation"):
        _fail(
            ImagePanelErrorCode.CONTRACT_INVALID,
            "Input contract correlation is unrelated and has no explicit external relation",
            f"{field_path}.correlation_id",
        )


def inspect_request(
    request: GenerationRequest,
    *,
    profiles: Mapping[str, ModelProfile],
    now: datetime,
) -> PreflightInspection:
    if request.command not in {GenerationCommand.GENERATE_PRODUCT_IMAGE, GenerationCommand.GENERATE_PANEL}:
        _fail(ImagePanelErrorCode.SKILL_BINDING_INVALID, "Command is not a generation command", "command")
    if not request.request_id or not request.idempotency_key or not request.items:
        _fail(ImagePanelErrorCode.CONTRACT_INVALID, "Request identity and at least one item are required", "request")

    task_spec = _validated(request.task_spec, "avp.contract.task-spec")
    task_context = _validated(request.task_context, "avp.contract.task-context")
    if task_spec.task_id != task_context.task_id:
        _fail(ImagePanelErrorCode.CONTRACT_INVALID, "Task identities do not match", "task_id")
    if request.task_spec.task_id is not None and request.task_spec.task_id != task_spec.task_id:
        _fail(ImagePanelErrorCode.CONTRACT_INVALID, "TaskSpec envelope task_id does not match its payload", "task_spec.task_id")
    _assert_task_relation(
        request.task_context,
        task_id=task_spec.task_id,
        correlation_id=request.task_spec.correlation_id,
        field_path="task_context",
    )
    if task_context.active_skill_id != SKILL_ID or SKILL_ID not in task_spec.requested_skills:
        _fail(ImagePanelErrorCode.SKILL_BINDING_INVALID, "Task is not bound to this Skill", "task_context.active_skill_id")
    if task_context.context_revision != request.expected_context_revision:
        _fail(ImagePanelErrorCode.STALE_INPUT, "TaskContext revision is stale", "expected_context_revision")

    if request.product_context is None:
        _fail(ImagePanelErrorCode.PRODUCT_CONTEXT_REQUIRED, "ProductContextBundle is required", "product_context")
    _validated(request.product_context, "avp.contract.product-context-bundle")
    product_facts = to_product_facts(request.product_context)
    _assert_task_relation(
        request.product_context,
        task_id=task_spec.task_id,
        correlation_id=request.task_spec.correlation_id,
        field_path="product_context",
    )
    if product_facts.product_id != request.product_id:
        _fail(ImagePanelErrorCode.PRODUCT_IDENTITY_MISMATCH, "Product identity does not match ProductContextBundle", "product_id")
    if request.sku_id != product_facts.sku_id:
        _fail(ImagePanelErrorCode.PRODUCT_IDENTITY_MISMATCH, "SKU identity does not match ProductContextBundle", "sku_id")

    approved_asset_ids = set(product_facts.approved_asset_ids)
    manifest_assets: dict[str, object] = {}
    for envelope in request.input_asset_manifests:
        manifest = _validated(envelope, "avp.contract.asset-manifest")
        _assert_task_relation(
            envelope,
            task_id=task_spec.task_id,
            correlation_id=request.task_spec.correlation_id,
            field_path="input_asset_manifests",
        )
        owner_matches = (
            (manifest.owner_type == "product" and manifest.owner_id == request.product_id)
            or (manifest.owner_type == "task" and manifest.owner_id == task_spec.task_id)
        )
        if not owner_matches:
            _fail(
                ImagePanelErrorCode.ASSET_NOT_APPROVED,
                "Input AssetManifest owner does not match the product or task",
                "input_asset_manifests.owner_id",
            )
        for asset in manifest.assets:
            if isinstance(asset, Mapping) and isinstance(asset.get("asset_id"), str):
                manifest_assets[asset["asset_id"]] = asset
    for index, item in enumerate(request.items):
        for asset_id in item.input_asset_ids:
            asset = manifest_assets.get(asset_id)
            if asset_id not in approved_asset_ids or not isinstance(asset, Mapping) or not asset.get("approval_ref"):
                _fail(ImagePanelErrorCode.ASSET_NOT_APPROVED, "Input asset is not approved", f"items[{index}].input_asset_ids")

    if request.reference_manifest is not None:
        references = _validated(request.reference_manifest, "avp.contract.reference-manifest")
        _assert_task_relation(
            request.reference_manifest,
            task_id=task_spec.task_id,
            correlation_id=request.task_spec.correlation_id,
            field_path="reference_manifest",
        )
        if references.task_id != task_spec.task_id:
            _fail(
                ImagePanelErrorCode.CONTRACT_INVALID,
                "ReferenceManifest task_id does not match the active task",
                "reference_manifest.task_id",
            )
        if references.references and not references.rights_assertion:
            _fail(
                ImagePanelErrorCode.REFERENCE_RIGHTS_UNCONFIRMED,
                "Reference rights assertion is required",
                "reference_manifest.rights_assertion",
            )

    profile = profiles.get(request.model_profile_id)
    if profile is None or profile.profile_id != request.model_profile_id:
        _fail(ImagePanelErrorCode.MODEL_PROFILE_INVALID, "Model profile is not configured", "model_profile_id")
    if (
        profile.cost_per_attempt <= 0
        or profile.min_dimension <= 0
        or profile.max_dimension < profile.min_dimension
        or profile.dimension_multiple <= 0
        or profile.max_concurrency <= 0
        or calculate_model_profile_digest(profile) != request.model_profile_digest
    ):
        _fail(
            ImagePanelErrorCode.MODEL_PROFILE_INVALID,
            "Model profile is invalid or does not match the approved profile digest",
            "model_profile_digest",
        )
    for index, item in enumerate(request.items):
        for value, name in ((item.width, "width"), (item.height, "height")):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < profile.min_dimension
                or value > profile.max_dimension
                or value % profile.dimension_multiple
            ):
                _fail(ImagePanelErrorCode.DIMENSIONS_INVALID, "Dimensions are outside the approved model profile", f"items[{index}].{name}")

    budget = request.budget
    if budget is None:
        _fail(ImagePanelErrorCode.BUDGET_REQUIRED, "Generation budget is required", "budget")
    if (
        budget.currency != "COST_UNITS"
        or budget.max_cost_units < 0
        or budget.max_attempts < 1
        or budget.timeout_seconds <= 0
        or budget.max_concurrency < 1
    ):
        _fail(ImagePanelErrorCode.BUDGET_REQUIRED, "Generation budget is invalid", "budget")
    if budget.max_concurrency > profile.max_concurrency:
        _fail(
            ImagePanelErrorCode.CONCURRENCY_LIMIT_EXCEEDED,
            "Requested concurrency exceeds the approved model profile",
            "budget.max_concurrency",
            category="authorization",
        )
    estimated_max_cost = len(request.items) * budget.max_attempts * profile.cost_per_attempt
    if estimated_max_cost > budget.max_cost_units:
        _fail(ImagePanelErrorCode.BUDGET_EXCEEDED, "Worst-case generation cost exceeds the approved budget", "budget.max_cost_units")

    expected_hash = calculate_request_hash(request)
    if request.request_hash != expected_hash:
        _fail(ImagePanelErrorCode.REQUEST_HASH_MISMATCH, "Request hash does not match canonical inputs", "request_hash")

    if request.approval_record is None:
        _fail(ImagePanelErrorCode.APPROVAL_REQUIRED, "ApprovalRecord is required", "approval_record")
    approval = _validated(request.approval_record, "avp.contract.approval-record")
    _assert_task_relation(
        request.approval_record,
        task_id=task_spec.task_id,
        correlation_id=request.task_spec.correlation_id,
        field_path="approval_record",
    )
    if approval.outcome != "approved":
        _fail(ImagePanelErrorCode.APPROVAL_NOT_EFFECTIVE, "ApprovalRecord is not approved", "approval_record.outcome", category="authorization")
    subject = approval.subject_ref
    if not isinstance(subject, Mapping) or subject.get("request_id") != request.request_id or subject.get("digest") != request.request_hash:
        _fail(ImagePanelErrorCode.APPROVAL_SUBJECT_MISMATCH, "ApprovalRecord does not bind this request", "approval_record.subject_ref", category="authorization")
    if approval.valid_until is not None and _parse_utc(approval.valid_until, "approval_record.valid_until") <= now.astimezone(timezone.utc):
        _fail(ImagePanelErrorCode.APPROVAL_NOT_EFFECTIVE, "ApprovalRecord has expired", "approval_record.valid_until", category="authorization")

    return PreflightInspection(
        approved=True,
        request_hash=request.request_hash,
        estimated_max_cost_units=estimated_max_cost,
        item_count=len(request.items),
        profile_id=profile.profile_id,
        product_facts=product_facts,
    )
