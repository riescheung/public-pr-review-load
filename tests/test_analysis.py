import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_report import cluster_key, periods, score_outcome
from weighted_pr import weighted_pr


def file(path, additions, deletions=0, change="MODIFIED"):
    return {
        "path": path, "additions": additions,
        "deletions": deletions, "changeType": change,
    }


def pr(number=1, title="fix(replay): prevent missing sessions", issue=None):
    return {
        "number": number, "title": title,
        "author": {"login": "engineer", "__typename": "User"},
        "bodyText": (
            "Problem: Users sometimes lose the replay session when opening "
            "the player. Changes: Keep the source identifier through navigation. "
            "How did you test: Regression test covers the affected route."
        ),
        "closingIssuesReferences": {
            "nodes": [{"number": issue, "title": "Replay issue", "url": "https://example.com"}]
            if issue else []
        },
    }


class AnalysisTests(unittest.TestCase):
    def test_seven_periods_cover_98_days_without_overlap(self):
        spans = periods()
        self.assertEqual(len(spans), 7)
        for left, right in zip(spans, spans[1:]):
            self.assertLess(left["end"], right["start"])

    def test_same_issue_groups_multiple_prs(self):
        self.assertEqual(cluster_key(pr(1, issue=42)), cluster_key(pr(2, issue=42)))
        self.assertNotEqual(cluster_key(pr(1, issue=42)), cluster_key(pr(2, issue=43)))

    def test_unrelated_fixes_in_area_do_not_group(self):
        first = pr(1, "fix(replay): keep missing session in list")
        second = pr(2, "fix(replay): keep scrubber selection after reload")
        self.assertNotEqual(cluster_key(first), cluster_key(second))

    def test_pr_only_description_does_not_prove_an_outcome(self):
        value, confidence, _ = score_outcome([pr()], None)
        self.assertEqual((value, confidence), (0, 0.5))

    def test_issue_supported_fix_gets_credit(self):
        value, confidence, _ = score_outcome([pr(issue=42)], None)
        self.assertEqual((value, confidence), (2, 0.75))

    def test_generated_files_are_not_review_load(self):
        self.assertEqual(weighted_pr([file("package-lock.json", 3000)], "chore: deps"), 0)

    def test_small_fix_has_low_review_load(self):
        self.assertEqual(weighted_pr([file("utils.py", 10, 10)], "fix: bug"), 1)

    def test_config_only_work_is_not_dismissed(self):
        files = [
            file("terraform/network.tf", 90),
            file("terraform/roles.tf", 60),
            file("helm/values.yaml", 70),
            file("config/app_settings.json", 120),
        ]
        self.assertEqual(weighted_pr(files, "fix: config"), 3)

    def test_nested_reverts_restore_review_load(self):
        files = [file("feature.py", 150)]
        self.assertEqual(weighted_pr(files, 'Revert "Add feature"'), 0)
        self.assertGreater(weighted_pr(files, 'Revert "Revert Add feature"'), 0)

    def test_every_interval_can_reconcile_to_the_visible_outcomes(self):
        report = json.loads(
            (Path(__file__).resolve().parents[1] / "data/report.json").read_text()
        )
        for person in report["people"]:
            for cell in person["periods"]:
                self.assertEqual(len(cell["examples"]), cell["outcomes"])
                self.assertAlmostEqual(
                    sum(item["credited_points"] for item in cell["examples"]),
                    cell["score"],
                    delta=0.051,
                )
                for item in cell["examples"]:
                    self.assertEqual(
                        item["credited_points"],
                        round(item["points"] / len(item["owners"]), 3),
                    )

    def test_period_prs_reconcile_to_review_load(self):
        report = json.loads(
            (Path(__file__).resolve().parents[1] / "data/report.json").read_text()
        )
        for person in report["people"]:
            self.assertEqual(
                sum(len(cell["prs"]) for cell in person["periods"]),
                person["merged_prs"],
            )
            for cell in person["periods"]:
                if cell["wpr"] is not None:
                    self.assertEqual(
                        sum(pr["wpr"] for pr in cell["prs"]), cell["wpr"]
                    )
        dmarchuk = next(
            person for person in report["people"] if person["login"] == "dmarchuk"
        )
        first = dmarchuk["periods"][0]
        self.assertEqual((len(first["prs"]), first["wpr"], first["outcomes"]),
                         (19, 58, 0))

    def test_attention_signal_includes_audit_context(self):
        report = json.loads(
            (Path(__file__).resolve().parents[1] / "data/report.json").read_text()
        )
        cohort = report["manifest"]["attention_cohort"]
        self.assertEqual(cohort["as_of"], "2026-10-06")
        for person in report["people"]:
            if not person["attention"]:
                continue
            context = person["attention_context"]
            self.assertGreaterEqual(context["mature_wpr"], cohort["wpr_cutoff"])
            self.assertLessEqual(context["mature_score"], cohort["impact_cutoff"])
            self.assertGreaterEqual(person["merged_prs"], cohort["minimum_merges"])
            self.assertTrue(context["unscored_examples"])
            for example in context["unscored_examples"]:
                self.assertTrue(example["url"].startswith("https://github.com/"))


if __name__ == "__main__":
    unittest.main()
