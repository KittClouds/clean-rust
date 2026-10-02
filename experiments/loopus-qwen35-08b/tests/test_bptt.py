import torch

from conftest import build_tiny
from src.bptt import bptt_loss, train_bptt
from src.lora import LoRALinear
from src.train_loopus import ConfidenceHead, TrainCfg, build_model, load_checkpoint, save_trainable, set_trainable

SPLIT = dict(enc=(0, 1), reasoning=(2, 6), dec=(7, 7))


def _model(tiny, passes, gc=False, gate="none"):
    return build_model(tiny, gate=gate, scope="lora", lora_rank=4, split=SPLIT, lora_passes=passes, grad_checkpoint=gc)


def _perturb(m, seed=0):
    g = torch.Generator().manual_seed(seed)
    for p in m.parameters():
        if p.requires_grad or p.dtype == torch.float32:
            pass
    for mod in m.modules():
        if isinstance(mod, LoRALinear):
            ps = [mod.B] if mod.n_passes == 1 else list(mod.B)
            for p in ps:
                p.data.copy_(torch.randn(p.shape, generator=g) * 0.05)


def test_per_pass_adapters_apply_the_right_pass(tiny):
    m = _model(tiny, 2)
    _perturb(m)
    x = torch.randint(1, 256, (2, 12))
    with torch.no_grad():
        ctx = m.prepare(x, None)
        h1 = m.step(m.encode(ctx), ctx, first=True)
        h2 = m.step(h1, ctx, first=False)
        # manual: run the block with pass-0 adapters then pass-1 adapters
        h = m.encode(ctx)
        for p in (0, 1):
            for i in m.rea_idx:
                m._set_pass(i, p)
                h = m.text.layers[i](
                    h, position_embeddings=ctx.position_embeddings, attention_mask=ctx.masks[m.cfg.layer_types[i]],
                    position_ids=ctx.text_position_ids, past_key_values=None, use_cache=False)
        assert torch.allclose(h, h2, atol=1e-5)
        # and passes genuinely differ: swapping adapter sets changes the output
        for mod in m.modules():
            if isinstance(mod, LoRALinear) and mod.n_passes == 2:
                mod.B[0].data, mod.B[1].data = mod.B[1].data.clone(), mod.B[0].data.clone()
        ctx = m.prepare(x, None)
        h1b = m.step(m.encode(ctx), ctx, first=True)
        assert not torch.allclose(h1, h1b, atol=1e-4)


def test_checkpointed_gradients_equal_plain_gradients_with_per_pass_adapters(tiny):
    x = torch.randint(1, 256, (3, 16))
    mk = torch.ones_like(x)
    grads = []
    for gc in (False, True):
        m = _model(build_tiny(), 2, gc=gc)
        _perturb(m)
        set_trainable(m, "lora")
        m.train()
        with torch.no_grad():
            ctx = m.prepare(x, mk)
            h0 = m.encode(ctx)
        loss, _ = bptt_loss(m, ctx, h0, 2, x.clone(), mk)
        loss.backward()
        grads.append(torch.cat([p.grad.flatten() for n, p in m.named_parameters() if p.requires_grad]))
    assert grads[0].norm() > 0
    assert torch.allclose(grads[0], grads[1], atol=1e-5, rtol=1e-4)


def test_gradient_flows_through_pass_one_and_pass_two_adapters(tiny):
    m = _model(tiny, 2)
    _perturb(m)
    set_trainable(m, "lora")
    x = torch.randint(1, 256, (2, 12))
    mk = torch.ones_like(x)
    with torch.no_grad():
        ctx = m.prepare(x, mk)
        h0 = m.encode(ctx)
    loss, _ = bptt_loss(m, ctx, h0, 2, x.clone(), mk)
    loss.backward()
    for mod in m.modules():
        if isinstance(mod, LoRALinear) and mod.n_passes == 2:
            assert mod.B[0].grad is not None and mod.B[0].grad.abs().sum() > 0     # pass 1: only via full backprop
            assert mod.B[1].grad is not None and mod.B[1].grad.abs().sum() > 0
            break


def test_warm_start_from_single_adapter_copies_into_every_pass_and_roundtrips(tiny, tmp_path):
    single = build_model(build_tiny(), gate="none", scope="lora", lora_rank=4, split=SPLIT)
    _perturb(single)
    conf = ConfidenceHead(tiny.config.hidden_size)
    meta1 = dict(gate="none", scope="lora", lora_rank=4, lora_alpha=None, gate_kwargs=None, split=SPLIT)
    save_trainable(single, conf, str(tmp_path / "one.pt"), meta1)
    from src.train_loopus import load_trainable
    two = _model(build_tiny(), 2)
    load_trainable(two, conf, str(tmp_path / "one.pt"))
    x = torch.randint(1, 256, (2, 12))
    with torch.no_grad():               # both passes start as copies of the single adapter, so R=1 is identical
        assert torch.allclose(single(x, None, R=1), two(x, None, R=1), atol=1e-6)
    # per-pass checkpoint rebuilds itself
    meta2 = dict(meta1, lora_passes=2)
    save_trainable(two, conf, str(tmp_path / "two.pt"), meta2)
    fresh, _, got = load_checkpoint(build_tiny(), str(tmp_path / "two.pt"), "cpu")
    with torch.no_grad():
        assert torch.equal(two(x, None, R=2), fresh(x, None, R=2))


def test_train_bptt_reduces_loss(tiny):
    m = _model(tiny, 2)
    g = torch.Generator().manual_seed(0)
    xb = torch.randint(1, 256, (4, 20), generator=g)

    def it():
        while True:
            yield xb, torch.ones_like(xb), xb.clone()
    hist = train_bptt(m, it(), 40, TrainCfg(n_reasoning_steps=2, lr=3e-3, scope="lora", log_every=0))
    assert sum(h["loss"] for h in hist[-5:]) < sum(h["loss"] for h in hist[:5])
