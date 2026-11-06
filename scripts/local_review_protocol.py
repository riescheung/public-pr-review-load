"""Validate raw local-model replies without inventing evidence or labels."""

import json
import re

from score_harness import validate_decision, validate_observations


def validate_reply(messages, reply):
    prompt = messages[-1]["content"]
    observation = prompt.startswith("Inspect every hunk in this chunk")
    combined = prompt.startswith("Review this one complete code-diff chunk")
    if observation or combined:
        allowed = {
            identifier: [
                line[1:] for line in text.splitlines()
                if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
            ]
            for identifier, text in re.findall(
                r"<hunk id=([^\s]+) path=[^>]+>\n(.*?)</hunk>", prompt, flags=re.DOTALL,
            )
        }
        validate_observations(reply, allowed)
        observed = {item["hunk"] for item in reply["observations"]}
    else:
        observations = json.loads(prompt.split("Observations:\n", 1)[1])
        observed = {item["hunk"] for chunk in observations for item in chunk["observations"]}
    if not observation:
        validate_decision(reply, observed)
    return reply


def review_with_feedback(messages, infer, attempts=3):
    conversation = list(messages)
    for attempt in range(attempts):
        text = infer(conversation).strip()
        if text.startswith("```json\n") and text.endswith("```"):
            text = text[len("```json\n"):-3].strip()
        try:
            return validate_reply(messages, json.loads(text))
        except ValueError as error:
            if attempt + 1 == attempts:
                raise ValueError(f"Contract failed after {attempts} attempts: {error}") from error
            conversation.extend([
                {"role": "assistant", "content": text},
                {"role": "user", "content": (
                    f"Your response failed the fixed review contract: {error}. "
                    "Return a corrected complete JSON object using only the original code and "
                    "instructions. Copy complete literal changed lines and exact supplied hunk "
                    "IDs. Evidence must cite your observations. Do not invent missing evidence. "
                    "This feedback contains no target tier; abstain if evidence is insufficient."
                )},
            ])
    raise ValueError("At least one inference attempt is required")
