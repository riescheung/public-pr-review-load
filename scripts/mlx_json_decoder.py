"""Apply a local JSON grammar to MLX logits without rewriting model answers."""

import json

from mlx_lm.tokenizer_utils import _byte_decoder
from outlines_core import Guide, Index, Vocabulary
from outlines_core.json_schema import build_regex_from_schema
from outlines_core.kernels.mlx import (
    allocate_token_bitmask, apply_token_bitmask, fill_next_token_bitmask,
)


def local_vocabulary(tokenizer):
    backend = json.loads(tokenizer.backend_tokenizer.to_str())
    if backend["model"]["type"] != "BPE" or backend["decoder"]["type"] != "ByteLevel":
        raise ValueError("Only the pinned Qwen ByteLevel tokenizer is supported")
    eos = tokenizer.eos_token_id
    if eos not in tokenizer.eos_token_ids:
        raise ValueError("Grammar EOS must terminate MLX generation")
    special = set(tokenizer.all_special_ids)
    added = {item["id"]: item["content"] for item in backend.get("added_tokens", [])}
    decoder = _byte_decoder()
    tokens = {}
    for token, identifier in tokenizer.get_vocab().items():
        if identifier in special:
            continue
        # Decoding individual tokens to Unicode loses incomplete UTF-8 bytes.
        raw = (added[identifier].encode("utf-8") if identifier in added
               else bytes(decoder[character] for character in token))
        if raw:
            tokens.setdefault(raw, []).append(identifier)
    return Vocabulary(eos, tokens)


class JSONLogitsProcessor:
    def __init__(self, tokenizer, schema):
        self.index = Index(build_regex_from_schema(json.dumps(schema)), local_vocabulary(tokenizer))
        self.eos_token_id = tokenizer.eos_token_id
        self.guide = None
        self.offset = None
        self.mask = None
        self.reset()

    def reset(self):
        self.guide = Guide(self.index)
        self.offset = None

    def __call__(self, tokens, logits):
        if self.offset is not None:
            for identifier in tokens[self.offset:].tolist():
                # MLX samples ahead once after the terminating EOS.
                if identifier == self.eos_token_id and self.guide.is_finished():
                    continue
                self.guide.advance(identifier, return_tokens=False)
        self.offset = tokens.size
        if self.mask is None:
            self.mask = allocate_token_bitmask(logits.shape[-1])
        fill_next_token_bitmask(self.guide, self.mask)
        if not self.mask.any():
            raise ValueError("JSON grammar has no valid next token")
        return apply_token_bitmask(logits, self.mask)
