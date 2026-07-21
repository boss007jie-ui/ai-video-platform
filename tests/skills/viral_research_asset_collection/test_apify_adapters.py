from __future__ import annotations

from datetime import datetime, timezone
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request

from ai_video_platform.skills.viral_research_asset_collection import ErrorCode, SkillError, research_viral
from ai_video_platform.skills.viral_research_asset_collection.apify import (
    APIFY_RESEARCH_AUTHORIZATION_ID,
    ApifyCollectionAdapter,
    ApifyDownloadAdapter,
    _NoRedirectHandler,
    resolve_apify_api_key,
)
from ai_video_platform.skills.viral_research_asset_collection.cli import main
from ai_video_platform.skills.viral_research_asset_collection.storage import InMemoryResearchLibraryAdapter
from tests.skills.viral_research_asset_collection.test_viral_research_interface import valid_request


NOW = datetime(2026, 7, 21, 4, 0, tzinfo=timezone.utc)
TOKEN = "synthetic-apify-secret"


class FakeJsonTransport:
    def __init__(self, responses: list[object] | None = None, *, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.requests: list[dict[str, object]] = []

    def request(self, method: str, url: str, *, headers: dict[str, str], body: bytes | None, timeout_seconds: int):
        self.requests.append({
            "method": method, "url": url, "headers": dict(headers), "body": body,
            "timeout_seconds": timeout_seconds,
        })
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def run_response(*, status: str = "SUCCEEDED") -> dict[str, object]:
    return {
        "data": {
            "id": "run-safe-001",
            "status": status,
            "defaultDatasetId": "dataset-safe-001",
            "usageTotalUsd": 0.006,
            "chargedEventCounts": {"dataset-item": 20},
        }
    }


def actor_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "7353781970163272993",
        "title": "laser pointer tactical EDC test",
        "views": 100_000,
        "likes": 7_400,
        "comments": 200,
        "shares": 1_200,
        "uploadedAtFormatted": "2026-07-20T03:10:05.000Z",
        "postPage": "https://www.tiktok.com/@publiccreator/video/7353781970163272993",
    }
    row.update(updates)
    return row


