"""Discourage descriptive repetition without biasing tiers or literal citations."""

import json
import re


DESCRIPTIVE_FIELDS = {
    "behavior", "posthog_connection", "limitations", "reason",
    "posthog_relevance", "uncertainty", "abstention_reason",
}


def descriptive_field(text):
    try:
        json.loads(text)
    except json.JSONDecodeError as error:
        if error.msg.startswith("Unterminated string"):
            match = re.search(r'"([^"]+)"\s*:\s*$', text[:error.pos])
            if match and match.group(1) in DESCRIPTIVE_FIELDS:
                return match.group(1)
    return None


class ProseRepetitionPenalty:
    def __init__(self, tokenizer, penalty):
        self.tokenizer = tokenizer
        self.penalty = penalty
        self.offset = None
        self.generated = []

    def __call__(self, tokens, logits):
        if self.offset is not None:
            self.generated.extend(tokens[self.offset:].tolist())
        self.offset = tokens.size
        text = self.tokenizer.decode(self.generated, skip_special_tokens=True)
        if descriptive_field(text) is not None:
            return self.penalty(tokens, logits)
        return logits
