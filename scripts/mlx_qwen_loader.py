"""Keep Ollama's NVFP4 tensor-global scales in the installed MLX version."""

from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
from mlx.utils import tree_flatten, tree_map
from mlx_lm.models.qwen3_5 import Model as QwenModel, ModelArgs
from mlx_lm.utils import load_adapters, load_model, load_tokenizer


class ScaledQuantizedLinear(nn.QuantizedLinear):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.global_scale = mx.array(1.0)

    def __call__(self, inputs):
        return (super().__call__(inputs) * self.global_scale).astype(inputs.dtype)


class GlobalScaleLinear(nn.Linear):
    def to_quantized(self, group_size=64, bits=4, mode="affine", global_scale=False):
        if global_scale and "bias" in self:
            raise ValueError("A tensor-global scale on a biased linear is unsupported")
        cls = ScaledQuantizedLinear if global_scale else nn.QuantizedLinear
        return cls.from_linear(self, group_size=group_size, bits=bits, mode=mode)


class Model(QwenModel):
    def __init__(self, args):
        super().__init__(args)

        def replace(module):
            if type(module) is not nn.Linear:
                return module
            outputs, inputs = module.weight.shape
            converted = GlobalScaleLinear(inputs, outputs, bias="bias" in module)
            converted.update(module.parameters())
            return converted

        self.update_modules(tree_map(
            replace, self.leaf_modules(), is_leaf=nn.Module.is_module,
        ))

    def train(self, mode=True):
        super().train(mode)
        if mode:
            # A frozen prefix needs no gradients; keep its recurrent inference kernels.
            for layer in self.layers:
                if tree_flatten(layer.trainable_parameters()):
                    break
                layer.eval()
        return self


def get_classes(config):
    if config["model_type"] != "qwen3_5":
        raise ValueError("Only the pinned Qwen 3.5 architecture is supported")
    return Model, ModelArgs


def load_local_model(path, adapter_path=None, lazy=False):
    path = Path(path)
    if not path.is_dir() or not (path / "conversion_receipt.json").is_file():
        raise ValueError("A verified local Ollama text-weight conversion is required")
    model, config = load_model(path, lazy=lazy, get_model_classes=get_classes)
    if adapter_path is not None:
        model = load_adapters(model, adapter_path)
        model.eval()
    tokenizer = load_tokenizer(path, eos_token_ids=config.get("eos_token_id"))
    return model, tokenizer
