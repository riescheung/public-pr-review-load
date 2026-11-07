import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_mlx_batch_reviews import pending_publication_cases, write_receipt


class ReceiptTests(unittest.TestCase):
    def test_completed_reviews_are_not_retried_and_errors_need_a_new_protocol(self):
        statuses = ("ok", "abstained", "preflight", "error", "deferred")
        cases = [{"id": status, "group": {"id": status}} for status in (*statuses, "pending")]
        publication = {
            "models": {"old": {"digest": "previous"}},
            "reviews": {status: {"status": status, "run": "old"} for status in statuses},
        }
        self.assertEqual([
            [case["id"] for case in pending_publication_cases(cases, publication, model)]
            for model in ("previous", "new")
        ], [["pending"], ["error", "deferred", "pending"]])

    def test_receipt_is_complete_when_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions" / "case.json"
            write_receipt(path, {"score": None, "status": "error"})
            self.assertEqual(json.loads(path.read_text()), {"score": None, "status": "error"})

    def test_existing_receipt_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.json"
            write_receipt(path, {"score": 2})
            with self.assertRaises(FileExistsError):
                write_receipt(path, {"score": None})
            self.assertEqual(json.loads(path.read_text()), {"score": 2})
