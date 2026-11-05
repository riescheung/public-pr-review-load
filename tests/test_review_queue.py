import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import review_queue
from score_harness import REPOSITORY, VERSION, review_instructions


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        self.answers = self.root / "calibration.json"
        self.group = {
            "prs": [123], "diff_sha256": {"123": "a" * 64}, "wpr": 7,
        }
        self.instructions_hash = review_instructions()[1]

    def add_review(self, reviewer, score, grouping_issue=False, digest=None):
        directory = self.runs / "01"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{reviewer}.json").write_text(json.dumps({
            "version": VERSION, "repository": REPOSITORY, "index": 1,
            "reviewer_id": reviewer, "model_id": "mock-model",
            "diff_sha256": digest or self.group["diff_sha256"],
            "instructions_sha256": self.instructions_hash,
            "review": {"score": score, "grouping_issue": grouping_issue,
                       "reason": "Observed behavior in the changed code"},
        }))

    def case(self, calibrations=()):
        return review_queue.review_case(
            1, self.group, self.runs, self.instructions_hash, calibrations
        )

    def test_disagreement_and_high_wpr_low_tier_are_review_flags(self):
        self.add_review("one", 1)
        self.add_review("two", 2)
        case = self.case()
        self.assertEqual(case["flags"], ["high_wpr_low_tier", "reviewer_disagreement"])
        self.assertEqual(case["status"], "pending")
        self.assertEqual(review_queue.build_queue([self.group], self.runs, []), [case])

    def test_low_wpr_high_tier_is_a_flag_not_an_automatic_score_change(self):
        self.group["wpr"] = 2
        self.add_review("one", 3)
        self.add_review("two", 3)
        case = self.case()
        self.assertEqual(case["flags"], ["low_wpr_high_tier"])
        self.assertEqual([review["score"] for review in case["reviews"]], [3, 3])

    def test_wpr_thresholds_do_not_flag_middle_tiers(self):
        self.group["wpr"] = 7
        self.add_review("one", 2)
        self.add_review("two", 2)
        self.assertEqual(self.case()["flags"], [])
        self.group["wpr"] = 3
        self.add_review("one", 3)
        self.add_review("two", 3)
        self.assertEqual(self.case()["flags"], [])

    def test_null_and_grouping_issue_flag_even_when_reviewers_agree(self):
        self.add_review("one", None, grouping_issue=True)
        self.add_review("two", None, grouping_issue=True)
        self.assertEqual(self.case()["flags"], ["grouping_issue", "unassessed"])

    def test_human_answer_is_append_only_and_calibrates_new_reviewers(self):
        self.add_review("one", 1)
        self.add_review("two", 2)
        case = self.case()
        record = review_queue.record_answer(
            case, 2, "Code demonstrates a bounded improvement", "posthog-expert",
            self.answers,
        )
        self.assertEqual(record["human_score"], 2)
        self.assertEqual(self.case(json.loads(self.answers.read_text()))["status"], "calibrated")
        self.add_review("three", 3)
        compared = self.case(json.loads(self.answers.read_text()))
        self.assertEqual(compared["status"], "calibrated")
        self.assertIn("human_calibration_mismatch", compared["flags"])
        review_queue.record_answer(
            self.case(), 3, "Broader safeguard supported by the code", "posthog-expert",
            self.answers,
        )
        self.assertEqual(len(json.loads(self.answers.read_text())), 2)
        self.group["diff_sha256"] = {"123": "b" * 64}
        with self.assertRaisesRegex(ValueError, "Stale or invalid"):
            self.case(json.loads(self.answers.read_text()))

    def test_stale_run_is_rejected_and_unflagged_requires_manual_review(self):
        self.add_review("one", 1, digest={"123": "b" * 64})
        with self.assertRaisesRegex(ValueError, "Stale or invalid"):
            self.case()
        (self.runs / "01" / "one.json").unlink()
        with self.assertRaisesRegex(ValueError, "No review flag"):
            review_queue.record_answer(
                self.case(), 2, "Human opinion without a flag", "expert", self.answers
            )
        self.assertIsNone(review_queue.record_answer(
            self.case(), None, "Insufficient surrounding code to decide", "expert",
            self.answers, manual=True,
        )["human_score"])


if __name__ == "__main__":
    unittest.main()
