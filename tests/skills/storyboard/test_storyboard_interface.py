from __future__ import annotations

import json
import unittest
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ai_video_platform.contracts.serialization import content_digest
from ai_video_platform.contracts.validation import validate_envelope
from ai_video_platform.skills import storyboard
from ai_video_platform.skills.storyboard.cli import run_cli_document

from .fixtures import (
    changed_plan,
    envelope_document,
    fixed_clock,
    product_context,
    reference_manifest,
    task_context,
    task_spec,
    valid_plan,
)


class StoryboardInterfaceTests(unittest.TestCase):
    def request(self, **overrides):
        values = {
            "command": "create-storyboard",
            "task_spec": task_spec(),
            "task_context": task_context(),
            "product_context": product_context(),
            "plan": valid_plan(),
            "idempotency_key": "storyboard-create-001",
            "expected_version": 0,
            "reference_manifest": reference_manifest(),
        }
        values.update(overrides)
        return storyboard.StoryboardRequest(**values)

    def test_public_interface_exports_independent_storyboard_service(self) -> None:
        self.assertTrue(hasattr(storyboard, "StoryboardService"))
        self.assertTrue(hasattr(storyboard, "StoryboardRequest"))
        self.assertTrue(hasattr(storyboard, "StoryboardResult"))
        self.assertTrue(hasattr(storyboard, "StoryboardArtifact"))
        self.assertTrue(hasattr(storyboard, "StoryboardError"))
        self.assertEqual(
            [item.name for item in fields(storyboard.StoryboardRequest)],
            [
                "command",
                "task_spec",
                "task_context",
                "product_context",
                "plan",
                "idempotency_key",
                "expected_version",
                "prior_artifact",
                "reference_manifest",
                "cancellation_requested",
            ],
        )

    def test_request_takes_an_immutable_snapshot_of_nested_plan_input(self) -> None:
        source = valid_plan()
        request = self.request(plan=source)

        source["title"] = "mutated after construction"

        self.assertEqual(request.plan["title"], "From friction to confidence")
        with self.assertRaises(TypeError):
            request.plan["title"] = "mutation forbidden"

    def test_create_emits_traceable_artifact_and_foundation_outputs(self) -> None:
        result = storyboard.StoryboardService(clock=fixed_clock).execute(self.request())

        self.assertEqual((result.status, result.replay_status), ("completed", "recorded"))
        self.assertEqual(result.artifact.version, 1)
        self.assertEqual(result.artifact.product_id, "product-001")
        self.assertEqual(len(result.artifact.story["scenes"]), 2)
        self.assertEqual(result.artifact.content_digest, content_digest(result.artifact.story))
        self.assertEqual(
            set(result.artifact.source_hashes),
            {
                self.request().task_spec.payload_digest,
                self.request().task_context.payload_digest,
                self.request().product_context.payload_digest,
                self.request().reference_manifest.payload_digest,
            },
        )
        asset = validate_envelope(result.asset_manifest).payload
        feedback = validate_envelope(result.feedback_event).payload
        event = validate_envelope(result.execution_event).payload
        self.assertEqual(asset.owner_type, "task")
        self.assertEqual(asset.assets[0]["role"], "owner-local-draft")
        self.assertEqual(asset.assets[0]["provenance"]["publication_status"], "not-registered")
        self.assertEqual(asset.assets[0]["sha256"], result.artifact.content_digest.removeprefix("sha256:"))
        self.assertEqual(feedback.source_skill_id, "storyboard")
        self.assertEqual(event.status, "completed")
        self.assertEqual(event.metrics["provider_calls"], 0)
        self.assertIsNone(result.execution_event.payload.get("provider_binding"))

    def test_exact_replay_is_idempotent_and_a_fresh_service_is_deterministic(self) -> None:
        service = storyboard.StoryboardService(clock=fixed_clock)
        request = self.request()

        first = service.execute(request)
        replay = service.execute(request)
        independent = storyboard.StoryboardService(clock=fixed_clock).execute(request)

        self.assertEqual(first.replay_status, "recorded")
        self.assertEqual(replay.replay_status, "replayed")
        self.assertIs(replay.artifact, first.artifact)
        self.assertEqual(independent.artifact, first.artifact)

    def test_revision_increments_version_and_preserves_lineage(self) -> None:
        service = storyboard.StoryboardService(clock=fixed_clock)
        first = service.execute(self.request())

        revised = service.execute(
            self.request(
                command="revise-storyboard",
                plan=changed_plan(),
                idempotency_key="storyboard-revise-002",
                expected_version=1,
                prior_artifact=first.artifact,
            )
        )

        self.assertEqual(revised.artifact.version, 2)
        self.assertEqual(revised.artifact.supersedes_storyboard_id, first.artifact.storyboard_id)
        self.assertNotEqual(revised.artifact.content_digest, first.artifact.content_digest)

    def test_unchanged_revision_gets_a_new_identity_and_parallel_stale_revision_is_rejected(self) -> None:
        service = storyboard.StoryboardService(clock=fixed_clock)
        base = self.request()
        first = service.execute(base)
        unchanged = service.execute(
            self.request(
                command="revise-storyboard",
                task_spec=base.task_spec,
                task_context=base.task_context,
                product_context=base.product_context,
                reference_manifest=base.reference_manifest,
                idempotency_key="storyboard-revise-unchanged",
                expected_version=1,
                prior_artifact=first.artifact,
            )
        )

        self.assertEqual(unchanged.artifact.version, 2)
        self.assertEqual(unchanged.artifact.content_digest, first.artifact.content_digest)
        self.assertNotEqual(unchanged.artifact.storyboard_id, first.artifact.storyboard_id)

        with self.assertRaises(storyboard.StoryboardError) as captured:
            service.execute(
                self.request(
                    command="revise-storyboard",
                    task_spec=base.task_spec,
                    task_context=base.task_context,
                    product_context=base.product_context,
                    reference_manifest=base.reference_manifest,
                    plan=changed_plan(),
                    idempotency_key="storyboard-parallel-stale",
                    expected_version=1,
                    prior_artifact=first.artifact,
                )
            )
        self.assertEqual(captured.exception.code, "STORYBOARD_VERSION_STALE")

    def test_cli_returns_machine_readable_success_without_filesystem_or_provider_side_effects(self) -> None:
        request = self.request()
        exit_code, payload = run_cli_document(
            {
                "command": request.command,
                "task_spec": envelope_document(request.task_spec),
                "task_context": envelope_document(request.task_context),
                "product_context": envelope_document(request.product_context),
                "reference_manifest": envelope_document(request.reference_manifest),
                "plan": request.plan,
                "idempotency_key": request.idempotency_key,
                "expected_version": request.expected_version,
            },
            service=storyboard.StoryboardService(clock=fixed_clock),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifact"]["version"], 1)
        self.assertEqual(payload["error"], None)

        validate_exit, validate_payload = run_cli_document(
            {"command": "validate-continuity", "artifact": payload["artifact"]}
        )
        self.assertEqual(validate_exit, 0)
        self.assertEqual(validate_payload["status"], "completed")

    def test_cli_version_store_rejects_a_second_cross_call_revision_from_stale_v1(self) -> None:
        request = self.request()
        base_document = {
            "task_spec": envelope_document(request.task_spec),
            "task_context": envelope_document(request.task_context),
            "product_context": envelope_document(request.product_context),
            "reference_manifest": envelope_document(request.reference_manifest),
            "plan": request.plan,
        }
        with TemporaryDirectory() as temporary, patch.dict(
            "os.environ", {"AVP_TASK_WORKSPACE_ROOT": temporary}
        ):
            state_file = str(Path(temporary) / "storyboard-state.json")
            create_document = {
                **base_document,
                "command": "create-storyboard",
                "task_workspace": temporary,
                "state_file": state_file,
                "idempotency_key": "cli-state-create",
                "expected_version": 0,
            }
            create_exit, created = run_cli_document(create_document)
            replay_exit, replayed = run_cli_document(create_document)
            conflict_exit, conflict = run_cli_document({**create_document, "plan": changed_plan()})
            revise_document = {
                **base_document,
                "command": "revise-storyboard",
                "task_workspace": temporary,
                "state_file": state_file,
                "prior_artifact": created["artifact"],
                "expected_version": 1,
            }
            first_exit, first_revision = run_cli_document(
                {**revise_document, "idempotency_key": "cli-state-revise-1"}
            )
            revision_replay_exit, revision_replay = run_cli_document(
                {**revise_document, "idempotency_key": "cli-state-revise-1"}
            )
            forged_prior = json.loads(json.dumps(created["artifact"]))
            forged_prior["product_id"] = "product-forged"
            forged_prior_exit, forged_prior_result = run_cli_document(
                {
                    **revise_document,
                    "idempotency_key": "cli-state-revise-1",
                    "prior_artifact": forged_prior,
                }
            )
            stale_exit, stale = run_cli_document(
                {**revise_document, "idempotency_key": "cli-state-revise-stale", "plan": changed_plan()}
            )

        self.assertEqual(create_exit, 0)
        self.assertEqual(replay_exit, 0, replayed)
        self.assertEqual(replayed["replay_status"], "replayed")
        self.assertEqual(replayed["artifact"], created["artifact"])
        self.assertEqual(conflict_exit, 2)
        self.assertEqual(conflict["error"]["code"], "STORYBOARD_IDEMPOTENCY_CONFLICT")
        self.assertEqual(first_exit, 0)
        self.assertEqual(first_revision["artifact"]["version"], 2)
        self.assertEqual(revision_replay_exit, 0)
        self.assertEqual(revision_replay["replay_status"], "replayed")
        self.assertEqual(forged_prior_exit, 2)
        self.assertEqual(forged_prior_result["error"]["code"], "STORYBOARD_VERSION_STALE")
        self.assertEqual(stale_exit, 2)
        self.assertEqual(stale["error"]["code"], "STORYBOARD_VERSION_STALE")

    def test_cli_persists_terminal_cancellation_for_cross_process_replay(self) -> None:
        request = self.request()
        with TemporaryDirectory() as temporary, patch.dict(
            "os.environ", {"AVP_TASK_WORKSPACE_ROOT": temporary}
        ):
            document = {
                "command": "create-storyboard",
                "task_workspace": temporary,
                "state_file": str(Path(temporary) / "storyboard-state.json"),
                "task_spec": envelope_document(request.task_spec),
                "task_context": envelope_document(request.task_context),
                "product_context": envelope_document(request.product_context),
                "plan": request.plan,
                "idempotency_key": "cli-cancelled-replay",
                "expected_version": 0,
                "cancellation_requested": True,
            }
            first_exit, first = run_cli_document(document)
            replay_exit, replay = run_cli_document(document)

        self.assertEqual((first_exit, first["status"], first["artifact"]), (0, "cancelled", None))
        self.assertEqual((replay_exit, replay["status"], replay["replay_status"]), (0, "cancelled", "replayed"))

    def test_cli_rejects_a_tampered_persistent_replay_artifact(self) -> None:
        request = self.request()
        with TemporaryDirectory() as temporary, patch.dict(
            "os.environ", {"AVP_TASK_WORKSPACE_ROOT": temporary}
        ):
            state_path = Path(temporary) / "storyboard-state.json"
            document = {
                "command": "create-storyboard",
                "task_workspace": temporary,
                "state_file": str(state_path),
                "task_spec": envelope_document(request.task_spec),
                "task_context": envelope_document(request.task_context),
                "product_context": envelope_document(request.product_context),
                "plan": request.plan,
                "idempotency_key": "cli-tamper-replay",
                "expected_version": 0,
            }
            created_exit, _ = run_cli_document(document)
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            forged = {
                **document,
                "task_context": json.loads(json.dumps(document["task_context"])),
            }
            forged["task_context"]["payload"]["active_skill_id"] = "qa-review"
            forged_exit, forged_payload = run_cli_document(forged)

            original = json.loads(json.dumps(persisted))
            record = next(iter(persisted["records"].values()))
            record["result"]["artifact"]["story"]["title"] = "tampered"
            state_path.write_text(json.dumps(persisted), encoding="utf-8")
            replay_exit, replay = run_cli_document(document)

            metadata_tamper = json.loads(json.dumps(original))
            metadata_record = next(iter(metadata_tamper["records"].values()))
            metadata_record["result"]["artifact"]["version"] = 999
            state_path.write_text(json.dumps(metadata_tamper), encoding="utf-8")
            metadata_exit, metadata_replay = run_cli_document(document)

        self.assertEqual(created_exit, 0)
        self.assertEqual(forged_exit, 2)
        self.assertEqual(forged_payload["error"]["code"], "CONTRACT_VALIDATION_FAILED")
        self.assertEqual(replay_exit, 2)
        self.assertEqual(replay["error"]["code"], "STORYBOARD_STATE_CORRUPTED")
        self.assertEqual(metadata_exit, 2)
        self.assertEqual(metadata_replay["error"]["code"], "STORYBOARD_STATE_CORRUPTED")

    def test_cli_create_without_explicit_state_store_fails_closed(self) -> None:
        request = self.request()
        exit_code, payload = run_cli_document(
            {
                "command": "create-storyboard",
                "task_spec": envelope_document(request.task_spec),
                "task_context": envelope_document(request.task_context),
                "product_context": envelope_document(request.product_context),
                "plan": request.plan,
                "idempotency_key": request.idempotency_key,
                "expected_version": 0,
            }
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["code"], "STORYBOARD_STATE_STORE_REQUIRED")


if __name__ == "__main__":
    unittest.main()
