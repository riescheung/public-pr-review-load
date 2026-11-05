import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import prepare_lora_data
from review_contract import FULL
from score_harness import make_packet, validate_decision, validate_observations


class LoRADatasetTests(unittest.TestCase):
    def test_splits_keep_calibration_out_of_training(self):
        splits = prepare_lora_data.build()
        train_prs = {tuple(item["prs"]) for item in splits["train"]}
        test_prs = {tuple(item["prs"]) for item in splits["test"]}
        self.assertFalse(train_prs & test_prs)
        self.assertEqual(
            {tuple(item["prs"]) for item in splits["test"]
             if item["source"] == "human_expert"},
            {(103592,), (116718,), (117287,)},
        )
        self.assertTrue(any(
            json.loads(item["row"]["messages"][-1]["content"])["score"] == 3
            for item in splits["train"]
        ))

    def test_fresh_teacher_quotes_are_real_changed_lines_and_blind_to_wpr(self):
        selection = json.loads((FULL / "selection.json").read_text())
        for label in json.loads((FULL / "teacher_labels.json").read_text()):
            group = selection[label["index"] - 1]
            packet = make_packet(group, FULL / "diffs")
            self.assertIsNone(packet["abstention_reason"])
            self.assertIn(label["code_quote"], {
                line for chunk in packet["chunks"] for line in
                chunk["changed_lines"].get(label["hunk"], [])
            })
            sample = prepare_lora_data.example(
                label["index"], group, label["score"], label["reason"],
                "gpt6_sol_in_session", FULL / "diffs",
                hunk=label["hunk"], quote=label["code_quote"],
            )
            self.assertIsNotNone(sample)
            answer = json.loads(sample["row"]["messages"][-1]["content"])
            validate_observations(answer, packet["chunks"][0]["changed_lines"])
            validate_decision(answer, {label["hunk"]})
            self.assertNotIn('"wpr"', json.dumps(sample["row"]))


if __name__ == "__main__":
    unittest.main()
