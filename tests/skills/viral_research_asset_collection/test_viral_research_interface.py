from __future__ import annotations

from datetime import datetime, timezone
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.skills.viral_research_asset_collection import (
    ErrorCode,
    SkillError,
    inspect_research_request,
    research_viral,
)
from ai_video_platform.skills.viral_research_asset_collection.cli import main


NOW = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)


def valid_request() -> dict[str, object]:
    return {
        "platform": "tiktok",
        "market": "US",
        "region": "en-US",
        "time_window": {"start": "2026-07-01T00:00:00Z", "end": "2026-07-19T00:00:00Z", "expires_at": "2026-07-21T00:00:00Z"},
        "campaign_goal": "conversion",
        "target_audience": "homeowners",
        "content_format": "short-video",
        "search_budget": {"max_queries": 4, "max_results": 10, "max_provider_calls": 2, "timeout_seconds": 30},
        "download_policy": {
            "mode": "METADATA_ONLY", "public_or_authorized_only": True,
            "no_drm_bypass": True, "no_login_bypass": True,
            "no_private_content": True, "no_unauthorized_reposting": True,
        },
        "seed_queries": ["wall panel", "panel makeover"],
        "idempotency_key": "idem-001",
        "retry_limit": 2,
    }


class FakeProvider:
    def __init__(self, rows: list[dict[str, object]], *, failures: int = 0) -> None:
        self.rows, self.failures, self.calls = rows, failures, 0

    def fetch(self, query: str, *, limit: int, timeout_seconds: int):
        del query, timeout_seconds
        self.calls += 1
        if self.calls <= self.failures:
            raise SkillError(ErrorCode.PROVIDER_FAILURE, "temporary failure", retryable=True)
        return self.rows[:limit]


class MemorySink:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def write_record(self, record, *, idempotency_key: str):
        del idempotency_key
        self.records.append(dict(record))


def candidate(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "source_id": "video-1", "source_url": "https://example.invalid/video-1",
        "title": "Fast wall panel makeover", "description": "Simple makeover for modern homes",
        "published_at": "2026-07-18T00:00:00Z", "retrieved_at": "2026-07-19T00:00:00Z",
        "views": 1000, "likes": 200, "comments": 30, "shares": 20,
        "comment_quality": 0.8, "reproducibility": 0.9, "production_feasibility": 0.8,
        "platform_fit": 0.9, "brand_safety": 0.95, "rights_status": "PUBLIC",
        "pii_detected": False, "expires_at": "2026-07-22T00:00:00Z",
        "raw_payload": {"provider_secret_field": "must-not-leak"},
    }
    row.update(updates)
    return row


