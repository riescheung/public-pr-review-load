import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from benchmark_data import seal
from prepare_review_assets import prepare_assets


class ReviewAssetsTests(unittest.TestCase):
    def publication(self):
        return seal({
            "version": 1, "human_gold": False, "reviews": {
                "change": {
                    "id": "change", "prs": [42], "status": "ok", "tier": 2,
                    "run": "qwen", "source": "publication", "known_calibration": False,
                    "review": {"reason": "Cited implementation", "score": 2},
                    "prediction_sha256": "original-prediction",
                },
            },
        })

    def test_conversion_is_lossless_and_repeated_builds_do_not_rewrite_the_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "publication.json"
            original = self.publication()
            path.write_text(json.dumps(original))
            assets = root / "assets"
            prepare_assets(path, assets)
            first = path.read_bytes()
            indexed = json.loads(first)
            row = indexed["reviews"]["change"]
            full = json.loads((assets / f"{row['evidence_sha256']}.json").read_text())
            prepare_assets(path, assets)
            self.assertEqual(
                (indexed["version"], "review" in row, full,
                 indexed["inline_publication_sha256"], path.read_bytes()),
                (2, False, original["reviews"]["change"], original["sha256"], first),
            )

    def test_changed_evidence_fails_without_replacing_the_valid_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, assets = root / "publication.json", root / "assets"
            path.write_text(json.dumps(self.publication()))
            prepare_assets(path, assets)
            indexed = path.read_bytes()
            next(assets.glob("*.json")).write_text('{"tier":3}')
            with self.assertRaisesRegex(ValueError, "evidence"):
                prepare_assets(path, assets)
            self.assertEqual(path.read_bytes(), indexed)

    def test_unsealed_publication_is_never_transformed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "publication.json"
            changed = copy.deepcopy(self.publication())
            changed["reviews"]["change"]["tier"] = 3
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "hash"):
                prepare_assets(path, Path(directory) / "assets")
