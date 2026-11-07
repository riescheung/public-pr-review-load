from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mlx_prose_penalty import ProseRepetitionPenalty, descriptive_field


class Tokens:
    def __init__(self, values):
        self.values = values
        self.size = len(values)

    def __getitem__(self, item):
        return Tokens(self.values[item])

    def tolist(self):
        return self.values


class Tokenizer:
    def decode(self, identifiers, **kwargs):
        return "".join(chr(identifier) for identifier in identifiers)


class ProsePenaltyTests(unittest.TestCase):
    def test_recognises_nested_and_escaped_prose_strings(self):
        self.assertEqual(
            [descriptive_field(prefix) for prefix in (
                '{"observations":[{"behavior":"Repeated hunk IDs',
                '{"reason":"A \\"quoted\\" description',
            )],
            ["behavior", "reason"],
        )

    def test_never_targets_tiers_citations_or_categorical_fields(self):
        self.assertEqual(
            [descriptive_field(prefix) for prefix in (
                '{"score":', '{"score":1', '{"code_quote":"literal code',
                '{"hunk":"P1.F1.H1', '{"evidence":["P1.F1.H1',
                '{"confidence":"hi', '{"metadata_dependency":false}',
            )],
            [None] * 7,
        )

    def test_penalty_stops_before_numeric_tier_selection(self):
        penalty = ProseRepetitionPenalty(Tokenizer(), lambda tokens, logits: "penalised")
        prefix = '{"reason":"repeated explanation'
        values = [
            penalty(Tokens([999]), "unchanged"),
            penalty(Tokens([999, *map(ord, prefix)]), "unchanged"),
            penalty(Tokens([999, *map(ord, prefix + '","score":')]), "unchanged"),
        ]
        self.assertEqual(values, ["unchanged", "penalised", "unchanged"])
