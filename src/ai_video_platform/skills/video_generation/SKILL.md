# Video Generation

Status: `RC_PROVIDER_PENDING`; local interface version `0.1.0`; DV status
`CLEAN_ROOM_ONLY`. KIE smoke requires the separately issued
`FTG-P-VIDEO-001` authorization plus its runtime credential and numeric budget cap.

The public `inspect_video_request` / `inspect-video-request` surface validates an
unregistered draft VideoExecutionPackage, effective ApprovalRecord, budget limits,
opaque Provider binding reference, deterministic request hash, and idempotency key.
It returns a safe provider summary without a credential reference and records
`provider_execution_performed: false`.

The injected Python interface also exposes `submit_video`, `poll_video`,
`cancel_video`, `download_video`, and `recover_video`. These operations require an
explicit adapter and ledger. The shipped Fake adapter is deterministic and
in-memory; Rejecting and NetworkBlocked adapters fail closed. The KIE production
adapter is available only by explicit Python construction and reads `KIE_API_KEY`
through its dedicated resolver. Approved local reference images use a separate,
digest-verified multipart uploader at KIE's `file-stream-upload` endpoint before
generation. Uploads use the authorized browser-header set and the exact `file`,
`uploadPath`, and `fileName` form fields. The current KIE response field is
`data.downloadUrl`, with `data.fileUrl` or a URL derived from `data.filePath`
accepted as fallbacks. The generic module CLI never selects the production adapter or uploader.
KIE execution results record `provider_network_performed: true`; offline adapters
continue to record `false`.

Preflight order is fixed and fail-closed: validate the execution package and its
nested master first, then ApprovalRecord, budget, Provider binding plus opaque
credential reference, output controls, and idempotency key; only then derive the
request hash. Every validation completes before an adapter, ledger, filesystem, or
other side-effect seam may be invoked.

Video Generation does not rewrite storyboards, import Planning implementation,
write Product Library, read Legacy, persist or display credential values, write
media files, or create a formal business identity. Network and remote download are
available only through the explicitly injected KIE adapter under FTG-P authorization.
Draft business artifacts remain `DRAFT_UNREGISTERED` pending the Codex-00 Business
Artifact Registry gate.

## Public command and side effects

```text
python -m ai_video_platform.skills.video_generation.cli inspect-video-request <file|->
python -m ai_video_platform.skills.video_generation.cli submit-video <file|->
python -m ai_video_platform.skills.video_generation.cli poll-video <job-file|->
python -m ai_video_platform.skills.video_generation.cli cancel-video <job-file|->
python -m ai_video_platform.skills.video_generation.cli download-video <job-file|->
python -m ai_video_platform.skills.video_generation.cli recover-video <job-file|->
python -m ai_video_platform.skills.video_generation.offline_acceptance --package <package> --evidence-dir <new-dir>
```

The CLI reads exactly the named local JSON file or stdin and writes one JSON result
to stdout. Exit `0` is ready; exit `2` is a fail-closed rejection. Preflight has no
Provider or filesystem write side effect. Submit/poll/cancel/download/recovery are
available only through an explicitly injected Python adapter plus snapshotting
execution ledger. `run_cli` accepts that explicit context for orchestration; the
module CLI never silently selects an adapter and thus fails closed for execution
commands unless the host supplies one.

The independent `offline_acceptance` CLI is Provider-free. It writes a sanitized
business request and a receipt demonstrating fake preflight/submit/poll/download,
Rejecting-adapter fail-closed behavior, cancellation, and ledger-only recovery.
It refuses to overwrite an existing evidence directory.

The authorized KIE path is fixed to provider `kie`, model
`bytedance/seedance-2-fast`, 480p, 16:9, no generated audio, no web search, at most
5 seconds, exactly one request slot, one concurrent task, at most two attempts, and
at most 600 seconds. It requires two or more HTTPS reference images. Provider task
results are queried through KIE's unified task endpoint; `creditsConsumed` is stored
as `provider_cost_units`, and downloaded bytes are digest-verified before producing
an opaque `kie://...` AssetManifestRequest URI. The documented KIE Market API does
not expose task cancellation, so the adapter rejects `cancel` explicitly instead of
claiming that a remote task was cancelled. Under Revision C, a module-fixed atomic
reservation prevents a second smoke across evidence directories. The first polling
transport or response anomaly is terminal: no automatic poll retry is permitted,
all later polling stops, and any late artifact must not be downloaded or registered.
HTTP failures and Provider business-error responses preserve a redacted status and
body summary for the smoke receipt; authorization and credential material remain excluded.
Task identifiers are retained because they are not credentials. The receipt records
the observed HTTP status chain and fails closed unless its exact-credential scan is zero.

Stable errors cover package identity/version/digest, ApprovalRecord effectiveness
and subject binding, budgets, Provider binding, opaque credential reference, and
idempotency input. Errors recursively redact credential/token-like fields and values.
Corrected inputs may be retried; deterministic request hashing supplies the basis
for exact replay and mismatch handling in the execution ledger.

The ledger atomically reserves request and concurrency budget, snapshots every
read/write, retains transition history, exposes read-only recovery, and records
deterministic states: `submitting`, `submitted`, `polling`,
`recovery_required`, `succeeded`, `failed`, `cancelled`, `timed_out`, and
`downloaded`. Uncertain Provider outcomes retain active capacity as
`recovery_required`; recovery reads ledger history without polling. Download verifies
the in-memory artifact digest and emits only a `DRAFT_UNREGISTERED`
AssetManifestRequest; it never writes Product Library.

Hermes example: call `inspect-video-request` with package, approval, budget,
provider-binding reference, output controls, and idempotency key. Route `ready` to
the separately authorized execution command only when that adapter/gate exists;
otherwise keep the task blocked. Hermes never resolves the credential reference.

## Tests and rollback

```text
python -m unittest -v tests.skills.video_generation.test_video_generation_interface
python -m unittest -v tests.skills.video_generation.test_video_generation_adapters
python -m unittest -v tests.skills.video_generation.test_video_generation_safety
python -m unittest -v tests.skills.video_generation.test_kie_adapter
python -m unittest -v tests.skills.video_generation.test_video_generation_offline_acceptance
```

Rollback by reverting the owning commits. Preflight creates no Provider job, remote
asset, credential, Library write, or formal Contract registration to undo.
