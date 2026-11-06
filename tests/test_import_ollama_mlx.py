import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_ollama_mlx import convert_tensor, import_model, verified_blob


class OllamaImportTests(unittest.TestCase):
    def test_scale_renaming_preserves_every_packed_byte_and_offset(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "raw", Path(folder) / "out"
            header = {
                "layer.weight": {"dtype": "U32", "shape": [1], "data_offsets": [0, 4]},
                "layer.weight.scale": {"dtype": "U8", "shape": [1], "data_offsets": [4, 5]},
                "layer.weight.global_scale": {"dtype": "F32", "shape": [], "data_offsets": [5, 9]},
            }
            encoded = json.dumps(header).encode()
            payload = bytes(range(9))
            source.write_bytes(struct.pack("<Q", len(encoded)) + encoded + payload)
            keys = convert_tensor(source, target)
            with target.open("rb") as result:
                size = struct.unpack("<Q", result.read(8))[0]
                actual = json.loads(result.read(size))
                self.assertEqual(result.read(), payload)
            self.assertEqual(set(keys), {"layer.weight", "layer.scales", "layer.global_scale"})
            self.assertEqual(actual["layer.scales"]["data_offsets"], [4, 5])
            with self.assertRaises(FileExistsError):
                convert_tensor(source, target)

    def test_bad_blob_is_rejected_before_repackaging(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "blobs").mkdir()
            digest = hashlib.sha256(b"expected").hexdigest()
            (root / "blobs" / f"sha256-{digest}").write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                verified_blob(root, {"digest": f"sha256:{digest}", "size": 8})

    def test_import_excludes_vision_and_speculative_heads_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "blobs").mkdir()

            def store(content):
                digest = hashlib.sha256(content).hexdigest()
                (root / "blobs" / f"sha256-{digest}").write_bytes(content)
                return {"digest": f"sha256:{digest}", "size": len(content)}

            layers = []
            for name, value in (
                ("config.json", {"model_type": "qwen3_5", "quantization_config": {}}),
                ("tokenizer.json", {}), ("tokenizer_config.json", {}),
            ):
                layers.append({**store(json.dumps(value).encode()), "name": name,
                               "mediaType": "application/vnd.ollama.image.json"})
            for name in ("model.visual.weight", "mtp.fc.weight"):
                layers.append({"name": name, "mediaType": "application/vnd.ollama.image.tensor"})
            header = json.dumps({"lm_head.weight": {
                "dtype": "U32", "shape": [1], "data_offsets": [0, 4],
            }}).encode()
            tensor = struct.pack("<Q", len(header)) + header + bytes(4)
            layers.append({**store(tensor), "name": "lm_head.weight",
                           "mediaType": "application/vnd.ollama.image.tensor"})
            manifest = store(json.dumps({"layers": layers}).encode())["digest"][7:]
            result = import_model(root, manifest, root / "converted")
            self.assertEqual(result["skipped_auxiliary_tensors"], 2)
            config = json.loads((root / "converted/config.json").read_text())
            self.assertNotIn("quantization_config", config)
            self.assertEqual(config["quantization"]["mode"], "nvfp4")


if __name__ == "__main__":
    unittest.main()
