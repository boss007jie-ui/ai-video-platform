"""Small independently callable Storyboard application interface."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re
from typing import Any, Callable, Mapping
from uuid import UUID

from ai_video_platform.contracts.envelope import ContractEnvelope, ProducerIdentity, build_envelope, format_utc
from ai_video_platform.contracts.errors import ContractError, ErrorCategory, ErrorCode
from ai_video_platform.contracts.serialization import canonical_json, content_digest, freeze_json, thaw_json
from ai_video_platform.contracts.validation import validate_envelope

from .state import InMemoryVersionStore, VersionStore, VersionStoreError


STORYBOARD_VERSION = "1.1.0"
MAX_PLAN_BYTES = 1_048_576
MAX_PANELS = 500
_CREATE_COMMANDS = {"create-storyboard", "create-storyboard-from-script"}
_COMMANDS = _CREATE_COMMANDS | {"revise-storyboard"}
_FORBIDDEN_CAPABILITY_KEYS = {
    "provider_submission",
    "provider_request",
    "image_generation",
    "video_generation",
    "submit_provider",
    "download_media",
}
_SENSITIVE_FIELD = re.compile(
    r"(?i)(authorization|api[_-]?key|token|secret|password|credential|private[_-]?key|traceback|stack)"
)


def safe_field_segment(value: object) -> str:
    text = str(value)
    return "redacted-key" if _SENSITIVE_FIELD.search(text) else text


@dataclass(frozen=True, slots=True)
class StoryboardArtifact:
    storyboard_id: str
    version: int
    task_id: str
    product_id: str
    source_contract_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    content_digest: str
    story: Mapping[str, Any]
    created_at: str
    supersedes_storyboard_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_contract_ids", tuple(self.source_contract_ids))
        object.__setattr__(self, "source_hashes", tuple(self.source_hashes))
        object.__setattr__(self, "story", freeze_json(self.story))


@dataclass(frozen=True, slots=True)
class StoryboardRequest:
    command: str
    task_spec: ContractEnvelope
    task_context: ContractEnvelope
    product_context: ContractEnvelope
    plan: Mapping[str, Any]
    idempotency_key: str
    expected_version: int
    prior_artifact: StoryboardArtifact | None = None
    reference_manifest: ContractEnvelope | None = None
    cancellation_requested: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan", freeze_json(self.plan))


@dataclass(frozen=True, slots=True)
class StoryboardResult:
    status: str
    replay_status: str
    artifact: StoryboardArtifact | None = None
    asset_manifest: ContractEnvelope | None = None
    feedback_event: ContractEnvelope | None = None
    execution_event: ContractEnvelope | None = None


def _artifact_document(artifact: StoryboardArtifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "storyboard_id": artifact.storyboard_id,
        "version": artifact.version,
        "task_id": artifact.task_id,
        "product_id": artifact.product_id,
        "source_contract_ids": list(artifact.source_contract_ids),
        "source_hashes": list(artifact.source_hashes),
        "content_digest": artifact.content_digest,
        "story": thaw_json(artifact.story),
        "created_at": artifact.created_at,
        "supersedes_storyboard_id": artifact.supersedes_storyboard_id,
    }


def _envelope_from_document(value: object) -> ContractEnvelope | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or not isinstance(value.get("producer"), Mapping):
        raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay envelope is malformed")
    producer = value["producer"]
    try:
        envelope = ContractEnvelope(
            contract_type=str(value["contract_type"]),
            schema_version=str(value["schema_version"]),
            contract_id=UUID(str(value["contract_id"])),
            created_at=datetime.fromisoformat(str(value["created_at"]).replace("Z", "+00:00")),
            producer=ProducerIdentity(
                str(producer["agent"]),
                str(producer["component_id"]),
                str(producer["component_version"]),
            ),
            correlation_id=str(value["correlation_id"]),
            idempotency_key=str(value["idempotency_key"]),
            payload_digest=str(value["payload_digest"]),
            payload=value["payload"],
            task_id=value.get("task_id"),
            causation_id=value.get("causation_id"),
            trace_id=value.get("trace_id"),
            source_contract_ids=tuple(value.get("source_contract_ids", ())),
            source_hashes=tuple(value.get("source_hashes", ())),
        )
        validate_envelope(envelope)
        return envelope
    except (KeyError, TypeError, ValueError, ContractError) as exc:
        raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay envelope is malformed") from exc


def _result_document(result: StoryboardResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "replay_status": result.replay_status,
        "artifact": _artifact_document(result.artifact),
        "asset_manifest": result.asset_manifest.to_dict() if result.asset_manifest else None,
        "feedback_event": result.feedback_event.to_dict() if result.feedback_event else None,
        "execution_event": result.execution_event.to_dict() if result.execution_event else None,
    }


def _result_from_document(value: object) -> StoryboardResult:
    if not isinstance(value, Mapping):
        raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay result is malformed")
    artifact_value = value.get("artifact")
    try:
        artifact = StoryboardArtifact(**artifact_value) if isinstance(artifact_value, Mapping) else None
        result = StoryboardResult(
            status=str(value["status"]),
            replay_status="replayed",
            artifact=artifact,
            asset_manifest=_envelope_from_document(value.get("asset_manifest")),
            feedback_event=_envelope_from_document(value.get("feedback_event")),
            execution_event=_envelope_from_document(value.get("execution_event")),
        )
        expected_types = (
            (result.asset_manifest, "avp.contract.asset-manifest"),
            (result.feedback_event, "avp.contract.feedback-event"),
            (result.execution_event, "avp.contract.skill-execution-event"),
        )
        if any(envelope is not None and envelope.contract_type != expected for envelope, expected in expected_types):
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay Contract type is invalid")
        if result.status == "cancelled":
            if artifact is not None or result.asset_manifest is not None or result.feedback_event is not None:
                raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard cancelled replay contains an artifact")
            if result.execution_event is None or result.execution_event.payload.get("status") != "cancelled":
                raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard cancelled replay event is invalid")
            return result
        if result.status != "completed" or artifact is None or any(envelope is None for envelope, _ in expected_types):
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard completed replay is incomplete")
        if content_digest(artifact.story) != artifact.content_digest:
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay artifact digest is invalid")
        expected_storyboard_id = (
            f"storyboard-{artifact.content_digest.removeprefix('sha256:')[:16]}-v{artifact.version}"
        )
        if artifact.storyboard_id != expected_storyboard_id or artifact.version < 1:
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay artifact identity is invalid")
        supersedes_match = (
            re.fullmatch(r"storyboard-[0-9a-f]{16}-v([1-9][0-9]*)", artifact.supersedes_storyboard_id)
            if artifact.supersedes_storyboard_id
            else None
        )
        if (artifact.version == 1 and artifact.supersedes_storyboard_id is not None) or (
            artifact.version > 1
            and (supersedes_match is None or int(supersedes_match.group(1)) != artifact.version - 1)
        ):
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay supersession is invalid")
        datetime.fromisoformat(artifact.created_at.replace("Z", "+00:00"))
        from .domain import validate_story

        validate_story(
            artifact.story,
            product_id=artifact.product_id,
            visual_constraints=artifact.story.get("product_constraints", {}),
        )
        if any(envelope.task_id != artifact.task_id for envelope, _ in expected_types if envelope is not None):
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay task lineage is invalid")
        if any(
            tuple(envelope.source_contract_ids) != artifact.source_contract_ids
            or tuple(envelope.source_hashes) != artifact.source_hashes
            for envelope, _ in expected_types
            if envelope is not None
        ):
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay source lineage is invalid")
        expected_provenance = [
            {"contract_id": contract_id, "payload_digest": digest}
            for contract_id, digest in zip(artifact.source_contract_ids, artifact.source_hashes, strict=True)
        ]
        if thaw_json(artifact.story.get("source_provenance", ())) != expected_provenance:
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay source provenance is invalid")
        asset = result.asset_manifest.payload["assets"][0]
        if (
            result.asset_manifest.payload["manifest_revision"] != artifact.version
            or result.asset_manifest.payload["created_at"] != artifact.created_at
            or asset["asset_id"] != artifact.storyboard_id
            or asset["created_at"] != artifact.created_at
            or f"sha256:{asset['sha256']}" != artifact.content_digest
        ):
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay asset lineage is invalid")
        if artifact.storyboard_id not in result.feedback_event.payload["evidence_refs"]:
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay feedback lineage is invalid")
        if tuple(result.execution_event.payload["output_contract_refs"]) != (
            artifact.storyboard_id,
            str(result.asset_manifest.contract_id),
        ):
            raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay execution lineage is invalid")
        return result
    except (KeyError, IndexError, TypeError, ValueError, ContractError, StoryboardError) as exc:
        raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay result is malformed") from exc


class StoryboardError(Exception):
    """Stable, machine-readable Storyboard failure."""

    def __init__(
        self,
        code: str,
        category: str,
        message: str,
        *,
        retryable: bool = False,
        field_paths: tuple[str, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.message = message
        self.retryable = retryable
        self.field_paths = tuple(field_paths)
        sanitized = ContractError(
            ErrorCode.CONTRACT_VALIDATION_FAILED,
            ErrorCategory.VALIDATION,
            "Storyboard error detail sanitizer",
            details=details or {},
        )
        self.details = sanitized.details

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "retryable": self.retryable,
            "message": self.message,
            "field_paths": list(self.field_paths),
            "details": thaw_json(self.details),
        }


class StoryboardService:
    """Deterministic Storyboard application service with an injectable state store."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        version_store: VersionStore | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._version_store = version_store or InMemoryVersionStore()
        self._object_records: dict[str, tuple[str, StoryboardResult]] = {}

    def execute(self, request: StoryboardRequest) -> StoryboardResult:
        if request.command not in _COMMANDS:
            raise StoryboardError(
                "STORYBOARD_COMMAND_UNSUPPORTED",
                "validation",
                "Storyboard command is not supported",
                field_paths=("command",),
            )
        if not request.idempotency_key:
            raise StoryboardError(
                "STORYBOARD_IDEMPOTENCY_KEY_REQUIRED",
                "validation",
                "idempotency_key is required",
                field_paths=("idempotency_key",),
            )
        task_spec = self._validated(request.task_spec, "avp.contract.task-spec", "task_spec")
        task_context = self._validated(request.task_context, "avp.contract.task-context", "task_context")
        product_context = self._validated(
            request.product_context,
            "avp.contract.product-context-bundle",
            "product_context",
        )
        reference = None
        if request.reference_manifest is not None:
            reference = self._validated(
                request.reference_manifest,
                "avp.contract.reference-manifest",
                "reference_manifest",
            )
        self._validate_context(task_spec, task_context, product_context, reference, request)
        self._validate_request_identity(
            request,
            task_id=task_spec.payload.task_id,
            product_id=product_context.payload.product_id,
        )
        request_digest = self._request_digest(request)
        local = self._object_records.get(request.idempotency_key)
        if local is not None:
            previous_digest, previous_result = local
            if previous_digest != request_digest:
                raise StoryboardError(
                    "STORYBOARD_IDEMPOTENCY_CONFLICT",
                    "conflict",
                    "idempotency_key was reused with different Storyboard input",
                    field_paths=("idempotency_key",),
                )
            return replace(previous_result, replay_status="replayed")
        try:
            existing = self._version_store.lookup(request.idempotency_key)
        except VersionStoreError as exc:
            raise self._state_error(exc) from exc
        if existing is not None:
            if existing["request_digest"] != request_digest:
                raise StoryboardError(
                    "STORYBOARD_IDEMPOTENCY_CONFLICT",
                    "conflict",
                    "idempotency_key was reused with different Storyboard input",
                    field_paths=("idempotency_key",),
                )
            try:
                return _result_from_document(existing["result"])
            except VersionStoreError as exc:
                raise self._state_error(exc) from exc
        self._validate_version(request)

        if request.cancellation_requested:
            event = self._execution_event(request, status="cancelled", output_refs=())
            result = StoryboardResult(
                status="cancelled",
                replay_status="recorded",
                execution_event=event,
            )
            try:
                outcome = self._version_store.record_outcome(
                    request.idempotency_key,
                    request_digest,
                    _result_document(result),
                )
            except VersionStoreError as exc:
                raise self._state_error(exc) from exc
            return self._resolve_commit_outcome(outcome, request, request_digest, result)

        self._enforce_budget(request.plan)
        self._reject_forbidden_capabilities(request.plan)
        visual_constraints = product_context.payload.visual_constraints or {}
        plan = self._materialize_plan(
            request,
            product_id=product_context.payload.product_id,
            visual_constraints=visual_constraints,
        )
        self._enforce_budget(plan)
        self._reject_forbidden_capabilities(plan)
        from .domain import validate_story

        validate_story(
            plan,
            product_id=product_context.payload.product_id,
            visual_constraints=visual_constraints,
        )
        artifact = self._artifact(
            request,
            product_context.payload.product_id,
            visual_constraints,
            plan=plan,
        )
        self.validate_continuity(artifact)
        asset_manifest = self._asset_manifest(request, artifact)
        feedback_event = self._feedback_event(request, artifact)
        execution_event = self._execution_event(
            request,
            status="completed",
            output_refs=(artifact.storyboard_id, str(asset_manifest.contract_id)),
        )
        result = StoryboardResult(
            status="completed",
            replay_status="recorded",
            artifact=artifact,
            asset_manifest=asset_manifest,
            feedback_event=feedback_event,
            execution_event=execution_event,
        )
        expected_version = None if request.command in _CREATE_COMMANDS else request.expected_version
        try:
            outcome = self._version_store.commit(
                artifact.task_id,
                artifact.product_id,
                expected=expected_version,
                new_version=artifact.version,
                idempotency_key=request.idempotency_key,
                request_digest=request_digest,
                result=_result_document(result),
            )
        except VersionStoreError as exc:
            raise self._state_error(exc) from exc
        return self._resolve_commit_outcome(outcome, request, request_digest, result)

    def _resolve_commit_outcome(
        self,
        outcome: str,
        request: StoryboardRequest,
        request_digest: str,
        result: StoryboardResult,
    ) -> StoryboardResult:
        if outcome == "recorded":
            self._object_records[request.idempotency_key] = (request_digest, result)
            return result
        if outcome == "idempotency-conflict":
            raise StoryboardError(
                "STORYBOARD_IDEMPOTENCY_CONFLICT",
                "conflict",
                "idempotency_key was reused with different Storyboard input",
                field_paths=("idempotency_key",),
            )
        if outcome == "replay":
            try:
                existing = self._version_store.lookup(request.idempotency_key)
                if existing is None or existing["request_digest"] != request_digest:
                    raise VersionStoreError("STORYBOARD_STATE_CORRUPTED", "Storyboard replay record disappeared")
                return _result_from_document(existing["result"])
            except VersionStoreError as exc:
                raise self._state_error(exc) from exc
        if outcome == "stale":
            raise StoryboardError(
                "STORYBOARD_VERSION_STALE",
                "state",
                "Storyboard version changed before this revision could be committed",
                field_paths=("expected_version",),
            )
        raise StoryboardError(
            "STORYBOARD_STATE_CORRUPTED",
            "state",
            "Storyboard state returned an unknown commit outcome",
            field_paths=("state_file",),
        )

    @staticmethod
    def _state_error(exc: VersionStoreError) -> StoryboardError:
        return StoryboardError(
            exc.code,
            "state",
            exc.message,
            retryable=exc.retryable,
            field_paths=("state_file",),
        )

    def validate_continuity(self, artifact: StoryboardArtifact) -> None:
        from .domain import validate_story

        constraints = artifact.story.get("product_constraints", {})
        validate_story(artifact.story, product_id=artifact.product_id, visual_constraints=constraints)

    def _validated(self, envelope: object, contract_type: str, field_name: str):
        if not isinstance(envelope, ContractEnvelope) or envelope.contract_type != contract_type:
            raise StoryboardError(
                "STORYBOARD_CONTRACT_INVALID",
                "validation",
                "Storyboard input uses an unexpected Contract type",
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

    def _validate_context(self, task_spec, task_context, product_context, reference, request) -> None:
        task_id = task_spec.payload.task_id
        if (
            "storyboard" not in task_spec.payload.requested_skills
            or task_context.payload.active_skill_id != "storyboard"
            or task_context.payload.task_id != task_id
            or request.task_spec.task_id not in (None, task_id)
            or request.task_context.task_id not in (None, task_id)
            or request.product_context.task_id not in (None, task_id)
        ):
            raise StoryboardError(
                "STORYBOARD_CONTEXT_INVALID",
                "conflict",
                "TaskSpec and TaskContext do not activate the Storyboard Skill for one task",
                field_paths=("task_context.payload.active_skill_id",),
            )
        if reference is not None and reference.payload.task_id != task_id:
            raise StoryboardError(
                "STORYBOARD_CONTEXT_INVALID",
                "conflict",
                "ReferenceManifest belongs to a different task",
                field_paths=("reference_manifest.payload.task_id",),
            )
        constraints = task_spec.payload.constraints or {}
        if constraints.get("reference_required") and reference is None:
            raise StoryboardError(
                "STORYBOARD_REFERENCE_REQUIRED",
                "reference",
                "TaskSpec requires a ReferenceManifest",
                field_paths=("reference_manifest",),
            )
        selector = task_spec.payload.product_selector or {}
        if selector.get("sku_required") and not product_context.payload.sku_id:
            raise StoryboardError(
                "PRODUCT_SKU_AMBIGUOUS",
                "conflict",
                "Task requires one confirmed SKU in ProductContextBundle",
                field_paths=("product_context.payload.sku_id",),
            )

    def _validate_version(self, request: StoryboardRequest) -> None:
        task_id = request.task_spec.payload["task_id"]
        product_id = request.product_context.payload["product_id"]
        try:
            latest_version = self._version_store.current(task_id, product_id)
        except VersionStoreError as exc:
            raise StoryboardError(
                exc.code,
                "state",
                exc.message,
                retryable=exc.retryable,
                field_paths=("state_file",),
            ) from exc
        if request.command in _CREATE_COMMANDS:
            valid = (
                request.expected_version == 0
                and request.prior_artifact is None
                and latest_version is None
            )
        else:
            valid = (
                request.prior_artifact is not None
                and request.expected_version == request.prior_artifact.version
                and request.prior_artifact.task_id == task_id
                and request.prior_artifact.product_id == product_id
                and request.expected_version == latest_version
            )
        if not valid:
            raise StoryboardError(
                "STORYBOARD_VERSION_STALE",
                "state",
                "expected_version does not match the immutable Storyboard revision",
                field_paths=("expected_version",),
            )

    def _validate_request_identity(self, request: StoryboardRequest, *, task_id: str, product_id: str) -> None:
        if request.command in _CREATE_COMMANDS:
            valid = request.expected_version == 0 and request.prior_artifact is None
        else:
            prior = request.prior_artifact
            valid = (
                prior is not None
                and request.expected_version == prior.version
                and prior.task_id == task_id
                and prior.product_id == product_id
                and prior.version >= 1
                and content_digest(prior.story) == prior.content_digest
                and prior.storyboard_id
                == f"storyboard-{prior.content_digest.removeprefix('sha256:')[:16]}-v{prior.version}"
                and prior.story.get("product_id") == product_id
            )
        if not valid:
            raise StoryboardError(
                "STORYBOARD_VERSION_STALE",
                "state",
                "Storyboard request identity does not match its immutable prior revision",
                field_paths=("prior_artifact", "expected_version"),
            )

    def _reject_forbidden_capabilities(self, value: object, path: str = "plan") -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized = str(key).casefold().replace("-", "_")
                if normalized in _FORBIDDEN_CAPABILITY_KEYS:
                    raise StoryboardError(
                        "STORYBOARD_CAPABILITY_FORBIDDEN",
                        "authorization",
                        "Storyboard cannot generate media or submit a Provider",
                        field_paths=(f"{path}.{key}",),
                    )
                self._reject_forbidden_capabilities(nested, f"{path}.{safe_field_segment(key)}")
        elif isinstance(value, (list, tuple)):
            for index, nested in enumerate(value):
                self._reject_forbidden_capabilities(nested, f"{path}[{index}]")

    def _materialize_plan(
        self,
        request: StoryboardRequest,
        *,
        product_id: str,
        visual_constraints: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        from .planning import build_storyboard_plan, validate_continuity_archive

        supplied = thaw_json(request.plan)
        raw_script = supplied.get("raw_script")
        if request.command == "create-storyboard-from-script" and raw_script is None:
            raise StoryboardError(
                "STORYBOARD_PLANNING_INVALID",
                "validation",
                "create-storyboard-from-script requires raw_script",
                field_paths=("plan.raw_script",),
            )
        if raw_script is not None and not supplied.get("scenes"):
            return freeze_json(
                build_storyboard_plan(
                    raw_script,
                    product_id=product_id,
                    visual_constraints=visual_constraints,
                    planning_options=supplied.get("planning_options"),
                    continuity_archive=supplied.get("continuity_archive"),
                )
            )
        archive = supplied.get("continuity_archive")
        if archive is not None:
            supplied["continuity_archive"] = validate_continuity_archive(
                archive,
                product_id=product_id,
            )
        return freeze_json(supplied)

    def _enforce_budget(self, plan: Mapping[str, Any]) -> None:
        if len(canonical_json(plan).encode("utf-8")) > MAX_PLAN_BYTES:
            raise StoryboardError(
                "STORYBOARD_BUDGET_EXCEEDED",
                "validation",
                "Storyboard plan exceeds the 1 MiB canonical input budget",
                field_paths=("plan",),
            )
        panel_count = 0
        for scene in plan.get("scenes", ()) if isinstance(plan, Mapping) else ():
            if not isinstance(scene, Mapping):
                continue
            for beat in scene.get("beats", ()):
                if not isinstance(beat, Mapping):
                    continue
                for shot in beat.get("shots", ()):
                    if isinstance(shot, Mapping) and isinstance(shot.get("panels"), (list, tuple)):
                        panel_count += len(shot["panels"])
        if panel_count > MAX_PANELS:
            raise StoryboardError(
                "STORYBOARD_BUDGET_EXCEEDED",
                "validation",
                "Storyboard plan exceeds the 500 Panel budget",
                field_paths=("plan.scenes",),
                details={"panel_count": panel_count, "maximum": MAX_PANELS},
            )

    def _request_digest(self, request: StoryboardRequest) -> str:
        return content_digest(
            {
                "command": request.command,
                "task_spec": getattr(request.task_spec, "payload_digest", None),
                "task_context": getattr(request.task_context, "payload_digest", None),
                "product_context": getattr(request.product_context, "payload_digest", None),
                "reference_manifest": getattr(request.reference_manifest, "payload_digest", None),
                "plan": request.plan,
                "expected_version": request.expected_version,
                "prior_artifact": _artifact_document(request.prior_artifact),
                "cancellation_requested": request.cancellation_requested,
            }
        )

    def _artifact(
        self,
        request: StoryboardRequest,
        product_id: str,
        visual_constraints: Mapping[str, Any],
        *,
        plan: Mapping[str, Any],
    ) -> StoryboardArtifact:
        source_envelopes = [request.task_spec, request.task_context, request.product_context]
        if request.reference_manifest is not None:
            source_envelopes.append(request.reference_manifest)
        story = thaw_json(freeze_json(plan))
        story["artifact_kind"] = "storyboard-owner-local-draft"
        story["artifact_version"] = STORYBOARD_VERSION
        story["product_constraints"] = thaw_json(freeze_json(visual_constraints))
        story["source_provenance"] = [
            {"contract_id": str(item.contract_id), "payload_digest": item.payload_digest}
            for item in source_envelopes
        ]
        digest = content_digest(story)
        version = 1 if request.prior_artifact is None else request.prior_artifact.version + 1
        return StoryboardArtifact(
            storyboard_id=f"storyboard-{digest.removeprefix('sha256:')[:16]}-v{version}",
            version=version,
            task_id=request.task_spec.payload["task_id"],
            product_id=product_id,
            source_contract_ids=tuple(str(item.contract_id) for item in source_envelopes),
            source_hashes=tuple(item.payload_digest for item in source_envelopes),
            content_digest=digest,
            story=freeze_json(story),
            created_at=format_utc(self._clock()),
            supersedes_storyboard_id=(request.prior_artifact.storyboard_id if request.prior_artifact else None),
        )

    def _asset_manifest(self, request: StoryboardRequest, artifact: StoryboardArtifact) -> ContractEnvelope:
        uri = f"task://{artifact.task_id}/storyboards/{artifact.storyboard_id}/v{artifact.version}.json"
        payload = {
            "manifest_id": f"manifest-{artifact.storyboard_id}",
            "manifest_revision": artifact.version,
            "owner_type": "task",
            "owner_id": artifact.task_id,
            "assets": [
                {
                    "asset_id": artifact.storyboard_id,
                    "role": "owner-local-draft",
                    "media_type": "application/json",
                    "uri": uri,
                    "sha256": artifact.content_digest.removeprefix("sha256:"),
                    "byte_size": len(canonical_json(artifact.story).encode("utf-8")),
                    "provenance": {
                        "kind": "clean-room-synthetic-plan",
                        "publication_status": "not-registered",
                        "source_contract_ids": list(artifact.source_contract_ids),
                        "source_hashes": list(artifact.source_hashes),
                    },
                    "created_at": artifact.created_at,
                }
            ],
            "created_at": artifact.created_at,
        }
        envelope = build_envelope(
            contract_type="avp.contract.asset-manifest",
            payload=payload,
            producer=ProducerIdentity("skill", "storyboard", STORYBOARD_VERSION),
            correlation_id=request.task_spec.correlation_id,
            idempotency_key=f"{request.idempotency_key}:asset-manifest",
            task_id=artifact.task_id,
            source_contract_ids=artifact.source_contract_ids,
            source_hashes=artifact.source_hashes,
            created_at=self._clock(),
        )
        validate_envelope(envelope)
        return envelope

    def _feedback_event(self, request: StoryboardRequest, artifact: StoryboardArtifact) -> ContractEnvelope:
        configured = [
            name
            for name in ("required_color", "logo_visibility")
            if artifact.story.get("product_constraints", {}).get(name) not in (None, "")
        ]
        if configured:
            statement = f"Configured {', '.join(configured)} constraints were traced into every synthetic Panel prompt."
        else:
            statement = "No supported visual constraints were configured; Panel product identity was validated."
        payload = {
            "feedback_id": f"feedback-{artifact.storyboard_id}",
            "task_id": artifact.task_id,
            "source_skill_id": "storyboard",
            "feedback_type": "storyboard-product-constraint-observation",
            "statement": statement,
            "evidence_refs": [artifact.storyboard_id],
            "rule_scope": "product",
            "scope_key": {"product_id": artifact.product_id},
            "bindings": {"task_id": artifact.task_id},
            "observed_at": artifact.created_at,
            "submitted_by": "storyboard",
            "product_id": artifact.product_id,
        }
        envelope = build_envelope(
            contract_type="avp.contract.feedback-event",
            payload=payload,
            producer=ProducerIdentity("skill", "storyboard", STORYBOARD_VERSION),
            correlation_id=request.task_spec.correlation_id,
            idempotency_key=f"{request.idempotency_key}:feedback",
            task_id=artifact.task_id,
            source_contract_ids=artifact.source_contract_ids,
            source_hashes=artifact.source_hashes,
            created_at=self._clock(),
        )
        validate_envelope(envelope)
        return envelope

    def _execution_event(self, request: StoryboardRequest, *, status: str, output_refs: tuple[str, ...]) -> ContractEnvelope:
        source_envelopes = [request.task_spec, request.task_context, request.product_context]
        if request.reference_manifest is not None:
            source_envelopes.append(request.reference_manifest)
        payload = {
            "execution_id": f"execution-{content_digest(self._request_digest(request)).removeprefix('sha256:')[:20]}",
            "task_id": request.task_spec.payload["task_id"],
            "skill_id": "storyboard",
            "event_type": status,
            "sequence": 1,
            "occurred_at": format_utc(self._clock()),
            "status": status,
            "input_contract_refs": [str(item.contract_id) for item in source_envelopes],
            "output_contract_refs": list(output_refs),
            "metrics": {"provider_calls": 0, "network_calls": 0},
        }
        envelope = build_envelope(
            contract_type="avp.contract.skill-execution-event",
            payload=payload,
            producer=ProducerIdentity("skill", "storyboard", STORYBOARD_VERSION),
            correlation_id=request.task_spec.correlation_id,
            idempotency_key=f"{request.idempotency_key}:execution:{status}",
            task_id=request.task_spec.payload["task_id"],
            source_contract_ids=tuple(str(item.contract_id) for item in source_envelopes),
            source_hashes=tuple(item.payload_digest for item in source_envelopes),
            created_at=self._clock(),
        )
        validate_envelope(envelope)
        return envelope
