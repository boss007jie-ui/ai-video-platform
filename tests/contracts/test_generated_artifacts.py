from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_video_platform.contracts.registry import (
    ENVELOPE_SCHEMA_ID,
    FOUNDATION_CONTRACT_IDS,
    REGISTRY,
)
from ai_video_platform.contracts.serialization import canonical_json
from ai_video_platform.contracts.validation import validate_payload
from tools.generate_foundation_artifacts import generate_fixtures, generate_schemas


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GeneratedArtifactTests(unittest.TestCase):
    def test_schema_identity_set_is_exactly_foundation_registry(self) -> None:
        schema_dir = PROJECT_ROOT / "schemas" / "v1"
        documents = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(schema_dir.glob("*.json"))]
        schema_ids = {document["$id"] for document in documents}

        self.assertEqual(schema_ids, {ENVELOPE_SCHEMA_ID, *FOUNDATION_CONTRACT_IDS})
        self.assertEqual(len(documents), 12)

    def test_envelope_schema_accepts_versioned_payload_semver(self) -> None:
        schema_path = PROJECT_ROOT / "schemas" / "v1" / "contract_envelope.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema_version = schema["properties"]["schema_version"]

        self.assertEqual(schema_version["type"], "string")
        self.assertIn("pattern", schema_version)
        self.assertNotIn("const", schema_version)

    def test_payload_schemas_are_mechanical_registry_projections(self) -> None:
        schema_dir = PROJECT_ROOT / "schemas" / "v1"
        for contract_type, definition in REGISTRY.items():
            schema = json.loads((schema_dir / definition.schema_filename).read_text(encoding="utf-8"))
            self.assertEqual(schema["$id"], contract_type)
            self.assertEqual(tuple(schema["required"]), definition.required_fields)
            self.assertEqual(schema["x-avp-registry"], "IR-2 Foundation Registry V1")

    def test_each_contract_has_five_synthetic_fixture_classes(self) -> None:
        fixture_root = PROJECT_ROOT / "fixtures" / "contracts"
        expected_kinds = {"minimal-valid", "full-valid", "invalid", "compatibility", "replay"}

        for contract_type, definition in REGISTRY.items():
            slug = contract_type.removeprefix("avp.contract.")
            fixture_dir = fixture_root / slug
            fixture_paths = sorted(fixture_dir.glob("*.json"))
            fixture_kinds = {path.stem for path in fixture_paths}
            self.assertEqual(fixture_kinds, expected_kinds)
            for path in fixture_paths:
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(document["manifest"]["synthetic"])
                self.assertEqual(document["manifest"]["contract_type"], contract_type)
                self.assertNotIn("credential", json.dumps(document).lower())

            minimal = json.loads((fixture_dir / "minimal-valid.json").read_text(encoding="utf-8"))
            model = validate_payload(
                contract_type,
                minimal["payload"],
                producer_component_id=minimal["manifest"]["producer_component_id"],
                producer_agent=minimal["manifest"]["producer_agent"],
            )
            self.assertEqual(type(model).__name__, definition.name)

            invalid = json.loads((fixture_dir / "invalid.json").read_text(encoding="utf-8"))
            with self.assertRaises(Exception):
                validate_payload(
                    contract_type,
                    invalid["payload"],
                    producer_component_id=invalid["manifest"]["producer_component_id"],
                    producer_agent=invalid["manifest"]["producer_agent"],
                )

            full = json.loads((fixture_dir / "full-valid.json").read_text(encoding="utf-8"))
            full_model = validate_payload(
                contract_type,
                full["payload"],
                producer_component_id=full["manifest"]["producer_component_id"],
                producer_agent=full["manifest"]["producer_agent"],
            )
            self.assertEqual(canonical_json(full_model), canonical_json(full["payload"]))

    def test_regeneration_has_no_checked_in_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            generated_root = Path(temporary_directory)
            generate_schemas(generated_root)
            generate_fixtures(generated_root)

            for relative_root in (Path("schemas/v1"), Path("fixtures/contracts")):
                expected_files = sorted(
                    path.relative_to(PROJECT_ROOT)
                    for path in (PROJECT_ROOT / relative_root).rglob("*.json")
                )
                generated_files = sorted(
                    path.relative_to(generated_root)
                    for path in (generated_root / relative_root).rglob("*.json")
                )
                self.assertEqual(generated_files, expected_files)
                for relative_path in expected_files:
                    self.assertEqual(
                        (generated_root / relative_path).read_bytes(),
                        (PROJECT_ROOT / relative_path).read_bytes(),
                        relative_path,
                    )


if __name__ == "__main__":
    unittest.main()
