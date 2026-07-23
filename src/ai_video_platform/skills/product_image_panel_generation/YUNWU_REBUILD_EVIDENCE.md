# Yunwu Rebuild Evidence

Task: `FT-04-YUNWU-R`

Branch: `ft/codex-04-image-panel`

Starting point: `b2e8b15`

## Commits

- `938214b` - rebuilt the Yunwu adapters and Provider metadata propagation.
- `3a9b523` - restored the 13 offline Yunwu adapter tests.
- `e9b053f` - wired both Yunwu adapter names into the CLI and removed the
  unknown-adapter test pin.

## Disassembly Alignment

`yunwu_adapters.py` and `test_yunwu_adapters.py` were reconstructed from:

- `yunwu_adapters.dis.txt`
- `test_yunwu_adapters.dis.txt`

The restored surface includes the FTG-P-003 authorization binding, exact
Provider/model endpoints, response and image size limits, timeout cap,
fail-closed model and endpoint checks, payload shapes, receipt metadata,
verified image dimensions, CLI artifact persistence, and exact replay without
a second transport call.

Alignment with the recovered adapter and test disassembly: `EXACT`.

## Offline Verification

Environment for all verification: Python 3.14, `PYTHONPATH` removed, and
`YUNWU_API_KEY` set to an empty string. No real Provider or credential was
used.

- Focused Yunwu plus interface tests: `36 passed, 4 subtests passed`.
- Product image/panel suite: `72 passed, 4 subtests passed`.
- Repository offline runner: `Ran 324 tests`; `OK (skipped=3)`.

The Yunwu tests use `RecordingTransport`; they perform no network I/O.

## Provider Gate

`real_smoke: NOT_DONE`

Real Yunwu Provider smoke, media generation, and receipt capture remain gated
behind a separate `FTG-P-004` authorization and explicit user approval.
