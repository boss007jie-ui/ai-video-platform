# CatPaw Targeted Read Request — Viral Research Capability

- `case_id`: `DV-codex-02-viral-research-001`
- `authorization_id`: `FTG-0-20260720-001`
- `work_item_id`: `FT-02-001`
- `workline_id` / `owner`: `codex-02`
- `capability`: static evidence for viral research query/normalization/ranking seams only
- `legacy_root_ids`: `LSL-01`, `LSL-02`, `LSL-03`, `LSL-04`, `LSL-06`
- `relative_path_allowlist[]`: `NOT_PROVIDED`
- `source_commit_dirty_state`: `NOT_READ`
- `source_sha256[]`: `NOT_READ`
- `tests_allowed[]`: `T0` only after an exact relative-path allowlist is approved
- `side_effect_controls`: read-only; network, subprocess, media download, credential values and source writes forbidden
- `expected_interface_mapping`: Viral Research public inspect/research/collect interfaces and internal Provider/Download seams
- `evidence_output`: `NOT_CREATED`
- `expiry`: current Fast Track sprint
- `status`: `REQUESTED_NOT_RUN`
- `implementation_provenance`: `CLEAN_ROOM_ONLY`

The root IDs are an upper bound, not an executable root-only allowlist. No CatPaw callable and no exact relative-path allowlist were supplied, so this case failed closed. No Legacy file was read, copied, hashed, tested, adopted or migrated. Any future CatPaw canonical/adopt/migrate wording is non-executable evidence and cannot update an Adoption Manifest.
