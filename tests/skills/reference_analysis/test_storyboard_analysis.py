from __future__ import annotations

from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from ai_video_platform.skills.reference_analysis import analyze_storyboard
from ai_video_platform.skills.reference_analysis.cli import main


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "storyboard-analysis-v1.json"
CANONICAL_IDENTITIES = {
    "ReferenceStoryboardAnalysis": "avp.contract.reference-storyboard-analysis",
    "ReferenceBeat": "avp.contract.reference-beat",
    "ReferenceShotEvidence": "avp.contract.reference-shot-evidence",
    "ReplicationPattern": "avp.contract.replication-pattern",
    "ReferenceAnalysisBoardManifest": "avp.contract.reference-analysis-board-manifest",
}


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _solid_png(width: int, height: int, rgb: list[int]) -> bytes:
    row = bytes(rgb) * width
    pixels = b"".join(b"\x00" + row for _ in range(height))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            _chunk(b"IDAT", zlib.compress(pixels, 9)),
            _chunk(b"IEND", b""),
        )
    )


def materialize_fixture(workspace: Path, *, include_comments: bool = True) -> dict[str, object]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    media = bytes.fromhex(fixture["media"]["bytes_hex"])
    media_path = workspace / fixture["media"]["path"]
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(media)
    replacements = {"$MEDIA_SHA256": hashlib.sha256(media).hexdigest()}
    for keyframe in fixture["keyframes"]:
        payload = _solid_png(keyframe["width"], keyframe["height"], keyframe["rgb"])
        path = workspace / keyframe["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        replacements[f"${keyframe['keyframe_id'].upper().replace('-', '_')}_SHA256"] = hashlib.sha256(payload).hexdigest()
    request = copy.deepcopy(fixture["request"])
    encoded = json.dumps(request)
    for marker, digest in replacements.items():
        encoded = encoded.replace(marker, digest)
    request = json.loads(encoded)
    if not include_comments:
        request.pop("popular_comments")
        for beat in request["analysis_configuration"]["timeline"]:
            beat["comment_evidence"] = {"value": "UNAVAILABLE", "evidence_refs": []}
            for field in beat.values():
                if isinstance(field, dict) and "evidence_refs" in field:
                    field["evidence_refs"] = [ref for ref in field["evidence_refs"] if not ref.startswith("comment:")]
        request["analysis_configuration"]["bottom_line_formula"]["evidence_refs"] = [
            ref
            for ref in request["analysis_configuration"]["bottom_line_formula"]["evidence_refs"]
            if not ref.startswith("comment:")
        ]
    return request


def _png_text_chunks(payload: bytes) -> dict[str, str]:
    chunks: dict[str, str] = {}
    offset = 8
    while offset < len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        kind = payload[offset + 4 : offset + 8]
        data = payload[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"tEXt":
            key, value = data.split(b"\x00", 1)
            chunks[key.decode("latin-1")] = value.decode("latin-1")
    return chunks


class StoryboardAnalysisTests(unittest.TestCase):
    def test_analyze_storyboard_publishes_evidence_bound_canonical_artifacts_and_boards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request = materialize_fixture(workspace)
            result = analyze_storyboard(request, workspace=workspace)

            self.assertEqual(result.status, "COMPLETED")
            self.assertEqual(result.output_root, "reference_analysis")
            artifact = result.to_dict()["artifact"]
            self.assertEqual(
                {item["artifact_name"]: item["contract_identity"] for item in artifact["artifact_refs"]},
                CANONICAL_IDENTITIES,
            )
            self.assertEqual(artifact["timeline"][0]["interval"], {"start_ms": 0, "end_ms": 1500})
            self.assertEqual(artifact["reference_beats"][0]["keyframe_ids"], ["kf-001"])
            self.assertEqual(artifact["shot_evidence"][0]["source_media_sha256"], request["selected_reference_video"]["sha256"])
            self.assertEqual(artifact["replication_patterns"][0]["adaptation_target_product_id"], "current-product-001")

            root = workspace / "reference_analysis"
            expected_paths = {
                "reference_storyboard_analysis.json",
                "reference_storyboard_analysis.md",
                "reference_storyboard_analysis_board.png",
                "shot_evidence_board.png",
                "replication_board.png",
                "analysis_provenance.json",
                "keyframes/kf-001.png",
                "keyframes/kf-002.png",
            }
            self.assertEqual(
                {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()},
                expected_paths,
            )
            manifest_assets = artifact["board_manifest"]["assets"]
            self.assertEqual(len(manifest_assets), 5)
            self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest_assets))
            self.assertTrue(all(item["provider_execution_input"] is False for item in manifest_assets))
            self.assertTrue(all(item["first_frame_eligible"] is False for item in manifest_assets))
            self.assertTrue(all(item["product_panel_eligible"] is False for item in manifest_assets))
            self.assertEqual(
                (root / "keyframes" / "kf-001.png").read_bytes(),
                (workspace / "inputs" / "keyframes" / "kf-001.png").read_bytes(),
            )
            for name in ("reference_storyboard_analysis_board.png", "shot_evidence_board.png", "replication_board.png"):
                self.assertTrue((root / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

            replication_metadata = json.loads(
                _png_text_chunks((root / "replication_board.png").read_bytes())["avp-layout"]
            )
            self.assertEqual(
                replication_metadata["columns"],
                ["actual reference behavior", "reusable mechanism", "adaptation to current product"],
            )

    def test_comments_are_optional_and_unavailable_evidence_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = analyze_storyboard(materialize_fixture(workspace, include_comments=False), workspace=workspace)
            artifact = result.to_dict()["artifact"]
            self.assertEqual(artifact["comments"]["status"], "UNAVAILABLE")
            self.assertEqual(artifact["reference_beats"][0]["comment_evidence"]["value"], "UNAVAILABLE")
            markdown = (workspace / "reference_analysis" / "reference_storyboard_analysis.md").read_text(encoding="utf-8")
            self.assertIn("UNAVAILABLE", markdown)

    def test_repeatability_holds_for_replay_and_independent_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as first_directory, tempfile.TemporaryDirectory() as second_directory:
            first_workspace = Path(first_directory)
            second_workspace = Path(second_directory)
            first_request = materialize_fixture(first_workspace)
            second_request = materialize_fixture(second_workspace)
            first = analyze_storyboard(first_request, workspace=first_workspace)
            replay = analyze_storyboard(first_request, workspace=first_workspace)
            second = analyze_storyboard(second_request, workspace=second_workspace)
            self.assertEqual(first, replay)
            self.assertEqual(first.to_dict()["artifact"], second.to_dict()["artifact"])
            first_files = {
                path.relative_to(first_workspace / "reference_analysis").as_posix(): path.read_bytes()
                for path in (first_workspace / "reference_analysis").rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second_workspace / "reference_analysis").as_posix(): path.read_bytes()
                for path in (second_workspace / "reference_analysis").rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_files, second_files)

    def test_skill_cli_exposes_analyze_storyboard_without_root_routing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            request_path = workspace / "storyboard-request.json"
            request_path.write_text(json.dumps(materialize_fixture(workspace)), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["analyze-storyboard", "--input", str(request_path), "--workspace", str(workspace)])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "COMPLETED")
            self.assertEqual(payload["output_root"], "reference_analysis")


if __name__ == "__main__":
    unittest.main()
