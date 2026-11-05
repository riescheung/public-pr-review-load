import hashlib
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "data" / "ai_pilot"
sys.path.insert(0, str(ROOT / "scripts"))

import ai_pilot


class AIPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.selection = json.loads((PILOT / "selection.json").read_text())
        cls.reviews = json.loads((PILOT / "reviews.json").read_text())

    def test_selection_covers_distinct_groups_and_requested_strata(self):
        self.assertEqual(len(self.selection), 50)
        self.assertEqual(len({group["id"] for group in self.selection}), 50)
        self.assertEqual(Counter(group["stratum"] for group in self.selection), {
            "high_volume": 12, "other_small": 12, "other_medium": 10,
            "linked": 8, "large": 4, "multi_pr": 4,
        })

    def test_each_group_has_a_review_or_explained_abstention(self):
        self.assertEqual(len(self.reviews), len(self.selection))
        for index, (group, review) in enumerate(zip(self.selection, self.reviews), 1):
            with self.subTest(index=index):
                self.assertEqual(review["index"], index)
                self.assertIn(review["score"], (1, 2, 3, None))
                self.assertTrue(review["reason"])
                if review["score"] is None:
                    self.assertEqual(review["confidence"], "none")
                    self.assertFalse(review["evidence"])
                else:
                    self.assertIn(review["confidence"], ("low", "medium", "high"))
                    self.assertTrue(review["evidence"])
                    self.assertEqual(
                        set(map(str, group["prs"])), set(group["diff_sha256"])
                    )

    def test_cached_diffs_match_the_selection_and_support_evidence_paths(self):
        for group, review in zip(self.selection, self.reviews):
            patches = []
            for number, digest in group["diff_sha256"].items():
                patch_path = PILOT / "diffs" / f"{number}.diff"
                if patch_path.exists():
                    patch = patch_path.read_bytes()
                    self.assertEqual(hashlib.sha256(patch).hexdigest(), digest)
                    patches.append(patch.decode(errors="replace"))
            if review["score"] is not None and patches:
                for path in review["evidence"].split("; "):
                    with self.subTest(group=group["id"], path=path):
                        self.assertTrue(any(f" b/{path}\n" in patch for patch in patches))

    def test_refetch_clears_stale_errors_but_rejects_invalid_cached_patch(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(ai_pilot, "OUT", Path(temp)):
            diff = Path(temp) / "diffs" / "123.diff"
            diff.parent.mkdir()
            group = {"id": "test", "prs": [123], "fetch_errors": {"123": "old error"}}
            with patch.object(ai_pilot.subprocess, "run", side_effect=AssertionError("unexpected network")):
                diff.write_bytes(b"diff --git a/code.py b/code.py\n")
                self.assertNotIn("fetch_errors", ai_pilot.fetch([group])[0])
                diff.write_bytes(b"not a patch")
                self.assertEqual(
                    ai_pilot.fetch([group])[0]["fetch_errors"],
                    {"123": "GitHub returned no usable diff"},
                )


if __name__ == "__main__":
    unittest.main()
