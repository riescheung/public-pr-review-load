from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import mlx.core as mx
    import mlx.nn as nn
    from mlx_training_loss import completion_loss
except ImportError:
    mx = None


@unittest.skipIf(mx is None, "Requires the existing local MLX environment")
class MLXCompletionLossTests(unittest.TestCase):
    def test_completion_only_head_matches_full_head_loss_and_gradients(self):
        class TinyLanguageModel(nn.Module):
            def __init__(self):
                super().__init__()
                self.model = nn.Embedding(8, 4)
                self.lm_head = nn.Linear(4, 8, bias=False)
                self.args = SimpleNamespace(tie_word_embeddings=False)

        class TinyModel(nn.Module):
            def __init__(self):
                super().__init__()
                self.language_model = TinyLanguageModel()

        model = TinyModel()
        batch = mx.array([[1, 2, 3, 4, 5, 0, 0]])
        lengths = mx.array([[3, 5]])

        def full_loss(model):
            hidden = model.language_model.model(batch[:, :-1])
            logits = model.language_model.lm_head(hidden)
            losses = nn.losses.cross_entropy(logits, batch[:, 1:])
            # The two targets are the first assistant token and its end marker.
            return losses[:, 2:4].mean()

        expected, expected_grad = nn.value_and_grad(model, full_loss)(model)
        actual, actual_grad = nn.value_and_grad(
            model, lambda value: completion_loss(value, batch, lengths)[0],
        )(model)
        self.assertTrue(mx.allclose(expected, actual).item())
        self.assertTrue(mx.allclose(expected_grad["language_model"]["lm_head"]["weight"],
                                    actual_grad["language_model"]["lm_head"]["weight"]).item())
        self.assertEqual(completion_loss(model, batch, lengths)[1].item(), 2)


if __name__ == "__main__":
    unittest.main()
