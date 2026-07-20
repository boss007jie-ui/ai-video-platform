"""Sole identity registry for IR-2 Foundation Registry V1."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


ENVELOPE_SCHEMA_ID = "avp.schema.contract-envelope"
FOUNDATION_REGISTRY_NAME = "IR-2 Foundation Registry V1"
FOUNDATION_VERSION = "1.0.0"


_PRODUCER_AGENT_TYPES = {
    "hermes": ("hermes",),
    "authorized-direct-cli-caller": ("human", "codex", "system"),
    "active-skill": ("skill",),
    "skill-runtime": ("skill",),
    "product-knowledge": ("skill",),
    "non-product-knowledge-skill": ("skill",),
    "authorized-human-review-interface": ("human",),
    "producing-skill": ("skill",),
    "reference-analysis": ("skill",),
    "qa-review": ("skill",),
    "authorized-approval-boundary": ("human", "hermes", "system"),
}


@dataclass(frozen=True, slots=True)
class ContractDefinition:
    name: str
    contract_type: str
    required_fields: tuple[str, ...]
    authorized_producers: tuple[str, ...]
    authorized_consumers: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    field_types: tuple[tuple[str, str], ...] = ()
    enum_fields: tuple[tuple[str, tuple[str, ...]], ...] = ()
    version: str = FOUNDATION_VERSION

    @property
    def schema_filename(self) -> str:
        return f"{self.contract_type.removeprefix('avp.contract.').replace('-', '_')}.schema.json"


_DEFINITIONS = (
    ContractDefinition(
        "TaskSpec",
        "avp.contract.task-spec",
        ("task_id", "task_type", "requested_skills", "objective", "input_refs", "requested_outputs", "created_by", "created_at"),
        ("hermes", "authorized-direct-cli-caller"),
        ("selected-skill", "hermes", "codex-maintenance"),
        ("product_selector", "bindings", "constraints", "review_policy", "priority", "deadline", "parent_task_id"),
        (
            ("task_id", "string"), ("task_type", "string"), ("requested_skills", "array"),
            ("objective", "string"), ("input_refs", "array"), ("requested_outputs", "array"),
            ("created_by", "string"), ("created_at", "string"), ("product_selector", "object"),
            ("bindings", "object"), ("constraints", "object"), ("review_policy", "object"),
            ("deadline", "string"), ("parent_task_id", "string"),
        ),
    ),
    ContractDefinition(
        "TaskContext",
        "avp.contract.task-context",
        ("task_id", "context_revision", "task_spec_ref", "active_skill_id", "input_contract_refs", "bindings", "state", "updated_at"),
        ("hermes", "active-skill"),
        ("active-skill", "hermes", "qa-review", "codex-maintenance"),
        ("product_context_ref", "product_review_context_ref", "asset_manifest_refs", "reference_manifest_refs", "prior_execution_event_refs", "review_decision_refs"),
        (
            ("task_id", "string"), ("context_revision", "integer"), ("task_spec_ref", "string"),
            ("active_skill_id", "string"), ("input_contract_refs", "array"), ("bindings", "object"),
            ("state", "string"), ("updated_at", "string"), ("product_context_ref", "string"),
            ("product_review_context_ref", "string"), ("asset_manifest_refs", "array"),
            ("reference_manifest_refs", "array"), ("prior_execution_event_refs", "array"),
            ("review_decision_refs", "array"),
        ),
    ),
    ContractDefinition(
        "SkillExecutionEvent",
        "avp.contract.skill-execution-event",
        ("execution_id", "task_id", "skill_id", "event_type", "sequence", "occurred_at", "status", "input_contract_refs"),
        ("skill-runtime", "hermes"),
        ("hermes", "qa-review", "codex-observability"),
        ("output_contract_refs", "error", "metrics", "provider_binding", "retry_of_execution_id"),
        (
            ("execution_id", "string"), ("task_id", "string"), ("skill_id", "string"),
            ("event_type", "string"), ("sequence", "integer"), ("occurred_at", "string"),
            ("status", "string"), ("input_contract_refs", "array"), ("output_contract_refs", "array"),
            ("error", "object"), ("metrics", "object"), ("provider_binding", "object"),
            ("retry_of_execution_id", "string"),
        ),
        (("event_type", ("accepted", "started", "progressed", "blocked", "completed", "failed", "cancelled")),),
    ),
    ContractDefinition(
        "ProductContextBundle",
        "avp.contract.product-context-bundle",
        ("bundle_id", "bundle_revision", "product_id", "purpose", "facts", "approved_asset_refs", "rule_refs", "known_error_refs", "successful_pattern_refs", "source_evidence", "generated_at"),
        ("product-knowledge",),
        ("reference-analysis", "storyboard", "product-image-panel-generation", "storyboard-master-video-planning", "video-generation", "qa-review", "hermes"),
        ("sku_id", "category_ids", "packaging", "dimensions", "visual_constraints", "expires_at"),
        (
            ("bundle_id", "string"), ("bundle_revision", "integer"), ("product_id", "string"),
            ("purpose", "string"), ("facts", "array"), ("approved_asset_refs", "array"),
            ("rule_refs", "array"), ("known_error_refs", "array"), ("successful_pattern_refs", "array"),
            ("source_evidence", "array"), ("generated_at", "string"), ("sku_id", "string"),
            ("category_ids", "array"), ("packaging", "object"), ("dimensions", "object"),
            ("visual_constraints", "object"), ("expires_at", "string"),
        ),
    ),
    ContractDefinition(
        "ProductReviewContext",
        "avp.contract.product-review-context",
        ("review_context_id", "context_revision", "product_id", "review_items", "generated_at"),
        ("product-knowledge",),
        ("hermes", "qa-review", "authorized-human-review-interface", "codex-maintenance"),
        ("sku_id", "related_feedback_refs", "recommended_resolution", "blocking_task_ids"),
        (
            ("review_context_id", "string"), ("context_revision", "integer"), ("product_id", "string"),
            ("review_items", "array"), ("generated_at", "string"), ("sku_id", "string"),
            ("related_feedback_refs", "array"), ("blocking_task_ids", "array"),
        ),
    ),
    ContractDefinition(
        "FeedbackEvent",
        "avp.contract.feedback-event",
        ("feedback_id", "task_id", "source_skill_id", "feedback_type", "statement", "evidence_refs", "rule_scope", "scope_key", "bindings", "observed_at", "submitted_by"),
        ("non-product-knowledge-skill", "hermes", "authorized-human-review-interface"),
        ("product-knowledge",),
        ("product_id", "sku_id", "asset_refs", "reference_refs", "suggested_rule", "severity", "supersedes_feedback_id"),
        (
            ("feedback_id", "string"), ("task_id", "string"), ("source_skill_id", "string"),
            ("feedback_type", "string"), ("statement", "string"), ("evidence_refs", "array"),
            ("rule_scope", "string"), ("scope_key", "object"), ("bindings", "object"),
            ("observed_at", "string"), ("submitted_by", "string"), ("product_id", "string"),
            ("sku_id", "string"), ("asset_refs", "array"), ("reference_refs", "array"),
            ("suggested_rule", "object"), ("severity", "string"), ("supersedes_feedback_id", "string"),
        ),
    ),
    ContractDefinition(
        "RuleRef",
        "avp.contract.rule-ref",
        ("rule_id", "rule_version", "rule_scope", "scope_key", "bindings", "status", "effective_period", "content_digest"),
        ("product-knowledge",),
        ("all-skills", "hermes"),
        (),
        (
            ("rule_id", "string"), ("rule_version", "string"), ("rule_scope", "string"),
            ("scope_key", "object"), ("bindings", "object"), ("status", "string"),
            ("effective_period", "object"), ("content_digest", "string"),
        ),
        (("status", ("draft", "pending_review", "approved", "deprecated", "revoked")),),
    ),
    ContractDefinition(
        "AssetManifest",
        "avp.contract.asset-manifest",
        ("manifest_id", "manifest_revision", "owner_type", "owner_id", "assets", "created_at"),
        ("product-knowledge", "producing-skill", "hermes"),
        ("all-skills", "hermes", "codex-maintenance"),
        (),
        (
            ("manifest_id", "string"), ("manifest_revision", "integer"), ("owner_type", "string"),
            ("owner_id", "string"), ("assets", "array"), ("created_at", "string"),
        ),
        (("owner_type", ("task", "product")),),
    ),
    ContractDefinition(
        "ReferenceManifest",
        "avp.contract.reference-manifest",
        ("reference_manifest_id", "revision", "task_id", "references", "created_at"),
        ("reference-analysis", "hermes"),
        ("storyboard", "product-image-panel-generation", "storyboard-master-video-planning", "video-generation", "qa-review"),
        ("analysis_contract_refs", "rights_assertion", "comparison_target_refs", "extraction_ranges"),
        (
            ("reference_manifest_id", "string"), ("revision", "integer"), ("task_id", "string"),
            ("references", "array"), ("created_at", "string"), ("analysis_contract_refs", "array"),
            ("comparison_target_refs", "array"), ("extraction_ranges", "array"),
        ),
    ),
    ContractDefinition(
        "ReviewDecision",
        "avp.contract.review-decision",
        ("review_decision_id", "subject_ref", "decision", "decided_by", "decided_at", "criteria_results", "evidence_refs"),
        ("qa-review", "hermes", "authorized-human-review-interface"),
        ("hermes", "subject-owning-skill", "product-knowledge", "codex-maintenance"),
        ("conditions", "issue_refs", "supersedes_decision_id", "product_review_item_refs"),
        (
            ("review_decision_id", "string"), ("subject_ref", "object"), ("decision", "string"),
            ("decided_by", "string"), ("decided_at", "string"), ("criteria_results", "array"),
            ("evidence_refs", "array"), ("issue_refs", "array"), ("supersedes_decision_id", "string"),
            ("product_review_item_refs", "array"),
        ),
        (("decision", ("approve", "approve_with_conditions", "reject", "request_changes", "defer")),),
    ),
    ContractDefinition(
        "ApprovalRecord",
        "avp.contract.approval-record",
        ("approval_id", "subject_ref", "approval_type", "outcome", "authority", "decided_at", "decision_ref"),
        ("authorized-approval-boundary",),
        ("hermes", "product-knowledge", "qa-review", "generation-skills", "release-tooling", "codex-audit"),
        ("conditions", "valid_until", "supersedes_approval_id", "policy_version", "signature"),
        (
            ("approval_id", "string"), ("subject_ref", "object"), ("approval_type", "string"),
            ("outcome", "string"), ("authority", "object"), ("decided_at", "string"),
            ("decision_ref", "string"), ("valid_until", "string"),
            ("supersedes_approval_id", "string"), ("policy_version", "string"),
        ),
        (("outcome", ("approved", "denied", "revoked", "expired")),),
    ),
)

FOUNDATION_CONTRACT_IDS = tuple(item.contract_type for item in _DEFINITIONS)
REGISTRY = MappingProxyType({item.contract_type: item for item in _DEFINITIONS})
PRODUCER_AGENT_TYPES = MappingProxyType(_PRODUCER_AGENT_TYPES)


def get_contract_definition(contract_type: str) -> ContractDefinition:
    try:
        return REGISTRY[contract_type]
    except KeyError as exc:
        raise KeyError(f"Unregistered foundation contract identity: {contract_type}") from exc
