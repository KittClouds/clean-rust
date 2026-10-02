import pytest
import torch

from conftest import build_tiny
from src.looped import LoopedQwen35, parse_split, weight_identity

SPLIT = dict(enc=(0, 1), reasoning=(2, 6), dec=(7, 7))     # block contains a full-attention layer (abs idx 3)


def test_hybrid_structure_and_lm_dispatch_precondition(tiny):
    """Documents why LoopUS's getattr(layer, 'attention_type', 'full_attention') is wrong here."""
    lt = tiny.config.layer_types
    assert lt.count("linear_attention") == 6 and lt.count("full_attention") == 2
    assert all(getattr(l, "attention_type", None) is None for l in tiny.model.layers)
    assert [l.block_type for l in tiny.model.layers] == lt


def test_split_must_partition():
    assert parse_split(8, (0, 1), (2, 6), (7, 7)) == ([0, 1], [2, 3, 4, 5, 6], [7])
    with pytest.raises(ValueError):
        parse_split(8, (0, 1), (3, 6), (7, 7))       # gap
    with pytest.raises(ValueError):
        parse_split(8, (0, 2), (2, 6), (7, 7))       # overlap


def test_r1_bit_exact_vs_hf_no_padding(tiny):
    m = LoopedQwen35(tiny, **SPLIT)
    x = torch.randint(1, 256, (2, 16))
    with torch.no_grad():
        assert torch.equal(tiny(input_ids=x).logits, m(x, None, R=1))


def test_r1_bit_exact_vs_hf_with_padding(tiny, batch):
    x, mask = batch
    m = LoopedQwen35(tiny, **SPLIT)
    with torch.no_grad():
        assert torch.equal(tiny(input_ids=x, attention_mask=mask).logits, m(x, mask, R=1))


@pytest.mark.parametrize("gate", ["loopus", "sigmoid"])
def test_r1_exact_even_with_gate(tiny, batch, gate):
    """First pass is never gated, so a gated model is still the pretrained model at R=1."""
    x, mask = batch
    m = LoopedQwen35(tiny, gate=gate, **SPLIT)
    with torch.no_grad():
        assert torch.equal(tiny(input_ids=x, attention_mask=mask).logits, m(x, mask, R=1))


def test_relative_index_dispatch_is_wrong(tiny, batch):
    """Negative control: dispatching on the index *within the block* breaks the model."""
    x, mask = batch

    class Wrong(LoopedQwen35):
        def _run(self, idx, h, ctx):
            for rel, i in enumerate(idx):
                layer = self.text.layers[i]
                mk = ctx.masks[self.cfg.layer_types[rel]]          # relative, not absolute
                h = layer(h, position_embeddings=ctx.position_embeddings, attention_mask=mk,
                          position_ids=ctx.text_position_ids, past_key_values=None, use_cache=False)
            return h

    ref = tiny(input_ids=x, attention_mask=mask).logits
    try:
        with torch.no_grad():
            out = Wrong(tiny, **SPLIT)(x, mask, R=1)
        assert not torch.equal(ref, out)
    except (RuntimeError, ValueError, TypeError, IndexError):
        pass   # a hard failure is also an acceptable demonstration


def test_weights_are_shared_not_copied(tiny):
    m = LoopedQwen35(tiny, **SPLIT)
    for i in range(8):
        assert all(a is b for a, b in zip(m.text.layers[i].parameters(), tiny.model.layers[i].parameters()))
    assert m.lm_head.weight is tiny.lm_head.weight


def test_weight_identity_handles_language_model_prefix(tiny):
    m = LoopedQwen35(tiny, **SPLIT)
    sd = {k.replace("model.", "model.language_model.", 1) if k.startswith("model.") else k: v.clone()
          for k, v in tiny.state_dict().items() if k != "lm_head.weight"}      # tied head absent, like the checkpoint
    r = weight_identity(m, sd)
    assert r["worst_abs_diff"] == 0.0 and not r["missing_in_checkpoint"]
    k = next(iter(sd))
    sd[k] = sd[k] + 1e-3
    assert weight_identity(m, sd)["worst_abs_diff"] > 0


def test_ungated_loop_is_plain_reapplication(tiny):
    m = LoopedQwen35(tiny, **SPLIT)
    x = torch.randint(1, 256, (2, 12))
    with torch.no_grad():
        st, ctx = m.states(x, None, depths=(1, 2, 3))
        h0 = m.encode(ctx)
        h1 = m.block(h0, ctx)
        h2 = m.block(h1, ctx)
        assert torch.equal(st[1], h1) and torch.equal(st[2], h2)
        assert not torch.allclose(m(x, None, R=1), m(x, None, R=3))


def test_deterministic_and_batch_independent(tiny, batch):
    x, mask = batch
    m = LoopedQwen35(tiny, gate="sigmoid", **SPLIT)
    with torch.no_grad():
        a = m(x, mask, R=3)
        assert torch.equal(a, m(x, mask, R=3))
        single = m(x[:1], mask[:1], R=3)
        assert torch.allclose(a[:1], single, atol=1e-5)
