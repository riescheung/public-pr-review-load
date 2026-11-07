import json
import signal
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from continue_mlx_reviews import cohort_finished, run_cohort, wait_for_power


class ContinuationTests(unittest.TestCase):
    def test_service_stop_interrupts_the_native_parent_and_preserves_receipts(self):
        with patch("continue_mlx_reviews.subprocess.Popen") as launch:
            child = launch.return_value
            child.poll.return_value = None
            child.wait.side_effect = [KeyboardInterrupt(), 0]
            with self.assertRaises(KeyboardInterrupt):
                run_cohort(["python", "worker.py"])
            self.assertEqual(child.send_signal.call_args.args, (signal.SIGINT,))

    def test_partial_cohort_is_resumed_until_every_selected_receipt_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "spec.json").write_text(json.dumps({"selected_case_ids": ["a", "b"]}))
            (root / "predictions").mkdir()
            (root / "predictions" / "a.json").write_text("{}")
            partial = cohort_finished(root)
            (root / "predictions" / "b.json").write_text("{}")
            self.assertEqual((partial, cohort_finished(root)), (False, True))

    def test_power_pause_uses_a_higher_resume_threshold_without_requiring_ac(self):
        with patch("continue_mlx_reviews.require_safe_power",
                   side_effect=[RuntimeError("20%"), None]) as guard, \
                patch("continue_mlx_reviews.time.sleep"):
            wait_for_power()
            self.assertEqual([call.args for call in guard.call_args_list], [(20,), (34,)])
