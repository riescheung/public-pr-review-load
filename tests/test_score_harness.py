import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import score_harness as harness


class ScoreHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.selection = json.loads(
            (ROOT / "data" / "ai_pilot" / "selection.json").read_text()
        )

    def test_packet_is_posthog_grounded_but_blind_to_metadata(self):
        group = self.selection[1]
        original = harness.make_packet(group)
        changed = copy.deepcopy(group)
        changed.update({
            "id": "issue:changed", "authors": ["new-author"],
            "old_points": 99, "wpr": 10, "stratum": "large",
            "title": "fix: extremely important", "links": ["https://example.com"],
        })
        self.assertEqual(original, harness.make_packet(changed))
        self.assertEqual(original["repository"], "PostHog/posthog")
        self.assertIn("external data ingestion", original["system"])
        self.assertNotIn("old_points", json.dumps(original))
        self.assertNotIn("Gilbert09", json.dumps(original))
        self.assertEqual(len(original["chunks"]), 1)
        self.assertIn("P1.F1.H1", original["chunks"][0]["text"])

    def test_large_diff_is_chunked_without_losing_hunks(self):
        group = self.selection[42]
        packet = harness.make_packet(group)
        self.assertIsNone(packet["abstention_reason"])
        self.assertGreater(len(packet["chunks"]), 1)
        expected = harness.parse_hunks(
            (harness.PILOT / "diffs" / f"{group['prs'][0]}.diff").read_text(), 1
        )
        actual = [h for chunk in packet["chunks"] for h in chunk["hunks"]]
        self.assertEqual(actual, [h["id"] for h in expected])
        self.assertTrue(all(len(chunk["text"]) <= harness.MAX_CHUNK_CHARS for chunk in packet["chunks"]))

    def test_missing_and_modified_diffs_abstain_before_model(self):
        missing = harness.make_packet(self.selection[46])
        self.assertEqual(missing["chunks"], [])
        self.assertIn("Missing cached diff", missing["abstention_reason"])
        modified = copy.deepcopy(self.selection[1])
        modified["diff_sha256"]["99617"] = hashlib.sha256(b"another diff").hexdigest()
        self.assertIn("does not match", harness.make_packet(modified)["abstention_reason"])
        with patch.object(harness, "call_model", side_effect=AssertionError("ran model")):
            self.assertIsNone(harness.run_review(missing, ["model"], "test")["score"])

    def test_incomplete_and_binary_patches_abstain(self):
        with self.assertRaisesRegex(ValueError, "Truncated hunk"):
            harness.parse_hunks(
                "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n+new\n", 1
            )
        with self.assertRaisesRegex(ValueError, "Binary"):
            harness.parse_hunks(
                "diff --git a/image.png b/image.png\nBinary files a/image.png and b/image.png differ\n", 1
            )
        self.assertEqual(harness.parse_hunks(
            "diff --git a/old.py b/old.py\n--- a/old.py\n+++ /dev/null\n"
            "@@ -1 +0,0 @@\n-old\n", 1
        )[0]["path"], "old.py")

    def test_multi_pr_review_keeps_prs_in_separate_chunks(self):
        packet = harness.make_packet(self.selection[49])
        self.assertIsNone(packet["abstention_reason"])
        self.assertGreaterEqual(len(packet["chunks"]), 2)
        self.assertTrue(any(chunk["hunks"][0].startswith("P2.") for chunk in packet["chunks"]))

    def test_chunk_observations_and_final_decision_are_validated(self):
        packet = harness.make_packet(self.selection[1])
        observed = {
            "observations": [{
                "hunk": "P1.F1.H1", "behavior": "Changes a release status",
                "posthog_connection": "Changes the warehouse connector display",
                "code_quote": "releaseStatus=ReleaseStatus.GA,",
            }],
            "limitations": "No adoption data",
        }
        decision = {
            "score": 1, "reason": "Only a status flag changes",
            "posthog_relevance": "Warehouse connector display",
            "confidence": "medium", "evidence": ["P1.F1.H1"],
            "uncertainty": "No adoption evidence", "metadata_dependency": False,
            "grouping_issue": False,
            "abstention_reason": None,
        }
        with patch.object(harness, "call_model", side_effect=[observed, decision]) as model:
            result = harness.run_review(packet, ["model"], "mock-v1")
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["model_id"], "mock-v1")
        self.assertEqual(model.call_count, 2)
        self.assertIn("hunk id=P1.F1.H1", model.call_args_list[0].args[1][1]["content"])
        self.assertNotIn("old_points", model.call_args_list[1].args[1][1]["content"])

    def test_one_pass_still_validates_code_quotes_and_tier(self):
        packet = harness.make_packet(self.selection[1])
        review = {
            "observations": [{
                "hunk": "P1.F1.H1", "behavior": "Release status changes",
                "posthog_connection": "Connector status label",
                "code_quote": "releaseStatus=ReleaseStatus.GA,",
            }],
            "limitations": "No adoption evidence",
            "score": 1, "reason": "Only a status flag changes",
            "posthog_relevance": "Warehouse connector release status",
            "confidence": "low", "evidence": ["P1.F1.H1"],
            "uncertainty": "The diff does not demonstrate connector adoption",
            "metadata_dependency": False, "grouping_issue": False,
            "abstention_reason": None,
        }
        with patch.object(harness, "call_model", return_value=review) as model:
            result = harness.run_review(packet, ["model"], "mock-v1", one_pass=True)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["observations"][0]["observations"], review["observations"])
        self.assertNotIn("old_points", model.call_args.args[1][1]["content"])
        with patch.object(harness, "call_model", return_value={
            **review, "observations": [{**review["observations"][0], "code_quote": "invented"}],
        }), self.assertRaisesRegex(ValueError, "Code quote"):
            harness.run_review(packet, ["model"], "mock-v1", one_pass=True)

    def test_invalid_or_metadata_dependent_answers_fail_closed(self):
        valid = {
            "score": 2, "reason": "Improves a bounded path",
            "posthog_relevance": "Warehouse sync correctness", "confidence": "low",
            "evidence": ["P1.F1.H1"], "uncertainty": "No usage evidence",
            "metadata_dependency": False, "grouping_issue": False,
            "abstention_reason": None,
        }
        for change in (
            {"score": True}, {"score": 4}, {"evidence": ["P9.F9.H9"]},
            {"metadata_dependency": True}, {"posthog_relevance": ""},
            {"score": None}, {"confidence": "very high"},
            {"grouping_issue": True}, {"grouping_issue": "false"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                harness.validate_decision({**valid, **change}, {"P1.F1.H1"})
        with self.assertRaisesRegex(ValueError, "unknown hunk"):
            harness.validate_observations({
                "observations": [{
                    "hunk": "P9.F9.H9", "behavior": "changed",
                    "posthog_connection": "warehouse", "code_quote": "meaningful code",
                }], "limitations": "unknown"
            }, {"P1.F1.H1": ["meaningful code"]})
        with self.assertRaisesRegex(ValueError, "Code quote"):
            harness.validate_observations({
                "observations": [{
                    "hunk": "P1.F1.H1", "behavior": "changed",
                    "posthog_connection": "warehouse", "code_quote": "made up code",
                }], "limitations": "unknown",
            }, {"P1.F1.H1": ["releaseStatus=ReleaseStatus.GA,"]})

    def test_model_command_gets_only_messages_and_json_is_required(self):
        fake = unittest.mock.Mock(returncode=0, stdout='{"ok":true}', stderr="")
        with patch.object(harness.subprocess, "run", return_value=fake) as run:
            self.assertEqual(harness.call_model(["local-model"], [{"role": "user", "content": "x"}]), {"ok": True})
        self.assertEqual(run.call_args.args[0], ["local-model"])
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), {
            "messages": [{"role": "user", "content": "x"}]
        })
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        with patch.object(harness.subprocess, "run", return_value=unittest.mock.Mock(
            returncode=0, stdout="not json", stderr=""
        )), self.assertRaisesRegex(ValueError, "JSON object"):
            harness.call_model(["local-model"], [])

    def test_local_adapter_protocol_end_to_end_without_a_model(self):
        adapter = """
import json, re, sys
prompt = json.load(sys.stdin)["messages"][1]["content"]
if "Observations:\\n" in prompt:
    result = {"score": 1, "reason": "A display flag changed",
              "posthog_relevance": "Warehouse connector status", "confidence": "low",
              "evidence": ["P1.F1.H1"], "uncertainty": "No usage data",
              "metadata_dependency": False, "grouping_issue": False,
              "abstention_reason": None}
else:
    hunk = re.search(r"<hunk id=([^ ]+)", prompt).group(1)
    result = {"observations": [
        {"hunk": hunk, "behavior": "A display flag changed",
         "posthog_connection": "Warehouse connector status",
         "code_quote": "releaseStatus=ReleaseStatus.GA,"}],
        "limitations": "No usage data"}
print(json.dumps(result))
"""
        decision = harness.run_review(
            harness.make_packet(self.selection[1]),
            [sys.executable, "-c", adapter], "offline-test-adapter",
        )
        self.assertEqual(decision["score"], 1)
        self.assertEqual(len(decision["observations"]), 1)

    def test_independent_runs_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "selection.json").write_text(json.dumps([self.selection[1]]))
            packet = harness.make_packet(self.selection[1])
            with (patch.object(harness, "PILOT", root),
                  patch.object(harness, "OUTPUT", root / "harness"),
                  patch.object(harness, "make_packet", return_value=packet),
                  patch.object(harness, "run_review", side_effect=[
                      {"score": 1, "grouping_issue": False, "reason": "Narrow change"},
                      {"score": 3, "grouping_issue": False, "reason": "Broad change"},
                  ])):
                for reviewer in ("reviewer-a", "reviewer-b"):
                    with patch.object(sys, "argv", [
                        "score_harness.py", "run", "--index", "1",
                        "--reviewer-id", reviewer, "--model-id", "mock",
                        "--model-command", "fake",
                    ]):
                        harness.main()
                self.assertEqual(len(list((root / "harness" / "runs" / "01").glob("*.json"))), 2)
                flags = json.loads((root / "harness" / "review_queue.json").read_text())[0]["flags"]
                self.assertEqual(flags, ["low_wpr_high_tier", "reviewer_disagreement"])
                with patch.object(sys, "argv", [
                    "score_harness.py", "run", "--index", "1",
                    "--reviewer-id", "reviewer-a", "--model-id", "mock",
                    "--model-command", "fake",
                ]), self.assertRaises(SystemExit):
                    harness.main()


if __name__ == "__main__":
    unittest.main()
