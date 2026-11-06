import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_data import digest, seal
import contribution_estimates as estimates
from run_contribution_reviews import prepare, require_safe_power, retained_publication_runs


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
    def test_snapshot_hash_and_data_come_from_one_file_version(self):
        first = b'[{"id":"first"}]'
        path = Mock()
        path.read_bytes.side_effect = [first, b'[{"id":"later"}]']
        data, identity = estimates.json_snapshot(path)
        self.assertEqual((data, identity, path.read_bytes.call_count),
                         ([{"id": "first"}], hashlib.sha256(first).hexdigest(), 1))

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
        estimates.validate_publication(manifest, benchmark, [g], "changed-cache", "report")
        with self.assertRaisesRegex(ValueError, "Snapshot"):
            estimates.validate_publication(manifest, benchmark, [g], "catalog", "changed-report")
        changed = copy.deepcopy(g)
        changed["diff_sha256"]["42"] = "changed-reviewed-patch"
        with self.assertRaisesRegex(ValueError, "foreign"):
            estimates.validate_publication(manifest, benchmark, [changed], "catalog", "report")
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

    def test_gpu_worker_preserves_a_battery_floor_on_macos(self):
        with patch("run_contribution_reviews.sys.platform", "darwin"), \
                patch("run_contribution_reviews.subprocess.run") as power:
            power.return_value.stdout = "Now drawing from 'Battery Power' 5%"
            with self.assertRaisesRegex(RuntimeError, "safety floor"):
                require_safe_power()
            power.return_value.stdout = "Now drawing from 'AC Power'"
            require_safe_power()

    def test_brief_ac_status_changes_above_the_battery_floor_do_not_cancel_jobs(self):
        with patch("run_contribution_reviews.sys.platform", "darwin"), \
                patch("run_contribution_reviews.subprocess.run") as power:
            power.return_value.stdout = "Now drawing from 'Battery Power' 44%"
            require_safe_power()
            power.return_value.stdout = "Now drawing from 'Battery Power' 20%"
            with self.assertRaisesRegex(RuntimeError, "20%"):
                require_safe_power()

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

    def test_prior_manifest_survives_cache_growth_without_rebinding_predictions(self):
        first, second = group(), group("other", [43])
        cases = [{
            "id": "E" + digest(g)[:16], "group": g, "source": "full",
            "index": i, "split": "publication", "packet_sha256": "packet",
        } for i, g in enumerate((first, second), 1)]
        original = seal({"benchmark_sha256": "benchmark", "report_sha256": "report",
                         "catalog_sha256": "old-cache", "cases": cases[:1]})
        expanded = seal({**{k: v for k, v in original.items() if k != "sha256"},
                         "catalog_sha256": "expanded-cache", "cases": cases})
        benchmark = {"sha256": "benchmark", "cases": []}
        seen = []

        def read_predictions(manifest, run):
            seen.append((manifest["sha256"], run))
            case = manifest["cases"][-1]
            return {case["id"]: {"status": "ok", "review": {
                "score": 2, "grouping_issue": False,
            }}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "manifests"
            archive.mkdir()
            (archive / f"{original['sha256']}.json").write_text(json.dumps(original))
            for run, manifest in (("old", original), ("new", expanded)):
                folder = root / "runs" / run
                folder.mkdir(parents=True)
                (folder / "spec.json").write_text(json.dumps({
                    "model": {"name": "qwen"}, "manifest_sha256": manifest["sha256"],
                }))
            with patch.object(estimates, "BENCHMARK", root), \
                    patch.object(estimates, "PUBLICATION_MANIFESTS", archive, create=True), \
                    patch.object(estimates, "predictions", side_effect=read_predictions):
                rows, _ = estimates.collect_reviews(benchmark, [], [first, second],
                                                    expanded, ["old", "new"])
        self.assertEqual(seen, [(original["sha256"], "old"), (expanded["sha256"], "new")])
        self.assertEqual(set(rows), {"change", "other"})

    def test_resume_keeps_run_priority_instead_of_the_order_of_published_groups(self):
        publication = {
            "models": {"old": {}, "middle": {}, "new": {}, "benchmark": {}},
            "reviews": {
                "first-group": {"run": "new", "source": "publication"},
                "second-group": {"run": "old", "source": "publication"},
                "third-group": {"run": "middle", "source": "publication"},
                "benchmark-group": {"run": "benchmark", "source": "benchmark"},
            },
        }
        self.assertEqual(retained_publication_runs(publication), ["old", "middle", "new"])


if __name__ == "__main__":
    unittest.main()
