# FT-04-001 Dependency And Coverage Request

Status: `REQUESTED_CODEX_00_REVIEW`
Authorization: `FTG-0-20260720-001`
Work item: `FT-04-001`
Requester: `codex-04`

## Runtime dependency decision

No runtime dependency is requested. The implementation uses only the Python standard library and approved in-repository Foundation Contract/Core interfaces. It contains no Provider SDK or production Adapter.

## Test/release tooling request

The launch baseline has no branch-coverage tool installed (`python -m coverage --version` returns `No module named coverage`). Codex-04 cannot edit `pyproject.toml` or the dependency lock.

Codex-00 is requested to choose one of the following before FTG-3:

1. add an offline-lockable, license-reviewed coverage tool to the shared development/release environment and record line/branch coverage for the Codex-04 owner package; or
2. issue the written FTG-3 coverage-tool waiver required by `PRODUCTION_READY_DEFINITION.md`, with equivalent review evidence.

No network installation is authorized by this request. Any package addition remains Codex-00-owned and must use the project's approved offline dependency process, SBOM, and license inventory.
