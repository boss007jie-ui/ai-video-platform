from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from ai_video_platform.contracts import ProducerIdentity, build_envelope
from ai_video_platform.contracts.serialization import thaw_json
from ai_video_platform.skills.product_image_panel_generation import (
    GenerationBudget,
    GenerationCommand,
    GenerationItem,
    GenerationRequest,
    ModelProfile,
    calculate_model_profile_digest,
    calculate_request_hash,
)


NOW = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
NOW_TEXT = "2026-07-20T10:00:00Z"
PRODUCT_ID = "product-synthetic-004"
TASK_ID = "task-synthetic-004"
ASSET_ID = "asset-approved-004"


def _envelope(contract_type: str, payload: dict, component_id: str, agent: str):
    return build_envelope(
        contract_type=contract_type,
        payload=payload,
        producer=ProducerIdentity(agent, component_id, "1.0.0"),
        correlation_id=TASK_ID,
        idempotency_key=f"{contract_type}:{component_id}",
        task_id=TASK_ID,
        created_at=NOW,
    )


def make_request(
    *,
    command: GenerationCommand = GenerationCommand.GENERATE_PANEL,
    approval_outcome: str = "approved",
    active_skill_id: str = "product-image-panel-generation",
    context_revision: int = 4,
    expected_context_revision: int = 4,
    product_id: str = PRODUCT_ID,
    context_product_id: str = PRODUCT_ID,
    approved_assets: tuple[str, ...] = (ASSET_ID,),
    input_asset_ids: tuple[str, ...] = (ASSET_ID,),
    max_cost_units: int = 12,
    max_attempts: int = 2,
    width: int = 1024,
    height: int = 1024,
    request_hash_override: str | None = None,
    valid_until: str | None = "2026-07-21T10:00:00Z",
) -> GenerationRequest:
    task_spec = _envelope(
        "avp.contract.task-spec",
        {
            "task_id": TASK_ID,
            "task_type": "single-skill",
            "requested_skills": ["product-image-panel-generation"],
            "objective": "Generate a synthetic approved panel",
            "input_refs": [],
            "requested_outputs": ["AssetManifest"],
            "created_by": "human:test",
            "created_at": NOW_TEXT,
        },
        "authorized-direct-cli-caller",
        "human",
    )
    task_context = _envelope(
        "avp.contract.task-context",
        {
            "task_id": TASK_ID,
            "context_revision": context_revision,
            "task_spec_ref": str(task_spec.contract_id),
            "active_skill_id": active_skill_id,
            "input_contract_refs": [str(task_spec.contract_id)],
            "bindings": {},
            "state": "ready",
            "updated_at": NOW_TEXT,
        },
        "hermes",
        "hermes",
    )
    product_context = _envelope(
        "avp.contract.product-context-bundle",
        {
            "bundle_id": "bundle-synthetic-004",
            "bundle_revision": 3,
            "product_id": context_product_id,
            "purpose": "product-image-panel-generation",
            "facts": [],
            "approved_asset_refs": list(approved_assets),
            "rule_refs": [],
            "known_error_refs": [],
            "successful_pattern_refs": [],
            "source_evidence": ["evidence-synthetic-004"],
            "generated_at": NOW_TEXT,
        },
        "product-knowledge",
        "skill",
    )
    asset_manifest = _envelope(
        "avp.contract.asset-manifest",
        {
            "manifest_id": "asset-manifest-synthetic-input-004",
            "manifest_revision": 1,
            "owner_type": "product",
            "owner_id": context_product_id,
            "assets": [
                {
                    "asset_id": ASSET_ID,
                    "role": "product-reference",
                    "media_type": "image",
                    "uri": "memory://synthetic/input.png",
                    "sha256": "0" * 64,
                    "byte_size": 8,
                    "provenance": {"source": "synthetic-test"},
                    "created_at": NOW_TEXT,
                    "approval_ref": "approval-asset-synthetic-004",
                }
            ],
            "created_at": NOW_TEXT,
        },
        "product-knowledge",
        "skill",
    )
    draft = GenerationRequest(
        command=command,
        request_id="image-panel-request-synthetic-004",
        idempotency_key="image-panel-idempotency-synthetic-004",
        request_hash="",
        task_spec=task_spec,
        task_context=task_context,
        product_context=product_context,
        approval_record=None,
        input_asset_manifests=(asset_manifest,),
        reference_manifest=None,
        product_id=product_id,
        sku_id=None,
        expected_context_revision=expected_context_revision,
        items=(
            GenerationItem(
                item_id="panel-synthetic-004",
                role="panel" if command is GenerationCommand.GENERATE_PANEL else "product-image",
                prompt="Synthetic clean-room product panel",
                width=width,
                height=height,
                input_asset_ids=input_asset_ids,
            ),
        ),
        model_profile_id="offline-image-v1",
        model_profile_digest=calculate_model_profile_digest(profile()),
        budget=GenerationBudget(
            currency="COST_UNITS",
            max_cost_units=max_cost_units,
            max_attempts=max_attempts,
            timeout_seconds=5.0,
            max_concurrency=1,
        ),
    )
    request_hash = calculate_request_hash(draft)
    approval_payload = {
        "approval_id": "approval-generation-synthetic-004",
        "subject_ref": {"request_id": draft.request_id, "digest": request_hash},
        "approval_type": "image-panel-generation",
        "outcome": approval_outcome,
        "authority": {"authority_id": "approval-boundary-synthetic"},
        "decided_at": NOW_TEXT,
        "decision_ref": "review-decision-synthetic-004",
    }
    if valid_until is not None:
        approval_payload["valid_until"] = valid_until
    approval = _envelope(
        "avp.contract.approval-record",
        approval_payload,
        "authorized-approval-boundary",
        "system",
    )
    return replace(
        draft,
        request_hash=request_hash_override or request_hash,
        approval_record=approval,
    )


def profile(*, cost_per_attempt: int = 3) -> ModelProfile:
    return ModelProfile(
        profile_id="offline-image-v1",
        provider_id="offline-fake",
        model_id="synthetic-image-model",
        version="1.0.0",
        cost_per_attempt=cost_per_attempt,
        min_dimension=64,
        max_dimension=2048,
        dimension_multiple=8,
        max_concurrency=1,
    )


def rebind_request(request: GenerationRequest, **changes) -> GenerationRequest:
    draft = replace(request, approval_record=None, request_hash="", **changes)
    request_hash = calculate_request_hash(draft)
    approval_payload = thaw_json(request.approval_record.payload)
    approval_payload["subject_ref"] = {
        "request_id": draft.request_id,
        "digest": request_hash,
    }
    approval = _envelope(
        "avp.contract.approval-record",
        approval_payload,
        "authorized-approval-boundary",
        "system",
    )
    return replace(draft, request_hash=request_hash, approval_record=approval)
