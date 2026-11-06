import copy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None

from mlx_review_schema import review_schema
from score_harness import decision_prompt, observation_prompt, one_pass_prompt
from test_benchmark import packet, review


@unittest.skipIf(Draft202012Validator is None, "Requires optional JSON schema test dependency")
class ReviewSchemaTests(unittest.TestCase):
    def validator(self, prompt):
        schema = review_schema([{"role": "user", "content": prompt}])
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)

    def test_all_review_stages_keep_scoring_and_abstention_available(self):
        for score in (1, 2, 3, None):
            expected = review(score)
            combined = {**expected, **expected["observations"][0]}
            decision = {key: value for key, value in expected.items() if key != "observations"}
            for prompt, answer in (
                (one_pass_prompt(packet()["chunks"][0]), combined),
                (observation_prompt(packet()["chunks"][0]), expected["observations"][0]),
                (decision_prompt(expected["observations"]), decision),
            ):
                with self.subTest(score=score, prompt=prompt[:20]):
                    self.validator(prompt).validate(answer)

    def test_quote_choices_are_paired_with_their_hunk_not_just_global_enums(self):
        chunk = copy.deepcopy(packet()["chunks"][0])
        chunk["text"] += '\n<hunk id=P1.F2.H1 path="b.py">\n+return other\n</hunk>'
        validator = self.validator(one_pass_prompt(chunk))
        expected = review()
        answer = {**expected, **expected["observations"][0]}
        validator.validate(answer)
        answer["observations"][0]["code_quote"] = "return other"
        self.assertFalse(validator.is_valid(answer))
        answer["observations"][0]["hunk"] = "P1.F2.H1"
        validator.validate(answer)
        answer["observations"][0]["code_quote"] = "a fabricated changed line"
        self.assertFalse(validator.is_valid(answer))

    def test_invalid_confidence_evidence_and_grouping_cannot_be_forced_into_scores(self):
        validator = self.validator(one_pass_prompt(packet()["chunks"][0]))
        expected = review()
        answer = {**expected, **expected["observations"][0]}
        for change in (
            {"confidence": "none"}, {"evidence": []},
            {"evidence": ["P99.F1.H1"]}, {"grouping_issue": True},
            {"metadata_dependency": True}, {"score": True},
            {"abstention_reason": "Missing context"},
        ):
            with self.subTest(change=change):
                self.assertFalse(validator.is_valid({**answer, **change}))
        abstention = {**review(None), **expected["observations"][0]}
        validator.validate({**abstention, "grouping_issue": True})
        for change in ({"confidence": "high"}, {"evidence": ["P1.F1.H1"]},
                       {"abstention_reason": ""}):
            self.assertFalse(validator.is_valid({**abstention, **change}))

    def test_decision_cannot_introduce_unobserved_hunk_ids(self):
        expected = review()
        answer = {key: value for key, value in expected.items() if key != "observations"}
        validator = self.validator(decision_prompt(expected["observations"]))
        self.assertFalse(validator.is_valid({**answer, "evidence": ["P1.F2.H1"]}))

    def test_no_citable_line_remains_an_error_not_an_invented_observation(self):
        chunk = {"text": '<hunk id=P1.F1.H1 path="a.py">\n+x\n</hunk>'}
        with self.assertRaisesRegex(ValueError, "citable"):
            review_schema([{"content": observation_prompt(chunk)}])


if __name__ == "__main__":
    unittest.main()
