# Product Knowledge Targeted DV Requests

These are prepared single-capability requests for Hermes/CatPaw routing. They do not authorize reads by themselves. No Legacy file has been read, copied, executed, wrapped, refactored, or adopted by Codex-01; current implementation verdict is `CLEAN_ROOM_ONLY`.

```yaml
catpaw_targeted_read_request:
  schema_version: "1.0"
  authorization_id: "FTG-0-20260720-001"
  request_id: "CP-FT-codex-01-001"
  requested_by: "hermes"
  workline_id: "codex-01"
  dv_case_id: "DV-codex-01-product-loader-validator-001"
  single_capability_question: "Which narrow files, if any, implement an offline product registry loader and validator with explicit schema/version failures and no runtime Provider or Legacy-path dependency?"
  allowed_legacy_root_ids: ["LSL-01", "LSL-02", "LSL-03", "LSL-04", "LSL-06"]
  relative_path_hints: ["product registry", "product schema", "loader", "validator", "tests for those exact capabilities"]
  evidence_required: ["path and SHA-256", "entrypoint and call-chain evidence", "dependency/config variable names without secret values", "test files and reproducible offline commands", "side effects: filesystem/network/subprocess/provider", "fork/duplicate/dirty-state evidence"]
  forbidden_actions: ["write, rename, delete or clean legacy files", "read .env, token or credential values", "run real Provider or network calls", "download media", "scan outside allowlisted capability", "issue executable canonical/adopt/migrate/deprecate decisions"]
  output_directory: "C:\\Users\\boss0\\Desktop\\05-项目文件夹\\AI Video Platform Audit\\fast_track\\codex-01\\DV-codex-01-product-loader-validator-001"
  expiry: "2026-07-27T18:00:00+08:00"
```

```yaml
catpaw_targeted_read_request:
  schema_version: "1.0"
  authorization_id: "FTG-0-20260720-001"
  request_id: "CP-FT-codex-01-002"
  requested_by: "hermes"
  workline_id: "codex-01"
  dv_case_id: "DV-codex-01-sku-conflict-provenance-002"
  single_capability_question: "Which narrow files, if any, implement deterministic product/SKU matching, ambiguity blocking, conflict history, and per-fact provenance without last-write-wins?"
  allowed_legacy_root_ids: ["LSL-01", "LSL-02", "LSL-03", "LSL-04", "LSL-06"]
  relative_path_hints: ["product/SKU match", "fact provenance", "conflict records", "asset relations", "tests for those exact capabilities"]
  evidence_required: ["path and SHA-256", "entrypoint and call-chain evidence", "dependency/config variable names without secret values", "test files and reproducible offline commands", "side effects: filesystem/network/subprocess/provider", "fork/duplicate/dirty-state evidence"]
  forbidden_actions: ["write, rename, delete or clean legacy files", "read .env, token or credential values", "run real Provider or network calls", "download media", "scan outside allowlisted capability", "issue executable canonical/adopt/migrate/deprecate decisions"]
  output_directory: "C:\\Users\\boss0\\Desktop\\05-项目文件夹\\AI Video Platform Audit\\fast_track\\codex-01\\DV-codex-01-sku-conflict-provenance-002"
  expiry: "2026-07-27T18:00:00+08:00"
```

```yaml
catpaw_targeted_read_request:
  schema_version: "1.0"
  authorization_id: "FTG-0-20260720-001"
  request_id: "CP-FT-codex-01-003"
  requested_by: "hermes"
  workline_id: "codex-01"
  dv_case_id: "DV-codex-01-feedback-rule-promotion-003"
  single_capability_question: "Which narrow files, if any, preserve immutable feedback events, deduplicate without source loss, and require explicit review/approval before six-scope rule promotion?"
  allowed_legacy_root_ids: ["LSL-01", "LSL-02", "LSL-03", "LSL-04", "LSL-06"]
  relative_path_hints: ["feedback intake", "feedback deduplication", "rule candidates", "approval/review separation", "tests for those exact capabilities"]
  evidence_required: ["path and SHA-256", "entrypoint and call-chain evidence", "dependency/config variable names without secret values", "test files and reproducible offline commands", "side effects: filesystem/network/subprocess/provider", "fork/duplicate/dirty-state evidence"]
  forbidden_actions: ["write, rename, delete or clean legacy files", "read .env, token or credential values", "run real Provider or network calls", "download media", "scan outside allowlisted capability", "issue executable canonical/adopt/migrate/deprecate decisions"]
  output_directory: "C:\\Users\\boss0\\Desktop\\05-项目文件夹\\AI Video Platform Audit\\fast_track\\codex-01\\DV-codex-01-feedback-rule-promotion-003"
  expiry: "2026-07-27T18:00:00+08:00"
```
