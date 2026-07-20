from __future__ import annotations

import unittest

from ai_video_platform.contracts.errors import ContractError, ErrorCode
from ai_video_platform.contracts.serialization import parse_json_object


class JsonInputTests(unittest.TestCase):
    def test_duplicate_object_keys_are_rejected_at_any_depth(self) -> None:
        document = '{"payload":{"task_id":"one","task_id":"two"}}'

        with self.assertRaises(ContractError) as captured:
            parse_json_object(document)

        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)
        self.assertEqual(captured.exception.field_paths, ("json",))

    def test_input_size_limit_is_measured_in_utf8_bytes(self) -> None:
        document = '{"value":"测试"}'

        with self.assertRaises(ContractError) as captured:
            parse_json_object(document, max_bytes=10)

        self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)

    def test_invalid_utf8_non_finite_numbers_and_non_object_roots_are_rejected(self) -> None:
        invalid_documents = (b'\xff', '{"value":NaN}', '[1,2,3]')

        for document in invalid_documents:
            with self.subTest(document=document):
                with self.assertRaises(ContractError) as captured:
                    parse_json_object(document)
                self.assertEqual(captured.exception.code, ErrorCode.CONTRACT_VALIDATION_FAILED)

    def test_valid_document_returns_a_mapping(self) -> None:
        parsed = parse_json_object(b'{"payload":{"ok":true}}')

        self.assertEqual(parsed, {"payload": {"ok": True}})


if __name__ == "__main__":
    unittest.main()
