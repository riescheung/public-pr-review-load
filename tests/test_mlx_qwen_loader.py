from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import mlx.core as mx
    import mlx.nn as nn
    from mlx_lm.tuner.lora import LoRALinear
    from mlx_lm.tuner.utils import linear_to_lora_layers
    from mlx_qwen_loader import GlobalScaleLinear, Model, ModelArgs, ScaledQuantizedLinear
except ImportError:
    mx = None


@unittest.skipIf(mx is None, "Requires the existing local MLX environment")
class MLXGlobalScaleTests(unittest.TestCase):
    def test_nvfp4_global_scale_is_applied_without_dequantizing(self):
        linear = GlobalScaleLinear(32, 16, bias=False)
        packed = linear.to_quantized(group_size=16, bits=4, mode="nvfp4", global_scale=True)
        self.assertIsInstance(packed, ScaledQuantizedLinear)
        packed.global_scale = mx.array(0.125)
        inputs = mx.ones((1, 32))
        raw = mx.quantized_matmul(
            inputs, packed.weight, scales=packed.scales, transpose=True,
            group_size=16, bits=4, mode="nvfp4",
        )
        self.assertTrue(mx.allclose(packed(inputs), raw * 0.125).item())

    def test_lora_gradients_work_with_the_scaled_packed_base(self):
        linear = GlobalScaleLinear(32, 16, bias=False)
        packed = linear.to_quantized(group_size=16, bits=4, mode="nvfp4", global_scale=True)
        packed.global_scale = mx.array(0.125)
        packed.freeze()
        layer = LoRALinear.from_base(packed, r=2, dropout=0, scale=1)
        inputs = mx.ones((1, 32))
        self.assertTrue(mx.allclose(layer(inputs), packed(inputs)).item())
        _, gradients = nn.value_and_grad(layer, lambda model: mx.sum(model(inputs)))(layer)
        self.assertTrue(mx.all(mx.isfinite(gradients["lora_b"])).item())
        self.assertGreater(mx.sum(mx.abs(gradients["lora_b"])).item(), 0)

    def test_frozen_recurrent_prefix_remains_in_inference_mode(self):
        args = ModelArgs.from_dict({"model_type": "qwen3_5", "text_config": {
            "model_type": "qwen3_5_text", "hidden_size": 32, "intermediate_size": 64,
            "num_hidden_layers": 4, "num_attention_heads": 4, "num_key_value_heads": 1,
            "head_dim": 8, "vocab_size": 64, "linear_num_value_heads": 1,
            "linear_num_key_heads": 1, "linear_key_head_dim": 32, "linear_value_head_dim": 32,
        }})
        model = Model(args)
        model.freeze()
        linear_to_lora_layers(model, 1, {"rank": 2, "scale": 1, "dropout": 0})
        model.train()
        self.assertEqual([layer.training for layer in model.layers], [False, False, False, True])
        model.eval()
        self.assertFalse(any(layer.training for layer in model.layers))


if __name__ == "__main__":
    unittest.main()
