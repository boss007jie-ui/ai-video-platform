from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from ai_video_platform.orchestration.hermes.project_runner import (
    HermesProjectRunner,
    RunnerError,
    main,
)


class HermesProjectRunnerTests(unittest.TestCase):
    def test_two_entry_modes_converge_on_one_simple_production_trunk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = HermesProjectRunner(root / "product").start(
                project_id="project-product-001",
                entry_mode="product_first",
            )
            reference = HermesProjectRunner(root / "reference").start(
                project_id="project-reference-001",
                entry_mode="reference_video_first",
            )

        self.assertEqual(product["current_step"]["step_id"], "product_context")
        self.assertEqual(reference["current_step"]["step_id"], "reference_analysis")
        product_steps = [step["step_id"] for step in product["steps"]]
        reference_steps = [step["step_id"] for step in reference["steps"]]
        self.assertEqual(reference_steps[1:], product_steps)
        self.assertEqual(product_steps, [
            "product_context",
            "storyboard",
            "panel_generation",
            "video_planning",
            "qa_review",
            "video_generation",
        ])

    def test_only_current_skill_is_authorized_and_failed_or_empty_completion_cannot_advance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = HermesProjectRunner(Path(directory))
            runner.start(project_id="project-001", entry_mode="product_first")

            with self.assertRaises(RunnerError):
                runner.authorize(skill_id="storyboard", command="derive-production-panels")
            with self.assertRaises(RunnerError):
                runner.complete({
                    "step_id": "product_context",
                    "skill_id": "product-knowledge",
                    "command": "build-product-context",
                    "status": "failed",
                    "artifact_refs": ["product-context.json"],
                    "result": {"ok": False},
                })
            with self.assertRaises(RunnerError):
                runner.complete({
                    "step_id": "product_context",
                    "skill_id": "product-knowledge",
                    "command": "build-product-context",
                    "status": "completed",
                    "artifact_refs": [],
                    "result": {"ok": True},
                })
            with self.assertRaises(RunnerError):
                runner.complete({
                    "step_id": "product_context",
                    "skill_id": "product-knowledge",
                    "command": "identify-product",
                    "status": "completed",
                    "artifact_refs": ["product-context.json"],
                    "result": {"ok": True},
                })

            unchanged = runner.status()
            authorized = runner.authorize(
                skill_id="product-knowledge",
                command="build-product-context",
            )

        self.assertEqual(unchanged["current_step"]["step_id"], "product_context")
        self.assertEqual(authorized["step_id"], "product_context")

    def test_one_successful_completion_advances_once_and_persists_only_a_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = HermesProjectRunner(workspace)
            runner.start(project_id="project-001", entry_mode="product_first")

            advanced = runner.complete({
                "step_id": "product_context",
                "skill_id": "product-knowledge",
                "command": "build-product-context",
                "status": "completed",
                "artifact_refs": ["artifacts/product-context.json"],
                "result": {
                    "ok": True,
                    "execution_event": {
                        "skill_id": "product-knowledge",
                        "event_type": "completed",
                        "status": "succeeded",
                    },
                },
            })
            persisted = json.loads((workspace / ".hermes" / "project_run.json").read_text(encoding="utf-8"))

        self.assertEqual(advanced["current_step"]["step_id"], "storyboard")
        self.assertEqual(advanced["completed_steps"], ["product_context"])
        completed = persisted["steps"][0]
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["artifact_refs"], ["artifacts/product-context.json"])
        self.assertRegex(completed["result_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("result", completed)

    def test_cli_starts_and_reads_the_same_local_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                start_code = main([
                    "start",
                    "--workspace", directory,
                    "--project-id", "project-cli-001",
                    "--entry-mode", "reference_video_first",
                ])
            started = json.loads(output.getvalue())

            output = io.StringIO()
            with redirect_stdout(output):
                status_code = main(["status", "--workspace", directory])
            status = json.loads(output.getvalue())

        self.assertEqual((start_code, status_code), (0, 0))
        self.assertEqual(started["current_step"]["step_id"], "reference_analysis")
        self.assertEqual(status, started)

    def test_modified_state_cannot_skip_a_pending_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = HermesProjectRunner(workspace)
            runner.start(project_id="project-001", entry_mode="product_first")
            state_path = workspace / ".hermes" / "project_run.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["current_index"] = 1
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaises(RunnerError):
                runner.status()


if __name__ == "__main__":
    unittest.main()
