from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_video_platform.skills.viral_research_asset_collection import (
    ErrorCode,
    SkillError,
    project_viral_research_pack,
    research_viral,
)
from ai_video_platform.skills.viral_research_asset_collection.adapters import FakeCollectionAdapter
from ai_video_platform.skills.viral_research_asset_collection.cli import main
from ai_video_platform.skills.viral_research_asset_collection.storage import InMemoryResearchLibraryAdapter


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "viral-research-pack-v1.json"
NOW = "2026-07-24T04:00:00Z"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ViralResearchPackTests(unittest.TestCase):
    def _run_fake(self) -> tuple[int, dict[str, object]]:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(json.dumps(fixture["request"]), encoding="utf-8")
            output = io.StringIO()
            with patch("ai_video_platform.skills.viral_research_asset_collection.cli.ApifyCollectionAdapter") as apify:
                try:
                    with redirect_stdout(output):
                        code = main([
                            "research-viral",
                            "--input", str(request_path),
                            "--now", NOW,
                            "--provider", "fake",
                            "--provider-fixture", str(FIXTURE_PATH),
                        ])
                except SystemExit as exc:
                    code = int(exc.code)
                apify.assert_not_called()
        return code, json.loads(output.getvalue()) if output.getvalue() else {}

    def test_public_fake_path_publishes_canonical_pack_with_full_search_evidence(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        code, payload = self._run_fake()

        self.assertEqual(code, 0)
        pack = payload["viral_research_pack"]
        self.assertEqual(pack["artifact_name"], "ViralResearchPack")
        self.assertEqual(pack["contract_identity"], fixture["expected"]["contract_identity"])
        self.assertEqual(pack["contract_version"], fixture["expected"]["contract_version"])
        self.assertEqual(
            [item["source_id"] for item in pack["ranked_results"]],
            fixture["expected"]["ranked_source_ids"],
        )
        first = pack["ranked_results"][0]
        self.assertEqual(first["rank"], 1)
        self.assertEqual(first["source_metadata"]["comment_count"], 842)
        self.assertEqual(first["comment_evidence"]["schema_version"], "1.0.0")
        self.assertEqual(first["comment_evidence"]["status"], "AVAILABLE")
        self.assertEqual(first["source_provenance"]["source_url"], first["source_url"])
        self.assertIn("contributions", first["score"])
        self.assertEqual(first["decisions"]["rights"]["status"], "PUBLIC")
        self.assertEqual(first["decisions"]["lifecycle"]["state"], "retained")
        self.assertEqual(first["decisions"]["retention"]["expires_at"], "2026-08-01T00:00:00Z")
        self.assertEqual(pack["execution_counters"]["external_provider_calls"], 0)
        self.assertEqual(pack["execution_counters"]["network_calls"], 0)
        self.assertGreater(pack["execution_counters"]["collection_attempts"], 0)
        self.assertEqual(pack["request_provenance"]["request_digest"], payload["request_digest"])
        for field in ("campaign_goal", "target_audience", "content_format", "search_budget", "download_policy"):
            self.assertIn(field, pack["request_provenance"])
            self.assertEqual(pack["request_provenance"][field], fixture["request"][field])

    def test_fixture_driven_fake_pack_is_repeatable_and_self_digesting(self) -> None:
        first_code, first_payload = self._run_fake()
        second_code, second_payload = self._run_fake()
        self.assertEqual((first_code, second_code), (0, 0))
        first = first_payload["viral_research_pack"]
        second = second_payload["viral_research_pack"]
        self.assertEqual(first, second)
        core = {key: value for key, value in first.items() if key != "artifact_digest"}
        self.assertEqual(first["artifact_digest"], hashlib.sha256(_canonical(core)).hexdigest())
        self.assertTrue(first["artifact_id"].startswith("viral-research-pack-"))

    def test_root_search_can_thin_translate_to_existing_owner_command(self) -> None:
        # Root routing only needs to replace `viral-research search` with this
        # existing owner command and forward the remaining public arguments.
        code, payload = self._run_fake()
        self.assertEqual(code, 0)
        self.assertIn("viral_research_pack", payload)

    def test_projection_rejects_result_from_a_different_request(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        request = fixture["request"]
        result = research_viral(
            request,
            provider=FakeCollectionAdapter(fixture["provider_rows"]),
            storage=InMemoryResearchLibraryAdapter(),
            now=datetime(2026, 7, 24, 4, 0, tzinfo=timezone.utc),
        )
        changed = {**request, "campaign_goal": "awareness"}
        with self.assertRaises(SkillError) as captured:
            project_viral_research_pack(changed, result, external_provider_calls=0, network_calls=0)
        self.assertEqual(captured.exception.code, ErrorCode.VALIDATION_FAILED)

    def test_projection_rejects_legacy_replay_without_canonical_evidence(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        request = fixture["request"]
        result = research_viral(
            request,
            provider=FakeCollectionAdapter(fixture["provider_rows"]),
            storage=InMemoryResearchLibraryAdapter(),
            now=datetime(2026, 7, 24, 4, 0, tzinfo=timezone.utc),
        )
        incomplete = replace(
            result.candidates[0],
            source_metadata={},
            comment_evidence={},
            source_provenance={},
        )
        legacy_replay = replace(result, candidates=(incomplete, *result.candidates[1:]))

        with self.assertRaises(SkillError) as captured:
            project_viral_research_pack(request, legacy_replay, external_provider_calls=0, network_calls=0)
        self.assertEqual(captured.exception.code, ErrorCode.VALIDATION_FAILED)

    def test_fake_fixture_rejects_invalid_retrieval_time_before_pack_publication(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        fixture["provider_rows"][0]["retrieved_at"] = "not-a-timestamp"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            fixture_path = root / "fixture.json"
            request_path.write_text(json.dumps(fixture["request"]), encoding="utf-8")
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            output = io.StringIO()
            with patch("ai_video_platform.skills.viral_research_asset_collection.cli.ApifyCollectionAdapter") as apify:
                with redirect_stdout(output):
                    code = main([
                        "research-viral", "--input", str(request_path), "--now", NOW,
                        "--provider", "fake", "--provider-fixture", str(fixture_path),
                    ])
                apify.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "VIRAL_RESEARCH_VALIDATION_FAILED")
        self.assertNotIn("viral_research_pack", payload)

    def test_default_rejecting_path_remains_fail_closed(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(json.dumps(fixture["request"]), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["research-viral", "--input", str(request_path), "--now", NOW])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "VIRAL_RESEARCH_PROVIDER_FORBIDDEN")
        self.assertNotIn("viral_research_pack", payload)

    def test_owner_source_has_no_cross_skill_private_import(self) -> None:
        source_root = Path(__file__).resolve().parents[3] / "src" / "ai_video_platform" / "skills" / "viral_research_asset_collection"
        source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.glob("*.py"))
        self.assertNotIn("ai_video_platform.skills.", source)


if __name__ == "__main__":
    unittest.main()
