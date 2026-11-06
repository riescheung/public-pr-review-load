import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark_data as data
from benchmark_metrics import compare, metrics
import pr_benchmark as runner


def packet():
    return {
        "system": "Review code, not authors.", "instructions_sha256": "rubric",
        "diff_sha256": {"42": "diff"}, "abstention_reason": None,
        "chunks": [{
            "text": '<hunk id=P1.F1.H1 path="a.py">\n+return safe\n</hunk>',
            "hunks": ["P1.F1.H1"],
            "changed_lines": {"P1.F1.H1": ["return safe"]},
        }],
    }


def review(score=2):
    return {
        "score": score, "reason": "A bounded behavior change is visible.",
        "posthog_relevance": "Improves query correctness.",
        "confidence": "medium" if score is not None else "none",
        "evidence": ["P1.F1.H1"] if score is not None else [],
        "uncertainty": "No adoption evidence.", "metadata_dependency": False,
        "grouping_issue": False,
        "abstention_reason": "Insufficient surrounding context." if score is None else None,
        "observations": [{
            "observations": [{
                "hunk": "P1.F1.H1", "behavior": "Changes returned behavior.",
                "posthog_connection": "Query correctness.", "code_quote": "return safe",
            }],
            "limitations": "No caller context.",
        }],
    }


