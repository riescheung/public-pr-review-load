import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_review_pair as pair


class ReviewPairTests(unittest.TestCase):
    def test_commands_isolate_teacher_and_local_student(self):
        teacher = pair.command("pilot", 2, "teacher", "6.1")
        student = pair.command("pilot", 2, "student", "qwen3.5:9b")
        self.assertEqual(teacher[teacher.index("--reviewer-id") + 1], "teacher-6-1")
        self.assertEqual(student[student.index("--reviewer-id") + 1], "student-qwen3-5-9b")
        self.assertEqual(teacher[-1], str(ROOT / "scripts" / "codex_review_adapter.py"))
        self.assertEqual(student[-1], str(ROOT / "scripts" / "ollama_review_adapter.py"))
        self.assertIn("--one-pass", teacher)

    def test_resume_requires_same_provenance_and_model(self):
        packet = {"diff_sha256": {"42": "a" * 64}, "instructions_sha256": "b" * 64}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "teacher-6-1.json"
            self.assertFalse(pair.check_existing(path, packet, 2, "teacher", "6.1"))
            path.write_text(json.dumps({
                "version": pair.VERSION, "repository": pair.REPOSITORY,
                "index": 2, "reviewer_id": "teacher-6-1", "model_id": "6.1",
                **packet,
            }))
            self.assertTrue(pair.check_existing(path, packet, 2, "teacher", "6.1"))
            with self.assertRaisesRegex(ValueError, "Stale or mismatched"):
                pair.check_existing(path, {**packet, "diff_sha256": {}},
                                    2, "teacher", "6.1")
            with self.assertRaisesRegex(ValueError, "Stale or mismatched"):
                pair.check_existing(path, packet, 2, "teacher", "gpt-6.1")

    def test_dry_run_never_starts_a_model(self):
        with patch.object(sys, "argv", [
            "run_review_pair.py", "--index", "2", "--teacher-model", "6.1",
        ]), patch.object(pair.subprocess, "run", side_effect=AssertionError("model called")):
            pair.main()


if __name__ == "__main__":
    unittest.main()
