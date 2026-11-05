import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_report import cluster_key, evidence_source, periods, score_group
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

    def test_pr_only_description_is_not_a_linked_group(self):
        self.assertIsNone(evidence_source([pr()], None))

    def test_issue_and_release_are_sources_not_impact_points(self):
        self.assertEqual(evidence_source([pr(issue=42)], None), "Closing issue")
        self.assertEqual(evidence_source([pr()], {"tag": "v1"}), "Release note")

    def test_linked_and_unlinked_changes_get_the_same_estimate(self):
        plain = pr()
        linked = pr(issue=42)
        files = {1: [file("replay.py", 20)]}
        self.assertEqual(
            score_group([plain], files, {1: 2})[:3],
            score_group([linked], files, {1: 2})[:3],
        )
        self.assertEqual(score_group([plain], files, {1: 2})[:3], (2, 0, 2))

    def test_scope_proxy_is_bounded_and_pr_splitting_does_not_stack_it(self):
        changes = [pr(1, title="feat: add a useful capability", issue=42),
                   pr(2, title="feat: add a useful capability", issue=42)]
        files = {1: [file("feature.py", 100)],
                 2: [file("feature.py", 100)]}
        self.assertEqual(score_group(changes, files, {1: 8, 2: 9})[:3],
                         (2, 1, 9))
        self.assertEqual(score_group(changes, files, {1: 3, 2: 6})[:3],
                         (2, 0.5, 6))

    def test_high_risk_title_still_needs_review_not_link_bonus(self):
        risk = pr(title="fix: prevent data loss on ingest")
        self.assertEqual(
            score_group([risk], {1: [file("ingest.py", 400)]}, {1: 10})[:3],
            (3, 1, 10),
        )

    def test_docs_are_not_zero_just_because_wpr_is_zero(self):
        self.assertEqual(
            score_group([pr(title="docs: explain install")],
                        {1: [file("docs/setup.md", 20)]}, {1: 0})[:3],
            (1, 0, 0),
        )

    def test_generated_only_and_reverts_are_not_automatic_credit(self):
        self.assertEqual(score_group(
            [pr()], {1: [file("package-lock.json", 3000)]}, {1: 0}
        )[0], 0)
        self.assertEqual(score_group(
            [pr(title='Revert "Add feature"', issue=42)],
            {1: [file("feature.py", 100)]}, {1: 0}
        )[0], 0)

    def test_pr_claim_does_not_create_an_independent_reference(self):
        claimed = pr(2)
        claimed["bodyText"] = "Performance improved from 600 s to 180 s."
        self.assertIsNone(evidence_source([pr(), claimed], None))

    def test_revert_is_not_a_new_linked_group(self):
        self.assertIsNone(evidence_source(
            [pr(title='Revert "Add feature"', issue=42)], None
        ))

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

    def test_every_interval_reconciles_to_scored_groups(self):
        report = json.loads(
            (Path(__file__).resolve().parents[1] / "data/report.json").read_text()
        )
        self.assertEqual(
            [p["score"] for p in report["people"]],
            sorted((p["score"] for p in report["people"]), reverse=True),
        )
        self.assertNotIn("attention_cohort", report["manifest"])
        for person in report["people"]:
            self.assertNotIn("attention", person)
            self.assertEqual(
                sum(cell["groups"] for cell in person["periods"]),
                person["group_count"],
            )
            self.assertEqual(
                sum(cell["linked_count"] for cell in person["periods"]),
                person["linked_count"],
            )
            for cell in person["periods"]:
                self.assertEqual(len(cell["examples"]), cell["groups"])
                self.assertAlmostEqual(
                    sum(item["credited_points"] for item in cell["examples"]),
                    cell["score"],
                    delta=0.051,
                )
                for item in cell["examples"]:
                    self.assertIn(person["login"], item["owners"])
                    self.assertEqual(item["points"],
                                     item["base"] + item["scope_bonus"])
                    self.assertEqual(
                        item["credited_points"],
                        round(item["points"] / len(item["owners"]), 3),
                    )
                    self.assertEqual(
                        sum(link["type"] == "PR" for link in item["evidence"]),
                        item["pr_count"],
                    )
                    self.assertIn(item["source"], (
                        "Closing issue", "Release note", "PR only"
                    ))

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
        self.assertEqual((len(first["prs"]), first["wpr"], first["linked_count"]),
                         (19, 58, 0))
        self.assertGreater(first["score"], 0)

    def test_unlinked_work_remains_inspectable_without_negative_label(self):
        report = json.loads(
            (Path(__file__).resolve().parents[1] / "data/report.json").read_text()
        )
        person = next(p for p in report["people"] if p["login"] == "dmarchuk")
        cell = person["periods"][0]
        self.assertEqual(cell["linked_count"], 0)
        self.assertGreater(cell["wpr"], 0)
        self.assertTrue(cell["prs"])


if __name__ == "__main__":
    unittest.main()
