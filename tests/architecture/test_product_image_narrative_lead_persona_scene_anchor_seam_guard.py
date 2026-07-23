from __future__ import annotations

import inspect
import unittest

from ai_video_platform.core.continuity_review import (
    ContinuityReviewAssembly,
    ContinuityReviewContext,
    assemble_continuity_review,
    consume_continuity_review,
)


class ProductImageNarrativeLeadPersonaSceneAnchorSeamGuardTests(unittest.TestCase):
    def test_public_assembly_and_consume_seams_expose_all_continuity_fields(self) -> None:
        assembly_parameters = set(inspect.signature(assemble_continuity_review).parameters)
        assembly_fields = set(ContinuityReviewAssembly.__dataclass_fields__)
        consume_fields = set(ContinuityReviewContext.__dataclass_fields__)
        expected = {"narrative_mode", "lead_persona_ids", "scene_anchor_ids"}

        self.assertTrue(expected <= assembly_parameters)
        self.assertTrue(expected <= assembly_fields)
        self.assertTrue(expected <= consume_fields)

    def test_field_values_survive_the_assembly_to_consume_boundary(self) -> None:
        assembly = assemble_continuity_review(
            sources={},
            reference_ids=(),
            narrative_mode="product-demo",
            lead_persona_ids=("lead-a", "lead-b"),
            scene_anchor_ids=("scene-a",),
        )
        consumed = consume_continuity_review(assembly)

        self.assertEqual(consumed.narrative_mode, assembly.narrative_mode)
        self.assertEqual(consumed.lead_persona_ids, assembly.lead_persona_ids)
        self.assertEqual(consumed.scene_anchor_ids, assembly.scene_anchor_ids)


if __name__ == "__main__":
    unittest.main()
