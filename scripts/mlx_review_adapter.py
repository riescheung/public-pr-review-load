#!/usr/bin/env python3
"""Local MLX inference with the same formatter before and after LoRA."""

import json
import os
from pathlib import Path
import sys

from mlx_lm import generate
from mlx_lm.sample_utils import make_sampler

from local_review_protocol import review_with_feedback
from mlx_qwen_loader import load_local_model as load


def main():
    base = Path(os.environ["WEAVE_MLX_BASE"])
    adapter = os.environ.get("WEAVE_MLX_ADAPTER") or None
    if not base.is_dir() or adapter and not Path(adapter).is_dir():
        raise ValueError("Only local model and adapter paths are accepted")
    messages = json.load(sys.stdin)["messages"]
    model, tokenizer = load(base, adapter_path=adapter)
    def infer(conversation):
        prompt = tokenizer.apply_chat_template(
            conversation, tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )
        return generate(model, tokenizer, prompt=prompt, max_tokens=1200,
                        sampler=make_sampler(temp=0), verbose=False)

    reply = review_with_feedback(messages, infer, attempts=3)
    print(json.dumps(reply))


if __name__ == "__main__":
    main()
