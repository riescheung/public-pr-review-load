import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from train_experimental_qwen import encoded_rows, record_failure


class FakeTokenizer:
    def apply_chat_template(self, messages, **kwargs):
        if kwargs["enable_thinking"] is not False:
            raise AssertionError("Thinking format drift")
        return [1, 2, 3]

    def encode(self, content, **kwargs):
        return [99] if content == "<|im_end|>" else [4, 5]


class ExperimentalTrainingTests(unittest.TestCase):
    def test_mask_matches_the_actual_inference_prefix(self):
        rows = [{"messages": [{"role": "user", "content": "code"},
                              {"role": "assistant", "content": "{}"}]}]
        self.assertEqual(encoded_rows(rows, FakeTokenizer(), 6), [([1, 2, 3, 4, 5, 99], 3)])
        with self.assertRaisesRegex(ValueError, "truncation"):
            encoded_rows(rows, FakeTokenizer(), 5)

    def test_failed_run_records_actual_saved_checkpoints_without_claiming_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "0000010_adapters.safetensors").write_bytes(b"checkpoint")
            failure = record_failure(root, RuntimeError("GPU failed"))
            self.assertFalse(failure["completed"])
            self.assertEqual(list(failure["saved_checkpoints"]), ["0000010_adapters.safetensors"])
            self.assertEqual(json.loads((root / "failure.json").read_text()), failure)
            with self.assertRaises(FileExistsError):
                record_failure(root, RuntimeError("Do not replace the original error"))


if __name__ == "__main__":
    unittest.main()
