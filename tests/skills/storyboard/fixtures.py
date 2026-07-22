from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from ai_video_platform.contracts.envelope import ProducerIdentity, build_envelope
from ai_video_platform.contracts.serialization import thaw_json


FIXED_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_NOW


def task_spec(*, constraints: dict[str, Any] | None = None, product_selector: dict[str, Any] | None = None):
    payload: dict[str, Any] = {
        "task_id": "task-storyboard-001",
        "task_type": "single-skill",
        "requested_skills": ["storyboard"],
        "objective": "Create a deterministic synthetic product story",
        "input_refs": ["contract-product-context-001"],
        "requested_outputs": ["asset-manifest"],
        "created_by": "human:test",
        "created_at": "2026-07-20T08:59:00Z",
        "constraints": constraints or {},
    }
    if product_selector is not None:
        payload["product_selector"] = product_selector
    return build_envelope(
        contract_type="avp.contract.task-spec",
        payload=payload,
        producer=ProducerIdentity("human", "authorized-direct-cli-caller", "1.0.0"),
        correlation_id="corr-storyboard-001",
        idempotency_key="task-spec-001",
        task_id="task-storyboard-001",
        created_at=FIXED_NOW,
    )


def task_context(*, active_skill_id: str = "storyboard", revision: int = 1):
    return build_envelope(
        contract_type="avp.contract.task-context",
        payload={
            "task_id": "task-storyboard-001",
            "context_revision": revision,
            "task_spec_ref": "contract-task-spec-001",
            "active_skill_id": active_skill_id,
            "input_contract_refs": ["contract-product-context-001"],
            "bindings": {"platform": "synthetic"},
            "state": "ready",
            "updated_at": "2026-07-20T08:59:30Z",
            "product_context_ref": "contract-product-context-001",
        },
        producer=ProducerIdentity("hermes", "hermes", "1.0.0"),
        correlation_id="corr-storyboard-001",
        idempotency_key=f"task-context-{revision}",
        task_id="task-storyboard-001",
        created_at=FIXED_NOW,
    )


def product_context(*, sku_id: str | None = "sku-001", pending: bool = False):
    fact = {
        "fact_id": "fact-001",
        "name": "finish",
        "value": "matte blue",
        "status": "pending" if pending else "confirmed",
        "provenance": {"source_ref": "synthetic://product/fact-001", "sha256": "0" * 64},
    }
    payload: dict[str, Any] = {
        "bundle_id": "bundle-001",
        "bundle_revision": 3,
        "product_id": "product-001",
        "purpose": "storyboard",
        "facts": [fact],
        "approved_asset_refs": ["asset-product-front"],
        "rule_refs": [],
        "known_error_refs": [],
        "successful_pattern_refs": [],
        "source_evidence": ["synthetic://product/source-001"],
        "generated_at": "2026-07-20T08:58:00Z",
        "visual_constraints": {"required_color": "matte blue", "logo_visibility": "front"},
    }
    if sku_id is not None:
        payload["sku_id"] = sku_id
    return build_envelope(
        contract_type="avp.contract.product-context-bundle",
        payload=payload,
        producer=ProducerIdentity("skill", "product-knowledge", "1.0.0"),
        correlation_id="corr-storyboard-001",
        idempotency_key="product-context-003",
        task_id="task-storyboard-001",
        created_at=FIXED_NOW,
    )


def reference_manifest():
    return build_envelope(
        contract_type="avp.contract.reference-manifest",
        payload={
            "reference_manifest_id": "reference-manifest-001",
            "revision": 1,
            "task_id": "task-storyboard-001",
            "references": [
                {
                    "reference_id": "reference-001",
                    "reference_type": "synthetic-layout",
                    "source_uri": "synthetic://reference/001",
                    "sha256": "1" * 64,
                    "usage": "composition-only",
                    "provenance": {"kind": "synthetic"},
                }
            ],
            "analysis_contract_refs": ["analysis-ref-001"],
            "created_at": "2026-07-20T08:57:00Z",
        },
        producer=ProducerIdentity("skill", "reference-analysis", "1.0.0"),
        correlation_id="corr-storyboard-001",
        idempotency_key="reference-manifest-001",
        task_id="task-storyboard-001",
        created_at=FIXED_NOW,
    )


def valid_plan() -> dict[str, Any]:
    return {
        "title": "From friction to confidence",
        "product_id": "product-001",
        "creative_direction": "clean synthetic demonstration",
        "scenes": [
            {
                "scene_id": "scene-001",
                "setting": "studio-entry",
                "emotion": "friction",
                "emotion_score": 20,
                "beats": [
                    {
                        "beat_id": "beat-001",
                        "action": "Show the initial problem",
                        "shots": [
                            {
                                "shot_id": "shot-001",
                                "framing": "medium",
                                "panels": [
                                    {
                                        "panel_id": "panel-001",
                                        "prompt": "Actor holds the matte blue product, logo facing front",
                                        "product_id": "product-001",
                                        "continuity": {
                                            "actor_outfit": "blue-jacket",
                                            "product_orientation": "front",
                                        },
                                    },
                                    {
                                        "panel_id": "panel-002",
                                        "prompt": "Closer matte blue product demonstration, logo orientation front",
                                        "product_id": "product-001",
                                        "continuity": {
                                            "actor_outfit": "blue-jacket",
                                            "product_orientation": "front",
                                        },
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "scene_id": "scene-002",
                "setting": "studio-resolution",
                "emotion": "confidence",
                "emotion_score": 80,
                "beats": [
                    {
                        "beat_id": "beat-002",
                        "action": "Resolve with a clear product payoff",
                        "shots": [
                            {
                                "shot_id": "shot-002",
                                "framing": "close-up",
                                "panels": [
                                    {
                                        "panel_id": "panel-003",
                                        "prompt": "Confident hero frame, matte blue product logo front",
                                        "product_id": "product-001",
                                        "continuity": {
                                            "actor_outfit": "blue-jacket",
                                            "product_orientation": "front",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
    }


def changed_plan() -> dict[str, Any]:
    plan = deepcopy(valid_plan())
    plan["scenes"][1]["beats"][0]["shots"][0]["panels"][0]["prompt"] = (
        "Revised confident hero frame, matte blue product logo front"
    )
    return plan


def envelope_document(envelope) -> dict[str, Any]:
    return thaw_json(envelope.to_dict())
