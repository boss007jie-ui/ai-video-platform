from __future__ import annotations

import ast
import json
import unittest
from io import BytesIO, StringIO, TextIOWrapper
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ai_video_platform.skills.storyboard import StoryboardError, StoryboardRequest, StoryboardService
from ai_video_platform.skills.storyboard.cli import main, run_cli_document
from ai_video_platform.skills.storyboard.state import FileVersionStore, InMemoryVersionStore, VersionStoreError

from .fixtures import envelope_document, fixed_clock, product_context, reference_manifest, task_context, task_spec, valid_plan


class StoryboardFailureTests(unittest.TestCase):
    def request(self, **overrides):
        values = {
            "command": "create-storyboard",
            "task_spec": task_spec(),
            "task_context": task_context(),
            "product_context": product_context(),
            "plan": valid_plan(),
            "idempotency_key": "failure-base",
            "expected_version": 0,
        }
        values.update(overrides)
        return StoryboardRequest(**values)

    def assert_error(self, code: str, **overrides) -> StoryboardError:
        with self.assertRaises(StoryboardError) as captured:
            StoryboardService(clock=fixed_clock).execute(self.request(**overrides))
        self.assertEqual(captured.exception.code, code)
        self.assertFalse(captured.exception.retryable)
        return captured.exception

    def test_malformed_context_and_ambiguous_product_fail_closed(self) -> None:
        self.assert_error("STORYBOARD_CONTEXT_INVALID", task_context=task_context(active_skill_id="qa-review"))
        self.assert_error(
            "PRODUCT_SKU_AMBIGUOUS",
            task_spec=task_spec(product_selector={"sku_required": True, "candidate_sku_ids": ["sku-a", "sku-b"]}),
            product_context=product_context(sku_id=None),
        )

    def test_missing_required_reference_and_partial_plan_are_rejected(self) -> None:
        self.assert_error("STORYBOARD_REFERENCE_REQUIRED", task_spec=task_spec(constraints={"reference_required": True}))
        partial = valid_plan()
        partial["scenes"][0]["beats"] = []
        self.assert_error("STORYBOARD_PLAN_INCOMPLETE", plan=partial)

    def test_stale_revision_and_idempotency_conflict_are_rejected(self) -> None:
        service = StoryboardService(clock=fixed_clock)
        first = service.execute(self.request(idempotency_key="create-one"))
        with self.assertRaises(StoryboardError) as stale:
            service.execute(
                self.request(
                    command="revise-storyboard",
                    expected_version=0,
                    prior_artifact=first.artifact,
                    idempotency_key="revise-stale",
                )
            )
        self.assertEqual(stale.exception.code, "STORYBOARD_VERSION_STALE")

        conflict_service = StoryboardService(clock=fixed_clock)
        conflict_service.execute(self.request(idempotency_key="same-key"))
        changed = valid_plan()
        changed["title"] = "Different input"
        with self.assertRaises(StoryboardError) as conflict:
            conflict_service.execute(self.request(idempotency_key="same-key", plan=changed))
        self.assertEqual(conflict.exception.code, "STORYBOARD_IDEMPOTENCY_CONFLICT")

    def test_cancellation_is_terminal_and_produces_no_business_artifact(self) -> None:
        result = StoryboardService(clock=fixed_clock).execute(self.request(cancellation_requested=True))

        self.assertEqual(result.status, "cancelled")
        self.assertIsNone(result.artifact)
        self.assertIsNone(result.asset_manifest)
        self.assertEqual(result.execution_event.payload["event_type"], "cancelled")

    def test_pending_product_content_and_forbidden_generation_capability_are_rejected(self) -> None:
        self.assert_error("PRODUCT_CONTEXT_CONTAMINATED", product_context=product_context(pending=True))
        forbidden = valid_plan()
        forbidden["provider_submission"] = {"provider_id": "forbidden"}
        self.assert_error("STORYBOARD_CAPABILITY_FORBIDDEN", plan=forbidden)

    def test_cli_has_stable_error_and_exit_code(self) -> None:
        exit_code, payload = run_cli_document({"command": "submit-provider"})

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["code"], "STORYBOARD_COMMAND_UNSUPPORTED")
        self.assertEqual(payload["status"], "failed")

    def test_public_boundary_rejects_command_identity_and_contract_mismatches(self) -> None:
        self.assert_error("STORYBOARD_COMMAND_UNSUPPORTED", command="submit-provider")
        self.assert_error("STORYBOARD_IDEMPOTENCY_KEY_REQUIRED", idempotency_key="")
        self.assert_error("STORYBOARD_CONTRACT_INVALID", task_spec=task_context())

        wrong_product = valid_plan()
        wrong_product["product_id"] = "product-other"
        self.assert_error("STORYBOARD_PRODUCT_MISMATCH", plan=wrong_product)

    def test_hierarchy_objects_ids_scores_and_constraints_fail_closed(self) -> None:
        cases = []
        missing_title = valid_plan()
        missing_title["title"] = ""
        cases.append((missing_title, "STORYBOARD_PLAN_INCOMPLETE"))

        invalid_score = valid_plan()
        invalid_score["scenes"][0]["emotion_score"] = 101
        cases.append((invalid_score, "STORYBOARD_EMOTIONAL_PROGRESSION_INVALID"))

        duplicate_panel = valid_plan()
        duplicate_panel["scenes"][0]["beats"][0]["shots"][0]["panels"][1]["panel_id"] = "panel-001"
        cases.append((duplicate_panel, "STORYBOARD_ID_DUPLICATE"))

        missing_constraint = valid_plan()
        missing_constraint["scenes"][0]["beats"][0]["shots"][0]["panels"][0]["prompt"] = "Generic product view"
        cases.append((missing_constraint, "STORYBOARD_PRODUCT_CONSTRAINT_VIOLATION"))

        missing_continuity = valid_plan()
        missing_continuity["scenes"][0]["beats"][0]["shots"][0]["panels"][0]["continuity"] = {}
        cases.append((missing_continuity, "STORYBOARD_PLAN_INCOMPLETE"))

        for index, (plan, code) in enumerate(cases):
            with self.subTest(index=index, code=code):
                self.assert_error(code, plan=plan, idempotency_key=f"hierarchy-{index}")

    def test_non_object_hierarchy_and_invalid_transition_declarations_are_rejected(self) -> None:
        mutations = []
        scene = valid_plan()
        scene["scenes"][0] = None
        mutations.append(scene)
        beat = valid_plan()
        beat["scenes"][0]["beats"][0] = None
        mutations.append(beat)
        shot = valid_plan()
        shot["scenes"][0]["beats"][0]["shots"][0] = None
        mutations.append(shot)
        panel = valid_plan()
        panel["scenes"][0]["beats"][0]["shots"][0]["panels"][0] = None
        mutations.append(panel)
        for index, plan in enumerate(mutations):
            with self.subTest(index=index):
                self.assert_error("STORYBOARD_PLAN_INCOMPLETE", plan=plan, idempotency_key=f"object-{index}")

        bad_changes = valid_plan()
        target = bad_changes["scenes"][0]["beats"][0]["shots"][0]["panels"][1]
        target["continuity"]["actor_outfit"] = "red-shirt"
        target["continuity_changes"] = []
        self.assert_error("STORYBOARD_CONTINUITY_CONFLICT", plan=bad_changes, idempotency_key="changes-type")

        bad_declaration = valid_plan()
        target = bad_declaration["scenes"][0]["beats"][0]["shots"][0]["panels"][1]
        target["continuity"]["actor_outfit"] = "red-shirt"
        target["continuity_changes"] = {
            "actor_outfit": {"from": "blue-jacket", "to": "red-shirt", "reason": ""}
        }
        self.assert_error("STORYBOARD_CONTINUITY_CONFLICT", plan=bad_declaration, idempotency_key="changes-fields")

    def test_cli_rejects_malformed_envelopes_scalars_and_prior_artifacts(self) -> None:
        exit_code, payload = run_cli_document({"command": "create-storyboard", "task_spec": {}})
        self.assertEqual((exit_code, payload["error"]["code"]), (2, "STORYBOARD_INPUT_INVALID"))

        base = {
            "command": "create-storyboard",
            "task_spec": envelope_document(task_spec()),
            "task_context": envelope_document(task_context()),
            "product_context": envelope_document(product_context()),
            "plan": valid_plan(),
            "idempotency_key": "cli-invalid",
            "expected_version": "not-an-integer",
        }
        exit_code, payload = run_cli_document(base)
        self.assertEqual((exit_code, payload["error"]["code"]), (2, "STORYBOARD_INPUT_INVALID"))

        revise = {**base, "command": "revise-storyboard", "expected_version": 1, "prior_artifact": "bad"}
        exit_code, payload = run_cli_document(revise)
        self.assertEqual((exit_code, payload["error"]["code"]), (2, "STORYBOARD_INPUT_INVALID"))

    def test_cli_main_maps_malformed_json_to_stable_machine_error(self) -> None:
        stdin = TextIOWrapper(BytesIO(b'{"command":'), encoding="utf-8")
        stdout = StringIO()
        with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
            exit_code = main(["create-storyboard", "--input", "-"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"]["code"], "STORYBOARD_INPUT_INVALID")

    def test_cli_main_maps_argument_errors_to_stable_machine_error(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            exit_code = main([])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"]["code"], "STORYBOARD_COMMAND_UNSUPPORTED")
        self.assertEqual(stderr.getvalue(), "")

        help_stdout = StringIO()
        with patch("sys.stdout", help_stdout), patch("sys.stderr", StringIO()):
            help_exit = main(["--help"])
        self.assertEqual(help_exit, 2)
        self.assertEqual(json.loads(help_stdout.getvalue())["error"]["code"], "STORYBOARD_COMMAND_UNSUPPORTED")

    def test_cli_main_uses_a_bounded_read(self) -> None:
        class RecordingBuffer:
            read_size = None

            def read(self, size=-1):
                self.read_size = size
                return b"{}"

        class RecordingStdin:
            buffer = RecordingBuffer()

        stdout = StringIO()
        with patch("sys.stdin", RecordingStdin()), patch("sys.stdout", stdout):
            exit_code = main(["create-storyboard", "--input", "-"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(RecordingStdin.buffer.read_size, 1_048_577)

    def test_error_details_and_sensitive_continuity_keys_are_redacted(self) -> None:
        error = StoryboardError(
            "STORYBOARD_INPUT_INVALID",
            "validation",
            "safe",
            details={"api_key": "synthetic-value", "safe": "visible"},
        )
        serialized = error.to_dict()
        self.assertEqual(serialized["details"]["api_key"], "[REDACTED]")
        self.assertEqual(serialized["details"]["safe"], "visible")

        plan = valid_plan()
        first, second = plan["scenes"][0]["beats"][0]["shots"][0]["panels"]
        first["continuity"]["api_key"] = "state-a"
        second["continuity"]["api_key"] = "state-b"
        captured = self.assert_error("STORYBOARD_CONTINUITY_CONFLICT", plan=plan, idempotency_key="redacted-key")
        self.assertNotIn("api_key", captured.field_paths[0])

        forbidden = valid_plan()
        forbidden["credential_bucket"] = {"provider_submission": {}}
        captured = self.assert_error("STORYBOARD_CAPABILITY_FORBIDDEN", plan=forbidden, idempotency_key="redacted-path")
        self.assertNotIn("credential", captured.field_paths[0])

    def test_panel_count_and_input_size_budgets_fail_closed(self) -> None:
        oversized_panels = valid_plan()
        panel_template = oversized_panels["scenes"][0]["beats"][0]["shots"][0]["panels"][0]
        oversized_panels["scenes"][0]["beats"][0]["shots"][0]["panels"] = [
            {**panel_template, "panel_id": f"panel-budget-{index:03d}"}
            for index in range(501)
        ]
        self.assert_error("STORYBOARD_BUDGET_EXCEEDED", plan=oversized_panels)

        oversized_bytes = valid_plan()
        oversized_bytes["creative_direction"] = "x" * 1_048_577
        self.assert_error("STORYBOARD_BUDGET_EXCEEDED", plan=oversized_bytes)

    def test_runtime_has_no_private_planning_provider_or_network_import(self) -> None:
        root = Path(__file__).resolve().parents[3] / "src" / "ai_video_platform" / "skills" / "storyboard"
        forbidden_roots = {
            "socket",
            "http",
            "requests",
            "httpx",
            "aiohttp",
            "urllib",
            "subprocess",
            "openai",
            "google.generativeai",
            "replicate",
            "fal_client",
            "apify_client",
            "ai_video_platform.skills.storyboard_master_video_planning",
            "ai_video_platform.skills.product_image_panel_generation",
            "ai_video_platform.skills.video_generation",
        }
        imported: set[str] = set()
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
        violations = {
            name
            for name in imported
            if any(name == root or name.startswith(root + ".") for root in forbidden_roots)
        }
        self.assertEqual(violations, set())

    def test_version_stores_fail_closed_for_conflicts_corruption_and_lock_contention(self) -> None:
        memory = InMemoryVersionStore()
        self.assertIsNone(memory.current("task", "product"))
        outcome = memory.commit(
            "task",
            "product",
            expected=None,
            new_version=1,
            idempotency_key="memory-key",
            request_digest="a" * 64,
            result={"status": "completed"},
        )
        self.assertEqual(outcome, "recorded")
        self.assertEqual(
            memory.commit(
                "task",
                "product",
                expected=None,
                new_version=1,
                idempotency_key="memory-key",
                request_digest="a" * 64,
                result={"status": "completed"},
            ),
            "replay",
        )
        self.assertEqual(
            memory.record_outcome("memory-key", "changed", {"status": "completed"}),
            "idempotency-conflict",
        )
        self.assertEqual(
            memory.commit(
                "task",
                "product",
                expected=None,
                new_version=2,
                idempotency_key="different-key",
                request_digest="b" * 64,
                result={"status": "completed"},
            ),
            "stale",
        )

        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "storyboard-state.json"
            state_path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(VersionStoreError) as corrupted:
                FileVersionStore(state_path, workspace_root=directory).current("task", "product")
            self.assertEqual(corrupted.exception.code, "STORYBOARD_STATE_CORRUPTED")

            state_path.write_text('{"schema_version":"2.0.0","versions":{},"records":{}}', encoding="utf-8")
            with self.assertRaises(VersionStoreError) as unsupported:
                FileVersionStore(state_path, workspace_root=directory).current("task", "product")
            self.assertEqual(unsupported.exception.code, "STORYBOARD_STATE_CORRUPTED")

            state_path.write_text(
                '{"schema_version":"1.0.0","versions":{"key":true},"records":{}}',
                encoding="utf-8",
            )
            with self.assertRaises(VersionStoreError) as invalid_version:
                FileVersionStore(state_path, workspace_root=directory).current("task", "product")
            self.assertEqual(invalid_version.exception.code, "STORYBOARD_STATE_CORRUPTED")

            state_path.write_text(
                '{"schema_version":"1.0.0","versions":{},"records":{}}', encoding="utf-8"
            )
            store = FileVersionStore(state_path, workspace_root=directory, lock_timeout_seconds=0)
            descriptor = store._acquire_lock()
            try:
                with self.assertRaises(VersionStoreError) as contention:
                    store.record_outcome("locked-key", "c" * 64, {"status": "completed"})
                self.assertEqual(contention.exception.code, "STORYBOARD_STATE_LOCK_TIMEOUT")
                self.assertTrue(contention.exception.retryable)
            finally:
                store._release_lock(descriptor)

            outside = Path(directory).parent / "outside-storyboard-state.json"
            with self.assertRaises(VersionStoreError) as escaped:
                FileVersionStore(outside, workspace_root=directory)
            self.assertEqual(escaped.exception.code, "STORYBOARD_STATE_PATH_FORBIDDEN")

            with self.assertRaises(VersionStoreError) as missing_root:
                FileVersionStore(state_path, workspace_root=Path(directory) / "missing-root")
            self.assertEqual(missing_root.exception.code, "STORYBOARD_STATE_PATH_FORBIDDEN")

    def test_file_version_store_maps_atomic_commit_failure_and_cleans_lock(self) -> None:
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "storyboard-state.json"
            store = FileVersionStore(state_path, workspace_root=directory)
            with patch(
                "ai_video_platform.skills.storyboard.state.os.replace",
                side_effect=OSError("synthetic commit failure"),
            ):
                with self.assertRaises(VersionStoreError) as captured:
                    store.commit(
                        "task",
                        "product",
                        expected=None,
                        new_version=1,
                        idempotency_key="commit-failure",
                        request_digest="d" * 64,
                        result={"status": "completed"},
                    )

            self.assertEqual(captured.exception.code, "STORYBOARD_STATE_UNAVAILABLE")
            self.assertTrue(captured.exception.retryable)
            descriptor = store._acquire_lock()
            store._release_lock(descriptor)

    def test_file_version_store_rejects_oversized_state_before_replacing_valid_state(self) -> None:
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "storyboard-state.json"
            store = FileVersionStore(state_path, workspace_root=directory)
            with patch("ai_video_platform.skills.storyboard.state.MAX_STATE_BYTES", 128):
                with self.assertRaises(VersionStoreError) as captured:
                    store.record_outcome(
                        "oversized-state",
                        "e" * 64,
                        {"status": "completed", "artifact": "x" * 256},
                    )

            self.assertEqual(captured.exception.code, "STORYBOARD_STATE_BUDGET_EXCEEDED")
            self.assertFalse(state_path.exists())

    def test_file_version_store_distinguishes_replay_from_idempotency_conflict(self) -> None:
        with TemporaryDirectory() as directory:
            store = FileVersionStore(Path(directory) / "state.json", workspace_root=directory)
            arguments = {
                "task_id": "task",
                "product_id": "product",
                "expected": None,
                "new_version": 1,
                "idempotency_key": "durable-key",
                "request_digest": "f" * 64,
                "result": {"status": "completed"},
            }
            self.assertEqual(store.commit(**arguments), "recorded")
            self.assertEqual(store.commit(**arguments), "replay")
            self.assertEqual(
                store.record_outcome("durable-key", "changed", {"status": "completed"}),
                "idempotency-conflict",
            )

    def test_cli_maps_state_path_escape_and_corruption_to_machine_errors(self) -> None:
        request = self.request()
        base = {
            "command": "create-storyboard",
            "task_spec": envelope_document(request.task_spec),
            "task_context": envelope_document(request.task_context),
            "product_context": envelope_document(request.product_context),
            "plan": request.plan,
            "idempotency_key": "state-path-failure",
            "expected_version": 0,
        }
        with TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"AVP_TASK_WORKSPACE_ROOT": directory}
        ):
            escaped_exit, escaped = run_cli_document(
                {
                    **base,
                    "task_workspace": directory,
                    "state_file": str(Path(directory).parent / "escaped-state.json"),
                }
            )
            self.assertEqual(escaped_exit, 2)
            self.assertEqual(escaped["error"]["code"], "STORYBOARD_STATE_PATH_FORBIDDEN")

            state_path = Path(directory) / "corrupted-state.json"
            state_path.write_text('{"schema_version":"1.0.0","versions":{},"records":{"bad":[]}}', encoding="utf-8")
            corrupted_exit, corrupted = run_cli_document(
                {**base, "task_workspace": directory, "state_file": str(state_path)}
            )
            self.assertEqual(corrupted_exit, 2)
            self.assertEqual(corrupted["error"]["code"], "STORYBOARD_STATE_CORRUPTED")


if __name__ == "__main__":
    unittest.main()
