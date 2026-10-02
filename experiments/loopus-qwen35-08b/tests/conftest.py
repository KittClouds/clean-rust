import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transformers import Qwen3_5ForCausalLM, Qwen3_5TextConfig  # noqa: E402
import transformers.models.qwen3_5.modeling_qwen3_5 as _mq  # noqa: E402


def _cpu_safe(fn):
    """With Triton + fla installed, Transformers binds the GPU gated-delta kernel at import time and
    would hand it CPU tensors. Route CPU tensors to the pure-PyTorch reference, keep the fast kernel
    for CUDA tensors (the layer looks these names up in module globals at call time)."""
    ref = getattr(fn, "__wrapped__", fn)

    def call(*args, **kwargs):
        first = next((v for v in (*args, *kwargs.values()) if isinstance(v, torch.Tensor)), None)
        return (ref if first is None or first.device.type == "cpu" else fn)(*args, **kwargs)
    return call


for _name in ("torch_chunk_gated_delta_rule", "torch_recurrent_gated_delta_rule",
              "causal_conv1d_fn", "causal_conv1d_update"):
    setattr(_mq, _name, _cpu_safe(getattr(_mq, _name)))


def tiny_config(layers: int = 8, vocab: int = 256, tie: bool = True) -> Qwen3_5TextConfig:
    """Same family/structure as Qwen3.5-0.8B (hybrid 3:1 linear:full) at toy width."""
    return Qwen3_5TextConfig(
        vocab_size=vocab, hidden_size=64, intermediate_size=128, num_hidden_layers=layers,
        num_attention_heads=4, num_key_value_heads=2, head_dim=16,
        linear_key_head_dim=16, linear_value_head_dim=16, linear_num_key_heads=2, linear_num_value_heads=4,
        max_position_embeddings=512, tie_word_embeddings=tie, pad_token_id=0,
    )


def build_tiny(seed: int = 0, **kw) -> Qwen3_5ForCausalLM:
    torch.manual_seed(seed)
    return Qwen3_5ForCausalLM(tiny_config(**kw)).eval()


@pytest.fixture()
def tiny():
    return build_tiny()


@pytest.fixture()
def batch():
    g = torch.Generator().manual_seed(1)
    x = torch.randint(1, 256, (3, 24), generator=g)
    m = torch.ones_like(x)
    m[1, 18:] = 0            # right padding
    m[2, 20:] = 0
    return x, m
