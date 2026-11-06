from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from train_experimental_qwen import encoded_rows


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


if __name__ == "__main__":
    unittest.main()
