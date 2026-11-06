import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_data import digest
import contribution_estimates as estimates
from run_contribution_reviews import prepare, require_ac


def group(identifier="change", prs=None, hashes=None):
    prs = prs or [42]
    return {"id": identifier, "prs": prs,
            "diff_sha256": hashes or {str(pr): f"hash-{pr}" for pr in prs}}


def report():
    return {"periods": [{}, {}], "people": [{
        "login": "alice", "periods": [
            {"prs": [{"number": 42}], "score": 9000},
            {"prs": [{"number": 43}], "score": 9000},
        ],
    }]}


def record(g, score=2, status="ok"):
    return {"prs": sorted(g["prs"]), "tier": score, "status": status}


class ContributionTests(unittest.TestCase):
    def test_mean_uses_scored_groups_only_and_never_legacy_points(self):
        catalog = [group(), group("pending", [43])]
        people, total = estimates.aggregate(report(), catalog, {"change": record(catalog[0])},
                                           {"cases": []})
        self.assertEqual(total["mean_tier"], 2)
        self.assertEqual((total["scored"], total["groups"], total["pending"]), (1, 2, 1))
        self.assertIsNone(people["alice"]["periods"][1]["mean_tier"])

    def test_split_prs_count_once_in_the_latest_author_interval(self):
        g = group(prs=[42, 43])
        people, total = estimates.aggregate(report(), [g], {"change": record(g)}, {"cases": []})
        self.assertEqual(people["alice"]["periods"][0]["groups"], 0)
        self.assertEqual(people["alice"]["periods"][1]["scored"], 1)
        self.assertEqual(total["groups"], 1)
        self.assertEqual(people["alice"]["total"]["mean_tier"], 2)

    def test_abstentions_failures_and_reserved_work_never_become_zero(self):
        catalog = [group(), group("other", [43])]
        for status in ("abstained", "error", "deferred"):
            _, total = estimates.aggregate(report(), catalog,
                {"change": record(catalog[0], None, status)}, {"cases": []})
            self.assertIsNone(total["mean_tier"])
            self.assertEqual(total["scored"], 0)
        _, total = estimates.aggregate(report(), catalog, {},
            {"cases": [{"group": catalog[0], "split": "test"}]})
        self.assertEqual(total["reserved"], 1)
        self.assertIsNone(total["mean_tier"])

    def test_reserved_family_pr_and_patch_are_blocked(self):
        reserved = group()
        benchmark = {"cases": [{"group": reserved, "split": "test"}]}
        aliases = [group("change", [99]), group("other", [42]),
                   group("other", [99], {"99": "hash-42"})]
        for alias in aliases:
            self.assertTrue(estimates.reserved(alias, benchmark))
        with self.assertRaisesRegex(ValueError, "Reserved test"):
            estimates.aggregate(report(), [reserved], {"change": record(reserved)}, benchmark)

    def test_duplicate_group_or_pr_and_foreign_review_fail_closed(self):
        g = group()
        for catalog in ([g, g], [g, group("other")]):
            with self.assertRaisesRegex(ValueError, "duplicate"):
                estimates.aggregate(report(), catalog, {}, {"cases": []})
        for bad in (record(group(prs=[99])), record(g, True)):
            with self.assertRaisesRegex(ValueError, "complete group"):
                estimates.aggregate(report(), [g], {"change": bad}, {"cases": []})

    def test_pr_missing_from_catalog_is_visible_in_coverage(self):
        _, total = estimates.aggregate(report(), [group()], {}, {"cases": []})
        self.assertEqual(total["unmapped_prs"], 1)
        self.assertIsNone(total["mean_tier"])

    def test_shared_group_is_counted_once_globally_and_is_not_split_into_points(self):
        snapshot = report()
        snapshot["people"].append({"login": "bob", "periods": [{"prs": []}, {"prs": [{"number": 44}]}]})
        g = group(prs=[42, 44])
        people, total = estimates.aggregate(snapshot, [g], {"change": record(g)}, {"cases": []})
        self.assertEqual(total["groups"], 1)
        self.assertEqual(people["alice"]["total"]["mean_tier"], 2)
        self.assertEqual(people["bob"]["total"]["mean_tier"], 2)

    def test_later_failed_model_does_not_fall_back_to_an_earlier_good_answer(self):
        g = group()
        manifest = {"cases": [{"id": "case", "group": g, "split": "development",
                                "packet_sha256": "packet"}]}
        replies = [
            {"case": {"status": "ok", "review": {"score": 2, "grouping_issue": False}}},
            {"case": {"status": "error"}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            for run in ("base", "trained"):
                root = Path(directory) / "runs" / run
                root.mkdir(parents=True)
                (root / "spec.json").write_text(json.dumps({"model": {"name": "qwen"}}))
            with patch.object(estimates, "BENCHMARK", Path(directory)), \
                    patch.object(estimates, "predictions", side_effect=replies):
                rows, _ = estimates.collect_reviews(manifest, ["base", "trained"], [g])
        self.assertEqual(rows["change"]["run"], "trained")
        self.assertIsNone(rows["change"]["tier"])
        self.assertEqual(rows["change"]["status"], "error")

    def test_publication_manifest_refuses_changed_snapshot_and_reserved_cases(self):
        g = group()
        case = {"id": "E" + digest(g)[:16], "group": g, "source": "full",
                "index": 1, "split": "publication"}
        benchmark = {"sha256": "benchmark", "cases": []}
        manifest = {"benchmark_sha256": "benchmark", "catalog_sha256": "catalog",
                    "report_sha256": "report", "cases": [case]}
        estimates.validate_publication(manifest, benchmark, [g], "catalog", "report")
        with self.assertRaisesRegex(ValueError, "Snapshot"):
            estimates.validate_publication(manifest, benchmark, [g], "changed", "report")
        held_out = {**benchmark, "cases": [{"group": g, "split": "test"}]}
        with self.assertRaisesRegex(ValueError, "reserved"):
            estimates.validate_publication(manifest, held_out, [g], "catalog", "report")
        duplicate = copy.deepcopy(manifest)
        duplicate["cases"].append(case)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            estimates.validate_publication(duplicate, benchmark, [g], "catalog", "report")

    def test_preparation_excludes_reserved_cases_before_making_any_packet(self):
        g = group()
        with patch("run_contribution_reviews.make_packet") as packet:
            manifest = prepare([g], {"sha256": "benchmark", "cases": [
                {"group": g, "split": "test"}]}, "catalog", "report")
        packet.assert_not_called()
        self.assertEqual(manifest["cases"], [])

    def test_gpu_worker_requires_ac_power_on_macos(self):
        with patch("run_contribution_reviews.sys.platform", "darwin"), \
                patch("run_contribution_reviews.subprocess.run") as power:
            power.return_value.stdout = "Now drawing from 'Battery Power' 5%"
            with self.assertRaisesRegex(RuntimeError, "Connect AC"):
                require_ac()
            power.return_value.stdout = "Now drawing from 'AC Power'"
            require_ac()

    def test_seed_export_cannot_silently_discard_completed_publication_reviews(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "publication.json"
            original = json.dumps({"reviews": {"change": {"source": "publication"}}})
            output.write_text(original)
            with self.assertRaisesRegex(ValueError, "Preserve expanded coverage"):
                estimates.publish({}, [], output)
            self.assertEqual(output.read_text(), original)

    def test_multiple_publication_runs_preserve_prior_coverage_and_use_latest_review(self):
        first, second = group(), group("other", [43])
        manifest = {"cases": [{
            "id": str(i), "group": g, "split": "publication", "packet_sha256": "packet",
        } for i, g in enumerate((first, second))]}
        replies = [
            {str(i): {"status": "ok", "review": {"score": 1, "grouping_issue": False}}
             for i in (0, 1)},
            {"0": {"status": "ok", "review": {"score": 2, "grouping_issue": False}}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            for run in ("previous", "current"):
                root = Path(directory) / "runs" / run
                root.mkdir(parents=True)
                (root / "spec.json").write_text(json.dumps({"model": {"name": "qwen"}}))
            with patch.object(estimates, "BENCHMARK", Path(directory)), \
                    patch.object(estimates, "predictions", side_effect=replies):
                rows, models = estimates.collect_reviews({"cases": []}, [], [first, second],
                    manifest, ["previous", "current"])
        self.assertEqual((rows["change"]["tier"], rows["change"]["run"]), (2, "current"))
        self.assertEqual((rows["other"]["tier"], rows["other"]["run"]), (1, "previous"))
        self.assertEqual(set(models), {"previous", "current"})


if __name__ == "__main__":
    unittest.main()
