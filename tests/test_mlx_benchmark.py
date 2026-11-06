import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_ollama_mlx import file_sha256
from pr_benchmark import evaluation_identity, installed_mlx_model


class MLXBenchmarkTests(unittest.TestCase):
    def test_base_and_candidate_pin_same_weights_and_experimental_provenance(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch("pr_benchmark.importlib.metadata.version", return_value="test"):
            base = Path(folder) / "base"
            adapter = Path(folder) / "adapter"
            base.mkdir()
            adapter.mkdir()
            (base / "model.safetensors").write_bytes(b"base weights")
            (base / "conversion_receipt.json").write_text(json.dumps({
                "ollama_model_digest": "pinned-base",
                "output_files": {"model.safetensors": file_sha256(base / "model.safetensors")},
            }))
            original = installed_mlx_model(base)
            self.assertFalse(original["experimental_ai_labels"])
            (adapter / "adapter_config.json").write_text("{}")
            (adapter / "adapters.safetensors").write_bytes(b"adapter weights")
            (adapter / "result.json").write_text(json.dumps({
                "completed": True, "human_gold": False, "base_ollama_digest": "pinned-base",
                "adapter_sha256": file_sha256(adapter / "adapters.safetensors"),
            }))
            candidate = installed_mlx_model(base, adapter)
            self.assertEqual(original["base_receipt_sha256"], candidate["base_receipt_sha256"])
            self.assertTrue(candidate["experimental_ai_labels"])
            self.assertNotEqual(original["digest"], candidate["digest"])
            spec = {"protocol": "review", "max_chunks": 8, "timeout_per_call": 360,
                    "harness_sha256": "harness"}
            self.assertEqual(evaluation_identity({**spec, "model": original}),
                             evaluation_identity({**spec, "model": candidate}))
            self.assertEqual(original["structured_decoding"], "schema-hunk-quote-v1")
            changed_environment = {
                **candidate, "runtime_environment": {"AGX_RELAX_CDM_CTXSTORE_TIMEOUT": "0"},
            }
            self.assertNotEqual(
                evaluation_identity({**spec, "model": original}),
                evaluation_identity({**spec, "model": changed_environment}),
            )
            other_runtime = {"digest": original["base_ollama_digest"],
                             "adapter_sha256": "ollama implementation", "ollama_version": "test"}
            self.assertNotEqual(
                evaluation_identity({**spec, "model": original})["evaluation_protocol_sha256"],
                evaluation_identity({**spec, "model": other_runtime})["evaluation_protocol_sha256"],
            )
            (adapter / "adapters.safetensors").write_bytes(b"changed adapter")
            with self.assertRaisesRegex(ValueError, "changed"):
                installed_mlx_model(base, adapter)
            (base / "model.safetensors").write_bytes(b"changed base")
            with self.assertRaisesRegex(ValueError, "base changed"):
                installed_mlx_model(base)


if __name__ == "__main__":
    unittest.main()
