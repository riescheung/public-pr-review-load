"""Constrain review syntax and literal choices, never semantic correctness."""

from local_review_protocol import review_inputs


TEXT = {"type": "string", "minLength": 1}


def closed_object(properties):
    return {
        "type": "object", "properties": properties,
        "required": list(properties), "additionalProperties": False,
    }


def review_schema(messages):
    mode, allowed = review_inputs(messages)
    observation_fields = {}
    if mode != "decision":
        choices = []
        for hunk, lines in allowed.items():
            quotes = sorted({line for line in lines if len(line.strip()) >= 8})
            if quotes:
                choices.append(closed_object({
                    "hunk": {"const": hunk},
                    "code_quote": {"enum": quotes},
                    "behavior": TEXT, "posthog_connection": TEXT,
                }))
        if not choices:
            raise ValueError("No citable changed lines in this chunk")
        observations = {
            "type": "array", "items": {"anyOf": choices}, "minItems": 1,
        }
        observations["maxItems"] = 3
        observation_fields = {"observations": observations, "limitations": TEXT}
        if mode == "observation":
            return closed_object(observation_fields)

    alternatives = []
    for abstain in (False, True):
        alternatives.append(closed_object({
            **observation_fields,
            "score": {"type": "null"} if abstain else {"enum": [1, 2, 3]},
            "reason": TEXT,
            "posthog_relevance": {"type": "string"} if abstain else TEXT,
            "confidence": {"const": "none"} if abstain else {"enum": ["low", "medium", "high"]},
            "evidence": ({"type": "array", "maxItems": 0} if abstain else {
                "type": "array", "items": {"enum": sorted(allowed)}, "minItems": 1,
            }),
            "uncertainty": TEXT,
            "metadata_dependency": {"const": False},
            "grouping_issue": {"type": "boolean"} if abstain else {"const": False},
            "abstention_reason": TEXT if abstain else {"type": "null"},
        }))
    return {"anyOf": alternatives}
