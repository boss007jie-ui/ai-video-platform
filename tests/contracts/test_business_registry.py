from __future__ import annotations

import unittest

from ai_video_platform.contracts.business_registry import (
    BUSINESS_ARTIFACT_IDS,
    BUSINESS_REGISTRY,
    BusinessArtifactDefinition,
    build_business_registry,
    evaluate_business_compatibility,
)
from ai_video_platform.contracts.compatibility import Compatibility
from ai_video_platform.contracts.registry import ENVELOPE_SCHEMA_ID, FOUNDATION_CONTRACT_IDS


class BusinessArtifactRegistryTests(unittest.TestCase):
    def test_fast_track_artifacts_are_separate_from_foundation_one_plus_eleven(self) -> None:
        self.assertEqual(ENVELOPE_SCHEMA_ID, "avp.schema.contract-envelope")
        self.assertEqual(len(FOUNDATION_CONTRACT_IDS), 11)
        self.assertEqual(
            set(BUSINESS_ARTIFACT_IDS),
            {
                "avp.contract.viral-research-request",
                "avp.contract.viral-research-pack",
                "avp.contract.reference-collection-manifest",
            },
        )
        self.assertTrue(set(BUSINESS_ARTIFACT_IDS).isdisjoint(FOUNDATION_CONTRACT_IDS))
        self.assertNotIn(ENVELOPE_SCHEMA_ID, BUSINESS_ARTIFACT_IDS)

    def test_registry_rejects_duplicate_or_foundation_identities(self) -> None:
        definition = BusinessArtifactDefinition(
            name="SyntheticArtifact",
            artifact_type="avp.contract.synthetic-artifact",
            version="1.0.0",
            owner="synthetic-owner",
            authorized_producers=("synthetic-producer",),
            authorized_consumers=("synthetic-consumer",),
        )
        with self.assertRaisesRegex(ValueError, "Duplicate business artifact identity"):
            build_business_registry((definition, definition))

        collision = BusinessArtifactDefinition(
            name="FoundationCollision",
            artifact_type=FOUNDATION_CONTRACT_IDS[0],
            version="1.0.0",
            owner="synthetic-owner",
            authorized_producers=("synthetic-producer",),
            authorized_consumers=("synthetic-consumer",),
        )
        with self.assertRaisesRegex(ValueError, "collides with Foundation Registry"):
            build_business_registry((collision,))

    def test_business_versions_use_foundation_compatibility_rules(self) -> None:
        artifact_type = "avp.contract.viral-research-pack"
        self.assertIn(artifact_type, BUSINESS_REGISTRY)
        self.assertEqual(
            evaluate_business_compatibility(artifact_type, reader_version="1.1.0", writer_version="1.0.0"),
            Compatibility.COMPATIBLE,
        )
        self.assertEqual(
            evaluate_business_compatibility(artifact_type, reader_version="1.0.0", writer_version="1.1.0"),
            Compatibility.READER_TOO_OLD,
        )
        self.assertEqual(
            evaluate_business_compatibility(artifact_type, reader_version="2.0.0", writer_version="1.0.0"),
            Compatibility.MAJOR_MISMATCH,
        )


if __name__ == "__main__":
    unittest.main()
