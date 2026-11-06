from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from experimental_distillation import assert_disjoint, assert_unreserved, teacher_review
from prepare_lora_data import approved_examples, review_examples
from test_benchmark import packet


class ExperimentalDistillationTests(unittest.TestCase):
    def test_ai_proposal_never_becomes_an_approved_human_label(self):
        label = {"score": 2, "reason": "A bounded change to returned query behavior.",
                 "hunk": "P1.F1.H1", "code_quote": "return safe"}
        proposed = teacher_review(label, packet())
        case = {"id": "teacher", "group": {"prs": [42], "diff_sha256": {"42": "diff"}}}
        rows = review_examples(case, packet(), proposed)
        self.assertEqual(rows[0]["source"], "historical_ai_proposal_not_human_gold")
        with self.assertRaisesRegex(ValueError, "human"):
            approved_examples(case, packet(), proposed)

    def test_reserved_development_test_and_calibration_are_all_excluded(self):
        for split in ("development", "test", "calibration"):
            manifest = {"cases": [{"split": split, "group": {
                "id": "reserved", "prs": [42, 43], "diff_sha256": {"42": "hash"},
            }}]}
            for group in (
                {"id": "other", "prs": [42], "diff_sha256": {}},
                {"id": "other", "prs": [44], "diff_sha256": {"44": "hash"}},
                {"id": "reserved", "prs": [44], "diff_sha256": {}},
            ):
                with self.assertRaisesRegex(ValueError, "reserved"):
                    assert_unreserved(group, manifest)

    def test_duplicate_teacher_groups_cannot_cross_train_and_validation(self):
        group = {"id": "family", "prs": [42], "diff_sha256": {"42": "patch"}}
        with self.assertRaisesRegex(ValueError, "overlap"):
            assert_disjoint([group, group])
        assert_disjoint([group, {"id": "other", "prs": [43], "diff_sha256": {"43": "other"}}])


if __name__ == "__main__":
    unittest.main()
