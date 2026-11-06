import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_ollama_mlx import file_sha256
from train_experimental_qwen import warm_start_identity


PARAMETERS = {"rank": 8, "scale": 8.0, "dropout": 0.05}


def checkpoint(directory, **changes):
    root = Path(directory)
    weights = root / "0000020_adapters.safetensors"
    weights.write_bytes(b"test checkpoint")
    experiment = {
        "human_gold": False, "eligible_for_promotion": False,
        "base_receipt_sha256": "base", "dataset_manifest_sha256": "dataset",
        "num_layers": 1, "lora_parameters": PARAMETERS, "iters": 40,
        **changes,
    }
    (root / "experiment.json").write_text(json.dumps(experiment))
    (root / "failure.json").write_text(json.dumps({
        "saved_checkpoints": {weights.name: file_sha256(weights)},
    }))
    return weights


class ReferenceWarmStartTests(unittest.TestCase):
    def test_checkpoint_is_verified_and_fresh_optimiser_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            weights = checkpoint(directory)
            identity = warm_start_identity(weights, "base", "dataset", 1, PARAMETERS)
            self.assertEqual(identity["previous_iterations"], 20)
            self.assertFalse(identity["optimizer_state_restored"])
            self.assertEqual(identity["checkpoint_sha256"], file_sha256(weights))

    def test_changed_dataset_base_layer_configuration_and_gold_flags_are_rejected(self):
        for changes in (
            {"base_receipt_sha256": "other"}, {"dataset_manifest_sha256": "other"},
            {"num_layers": 2}, {"lora_parameters": {**PARAMETERS, "rank": 16}},
            {"human_gold": True}, {"eligible_for_promotion": True}, {"iters": 10},
        ):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                weights = checkpoint(directory, **changes)
                with self.assertRaises(ValueError):
                    warm_start_identity(weights, "base", "dataset", 1, PARAMETERS)

    def test_tampered_checkpoint_and_unfinished_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            weights = checkpoint(directory)
            weights.write_bytes(b"changed checkpoint")
            with self.assertRaises(ValueError):
                warm_start_identity(weights, "base", "dataset", 1, PARAMETERS)
        with tempfile.TemporaryDirectory() as directory:
            weights = checkpoint(directory)
            # A different source directory has no closed-run receipt.
            active = Path(directory) / "active"
            active.mkdir()
            unrecorded = active / weights.name
            unrecorded.write_bytes(weights.read_bytes())
            with self.assertRaises(ValueError):
                warm_start_identity(unrecorded, "base", "dataset", 1, PARAMETERS)

    def test_cumulative_steps_are_not_mistaken_for_one_uninterrupted_run(self):
        with tempfile.TemporaryDirectory() as directory:
            weights = checkpoint(directory, completed_iterations_before_run=10)
            identity = warm_start_identity(weights, "base", "dataset", 1, PARAMETERS)
            self.assertEqual(identity["previous_iterations"], 30)
            self.assertEqual(identity["source_checkpoint_iterations"], 20)


if __name__ == "__main__":
    unittest.main()
