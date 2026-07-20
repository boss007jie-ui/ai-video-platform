from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from ai_video_platform.contracts.registry import FOUNDATION_CONTRACT_IDS
from ai_video_platform.core.guards import SecretScanner


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_ROOT = PROJECT_ROOT.parent / "AI Video Platform Re-architecture Control"
PRODUCT_LIBRARY = PROJECT_ROOT.parent / "AI Video Product Library"
RESEARCH_LIBRARY = PROJECT_ROOT.parent / "AI Video Research Library"
SKILL_NAMES = {
    "product_knowledge",
    "viral_research_asset_collection",
    "reference_analysis",
    "storyboard",
    "product_image_panel_generation",
    "storyboard_master_video_planning",
    "video_generation",
    "qa_review",
}


class CleanRoomBoundaryTests(unittest.TestCase):
    def test_authorized_clean_skeleton_directories_exist(self) -> None:
        expected_directories = {
            "docs/contracts",
            "docs/operations",
            "docs/maintenance",
            "fixtures/skills",
            "fixtures/workflows",
            "tests/skills",
            "tests/orchestration",
            "tools/release",
            "tools/migration",
            "tools/verification",
        }

        missing = [relative for relative in sorted(expected_directories) if not (PROJECT_ROOT / relative).is_dir()]
        self.assertEqual(missing, [])

    def test_business_namespaces_are_placeholders_only(self) -> None:
        skills_root = PROJECT_ROOT / "src" / "ai_video_platform" / "skills"
        skill_dirs = [path for path in skills_root.iterdir() if path.is_dir() and path.name != "__pycache__"]
        self.assertEqual({path.name for path in skill_dirs}, SKILL_NAMES)
        for skill_dir in skill_dirs:
            self.assertFalse((skill_dir / "SKILL.md").exists())
            entries = [path for path in skill_dir.iterdir() if path.name != "__pycache__"]
            self.assertEqual([path.name for path in entries], ["__init__.py"])
            tree = ast.parse(entries[0].read_text(encoding="utf-8"))
            imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
            self.assertEqual(imports, [])

    def test_no_business_artifact_contract_ids_are_registered(self) -> None:
        forbidden_fragments = {
            "reference-blueprint",
            "gap-analysis-report",
            "revision-request",
            "storyboard-plan",
            "panel-plan",
            "panel-result",
            "image-result",
            "storyboard-master",
            "shot-motion-plan",
            "video-execution-package",
            "video-job",
            "video-result",
            "provider-request-record",
            "qa-report",
            "issue-report",
            "viral-research-request",
            "viral-research-pack",
            "reference-collection-manifest",
        }
        self.assertFalse(any(fragment in contract_id for contract_id in FOUNDATION_CONTRACT_IDS for fragment in forbidden_fragments))

    def test_product_library_is_not_created_and_adoptions_remain_empty(self) -> None:
        self.assertFalse(PRODUCT_LIBRARY.exists())
        self.assertFalse(RESEARCH_LIBRARY.exists())
        manifest = json.loads((CONTROL_ROOT / "08_ADOPTION_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["adoptions"], [])
        self.assertEqual(manifest["governance_status"]["direct_verification"], "NOT_AUTHORIZED")

    def test_runtime_source_contains_no_legacy_project_name_or_provider_sdk_import(self) -> None:
        forbidden_names = {
            "veo3.1",
            "veo3.1-production",
            "veo3.1-catpaw-dev",
            "veo3.1-seedance-skill-sandbox",
            "ai-video-reference-gap-analyzer",
            "veo3.1-seedance-skill-runtime",
        }
        forbidden_import_roots = {"openai", "google.generativeai", "replicate", "fal_client", "apify_client"}
        runtime_files = sorted((PROJECT_ROOT / "src").rglob("*.py"))
        for path in runtime_files:
            text = path.read_text(encoding="utf-8")
            if path.name != "guards.py":
                self.assertTrue(forbidden_names.isdisjoint(text.lower()), path)
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = {alias.name for alias in node.names}
                    self.assertTrue(imported.isdisjoint(forbidden_import_roots), path)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module, forbidden_import_roots, path)

    def test_repository_secret_scan_is_clean(self) -> None:
        findings = SecretScanner().scan_tree(PROJECT_ROOT)
        self.assertEqual(findings, ())


if __name__ == "__main__":
    unittest.main()
