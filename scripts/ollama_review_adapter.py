#!/usr/bin/env python3
"""Read harness messages on stdin and obtain one local Ollama JSON review."""

import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def review(messages, model="qwen3.5:9b", endpoint="http://127.0.0.1:11434/api/chat"):
    prompt = messages[-1]["content"]
    observation = "Inspect every hunk in this chunk" in prompt
    combined = "Review this one complete code-diff chunk" in prompt
    shape = {"type": "object", "additionalProperties": False, "properties": {}}
    if observation or combined:
        cited_lines = {}
        for hunk_id, text in re.findall(
            r"<hunk id=([^\s]+) path=[^>]+>\n(.*?)</hunk>",
            prompt, flags=re.DOTALL,
        ):
            cited_lines[hunk_id] = sorted({
                line[1:] for line in text.splitlines()
                if line.startswith(("+", "-"))
                and not line.startswith(("+++", "---"))
                and len(line[1:].strip()) >= 8
            })
        citation_shapes = [{
            "type": "object", "additionalProperties": False,
            "properties": {
                "hunk": {"const": hunk_id},
                "behavior": {"type": "string", "minLength": 1, "maxLength": 220},
                "posthog_connection": {"type": "string", "minLength": 1,
                                       "maxLength": 220},
                "code_quote": {"enum": lines},
            },
            "required": ["hunk", "behavior", "posthog_connection", "code_quote"],
        } for hunk_id, lines in cited_lines.items() if lines]
        shape["properties"].update({
            "observations": {"type": "array", "minItems": 1, "maxItems": 3,
                             "items": {"oneOf": citation_shapes} if citation_shapes
                             else {"type": "object"}},
            "limitations": {"type": "string", "minLength": 1, "maxLength": 240},
        })
    if not observation:
        shape["properties"].update({
            "score": {"type": ["integer", "null"], "enum": [1, 2, 3, None]},
            "reason": {"type": "string", "minLength": 1, "maxLength": 380},
            "posthog_relevance": {"type": "string", "maxLength": 240},
            "confidence": {"type": "string", "enum": ["low", "medium", "high", "none"]},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "uncertainty": {"type": "string", "minLength": 1, "maxLength": 240},
            "metadata_dependency": {"type": "boolean", "enum": [False]},
            "grouping_issue": {"type": "boolean"},
            "abstention_reason": {"type": ["string", "null"]},
        })
    shape["required"] = list(shape["properties"])
    request = Request(
        endpoint,
        data=json.dumps({
            "model": model,
            "messages": messages,
            "format": shape,
            "think": False,
            "stream": False,
            "options": {
                "temperature": 0,
                "num_ctx": 16384,
                "num_predict": 1200,
            },
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=300) as response:
        result = json.load(response)
    content = result.get("message", {}).get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Ollama returned no JSON answer")
    return json.loads(content)


def main():
    try:
        messages = json.load(sys.stdin)["messages"]
        print(json.dumps(review(messages, os.environ.get("WEAVE_REVIEW_MODEL", "qwen3.5:9b"))))
    except (KeyError, ValueError, HTTPError, URLError) as error:
        raise SystemExit(f"Local Ollama review failed: {error}") from error


if __name__ == "__main__":
    main()