class ApifyAdapterTests(unittest.TestCase):
    def test_credential_resolver_only_accepts_named_environment_value(self) -> None:
        self.assertEqual(resolve_apify_api_key({"APIFY_API_KEY": TOKEN}), TOKEN)
        with self.assertRaises(SkillError) as caught:
            resolve_apify_api_key({})
        self.assertEqual(caught.exception.code, ErrorCode.PROVIDER_FORBIDDEN)
        self.assertNotIn(TOKEN, json.dumps(caught.exception.to_dict()))

    def test_collection_adapter_uses_one_capped_run_and_one_dataset_read(self) -> None:
        transport = FakeJsonTransport([run_response(), [actor_row()]])
        with patch.dict(os.environ, {"APIFY_API_KEY": TOKEN}):
            adapter = ApifyCollectionAdapter(
                authorization_id=APIFY_RESEARCH_AUTHORIZATION_ID,
                seed_queries=("laser pointer tactical gear", "laser pointer EDC tools"),
                market="US", transport=transport, now=lambda: NOW,
            )
            rows = adapter.fetch("ignored expanded query", limit=20, timeout_seconds=60)

        self.assertEqual(len(rows), 1)
        self.assertEqual(adapter.attempt_count, 1)
        self.assertEqual(adapter.receipt.to_dict(), {
            "actor_id": "apidojo/tiktok-scraper",
            "actor_run_id": "run-safe-001",
            "actor_status": "SUCCEEDED",
            "returned_count": 1,
            "actual_cost_usd": 0.006,
            "charged_event_counts": {"dataset-item": 20},
        })
        self.assertEqual(len(transport.requests), 2)
        run_request = transport.requests[0]
        self.assertEqual(run_request["method"], "POST")
        self.assertIn("apidojo~tiktok-scraper/runs", str(run_request["url"]))
        self.assertIn("waitForFinish=60", str(run_request["url"]))
        self.assertIn("maxItems=20", str(run_request["url"]))
        self.assertIn("maxTotalChargeUsd=0.01", str(run_request["url"]))
        self.assertNotIn(TOKEN, str(run_request["url"]))
        self.assertEqual(run_request["headers"]["Authorization"], f"Bearer {TOKEN}")
        body = json.loads(bytes(run_request["body"]).decode("utf-8"))
        self.assertEqual(body["keywords"], ["laser pointer tactical gear", "laser pointer EDC tools"])
        self.assertEqual(body["location"], "US")
        self.assertEqual(body["maxItems"], 20)
        dataset_request = transport.requests[1]
        self.assertEqual(dataset_request["method"], "GET")
        self.assertIn("datasets/dataset-safe-001/items", str(dataset_request["url"]))
        self.assertIn("limit=20", str(dataset_request["url"]))
        self.assertNotIn(TOKEN, repr(adapter))

        row = rows[0]
        self.assertEqual(row["source_id"], "7353781970163272993")
        self.assertEqual(row["rights_status"], "UNKNOWN")
        self.assertFalse(row["pii_detected"])
        self.assertEqual(row["expires_at"], "2026-07-28T04:00:00Z")
        self.assertNotIn("video", row)

    def test_collection_adapter_is_explicitly_authorized_and_single_use(self) -> None:
        with self.assertRaises(SkillError) as caught:
            ApifyCollectionAdapter(
                authorization_id="wrong", seed_queries=("a", "b"), market="US",
                transport=FakeJsonTransport(), now=lambda: NOW,
            )
        self.assertEqual(caught.exception.code, ErrorCode.PROVIDER_FORBIDDEN)

        transport = FakeJsonTransport([run_response(), [actor_row()]])
        with patch.dict(os.environ, {"APIFY_API_KEY": TOKEN}):
            adapter = ApifyCollectionAdapter(
                authorization_id=APIFY_RESEARCH_AUTHORIZATION_ID,
                seed_queries=("a", "b"), market="US", transport=transport, now=lambda: NOW,
            )
            adapter.fetch("q", limit=20, timeout_seconds=60)
        with self.assertRaises(SkillError) as caught:
            adapter.fetch("q2", limit=20, timeout_seconds=60)
        self.assertEqual(caught.exception.code, ErrorCode.BUDGET_EXCEEDED)
        self.assertEqual(len(transport.requests), 2)

    def test_provider_failure_is_stable_and_secret_free(self) -> None:
        with patch.dict(os.environ, {"APIFY_API_KEY": TOKEN}):
            adapter = ApifyCollectionAdapter(
                authorization_id=APIFY_RESEARCH_AUTHORIZATION_ID,
                seed_queries=("a", "b"), market="US",
                transport=FakeJsonTransport(error=RuntimeError(f"Bearer {TOKEN}")), now=lambda: NOW,
            )
            with self.assertRaises(SkillError) as caught:
                adapter.fetch("q", limit=20, timeout_seconds=60)
        serialized = json.dumps(caught.exception.to_dict())
        self.assertEqual(caught.exception.code, ErrorCode.PROVIDER_FAILURE)
        self.assertNotIn(TOKEN, serialized)

    def test_research_interface_accepts_only_the_authorized_exact_apify_adapter(self) -> None:
        request = valid_request()
        request["time_window"] = {
            "start": "2026-07-01T00:00:00Z", "end": "2026-07-21T00:00:00Z",
            "expires_at": "2026-07-29T00:00:00Z",
        }
        request["seed_queries"] = ["laser pointer tactical gear", "laser pointer EDC tools"]
        request["target_audience"] = "US tactical and EDC audience"
        request["search_budget"] = {
            "max_queries": 2, "max_results": 20, "max_provider_calls": 1, "timeout_seconds": 60,
        }
        request["retry_limit"] = 0
        with patch.dict(os.environ, {"APIFY_API_KEY": TOKEN}):
            adapter = ApifyCollectionAdapter(
                authorization_id=APIFY_RESEARCH_AUTHORIZATION_ID,
                seed_queries=tuple(request["seed_queries"]), market="US",
                transport=FakeJsonTransport([run_response(), [actor_row()]]), now=lambda: NOW,
            )
            result = research_viral(request, provider=adapter, storage=InMemoryResearchLibraryAdapter(), now=NOW)

        self.assertEqual(result.provider_calls, 1)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].lifecycle_state, "metadata_only")

    def test_transport_refuses_redirects_before_forwarding_authorization(self) -> None:
        handler = _NoRedirectHandler()
        redirected = handler.redirect_request(
            Request("https://api.apify.com/v2/acts/x/runs", headers={"Authorization": f"Bearer {TOKEN}"}),
            None, 302, "Found", {}, "https://attacker.invalid/capture",
        )
        self.assertIsNone(redirected)

    def test_over_cap_cost_stops_before_dataset_read(self) -> None:
        response = run_response()
        response["data"]["usageTotalUsd"] = 0.010001
        transport = FakeJsonTransport([response])
        with patch.dict(os.environ, {"APIFY_API_KEY": TOKEN}):
            adapter = ApifyCollectionAdapter(
                authorization_id=APIFY_RESEARCH_AUTHORIZATION_ID,
                seed_queries=("a", "b"), market="US", transport=transport, now=lambda: NOW,
            )
            with self.assertRaises(SkillError) as caught:
                adapter.fetch("q", limit=20, timeout_seconds=60)
        self.assertEqual(caught.exception.code, ErrorCode.PROVIDER_FAILURE)
        self.assertEqual(len(transport.requests), 1)

    def test_explicit_cli_writes_controlled_ledger_and_replays_without_a_second_run(self) -> None:
        request = valid_request()
        request["time_window"] = {
            "start": "2026-07-01T00:00:00Z", "end": "2026-07-21T00:00:00Z",
            "expires_at": "2026-07-29T00:00:00Z",
        }
        request["seed_queries"] = ["laser pointer tactical gear", "laser pointer EDC tools"]
        request["target_audience"] = "US tactical and EDC audience"
        request["search_budget"] = {
            "max_queries": 2, "max_results": 20, "max_provider_calls": 1, "timeout_seconds": 60,
        }
        request["retry_limit"] = 0
        first_transport = FakeJsonTransport([run_response(), [actor_row()]])
        replay_transport = FakeJsonTransport()
        transports = iter((first_transport, replay_transport))
        real_adapter = ApifyCollectionAdapter

        def adapter_factory(**kwargs):
            return real_adapter(transport=next(transports), **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            library_root = root / "research-library"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            args = [
                "research-viral", "--input", str(request_path), "--now", "2026-07-21T04:00:00Z",
                "--provider", "apify", "--authorization-id", APIFY_RESEARCH_AUTHORIZATION_ID,
                "--library-root", str(library_root),
            ]
            first_output = io.StringIO()
            replay_output = io.StringIO()
            with patch("ai_video_platform.skills.viral_research_asset_collection.cli.ApifyCollectionAdapter", side_effect=adapter_factory):
                with patch.dict(os.environ, {"APIFY_API_KEY": TOKEN}, clear=True):
                    with redirect_stdout(first_output):
                        self.assertEqual(main(args), 0)
                with patch.dict(os.environ, {}, clear=True):
                    self.assertNotIn("APIFY_API_KEY", os.environ)
                    with redirect_stdout(replay_output):
                        self.assertEqual(main(args), 0)

            first_payload = json.loads(first_output.getvalue())
            replay_payload = json.loads(replay_output.getvalue())
            self.assertEqual(first_payload["provider_receipt"]["actor_run_id"], "run-safe-001")
            self.assertEqual(replay_payload["provider_receipt"]["status"], "IDEMPOTENT_REPLAY")
            self.assertEqual(len(first_transport.requests), 2)
            self.assertEqual(replay_transport.requests, [])
            self.assertTrue(any((library_root / "audit" / "requests").glob("*.json")))

    def test_downloader_is_staged_but_current_authorization_cannot_download(self) -> None:
        downloader = ApifyDownloadAdapter(authorization_id=APIFY_RESEARCH_AUTHORIZATION_ID)
        with self.assertRaises(SkillError) as caught:
            downloader.download({"source_id": "x", "source_url": "https://www.tiktok.com/x"})
        self.assertEqual(caught.exception.code, ErrorCode.DOWNLOAD_FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
