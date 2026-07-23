from __future__ import annotations

import unittest
from dataclasses import fields

from ai_video_platform.interfaces.viral_script import ViralScript
from ai_video_platform.skills.product_image_panel_generation import (
    ProductFacts,
    to_product_facts,
)


class ServiceRuntimeDtoGatewayContractTests(unittest.TestCase):
    def test_submitted_context_is_warning_not_blocker(self) -> None:
        result = ViralScript(script_id="script-1", content="A product story").validate()

        self.assertTrue(result.is_valid)
        self.assertEqual(result.blockers, ())
        self.assertEqual([issue.field_path for issue in result.warnings], ["submitted_context"])

    def test_product_mapping_projects_only_provider_neutral_product_data(self) -> None:
        facts = to_product_facts(
            {
                "product_id": "product-1",
                "sku_id": "sku-1",
                "facts": [{"name": "Lamp", "status": "confirmed"}],
                "approved_asset_refs": ["asset-1"],
                "visual_constraints": {"background": "white"},
                "packaging": {"material": "paper"},
                "dimensions": {"width_mm": 100},
                "category_ids": ["lighting"],
                "provider_id": "must-not-cross-domain-boundary",
            }
        )

        self.assertIsInstance(facts, ProductFacts)
        self.assertEqual(facts.product_id, "product-1")
        self.assertEqual(facts.approved_asset_ids, ("asset-1",))
        self.assertFalse(hasattr(facts, "provider_id"))
        self.assertEqual(
            {field.name for field in fields(ProductFacts)},
            {
                "product_id",
                "sku_id",
                "facts",
                "approved_asset_ids",
                "visual_constraints",
                "packaging",
                "dimensions",
                "category_ids",
            },
        )

    def test_product_facts_are_immutable_after_mapping(self) -> None:
        facts = to_product_facts(
            {"product_id": "product-1", "facts": [{"name": "Lamp"}]}
        )

        with self.assertRaises(TypeError):
            facts.visual_constraints["background"] = "red"  # type: ignore[index]
        with self.assertRaises(TypeError):
            facts.facts[0]["name"] = "Changed"  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
