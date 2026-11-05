import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import devin_swe_review_adapter as adapter
import run_full_swe_review as runner
from review_contract import PILOT


class SWEReviewTests(unittest.TestCase):
    def test_cli_is_local_explicit_model_and_json_only(self):
        messages = [
            {"role": "system", "content": "Follow blinded diff rules"},
            {"role": "user", "content": "Complete hunk"},
        ]
        with patch.object(adapter.subprocess, "run", return_value=Mock(
            returncode=0, stdout='{"score": 2}', stderr="",
        )) as call:
            self.assertEqual(adapter.review(messages, "swe-2"), {"score": 2})
        command = call.call_args.args[0]
        self.assertEqual(command[command.index("--model") + 1], "swe-2")
        self.assertIn("--print", command)
        self.assertIn("--sandbox", command)
        self.assertNotIn("--cloud", command)
        self.assertEqual(call.call_args.kwargs["timeout"], 110)
        with patch.object(adapter.subprocess, "run", return_value=Mock(
            returncode=0, stdout="```json\n{}\n```", stderr="",
        )), self.assertRaisesRegex(ValueError, "exactly one JSON"):
            adapter.review(messages, "swe-2")
        with self.assertRaisesRegex(ValueError, "exact SWE-2"):
            adapter.review(messages, "swe")

    def test_preflight_requires_logged_in_exact_model(self):
        with patch.object(runner.subprocess, "run", return_value=Mock(
            returncode=1, stdout="", stderr="Not logged in",
        )), self.assertRaisesRegex(ValueError, "Not logged in"):
            runner.preflight("swe-2")
        with patch.object(runner.subprocess, "run", return_value=Mock(
            returncode=0, stdout="swe-2-fast\nswe-2", stderr="",
        )):
            runner.preflight("swe-2")
            with self.assertRaisesRegex(ValueError, "not found"):
                runner.preflight("swe-2-thinking")

    def test_full_runner_plan_never_calls_a_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "selection.json").write_text(json.dumps([
                {"prs": [42], "diff_sha256": {"42": "a" * 64}},
            ]))
            with (patch.object(runner, "FULL", root),
                  patch.object(runner, "preflight", side_effect=AssertionError("preflight")),
                  patch.object(runner, "review_one", side_effect=AssertionError("model")),
                  patch.object(sys, "argv", ["run_full_swe_review.py", "--model-id", "swe-2"])):
                runner.main()
            self.assertFalse((root / "harness").exists())

    def test_complete_diff_is_recorded_once_and_stale_runs_block_resume(self):
        group = json.loads((PILOT / "selection.json").read_text())[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (patch.object(runner, "FULL", PILOT),
                  patch.object(runner, "run_review", return_value={
                      "score": 1, "reason": "Status flag only",
                      "grouping_issue": False,
                  }) as model):
                self.assertEqual(runner.review_one(2, group, "swe-2", root), "reviewed")
                self.assertEqual(runner.review_one(2, group, "swe-2", root), "already_reviewed")
                self.assertEqual(model.call_count, 1)
                record = json.loads((root / "02" / "swe2-cli-v1.json").read_text())
                self.assertEqual(record["model_id"], "swe-2")
                self.assertEqual(record["diff_sha256"], group["diff_sha256"])
                with self.assertRaisesRegex(ValueError, "Stale or mismatched"):
                    runner.review_one(2, group, "swe-2-fast", root)
            incomplete = {**group, "diff_sha256": {}}
            with patch.object(runner, "FULL", PILOT):
                self.assertEqual(runner.review_one(2, incomplete, "swe-2", root), "missing_diff")


if __name__ == "__main__":
    unittest.main()
