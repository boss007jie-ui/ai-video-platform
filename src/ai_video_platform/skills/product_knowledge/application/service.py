"""Product Knowledge use cases exposed through one small public service."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from ai_video_platform.contracts.serialization import content_digest
from ai_video_platform.contracts.validation import validate_payload
from ai_video_platform.core.ids import uuid7

from ..errors import ProductKnowledgeError, ProductKnowledgeErrorCode
from ..domain import is_effective
from ..adapters.authority import _PRODUCT_KNOWLEDGE_WRITER


def _normalize(value: object) -> str:
    return " ".join(str(value).strip().casefold().split())


def _normalized_mapping(value: Mapping[str, object]) -> dict[str, str]:
    return {str(key): _normalize(item) for key, item in value.items() if _normalize(item)}


def _stable_id(prefix: str, value: object) -> str:
    return f"{prefix}-{content_digest(value).removeprefix('sha256:')[:32]}"


class ProductKnowledgeService:
    """The sole controlled writer and publisher for product knowledge."""

    def __init__(self, library: Any) -> None:
        self._library = library

    def _commit(
        self,
        command: str,
        request: Mapping[str, Any],
        update: Any,
    ) -> dict[str, Any]:
        return self._library.commit(
            writer_authority=_PRODUCT_KNOWLEDGE_WRITER,
            command=command,
            idempotency_key=request["idempotency_key"],
            input_digest=content_digest(dict(request)),
            actor=request["actor"],
            reason=request["reason"],
            expected_revision=request["expected_library_revision"],
            update=update,
        )

    def backup_library(self, request: Mapping[str, Any]) -> Any:
        return self._library.backup(
            writer_authority=_PRODUCT_KNOWLEDGE_WRITER,
            actor=request["actor"],
            reason=request["reason"],
        )

    def restore_library(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._library.restore(
            request["snapshot_path"],
            writer_authority=_PRODUCT_KNOWLEDGE_WRITER,
            expected_revision=request["expected_library_revision"],
            actor=request["actor"],
            reason=request["reason"],
        )

    @staticmethod
    def _product(state: Mapping[str, Any], product_id: str) -> dict[str, Any]:
        try:
            return state["products"][product_id]
        except KeyError as exc:
            raise ProductKnowledgeError(
                ProductKnowledgeErrorCode.PRODUCT_NOT_FOUND,
                "Product does not exist",
                details={"product_id": product_id},
            ) from exc

    @staticmethod
    def _assert_version(actual: int, expected: int, *, aggregate: str) -> None:
        if actual != expected:
            raise ProductKnowledgeError(
                ProductKnowledgeErrorCode.AGGREGATE_VERSION_CONFLICT,
                "Aggregate version changed",
                retryable=True,
                details={"aggregate": aggregate, "expected_version": expected, "actual_version": actual},
            )

    def identify_product(self, request: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _normalized_mapping(request.get("clues", {}))
        if not normalized:
            raise ProductKnowledgeError(
                ProductKnowledgeErrorCode.VALIDATION_FAILED,
                "At least one product identity clue is required",
            )
        if not request.get("evidence_refs"):
            raise ProductKnowledgeError(
                ProductKnowledgeErrorCode.VALIDATION_FAILED,
                "Product identification requires traceable evidence",
            )
        confidence = "high" if len(normalized) >= 3 and request.get("evidence_refs") else "medium"
        return {"normalized_clues": normalized, "confidence": confidence}

    def create_product(self, request: Mapping[str, Any]) -> dict[str, Any]:
        product_id = str(uuid7())
        identity = _normalized_mapping(request["identity"])

        def update(state: dict[str, Any]) -> dict[str, Any]:
            duplicate_candidates = [
                product["product_id"]
                for product in state["products"].values()
                if identity.get("brand")
                and identity.get("model")
                and product["identity"].get("brand") == identity["brand"]
                and product["identity"].get("model") == identity["model"]
                and product["status"] == "active"
            ]
            if duplicate_candidates:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.PRODUCT_MATCH_AMBIGUOUS,
                    "A high-confidence duplicate candidate requires review",
                    details={"candidate_product_ids": duplicate_candidates},
                )
            state["products"][product_id] = {
                "product_id": product_id,
                "version": 1,
                "status": "active",
                "identity": identity,
                "evidence_refs": list(request["evidence_refs"]),
                "skus": {},
                "facts": [],
                "assets": [],
            }
            return {"product_id": product_id, "product_version": 1}

        return self._commit("create-product", request, update)

    def create_sku(self, request: Mapping[str, Any]) -> dict[str, Any]:
        sku_id = str(uuid7())

        def update(state: dict[str, Any]) -> dict[str, Any]:
            product = self._product(state, request["product_id"])
            self._assert_version(
                product["version"],
                request["expected_product_version"],
                aggregate=f"product:{request['product_id']}",
            )
            product["skus"][sku_id] = {
                "sku_id": sku_id,
                "version": 1,
                "status": "active",
                "identity": _normalized_mapping(request["identity"]),
                "evidence_refs": list(request["evidence_refs"]),
                "facts": [],
                "assets": [],
            }
            product["version"] += 1
            return {
                "product_id": product["product_id"],
                "product_version": product["version"],
                "sku_id": sku_id,
                "sku_version": 1,
            }

        return self._commit("create-sku", request, update)

    def ingest_product(self, request: Mapping[str, Any]) -> dict[str, Any]:
        facts = [dict(fact) for fact in request.get("facts", [])]

        def update(state: dict[str, Any]) -> dict[str, Any]:
            product = self._product(state, request["product_id"])
            self._assert_version(
                product["version"],
                request["expected_product_version"],
                aggregate=f"product:{request['product_id']}",
            )
            for fact in facts:
                if not fact.get("provenance"):
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.VALIDATION_FAILED,
                        "Fact provenance is required",
                        details={"fact_id": fact.get("fact_id")},
                    )
                if fact.get("status") not in {"confirmed", "pending", "conflicted"}:
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.VALIDATION_FAILED,
                        "Fact status is unsupported",
                        details={"fact_id": fact.get("fact_id"), "status": fact.get("status")},
                    )
                product["facts"].append(fact)
                if fact["status"] == "conflicted":
                    conflict = {
                        "conflict_id": fact["fact_id"],
                        "fact_id": fact["fact_id"],
                        "product_id": product["product_id"],
                        "status": "open",
                        "candidate_values": deepcopy(fact.get("candidate_values", [fact["value"]])),
                        "evidence_refs": list(fact["provenance"]),
                    }
                    state["conflicts"][fact["fact_id"]] = conflict
            product["version"] += 1
            return {
                "product_id": product["product_id"],
                "product_version": product["version"],
                "accepted_fact_ids": [fact["fact_id"] for fact in facts],
                "conflict_refs": [
                    {
                        "conflict_id": fact["fact_id"],
                        "digest": content_digest(state["conflicts"][fact["fact_id"]]),
                    }
                    for fact in facts
                    if fact["status"] == "conflicted"
                ],
            }

        return self._commit("ingest-product", request, update)

    def organize_assets(self, request: Mapping[str, Any]) -> dict[str, Any]:
        manifest_model = validate_payload(
            "avp.contract.asset-manifest",
            request["manifest"],
            producer_component_id="product-knowledge",
            producer_agent="skill",
        )
        manifest = manifest_model.__contract_json__()
        if manifest["owner_type"] != "product":
            raise ProductKnowledgeError(
                ProductKnowledgeErrorCode.VALIDATION_FAILED,
                "Product Knowledge accepts only product-owned asset manifests",
            )

        def update(state: dict[str, Any]) -> dict[str, Any]:
            product = self._product(state, manifest["owner_id"])
            self._assert_version(
                product["version"],
                request["expected_product_version"],
                aggregate=f"product:{manifest['owner_id']}",
            )
            existing = {asset["asset_id"]: asset for asset in product["assets"]}
            for asset in manifest["assets"]:
                approval_state = asset.get("approval_state", "pending")
                if approval_state not in {"approved", "pending", "rejected", "superseded"}:
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.VALIDATION_FAILED,
                        "Asset approval_state is unsupported",
                        details={"asset_id": asset["asset_id"], "approval_state": approval_state},
                    )
                prior = existing.get(asset["asset_id"])
                if prior is not None and prior["sha256"] != asset["sha256"]:
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.VALIDATION_FAILED,
                        "Asset identity cannot be rebound to different content",
                        details={"asset_id": asset["asset_id"]},
                    )
                if prior is None:
                    product["assets"].append(deepcopy(asset))
            product["version"] += 1
            return {
                "product_id": product["product_id"],
                "product_version": product["version"],
                "asset_ids": [asset["asset_id"] for asset in manifest["assets"]],
            }

        return self._commit("organize-assets", request, update)

    def resolve_conflict(self, request: Mapping[str, Any]) -> dict[str, Any]:
        review_producer = request["review_producer"]
        approval_producer = request["approval_producer"]
        review = validate_payload(
            "avp.contract.review-decision",
            request["review_decision"],
            producer_component_id=review_producer["component_id"],
            producer_agent=review_producer["agent"],
        ).__contract_json__()
        approval = validate_payload(
            "avp.contract.approval-record",
            request["approval_record"],
            producer_component_id=approval_producer["component_id"],
            producer_agent=approval_producer["agent"],
        ).__contract_json__()

        def update(state: dict[str, Any]) -> dict[str, Any]:
            try:
                conflict = state["conflicts"][request["conflict_id"]]
            except KeyError as exc:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.CONFLICT_NOT_FOUND,
                    "Conflict does not exist",
                ) from exc
            product = self._product(state, conflict["product_id"])
            self._assert_version(
                product["version"],
                request["expected_product_version"],
                aggregate=f"product:{product['product_id']}",
            )
            expected_subject = {
                "contract_id": conflict["conflict_id"],
                "digest": content_digest(conflict),
            }
            if review["subject_ref"] != expected_subject or approval["subject_ref"] != expected_subject:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.APPROVAL_SUBJECT_MISMATCH,
                    "Review and approval must reference the current conflict",
                )
            if approval["decision_ref"] != review["review_decision_id"]:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.APPROVAL_SUBJECT_MISMATCH,
                    "ApprovalRecord must reference the supplied ReviewDecision",
                )
            if review["decision"] not in {"approve", "approve_with_conditions"} or approval["outcome"] != "approved":
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.REVIEW_AUTHORITY_INSUFFICIENT,
                    "Conflict resolution requires an approving review and ApprovalRecord",
                )
            if request["selected_value"] not in conflict["candidate_values"]:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.VALIDATION_FAILED,
                    "Selected conflict value is not one of the recorded candidates",
                )
            original = next(fact for fact in product["facts"] if fact["fact_id"] == conflict["fact_id"])
            original["status"] = "superseded"
            resolved_fact_id = f"{original['fact_id']}-resolved-{approval['approval_id']}"
            product["facts"].append(
                {
                    "fact_id": resolved_fact_id,
                    "claim_type": original["claim_type"],
                    "value": deepcopy(request["selected_value"]),
                    "status": "confirmed",
                    "inferred": False,
                    "provenance": sorted(set([*conflict["evidence_refs"], *review["evidence_refs"]])),
                    "supersedes_fact_id": original["fact_id"],
                    "review_decision_ref": review["review_decision_id"],
                    "approval_ref": approval["approval_id"],
                }
            )
            conflict["status"] = "resolved"
            conflict["selected_value"] = deepcopy(request["selected_value"])
            conflict["review_decision_ref"] = review["review_decision_id"]
            conflict["approval_ref"] = approval["approval_id"]
            conflict["resolved_fact_id"] = resolved_fact_id
            product["version"] += 1
            return {
                "conflict_id": conflict["conflict_id"],
                "status": "resolved",
                "resolved_fact_id": resolved_fact_id,
                "product_version": product["version"],
            }

        return self._commit("resolve-conflict", request, update)

    def build_product_context(self, request: Mapping[str, Any]) -> dict[str, Any]:
        state = self._library.snapshot()
        product = self._product(state, request["product_id"])
        sku = None
        if request.get("sku_id") is not None:
            try:
                sku = product["skus"][request["sku_id"]]
            except KeyError as exc:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.SKU_NOT_FOUND,
                    "SKU does not exist under the selected product",
                    details={"product_id": product["product_id"], "sku_id": request["sku_id"]},
                ) from exc
        fact_source = [*product["facts"], *(sku["facts"] if sku is not None else [])]
        facts = [
            dict(fact)
            for fact in fact_source
            if fact["status"] == "confirmed"
            and not fact.get("inferred", False)
            and is_effective(fact.get("effective_period"), request["at"])
        ]
        asset_source = [*product["assets"], *(sku["assets"] if sku is not None else [])]
        approved_assets = [
            asset
            for asset in asset_source
            if asset.get("approval_state") == "approved"
            and is_effective(asset.get("effective_period"), request["at"])
            and (
                asset.get("sku_id") is None
                or (sku is not None and asset.get("sku_id") == sku["sku_id"])
            )
        ]
        rule_refs = [
            deepcopy(rule["rule_ref"])
            for rule in state["rules"].values()
            if rule["rule_ref"]["status"] == "approved"
            and is_effective(rule["rule_ref"].get("effective_period"), request["at"])
            and self._rule_applies(rule["rule_ref"], product, sku, request)
        ]
        publication_identity = {
            "product_id": product["product_id"],
            "product_version": product["version"],
            "sku_id": request.get("sku_id"),
            "purpose": request["purpose"],
            "at": request["at"],
        }
        payload: dict[str, Any] = {
            "bundle_id": _stable_id("bundle", publication_identity),
            "bundle_revision": product["version"],
            "product_id": product["product_id"],
            "purpose": request["purpose"],
            "facts": facts,
            "approved_asset_refs": [asset["asset_id"] for asset in approved_assets],
            "rule_refs": rule_refs,
            "known_error_refs": [],
            "successful_pattern_refs": [],
            "source_evidence": sorted(
                {
                    *{ref for fact in facts for ref in fact["provenance"]},
                    *{
                        ref
                        for asset in approved_assets
                        for ref in asset.get("provenance", {}).get("evidence_refs", [])
                    },
                }
            ),
            "generated_at": request["at"],
        }
        if request.get("sku_id"):
            payload["sku_id"] = request["sku_id"]
        validated = validate_payload(
            "avp.contract.product-context-bundle",
            payload,
            producer_component_id="product-knowledge",
            producer_agent="skill",
        )
        return validated.__contract_json__()

    @staticmethod
    def _rule_applies(
        rule_ref: Mapping[str, Any],
        product: Mapping[str, Any],
        sku: Mapping[str, Any] | None,
        request: Mapping[str, Any],
    ) -> bool:
        scope = rule_ref["rule_scope"]
        scope_key = rule_ref["scope_key"]
        if scope == "product":
            owner_matches = scope_key.get("product_id") == product["product_id"]
        elif scope == "sku":
            owner_matches = (
                sku is not None
                and scope_key.get("product_id") == product["product_id"]
                and scope_key.get("sku_id") == sku["sku_id"]
            )
        elif scope == "category":
            owner_matches = scope_key.get("category_id") in request.get("category_ids", [])
        elif scope == "skill":
            owner_matches = scope_key.get("skill_id") == request.get("skill_id")
        elif scope == "provider":
            owner_matches = scope_key.get("provider_id") == request.get("bindings", {}).get("provider_id")
        else:
            owner_matches = scope == "global"
        if not owner_matches:
            return False
        request_bindings = request.get("bindings", {})
        return all(request_bindings.get(key) == value for key, value in rule_ref.get("bindings", {}).items())

    def record_feedback(self, request: Mapping[str, Any]) -> dict[str, Any]:
        event_model = validate_payload(
            "avp.contract.feedback-event",
            request["event"],
            producer_component_id=request["producer_component_id"],
            producer_agent=request["producer_agent"],
        )
        event = event_model.__contract_json__()
        event_digest = content_digest(event)
        dedup_digest = content_digest(
            {
                "statement": _normalize(event["statement"]),
                "product_id": event.get("product_id"),
                "sku_id": event.get("sku_id"),
                "rule_scope": event["rule_scope"],
                "scope_key": event["scope_key"],
                "bindings": event["bindings"],
                "evidence_refs": sorted(event["evidence_refs"]),
            }
        )

        def update(state: dict[str, Any]) -> dict[str, Any]:
            if event["feedback_id"] in state["feedback_events"]:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.FEEDBACK_EVENT_IMMUTABLE,
                    "Feedback event identity is immutable and already recorded",
                    details={"feedback_id": event["feedback_id"]},
                )
            duplicate_of = next(
                (
                    feedback_id
                    for feedback_id, record in state["feedback_events"].items()
                    if record["dedup_digest"] == dedup_digest
                ),
                None,
            )
            state["feedback_events"][event["feedback_id"]] = {
                "event": deepcopy(event),
                "event_digest": event_digest,
                "dedup_digest": dedup_digest,
                "classification": self._classify_feedback(event["feedback_type"]),
                "status": "pending_review",
                "duplicate_of": duplicate_of,
                "review_decision_ref": None,
                "approval_ref": None,
            }
            return {
                "feedback_id": event["feedback_id"],
                "event_digest": event_digest,
                "status": "pending_review",
                "duplicate_of": duplicate_of,
            }

        return self._commit("record-feedback", request, update)

    @staticmethod
    def _classify_feedback(feedback_type: str) -> str:
        normalized = _normalize(feedback_type).replace(" ", "_")
        categories = {
            "fact_correction": "product_fact_correction",
            "asset_acceptance": "asset_decision",
            "asset_rejection": "asset_decision",
            "asset_replacement": "asset_decision",
            "visual_constraint": "visual_or_packaging_constraint",
            "packaging_constraint": "visual_or_packaging_constraint",
            "known_issue": "known_issue",
            "success_pattern": "success_pattern",
            "rule_candidate": "rule_candidate",
            "one_task_preference": "one_task_preference",
        }
        return categories.get(normalized, "non_product_operational_issue")

    def confirm_feedback(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if request.get("action") not in {
            "confirmed",
            "rejected",
            "deferred",
            "scope_changed",
            "binding_changed",
        }:
            raise ProductKnowledgeError(
                ProductKnowledgeErrorCode.VALIDATION_FAILED,
                "Feedback confirmation action is unsupported",
                details={"action": request.get("action")},
            )
        review_producer = request["review_producer"]
        approval_producer = request["approval_producer"]
        review_model = validate_payload(
            "avp.contract.review-decision",
            request["review_decision"],
            producer_component_id=review_producer["component_id"],
            producer_agent=review_producer["agent"],
        )
        approval_model = validate_payload(
            "avp.contract.approval-record",
            request["approval_record"],
            producer_component_id=approval_producer["component_id"],
            producer_agent=approval_producer["agent"],
        )
        review = review_model.__contract_json__()
        approval = approval_model.__contract_json__()

        def update(state: dict[str, Any]) -> dict[str, Any]:
            try:
                record = state["feedback_events"][request["feedback_id"]]
            except KeyError as exc:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.FEEDBACK_NOT_FOUND,
                    "Feedback event does not exist",
                ) from exc
            expected_subject = {
                "contract_id": request["feedback_id"],
                "digest": record["event_digest"],
            }
            if review["subject_ref"] != expected_subject or approval["subject_ref"] != expected_subject:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.APPROVAL_SUBJECT_MISMATCH,
                    "Review and approval must reference the immutable feedback event",
                )
            if approval["decision_ref"] != review["review_decision_id"]:
                raise ProductKnowledgeError(
                    ProductKnowledgeErrorCode.APPROVAL_SUBJECT_MISMATCH,
                    "ApprovalRecord must reference the supplied ReviewDecision",
                )
            if request["action"] == "confirmed":
                if review["decision"] not in {"approve", "approve_with_conditions"} or approval["outcome"] != "approved":
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.REVIEW_AUTHORITY_INSUFFICIENT,
                        "Confirmed promotion requires an approving review and effective approval",
                    )
            record["status"] = request["action"]
            record["review_decision_ref"] = review["review_decision_id"]
            record["approval_ref"] = approval["approval_id"]
            return {"feedback_id": request["feedback_id"], "status": record["status"]}

        return self._commit("confirm-feedback", request, update)

    def consolidate_learning(self, request: Mapping[str, Any]) -> dict[str, Any]:
        def update(state: dict[str, Any]) -> dict[str, Any]:
            rule_refs: list[dict[str, Any]] = []
            for feedback_id in request["feedback_ids"]:
                try:
                    record = state["feedback_events"][feedback_id]
                except KeyError as exc:
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.FEEDBACK_NOT_FOUND,
                        "Feedback event does not exist",
                    ) from exc
                if record["status"] != "confirmed":
                    raise ProductKnowledgeError(
                        ProductKnowledgeErrorCode.FEEDBACK_NOT_CONFIRMED,
                        "Only confirmed feedback can be consolidated",
                    )
                event = record["event"]
                content = event.get("suggested_rule")
                if not content:
                    continue
                rule_id = str(uuid7())
                rule_ref = {
                    "rule_id": rule_id,
                    "rule_version": "1.0.0",
                    "rule_scope": event["rule_scope"],
                    "scope_key": deepcopy(event["scope_key"]),
                    "bindings": deepcopy(event["bindings"]),
                    "status": "approved",
                    "effective_period": deepcopy(request["effective_period"]),
                    "content_digest": content_digest(content),
                }
                validated = validate_payload(
                    "avp.contract.rule-ref",
                    rule_ref,
                    producer_component_id="product-knowledge",
                    producer_agent="skill",
                )
                canonical_ref = validated.__contract_json__()
                state["rules"][rule_id] = {
                    "rule_ref": canonical_ref,
                    "content": deepcopy(content),
                    "source_feedback_refs": [feedback_id],
                    "approval_ref": record["approval_ref"],
                }
                record["status"] = "consolidated"
                rule_refs.append(canonical_ref)
            return {"rule_refs": rule_refs}

        return self._commit("consolidate-learning", request, update)

    def build_product_review_context(self, request: Mapping[str, Any]) -> dict[str, Any]:
        state = self._library.snapshot()
        product = self._product(state, request["product_id"])
        review_items = []
        for fact in product["facts"]:
            if fact["status"] in {"superseded", "rejected"}:
                continue
            if fact["status"] == "confirmed" and not fact.get("inferred", False):
                continue
            kind = "fact_conflict" if fact["status"] == "conflicted" else "inferred_fact"
            review_items.append(
                {
                    "review_item_id": fact["fact_id"],
                    "kind": kind,
                    "status": "pending_review",
                    "candidate_values": deepcopy(fact.get("candidate_values", [fact["value"]])),
                    "evidence_refs": list(fact["provenance"]),
                    "requested_decision": "Confirm, reject, or defer this fact candidate",
                }
            )
        for asset in product["assets"]:
            if asset.get("approval_state") == "approved":
                continue
            review_items.append(
                {
                    "review_item_id": asset["asset_id"],
                    "kind": "asset_confirmation",
                    "status": "pending_review",
                    "candidate_values": [
                        {
                            "asset_id": asset["asset_id"],
                            "sha256": asset["sha256"],
                            "role": asset["role"],
                            "relations": deepcopy(asset.get("relations", [])),
                        }
                    ],
                    "evidence_refs": list(asset.get("provenance", {}).get("evidence_refs", [])),
                    "requested_decision": "Approve, reject, or supersede this product asset",
                }
            )
        related_feedback_refs: list[str] = []
        for feedback_id, record in state["feedback_events"].items():
            event = record["event"]
            if event.get("product_id") != product["product_id"] or record["status"] != "pending_review":
                continue
            related_feedback_refs.append(feedback_id)
            review_items.append(
                {
                    "review_item_id": feedback_id,
                    "kind": "pending_feedback",
                    "status": "pending_review",
                    "candidate_values": [deepcopy(event.get("suggested_rule", event["statement"]))],
                    "evidence_refs": list(event["evidence_refs"]),
                    "requested_decision": "Confirm, reject, defer, or narrow this feedback candidate",
                }
            )
        publication_identity = {
            "product_id": product["product_id"],
            "product_version": product["version"],
            "sku_id": request.get("sku_id"),
            "at": request["at"],
        }
        payload = {
            "review_context_id": _stable_id("review-context", publication_identity),
            "context_revision": product["version"],
            "product_id": product["product_id"],
            "review_items": review_items,
            "generated_at": request["at"],
            "related_feedback_refs": related_feedback_refs,
        }
        validated = validate_payload(
            "avp.contract.product-review-context",
            payload,
            producer_component_id="product-knowledge",
            producer_agent="skill",
        )
        return validated.__contract_json__()

    def match_product(self, request: Mapping[str, Any]) -> dict[str, Any]:
        clues = _normalized_mapping(request.get("clues", {}))
        if not clues:
            raise ProductKnowledgeError(
                ProductKnowledgeErrorCode.VALIDATION_FAILED,
                "At least one product identity clue is required for matching",
            )
        state = self._library.snapshot()
        product_candidates: list[dict[str, Any]] = []
        sku_candidates: list[dict[str, str]] = []
        for product in state["products"].values():
            identity = product["identity"]
            product_matches = all(identity.get(key) == value for key, value in clues.items())
            for sku in product["skus"].values():
                combined = {**identity, **sku["identity"]}
                if all(combined.get(key) == value for key, value in clues.items()):
                    sku_candidates.append({"product_id": product["product_id"], "sku_id": sku["sku_id"]})
            if product_matches:
                product_candidates.append(product)
        if len(sku_candidates) == 1:
            return {"status": "exact", **sku_candidates[0]}
        if len(sku_candidates) > 1 or (
            len(product_candidates) == 1 and len(product_candidates[0]["skus"]) > 1
        ):
            candidates = sku_candidates or [
                {"product_id": product_candidates[0]["product_id"], "sku_id": sku_id}
                for sku_id in product_candidates[0]["skus"]
            ]
            raise ProductKnowledgeError(
                ProductKnowledgeErrorCode.PRODUCT_MATCH_AMBIGUOUS,
                "Product identity matches multiple SKUs",
                details={"sku_candidates": candidates},
            )
        if len(product_candidates) == 1:
            return {"status": "exact", "product_id": product_candidates[0]["product_id"], "sku_id": None}
        return {"status": "no_match", "candidates": []}
