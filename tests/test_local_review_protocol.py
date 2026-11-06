import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_review_protocol import review_with_feedback, validate_reply
from score_harness import decision_prompt, observation_prompt, one_pass_prompt
from test_benchmark import packet, review


class LocalReviewProtocolTests(unittest.TestCase):
    def test_validation_covers_combined_observation_and_group_decision(self):
        expected = review()
        combined = {**expected, **expected["observations"][0]}
        chunk = packet()["chunks"][0]
        for prompt, answer in (
            (one_pass_prompt(chunk), combined),
            (observation_prompt(chunk), expected["observations"][0]),
            (decision_prompt(expected["observations"]), expected),
        ):
            self.assertEqual(validate_reply([{"content": prompt}], answer), answer)

    def test_retry_uses_only_contract_feedback_not_a_target_label(self):
        expected = review()
        combined = {**expected, **expected["observations"][0]}
        broken = copy.deepcopy(combined)
        broken["observations"][0]["code_quote"] = "invented quote"
        replies = [json.dumps(broken), json.dumps(combined)]
        conversations = []

        def infer(messages):
            conversations.append(copy.deepcopy(messages))
            return replies[len(conversations) - 1]

        messages = [{"role": "user", "content": one_pass_prompt(packet()["chunks"][0])}]
        self.assertEqual(review_with_feedback(messages, infer), combined)
        self.assertEqual(len(messages), 1)
        self.assertIn("no target tier", conversations[1][-1]["content"])

    def test_invalid_replies_remain_errors_after_the_fixed_attempt_budget(self):
        infer = Mock(return_value="not JSON")
        with self.assertRaisesRegex(ValueError, "3 attempts"):
            review_with_feedback([{"content": "unused"}], infer)
        self.assertEqual(infer.call_count, 3)


if __name__ == "__main__":
    unittest.main()