class BenchmarkTests(unittest.TestCase):
    def test_selection_is_deterministic_diverse_and_does_not_reuse_prs(self):
        candidates = [
            {"group": {"id": str(i), "prs": [i], "diff_sha256": {str(i): str(i)}},
             "stratum": ("large" if i % 2 else "single"), "source": "full", "index": i}
            for i in range(1, 21)
        ]
        candidates.append(copy.deepcopy(candidates[0]))
        first = data.select_cases(candidates, 10)
        self.assertEqual(first, data.select_cases(list(reversed(candidates)), 10))
        self.assertEqual(len({c["group"]["prs"][0] for c in first}), 10)
        self.assertEqual({c["stratum"] for c in first}, {"large", "single"})

    def test_no_label_or_metadata_in_human_packet(self):
        exported = data.blind_packet(packet())
        self.assertEqual(set(exported), {"system", "chunks", "abstention_reason"})
        self.assertNotIn("42", json.dumps(exported))

    def test_readable_blind_exports_include_assignment_ids_not_metadata(self):
        manifest = {"cases": [{"id": "opaque", "split": "development"}]}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(data, "case_packet", return_value=packet()):
            data.export_packets(manifest, Path(folder))
            root = Path(folder) / "packets"
            self.assertEqual(json.loads((root / "development.json").read_text()), ["opaque"])
            text = (root / "opaque.md").read_text()
            self.assertIn("return safe", text)
            self.assertNotIn('"42"', text)
            data.export_packets(manifest, Path(folder))

    def test_gold_requires_real_human_identity_and_valid_decision(self):
        answer = {"reviewer": "expert", "score": None,
                  "reason": "Insufficient context to distinguish tiers.", "review": review(None)}
        self.assertEqual(data.validate_label(answer, packet())["score"], None)
        for bad in ({**answer, "score": True}, {**answer, "reviewer": ""},
                    {**answer, "score": 3}):
            with self.assertRaises(ValueError):
                data.validate_label(bad, packet())

    def test_citations_and_every_chunk_are_validated(self):
        broken = review()
        broken["observations"][0]["observations"][0]["code_quote"] = "invented line"
        with self.assertRaises(ValueError):
            data.validate_review(broken, packet())
        large = packet()
        large["chunks"] *= 2
        with self.assertRaises(ValueError):
            data.validate_review(review(), large)
        longer = packet()
        longer["chunks"][0]["changed_lines"]["P1.F1.H1"] = ["return safe()"]
        with self.assertRaises(ValueError):
            data.validate_review(review(), longer)

    def test_immutable_artifacts_and_manifest_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            data.write_new(path, data.seal({"cases": [], "version": 1}))
            self.assertEqual(data.load_manifest(path)["cases"], [])
            with self.assertRaises(FileExistsError):
                data.write_new(path, {})
            edited = json.loads(path.read_text())
            edited["cases"] = ["changed"]
            path.write_text(json.dumps(edited))
            with self.assertRaises(ValueError):
                data.load_manifest(path)

    def test_errors_and_unlabelled_cases_cannot_inflate_accuracy(self):
        cases = [{"id": str(i)} for i in range(6)]
        gold = {"0": {"score": 1}, "1": {"score": 2}, "2": {"score": 3},
                "3": {"score": None}, "4": {"score": 2}}
        runs = {
            "0": {"status": "ok", "review": review(3)},
            "1": {"status": "ok", "review": review(2)},
            "2": {"status": "ok", "review": review(None)},
            "3": {"status": "preflight", "review": review(None)},
            "4": {"status": "error", "error": "timeout"},
            "5": {"status": "ok", "review": review(1)},
        }
        result = metrics(cases, runs, gold, {})
        self.assertEqual(result["labelled"], 5)
        self.assertEqual(result["unlabelled"], 1)
        self.assertEqual(result["model_exact_accuracy"], 0.25)
        self.assertEqual(result["selective_accuracy"], 0.5)
        self.assertEqual(result["tier3"]["false_positives"], 1)
        self.assertEqual(result["per_tier"]["2"]["recall"], 0.5)
        self.assertEqual(result["preflight_rejections"], 1)
        self.assertIsNone(result["semantic_evidence_accuracy"])

    def test_promotion_rejects_unpaired_or_tiny_comparisons(self):
        report = {
            "split": "test", "manifest_sha256": "frozen", "case_ids": ["a"],
            **metrics([{"id": "a"}], {"a": {"status": "ok", "review": review(2)}},
                      {"a": {"score": 2}}, {}),
        }
        self.assertFalse(compare(report, report)["eligible_for_human_approval"])
        experimental = compare(report, {**report, "experimental_ai_labels": True})
        self.assertTrue(any("distillation" in item for item in experimental["blockers"]))
        paired = {**report, "base_model_sha256": "base", "evaluation_protocol_sha256": "protocol"}
        mismatched = compare(paired, {**paired, "evaluation_protocol_sha256": "other"})
        self.assertTrue(any("evaluation_protocol" in item for item in mismatched["blockers"]))
        with self.assertRaisesRegex(ValueError, "paired"):
            compare(report, {**report, "case_ids": ["other"]})
        with self.assertRaisesRegex(ValueError, "test"):
            compare({**report, "split": "development"}, report)

    def test_frozen_test_contains_no_previous_teacher_or_pilot_prs(self):
        manifest = data.load_manifest()
        pilot = json.loads((data.PILOT / "selection.json").read_text())
        catalog = json.loads((data.FULL / "selection.json").read_text())
        teachers = json.loads((data.FULL / "teacher_labels.json").read_text())
        prior = [*pilot, *(catalog[label["index"] - 1] for label in teachers)]
        prs = {pr for group in prior for pr in group["prs"]}
        hashes = {h for group in prior for h in group["diff_sha256"].values()}
        for case in manifest["cases"]:
            if case["split"] == "calibration":
                continue
            self.assertFalse(prs.intersection(case["group"]["prs"]))
            self.assertFalse(hashes.intersection(case["group"]["diff_sha256"].values()))
        self.assertEqual(sum(c["split"] == "test" for c in manifest["cases"]), 60)

    def test_inference_failure_is_recorded_as_error_not_an_abstention(self):
        case = {"id": "case", "split": "development", "packet_sha256": data.digest(packet())}
        manifest = data.seal({"cases": [case]})
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(runner, "BENCHMARK", Path(folder)), \
                patch.object(runner, "installed_model", return_value={"digest": "base"}), \
                patch.object(runner, "case_packet", return_value=packet()), \
                patch.object(runner, "run_review", side_effect=subprocess.TimeoutExpired("test", 1)):
            runner.run_cases(manifest, "base", "qwen", "development", 1, 8)
            record = json.loads((Path(folder) / "runs/base/predictions/case.json").read_text())
            self.assertEqual(record["status"], "error")
            self.assertNotIn("review", record)
            with patch.object(runner, "installed_model", return_value={"digest": "different"}):
                with self.assertRaisesRegex(ValueError, "changed"):
                    runner.run_cases(manifest, "base", "qwen", "development", 1, 8)

    def test_final_test_is_not_opened_without_explicit_flag(self):
        with patch.object(sys, "argv", [
            "pr_benchmark.py", "run", "--run", "base", "--split", "test",
        ]), patch.object(runner, "load_manifest", return_value={}), \
                patch.object(runner, "run_cases") as run:
            with self.assertRaises(SystemExit):
                runner.main()
            run.assert_not_called()

    def test_invalid_semantic_audit_cannot_inflate_precision(self):
        for answer in ({}, {"verdict": "correct", "reviewer": "x", "reason": "ok"}):
            with self.assertRaises(ValueError):
                data.validate_audit(answer)


if __name__ == "__main__":
    unittest.main()
