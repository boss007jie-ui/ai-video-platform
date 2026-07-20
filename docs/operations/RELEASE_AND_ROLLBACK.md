# Release and rollback

Only an offline release candidate may be produced under
`FTG-0-20260720-001`. Provider smoke remains `NOT_AUTHORIZED`, and this
procedure must not label the platform Production Ready.

Generate the deterministic evidence bundle from a reviewed source commit and
an immutable JSON test summary:

```powershell
python tools\release\build_release_bundle.py `
  --source-commit <40-character-sha> `
  --version 0.1.0 `
  --authorization-id FTG-0-20260720-001 `
  --test-evidence <test-summary.json> `
  --output <release-evidence-directory>
```

The test evidence JSON must contain exactly `offline-tests`,
`reproducible-build`, `ownership-scan`, `secret-scan`, `license-scan`, and
`rollback-exercise`. Every record must have `status: PASS` plus a
`sha256:<hex>` digest for its immutable log. The generator rejects a dirty
worktree, a source SHA other than current `HEAD`, a version mismatch, or any
missing/failed evidence. It hashes the reproducibly built wheel into the
manifest.

The bundle also contains an SPDX 2.3 SBOM, license inventory and rollback
record. Because the current package has no runtime or build dependencies,
`requirements.lock` is an explicit empty lock. Any dependency addition
requires Codex-00 review and regenerated license/SBOM evidence.

Rollback uses a normal `git revert` of the release commit, followed by
`python tools\run_offline_tests.py`. Offline RCs have no Provider side effects
or data migration to reverse.