class ViralResearchInterfaceTests(unittest.TestCase):
    def test_cli_inspect_returns_machine_readable_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(json.dumps(valid_request()), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["inspect-research-request", "--input", str(request_path), "--now", "2026-07-20T04:00:00Z"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "READY")

    def test_inspection_is_deterministic_and_enforces_budgets(self) -> None:
        first = inspect_research_request(valid_request(), now=NOW)
        self.assertEqual(first, inspect_research_request(valid_request(), now=NOW))
        self.assertEqual(len(first.expanded_queries), 4)
        self.assertEqual(first.to_dict()["status"], "READY")
        invalid = valid_request()
        invalid["search_budget"] = {"max_queries": 51, "max_results": 10, "max_provider_calls": 2, "timeout_seconds": 30}
        with self.assertRaises(SkillError) as caught:
            inspect_research_request(invalid, now=NOW)
        self.assertEqual(caught.exception.code, ErrorCode.BUDGET_EXCEEDED)

    def test_inspection_fails_closed_on_expired_window_and_unsafe_policy(self) -> None:
        expired = valid_request()
        expired["time_window"] = {"start": "2026-07-01T00:00:00Z", "end": "2026-07-10T00:00:00Z", "expires_at": "2026-07-19T00:00:00Z"}
        with self.assertRaises(SkillError) as caught:
            inspect_research_request(expired, now=NOW)
        self.assertEqual(caught.exception.code, ErrorCode.REQUEST_EXPIRED)
        unsafe = valid_request()
        unsafe["download_policy"] = {**unsafe["download_policy"], "no_drm_bypass": False}
        with self.assertRaises(SkillError) as caught:
            inspect_research_request(unsafe, now=NOW)
        self.assertEqual(caught.exception.code, ErrorCode.RIGHTS_FORBIDDEN)

        bad_order = valid_request()
        bad_order["time_window"] = {
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-07-22T00:00:00Z",
            "expires_at": "2026-07-21T00:00:00Z",
        }
        with self.assertRaises(SkillError) as caught:
            inspect_research_request(bad_order, now=NOW)
        self.assertEqual(caught.exception.code, ErrorCode.VALIDATION_FAILED)

    def test_research_normalizes_dedupes_scores_and_classifies(self) -> None:
        rows = [
            candidate(),
            candidate(source_id="video-2", source_url="https://example.invalid/video-2", title="Fast wall panel makeover!", views=900),
            candidate(source_id="video-pii", source_url="https://example.invalid/pii", title="Owner phone reveal", pii_detected=True),
            candidate(source_id="video-u", source_url="https://example.invalid/u", title="Unknown rights", rights_status="UNKNOWN"),
            candidate(source_id="video-x", source_url="https://example.invalid/x", title="Old", expires_at="2026-07-19T00:00:00Z"),
        ]
        sink = MemorySink()
        result = research_viral(valid_request(), provider=FakeProvider(rows), storage=sink, now=NOW)
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(len(result.candidates), 4)
        self.assertEqual(set(result.candidates[0].score.explanation), {
            "relevance", "freshness", "engagement_velocity", "comment_quality",
            "reproducibility", "production_feasibility", "platform_fit", "brand_safety",
            "rights_status", "duplicate_distance",
        })
        self.assertNotIn("raw_payload", result.candidates[0].to_dict())
        self.assertEqual(set(result.candidates[0].score.inputs), set(result.candidates[0].score.weights))
        self.assertEqual(set(result.candidates[0].score.inputs), set(result.candidates[0].score.contributions))
        self.assertAlmostEqual(result.candidates[0].score.total, sum(result.candidates[0].score.contributions.values()))
        states = {item.source_id: item.lifecycle_state for item in result.candidates}
        self.assertEqual(states["video-pii"], "quarantined")
        self.assertEqual(states["video-u"], "metadata_only")
        self.assertEqual(states["video-x"], "expired")
        self.assertEqual(len(sink.records), 4)
        self.assertFalse(hasattr(result, "contract_type"))

    def test_research_dedupes_independent_source_and_content_identities(self) -> None:
        rows = [
            candidate(),
            candidate(source_id="video-1", source_url="https://example.invalid/changed", title="Different content"),
            candidate(source_id="different", source_url="https://example.invalid/video-1", title="Other content"),
            candidate(source_id="digest-copy", source_url="https://example.invalid/copy"),
        ]
        result = research_viral(valid_request(), provider=FakeProvider(rows), storage=MemorySink(), now=NOW)
        self.assertEqual([item.source_id for item in result.candidates], ["video-1"])

    def test_retry_is_capped_cancellation_is_stable_and_errors_redact(self) -> None:
        provider = FakeProvider([candidate()], failures=1)
        result = research_viral(valid_request(), provider=provider, storage=MemorySink(), now=NOW)
        self.assertEqual(result.provider_calls, 2)
        with self.assertRaises(SkillError) as caught:
            research_viral(valid_request(), provider=provider, storage=MemorySink(), now=NOW, cancelled=lambda: True)
        self.assertEqual(caught.exception.code, ErrorCode.CANCELLED)
        error = SkillError(ErrorCode.VALIDATION_FAILED, "bad token", details={"api_token": "synthetic-secret-value"})
        self.assertEqual(error.to_dict()["details"]["api_token"], "[REDACTED]")
        nested = SkillError(
            ErrorCode.PROVIDER_FAILURE,
            "Authorization Bearer synthetic-bearer-value",
            details={"provider_error": "token synthetic-token-value", "nested": {"message": "Bearer nested-bearer-value"}},
        ).to_dict()
        self.assertNotIn("synthetic-bearer-value", nested["message"])
        self.assertNotIn("synthetic-token-value", nested["details"]["provider_error"])
        self.assertNotIn("nested-bearer-value", nested["details"]["nested"]["message"])

        class CrashingProvider:
            def fetch(self, query: str, *, limit: int, timeout_seconds: int):
                del query, limit, timeout_seconds
                raise RuntimeError("token=synthetic-secret-value")

        with self.assertRaises(SkillError) as caught:
            research_viral(valid_request(), provider=CrashingProvider(), storage=MemorySink(), now=NOW)
        self.assertEqual(caught.exception.code, ErrorCode.PROVIDER_FAILURE)
        self.assertNotIn("synthetic-secret-value", caught.exception.message)

        class FailingIteratorProvider:
            def fetch(self, query: str, *, limit: int, timeout_seconds: int):
                del query, limit, timeout_seconds
                def rows():
                    yield candidate()
                    raise RuntimeError("Bearer iterator-secret")
                return rows()

        sink = MemorySink()
        with self.assertRaises(SkillError) as caught:
            research_viral(valid_request(), provider=FailingIteratorProvider(), storage=sink, now=NOW)
        self.assertEqual(caught.exception.code, ErrorCode.PROVIDER_FAILURE)
        self.assertEqual(sink.records, [])

        with self.assertRaises(SkillError) as caught:
            research_viral(valid_request(), provider=FakeProvider([candidate(pii_detected="false")]), storage=MemorySink(), now=NOW)
        self.assertEqual(caught.exception.code, ErrorCode.VALIDATION_FAILED)


if __name__ == "__main__":
    unittest.main()
