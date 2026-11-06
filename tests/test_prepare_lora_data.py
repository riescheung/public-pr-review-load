import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import prepare_lora_data
from test_benchmark import packet, review


class LoRADatasetTests(unittest.TestCase):
    def case(self, identifier="a", split="development", prs=(42,)):
        return {"id": identifier, "split": split, "group": {
            "id": identifier, "prs": list(prs),
            "diff_sha256": {str(pr): str(pr) for pr in prs},
        }}

    def label(self, score=2):
        return {"score": score, "reason": "Adjudicated by reading the actual behavior.",
                "reviewer": "expert", "source": "human_adjudicated", "review": review(score)}

    def test_single_chunk_and_abstentions_use_real_approved_answers(self):
        for score in (1, 2, 3, None):
            examples = prepare_lora_data.approved_examples(self.case(), packet(), self.label(score))
            self.assertEqual(len(examples), 1)
            answer = json.loads(examples[0]["row"]["messages"][-1]["content"])
            self.assertEqual(answer["score"], score)
            self.assertEqual(answer["observations"][0]["code_quote"], "return safe")

    def test_multi_chunk_never_assigns_group_tier_to_an_individual_chunk(self):
        large = packet()
        second = json.loads(json.dumps(large["chunks"][0]).replace("P1.F1", "P1.F2"))
        large["chunks"].append(second)
        answer = self.label()
        answer["review"]["observations"].append(json.loads(
            json.dumps(answer["review"]["observations"][0]).replace("P1.F1", "P1.F2")))
        examples = prepare_lora_data.approved_examples(self.case(), large, answer)
        self.assertEqual([e["kind"] for e in examples], ["observation", "observation", "decision"])
        for example in examples[:-1]:
            self.assertNotIn("score", json.loads(example["row"]["messages"][-1]["content"]))
        self.assertEqual(json.loads(examples[-1]["row"]["messages"][-1]["content"])["score"], 2)

    def test_test_calibration_and_partial_pr_overlap_cannot_enter_training(self):
        cases = [self.case("dev"), self.case("held", "test", (42, 43))]
        with self.assertRaisesRegex(ValueError, "held-out"):
            prepare_lora_data.split_examples(cases, {"dev": self.label()}, {})
        cases = [self.case("dev"), self.case("held", "calibration", (43,))]
        with patch.object(prepare_lora_data, "case_packet", return_value=packet()):
            splits = prepare_lora_data.split_examples(cases, {
                "dev": self.label(), "held": self.label(),
            })
        self.assertEqual(set(splits), {"train", "valid"})
        self.assertTrue(all(x["index"] == "dev" for s in splits.values() for x in s))

    def test_weak_labels_and_auto_selected_quotes_are_not_training_data(self):
        bad = {**self.label(), "source": "gpt6_sol_in_session"}
        with self.assertRaisesRegex(ValueError, "human"):
            prepare_lora_data.approved_examples(self.case(), packet(), bad)
        bad = self.label()
        del bad["review"]
        with self.assertRaisesRegex(ValueError, "approved"):
            prepare_lora_data.approved_examples(self.case(), packet(), bad)

    def test_chunks_stay_in_one_split_and_duplicate_patches_are_rejected(self):
        cases = [self.case(str(i), prs=(i,)) for i in range(10)]
        labels = {c["id"]: self.label() for c in cases}
        with patch.object(prepare_lora_data, "case_packet", return_value=packet()):
            splits = prepare_lora_data.split_examples(cases, labels)
        self.assertFalse({x["index"] for x in splits["train"]} &
                         {x["index"] for x in splits["valid"]})
        cases[1]["group"]["diff_sha256"] = cases[0]["group"]["diff_sha256"]
        with self.assertRaisesRegex(ValueError, "overlap"):
            prepare_lora_data.split_examples(cases, labels)


if __name__ == "__main__":
    unittest.main()
