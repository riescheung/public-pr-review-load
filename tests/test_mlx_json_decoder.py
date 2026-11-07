import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mlx_review_schema import review_schema
from score_harness import one_pass_prompt
from test_benchmark import packet, review

try:
    import mlx.core as mx
    from mlx_lm.tokenizer_utils import _byte_decoder
    from mlx_json_decoder import JSONLogitsProcessor, local_vocabulary
    from outlines_core import Guide
except ImportError:
    mx = None


class ByteTokenizer:
    eos_token_id = 256
    eos_token_ids = {256}
    all_special_ids = [256]
    backend_tokenizer = SimpleNamespace(to_str=lambda: json.dumps({
        "model": {"type": "BPE"}, "decoder": {"type": "ByteLevel"},
    }))

    def get_vocab(self):
        return {**_byte_decoder(), "<|im_end|>": 256}


@unittest.skipIf(mx is None, "Requires optional MLX and outlines-core dependencies")
class JSONDecoderTests(unittest.TestCase):
    def test_persistent_tokenizer_reuses_immutable_vocabulary(self):
        tokenizer = ByteTokenizer()
        self.assertTrue(local_vocabulary(tokenizer) is local_vocabulary(tokenizer))

    def test_byte_vocabulary_keeps_newlines_and_partial_utf8_and_excludes_specials(self):
        vocab = local_vocabulary(ByteTokenizer())
        self.assertEqual(vocab.get(b"\n"), [10])
        self.assertEqual(vocab.get(b"\xe2"), [226])
        self.assertIsNone(vocab.get(b"<|im_end|>"))

    def test_mask_ignores_prompt_advances_generated_tokens_and_allows_eos_only_at_end(self):
        processor = JSONLogitsProcessor(ByteTokenizer(), {"enum": ["return safe"]})
        prompt = [999, 1000]
        encoded = list(json.dumps("return safe").encode())
        for index in range(len(encoded) + 1):
            masked = processor(mx.array(prompt + encoded[:index]), mx.zeros((1, 257)))
            next_token = encoded[index] if index < len(encoded) else 256
            self.assertTrue(mx.isfinite(masked[0, next_token]).item())
            self.assertEqual(mx.isfinite(masked[0, 256]).item(), index == len(encoded))
        self.assertEqual(mx.sum(mx.isfinite(masked)).item(), 1)
        # MLX computes one sample ahead before yielding the terminating EOS.
        terminal = processor(mx.array(prompt + encoded + [256]), mx.zeros((1, 257)))
        self.assertEqual(mx.sum(mx.isfinite(terminal)).item(), 1)
        self.assertTrue(mx.isfinite(terminal[0, 256]).item())
        processor.reset()
        restarted = processor(mx.array(prompt), mx.zeros((1, 257)))
        self.assertTrue(mx.isfinite(restarted[0, ord('"')]).item())
        self.assertFalse(mx.isfinite(restarted[0, ord("x")]).item())

    def test_an_invalid_generated_token_fails_instead_of_silently_resetting(self):
        processor = JSONLogitsProcessor(ByteTokenizer(), {"enum": ["return safe"]})
        processor(mx.array([999]), mx.zeros((1, 257)))
        with self.assertRaises(ValueError):
            processor(mx.array([999, ord("x")]), mx.zeros((1, 257)))
        processor.reset()
        processor(mx.array([999]), mx.zeros((1, 257)))
        with self.assertRaises(ValueError):
            processor(mx.array([999, 256]), mx.zeros((1, 257)))

    def test_real_review_grammar_admits_all_tiers_and_abstention_not_invented_quotes(self):
        schema = review_schema([{"content": one_pass_prompt(packet()["chunks"][0])}])
        processor = JSONLogitsProcessor(ByteTokenizer(), schema)
        for score in (1, 2, 3, None):
            expected = review(score)
            answer = {**expected, **expected["observations"][0]}
            fields = schema["anyOf"][int(score is None)]["properties"]
            answer = {key: answer[key] for key in fields}
            answer["observations"] = [
                {key: item[key] for key in ("hunk", "code_quote", "behavior", "posthog_connection")}
                for item in answer["observations"]
            ]
            with self.subTest(score=score):
                self.assertTrue(Guide(processor.index).accepts_tokens(
                    list(json.dumps(answer).encode()),
                ))
            answer["observations"][0]["code_quote"] = "invented quote"
            self.assertFalse(Guide(processor.index).accepts_tokens(
                list(json.dumps(answer).encode()),
            ))


if __name__ == "__main__":
    unittest.main()
