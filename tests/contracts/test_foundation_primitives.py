from __future__ import annotations

import unittest
import uuid
from dataclasses import replace
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from ai_video_platform.contracts.compatibility import Compatibility, SemVer, evaluate_compatibility
from ai_video_platform.contracts.envelope import ProducerIdentity, build_envelope
from ai_video_platform.contracts.errors import ContractError, ErrorCode
from ai_video_platform.contracts.serialization import canonical_json, content_digest
from ai_video_platform.contracts.validation import validate_envelope, validate_payload
from ai_video_platform.core.ids import uuid7


class FoundationPrimitiveTests(unittest.TestCase):
    def test_canonical_json_and_digest_are_reproducible(self) -> None:
        left = {"b": "x", "a": 1}
        right = {"a": 1, "b": "x"}

        self.assertEqual(canonical_json(left), '{"a":1,"b":"x"}')
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(
            content_digest(left),
            "sha256:ecf9e98ec0641e23113ff3ce8bdc78d0ddd249886517fd4a7f68cc83d4e65667",
        )

    def test_typed_payload_canonical_json_and_digest_are_reproducible(self) -> None:
        typed = validate_payload(
            "avp.contract.task-spec",
            {
                "task_id": "task-001",
                "task_type": "single-skill",
                "requested_skills": ["storyboard"],
                "objective": "Create a synthetic plan",
                "input_refs": [],
                "requested_outputs": ["synthetic-output"],
                "created_by": "human:test",
                "created_at": "2026-07-20T00:00:00Z",
                "bindings": {"region": "US"},
            },
        )
        expected = (
            '{"bindings":{"region":"US"},"created_at":"2026-07-20T00:00:00Z",'
            '"created_by":"human:test","input_refs":[],"objective":"Create a synthetic plan",'
            '"requested_outputs":["synthetic-output"],"requested_skills":["storyboard"],'
            '"task_id":"task-001","task_type":"single-skill"}'
        )

        self.assertEqual(canonical_json(typed), expected)
        self.assertEqual(canonical_json(typed), canonical_json(typed))
        self.assertEqual(
            content_digest(typed),
            "sha256:915b45b36d9c63f8b81b3fc208ad44c91a18672559ceed2abda4ca50bef59182",
        )

    def test_uuid7_has_version_and_variant_bits(self) -> None:
        value = uuid7(timestamp_ms=1_700_000_000_000, random_bits=0)

        self.assertIsInstance(value, uuid.UUID)
        self.assertEqual(value.version, 7)
        self.assertEqual(value.variant, uuid.RFC_4122)

    def test_semver_compatibility_follows_reader_writer_matrix(self) -> None:
        self.assertEqual(evaluate_compatibility("1.2.0", "1.1.0"), Compatibility.COMPATIBLE)
        self.assertEqual(evaluate_compatibility("1.1.0", "1.2.0"), Compatibility.READER_TOO_OLD)
        self.assertEqual(evaluate_compatibility("2.0.0", "1.9.9"), Compatibility.MAJOR_MISMATCH)

    def test_semver_parser_enforces_numeric_identifier_rules(self) -> None:
        parsed = SemVer.parse("1.2.3-alpha.1+build.5")

        self.assertEqual((parsed.major, parsed.minor, parsed.patch), (1, 2, 3))
        self.assertEqual(parsed.prerelease, "alpha.1")
        self.assertEqual(parsed.build, "build.5")
        for invalid in ("01.2.3", "1.0", "1.0.0-01", "1.0.0-alpha..1"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    SemVer.parse(invalid)

    def test_envelope_accepts_supported_additive_minor_and_preserves_unknown_fields(self) -> None:
        payload = {
            "task_id": "task-001",
            "task_type": "single-skill",
            "requested_skills": ["storyboard"],
            "objective": "Create a synthetic plan",
            "input_refs": [],
            "requested_outputs": ["synthetic-output"],
            "created_by": "human:test",
            "created_at": "2026-07-20T00:00:00Z",
            "x-avp-future": {"optional": True},
        }
        envelope = build_envelope(
            contract_type="avp.contract.task-spec",
            payload=payload,
            producer=ProducerIdentity("human", "authorized-direct-cli-caller", "1.0.0"),
            correlation_id="corr-001",
            idempotency_key="idem-001",
            contract_id=uuid7(timestamp_ms=1_700_000_000_000, random_bits=5),
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )
        future_minor = replace(envelope, schema_version="1.1.0")

        result = validate_envelope(future_minor, reader_version="1.1.0")

        self.assertEqual(result.payload.__contract_json__()["x-avp-future"], {"optional": True})

    def test_envelope_rejects_unknown_major_even_when_reader_matches_it(self) -> None:
        envelope = build_envelope(
            contract_type="avp.contract.task-spec",
            payload={
                "task_id": "task-001",
                "task_type": "single-skill",
                "requested_skills": ["storyboard"],
                "objective": "Create a synthetic plan",
                "input_refs": [],
                "requested_outputs": ["synthetic-output"],
                "created_by": "human:test",
                "created_at": "2026-07-20T00:00:00Z",
            },
            producer=ProducerIdentity("human", "authorized-direct-cli-caller", "1.0.0"),
            correlation_id="corr-001",
            idempotency_key="idem-001",
            contract_id=uuid7(timestamp_ms=1_700_000_000_000, random_bits=6),
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )
        unknown_major = replace(envelope, schema_version="2.0.0")

        with self.assertRaises(ContractError) as captured:
            validate_envelope(unknown_major, reader_version="2.0.0")

        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_SCHEMA_UNSUPPORTED)

    def test_envelope_maps_malformed_schema_version_to_stable_contract_error(self) -> None:
        envelope = build_envelope(
            contract_type="avp.contract.task-spec",
            payload={
                "task_id": "task-001",
                "task_type": "single-skill",
                "requested_skills": ["storyboard"],
                "objective": "Create a synthetic plan",
                "input_refs": [],
                "requested_outputs": ["synthetic-output"],
                "created_by": "human:test",
                "created_at": "2026-07-20T00:00:00Z",
            },
            producer=ProducerIdentity("human", "authorized-direct-cli-caller", "1.0.0"),
            correlation_id="corr-001",
            idempotency_key="idem-001",
            contract_id=uuid7(timestamp_ms=1_700_000_000_000, random_bits=7),
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )
        malformed = replace(envelope, schema_version="not-semver")

        with self.assertRaises(ContractError) as captured:
            validate_envelope(malformed)

        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_SCHEMA_UNSUPPORTED)

    def test_build_envelope_uses_registered_contract_and_payload_hash(self) -> None:
        payload = {
            "task_id": "task-001",
            "task_type": "single-skill",
            "requested_skills": ["storyboard"],
            "objective": "Create a synthetic plan",
            "input_refs": [],
            "requested_outputs": ["synthetic-output"],
            "created_by": "human:test",
            "created_at": "2026-07-20T00:00:00Z",
        }
        envelope = build_envelope(
            contract_type="avp.contract.task-spec",
            payload=payload,
            producer=ProducerIdentity("human", "authorized-direct-cli-caller", "1.0.0"),
            correlation_id="corr-001",
            idempotency_key="idem-001",
            contract_id=uuid7(timestamp_ms=1_700_000_000_000, random_bits=1),
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        serialized = envelope.to_dict()
        self.assertEqual(serialized["contract_type"], "avp.contract.task-spec")
        self.assertEqual(serialized["schema_version"], "1.0.0")
        self.assertEqual(serialized["payload_digest"], content_digest(payload))
        self.assertEqual(serialized["created_at"], "2026-07-20T00:00:00Z")

    def test_envelope_rejects_empty_identity_fields_and_malformed_source_hash(self) -> None:
        base = {
            "contract_type": "avp.contract.task-spec",
            "payload": {
                "task_id": "task-001",
                "task_type": "single-skill",
                "requested_skills": ["storyboard"],
                "objective": "Create a synthetic plan",
                "input_refs": [],
                "requested_outputs": ["synthetic-output"],
                "created_by": "human:test",
                "created_at": "2026-07-20T00:00:00Z",
            },
            "producer": ProducerIdentity("human", "authorized-direct-cli-caller", "1.0.0"),
            "correlation_id": "corr-001",
            "idempotency_key": "idem-001",
            "contract_id": uuid7(timestamp_ms=1_700_000_000_000, random_bits=8),
            "created_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
        }

        with self.assertRaises(ValueError):
            build_envelope(**{**base, "correlation_id": ""})
        with self.assertRaises(ValueError):
            build_envelope(**{**base, "source_hashes": ("not-a-digest",)})

    def test_envelope_and_typed_payload_are_deeply_immutable(self) -> None:
        payload = {
            "task_id": "task-001",
            "task_type": "single-skill",
            "requested_skills": ["storyboard"],
            "objective": "Create a synthetic plan",
            "input_refs": [],
            "requested_outputs": ["synthetic-output"],
            "created_by": "human:test",
            "created_at": "2026-07-20T00:00:00Z",
            "bindings": {"region": "US"},
        }
        envelope = build_envelope(
            contract_type="avp.contract.task-spec",
            payload=payload,
            producer=ProducerIdentity("human", "authorized-direct-cli-caller", "1.0.0"),
            correlation_id="corr-001",
            idempotency_key="idem-001",
            contract_id=uuid7(timestamp_ms=1_700_000_000_000, random_bits=3),
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        payload["requested_skills"].append("qa-review")
        payload["bindings"]["region"] = "EU"
        self.assertEqual(envelope.payload["requested_skills"], ("storyboard",))
        self.assertEqual(envelope.payload["bindings"]["region"], "US")
        with self.assertRaises(TypeError):
            envelope.payload["bindings"]["region"] = "EU"

        typed = validate_payload("avp.contract.task-spec", envelope.payload)
        with self.assertRaises(FrozenInstanceError):
            typed.objective = "Changed"
        with self.assertRaises(TypeError):
            typed.bindings["region"] = "EU"

        serialized = envelope.to_dict()
        self.assertEqual(serialized["payload"]["requested_skills"], ["storyboard"])
        self.assertEqual(serialized["payload"]["bindings"], {"region": "US"})

    def test_envelope_source_metadata_is_snapshotted(self) -> None:
        source_contract_ids = ["contract-source-001"]
        source_hashes = ["sha256:" + "0" * 64]
        envelope = build_envelope(
            contract_type="avp.contract.task-spec",
            payload={
                "task_id": "task-001",
                "task_type": "single-skill",
                "requested_skills": ["storyboard"],
                "objective": "Create a synthetic plan",
                "input_refs": [],
                "requested_outputs": ["synthetic-output"],
                "created_by": "human:test",
                "created_at": "2026-07-20T00:00:00Z",
            },
            producer=ProducerIdentity("human", "authorized-direct-cli-caller", "1.0.0"),
            correlation_id="corr-001",
            idempotency_key="idem-001",
            contract_id=uuid7(timestamp_ms=1_700_000_000_000, random_bits=4),
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
            source_contract_ids=source_contract_ids,
            source_hashes=source_hashes,
        )

        source_contract_ids.append("contract-source-002")
        source_hashes.append("sha256:" + "1" * 64)

        self.assertEqual(envelope.source_contract_ids, ("contract-source-001",))
        self.assertEqual(envelope.source_hashes, ("sha256:" + "0" * 64,))


if __name__ == "__main__":
    unittest.main()
