import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_review_catalog
import build_review_status
from review_contract import REPOSITORY, VERSION, review_instructions


class ReviewStatusTests(unittest.TestCase):
    def test_status_does_not_confuse_expert_calibration_with_model_scores(self):
        selection = json.loads((ROOT / "data" / "ai_pilot" / "selection.json").read_text())
        calibrations = json.loads((ROOT / "data" / "ai_pilot" / "calibration.json").read_text())
        report = {"manifest": {"scored_groups": 17220}}
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            status = build_review_status.build_status(report, selection, calibrations, run_root)
            self.assertEqual(status["ai_reviewed_groups"], 0)
            self.assertEqual(status["awaiting_ai_review"], 17220)
            self.assertEqual(
                {tuple(item["prs"]): item["tier"] for item in status["calibrations"]},
                {(103592,): 1, (116718,): 2, (117287,): 3},
            )

    def test_stale_human_hash_does_not_publish_as_current(self):
        selection = json.loads((ROOT / "data" / "ai_pilot" / "selection.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            status = build_review_status.build_status(
                {"manifest": {"scored_groups": 17220}}, selection,
                [{"index": 2, "diff_sha256": {"99617": "stale"},
                  "instructions_sha256": review_instructions()[1],
                  "human_score": 3, "reason": "stale", "reviewer": "expert"}],
                Path(temp),
            )
        self.assertEqual(status["calibrations"], [])

    def test_full_catalog_matches_report_and_excludes_noneligible_groups(self):
        groups = build_review_catalog.select_all()
        report = json.loads((ROOT / "data" / "report.json").read_text())
        self.assertEqual(len(groups), report["manifest"]["scored_groups"])
        self.assertEqual(len({group["id"] for group in groups}), len(groups))


if __name__ == "__main__":
    unittest.main()
