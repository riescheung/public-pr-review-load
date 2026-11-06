import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_data import digest, seal, write_new
import frontier_reference as frontier
import frontier_review_adapter as adapter
import reference_feedback as feedback
import pr_benchmark
from reference_learning import learning_examples
from test_benchmark import packet, review
from test_experimental_training import FakeTokenizer


def case(identifier="dev", split="development", number=42):
    return {
        "id": identifier, "split": split, "source": "full",
        "packet_sha256": digest(packet()),
        "group": {"id": identifier, "prs": [number], "diff_sha256": {str(number): str(number)}},
    }


class FrontierReferenceTests(unittest.TestCase):
    def test_cli_uses_exact_model_isolated_directory_and_noninherited_auth_environment(self):
        with patch.object(adapter.subprocess, "run", return_value=Mock(
            returncode=0, stdout='{"score": 2}',
        )) as run:
            self.assertEqual(adapter.cli_reply([{"content": "blinded"}], "gpt-6-1-sol-high"),
                             '{"score": 2}')
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--model") + 1], "gpt-6-1-sol-high")
        self.assertIn("--sandbox", command)
        self.assertNotEqual(Path(run.call_args.kwargs["cwd"]), ROOT)
        self.assertNotIn("DEVIN_API_KEY", run.call_args.kwargs["env"])

    def test_signed_in_catalog_never_silently_substitutes_a_model(self):
        with patch.object(frontier.subprocess, "run", side_effect=[
            Mock(returncode=0, stdout="  gpt-6-1-sol-high    GPT-6.1 Sol High"),
            Mock(stdout="devin test"),
        ]):
            self.assertEqual(frontier.model_identity("gpt-6-1-sol-high")["model_id"],
                             "gpt-6-1-sol-high")
        with patch.object(frontier.subprocess, "run", return_value=Mock(
            returncode=0, stdout="  gpt-6-sol-high    GPT-6 Sol",
        )), self.assertRaisesRegex(ValueError, "unavailable"):
            frontier.model_identity("gpt-6-1-sol-high")

    def test_only_development_is_called_and_successes_are_immutable(self):
        manifest = seal({"cases": [case(), case("reserved", "test", 43)]})
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(frontier, "case_packet", return_value=packet()), \
                patch.object(frontier, "model_identity", return_value={"model_id": "sol"}), \
                patch.object(frontier, "run_review", return_value=review()) as model:
            directory = Path(folder)
            frontier.run_references(manifest, directory, "sol", 40, 8)
            frontier.run_references(manifest, directory, "sol", 40, 8)
            self.assertEqual(model.call_count, 1)
            self.assertFalse((directory / "predictions/reserved.json").exists())
            record = json.loads((directory / "predictions/dev.json").read_text())
            self.assertIs(record["human_gold"], False)
            self.assertEqual(record["source"], "frontier_model_reference")

    def test_model_error_is_not_a_trusted_abstention(self):
        manifest = seal({"cases": [case()]})
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(frontier, "case_packet", return_value=packet()), \
                patch.object(frontier, "model_identity", return_value={"model_id": "sol"}), \
                patch.object(frontier, "run_review", side_effect=subprocess.TimeoutExpired("cli", 1)):
            frontier.run_references(manifest, Path(folder), "sol", 1, 8)
            record = json.loads((Path(folder) / "predictions/dev.json").read_text())
            self.assertEqual(record["status"], "error")
            self.assertNotIn("review", record)

    def test_explicit_reference_worker_assignment_cannot_open_a_reserved_case(self):
        manifest = seal({"cases": [case(), case("reserved", "test", 43)]})
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(frontier, "model_identity") as identity, \
                self.assertRaisesRegex(ValueError, "development"):
            frontier.run_references(manifest, Path(folder), "sol", 1, 8, ["reserved"])
        identity.assert_not_called()

    def test_benchmark_case_filter_cannot_cross_the_requested_split(self):
        manifest = seal({"cases": [case(), case("reserved", "test", 43)]})
        with patch.object(pr_benchmark, "installed_model") as identity, \
                self.assertRaisesRegex(ValueError, "requested benchmark split"):
            pr_benchmark.run_cases(manifest, "smoke", "qwen", "development", 1, 8,
                                   only_cases=["reserved"])
        identity.assert_not_called()

    def test_benchmark_case_filter_is_frozen_in_the_run_spec(self):
        manifest = seal({"cases": [case(), case("other", number=44)]})
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(pr_benchmark, "BENCHMARK", Path(folder)), \
                patch.object(pr_benchmark, "case_packet", return_value=packet()), \
                patch.object(pr_benchmark, "installed_model", return_value={"digest": "base"}), \
                patch.object(pr_benchmark, "run_review", return_value=review()) as model:
            pr_benchmark.run_cases(manifest, "smoke", "qwen", "development", 1, 8,
                                   only_cases=["other"])
            self.assertEqual(model.call_count, 1)
            spec = json.loads((Path(folder) / "runs/smoke/spec.json").read_text())
            self.assertEqual(spec["selected_case_ids"], ["other"])
            self.assertFalse((Path(folder) / "runs/smoke/predictions/dev.json").exists())


class QueueFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.case = case()
        self.manifest = seal({"cases": [self.case, case("reserved", "test", 43)]})
        self.reference = {"source": "frontier_model_reference", "human_gold": False,
                          "status": "ok", "review": review()}
        self.references = {"dev": self.reference}
        body = {"version": 1, "manifest_sha256": self.manifest["sha256"], "cases": [{
            "case_id": "dev", "reference_sha256": digest(self.reference),
        }]}
        self.queue = {**body, "sha256": digest(body)}
        self.answer = {
            "case_id": "dev", "reference_sha256": digest(self.reference),
            "packet_sha256": self.case["packet_sha256"], "supersedes": None,
            "reviewer": "queue-user", "score": 3, "reason": "Checked a larger change mechanism.",
            "review": review(3), "evidence_checked": True,
        }

    def payload(self, answers=None):
        return {"version": 1, "queue_sha256": self.queue["sha256"],
                "answers": answers if answers is not None else [self.answer]}

    def test_import_is_versioned_validated_and_never_renamed_human_gold(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(feedback, "case_packet", return_value=packet()):
            root = Path(folder)
            feedback.import_feedback(self.manifest, self.references, self.queue, self.payload(), root)
            latest = feedback.load_feedback(self.manifest, root, self.references)["dev"]
            self.assertEqual(latest["score"], 3)
            self.assertEqual(latest["source"], "user_feedback")
            self.assertIs(latest["human_gold"], False)
            with self.assertRaisesRegex(ValueError, "stale"):
                feedback.import_feedback(self.manifest, self.references, self.queue, self.payload(), root)
            next_answer = {**self.answer, "score": None, "review": review(None),
                           "supersedes": digest(latest)}
            feedback.import_feedback(self.manifest, self.references, self.queue,
                                     self.payload([next_answer]), root)
            self.assertEqual(len(list(root.glob("*.json"))), 2)
            self.assertIsNone(feedback.load_feedback(self.manifest, root, self.references)["dev"]["score"])

    def test_reserved_wrong_hash_unchecked_and_invalid_quotes_are_rejected(self):
        invalid = [
            {**self.answer, "case_id": "reserved"},
            {**self.answer, "packet_sha256": "different"},
            {**self.answer, "reference_sha256": "different"},
            {**self.answer, "evidence_checked": False},
        ]
        wrong_quote = copy.deepcopy(self.answer)
        wrong_quote["review"]["observations"][0]["observations"][0]["code_quote"] = "invented"
        invalid.append(wrong_quote)
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(feedback, "case_packet", return_value=packet()):
            for answer in invalid:
                with self.subTest(answer=answer), self.assertRaises(ValueError):
                    feedback.import_feedback(self.manifest, self.references, self.queue,
                                             self.payload([answer]), Path(folder))
            self.assertEqual(list(Path(folder).glob("*.json")), [])

    def test_validated_user_correction_overrides_teacher_for_training(self):
        corrected = {**self.answer, "source": "user_feedback"}
        with patch("reference_learning.case_packet", return_value=packet()):
            splits, excluded = learning_examples(self.manifest, self.references,
                                                 {"dev": corrected}, FakeTokenizer(), 1000)
        rows = splits["train"] + splits["valid"]
        self.assertEqual(excluded, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 3)
        self.assertEqual(rows[0]["source"], "user_feedback")
        self.assertEqual(rows[0]["label_sha256"], digest(corrected))
        self.assertFalse(any(row["index"] == "reserved" for row in rows))

    def test_split_membership_does_not_move_when_more_queue_cases_arrive(self):
        first = seal({"cases": [case()]})
        more = seal({"cases": [case(), case("other", number=44)]})
        refs = {**self.references, "other": self.reference}
        with patch("reference_learning.case_packet", return_value=packet()):
            a, _ = learning_examples(first, refs, {}, FakeTokenizer(), 1000)
            b, _ = learning_examples(more, refs, {}, FakeTokenizer(), 1000)
        self.assertEqual(next(k for k in a if any(r["index"] == "dev" for r in a[k])),
                         next(k for k in b if any(r["index"] == "dev" for r in b[k])))

    def test_overlength_family_is_excluded_whole_without_partial_chunk_training(self):
        with patch("reference_learning.case_packet", return_value=packet()), \
                patch("reference_learning.encoded_rows", side_effect=ValueError("truncation is forbidden")):
            splits, excluded = learning_examples(self.manifest, self.references, {},
                                                 FakeTokenizer(), 1000)
        self.assertEqual(splits, {"train": [], "valid": []})
        self.assertEqual(excluded, [{"case_id": "dev", "reason": "truncation is forbidden"}])

    def test_reserved_partial_patch_overlap_is_blocked_before_serializing(self):
        overlap = copy.deepcopy(self.manifest)
        overlap["cases"][0]["group"]["diff_sha256"] = {"42": "43"}
        with self.assertRaisesRegex(ValueError, "held-out"):
            feedback.development_cases(overlap)


if __name__ == "__main__":
    unittest.main()
