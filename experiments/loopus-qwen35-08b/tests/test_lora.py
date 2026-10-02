import torch

from conftest import build_tiny
from src.looped import LoopedQwen35
from src.lora import LoRALinear, lora_parameters
from src.train_loopus import (ConfidenceHead, TrainCfg, build_model, load_checkpoint, save_trainable, set_trainable,
                              train)

SPLIT = dict(enc=(0, 1), reasoning=(2, 6), dec=(7, 7))


def _batches(seed=0):
    g = torch.Generator().manual_seed(seed)
    x = torch.randint(1, 256, (4, 24), generator=g)
    while True:
        yield x, torch.ones_like(x), x.clone()


def test_lora_is_bit_identical_to_base_at_init(tiny):
    x = torch.randint(1, 256, (2, 16))
    with torch.no_grad():
        ref = LoopedQwen35(tiny, **SPLIT)(x, None, R=1).clone()
    m = build_model(tiny, gate="sigmoid", scope="lora", lora_rank=4, split=SPLIT)      # wraps tiny in place
    assert sum(isinstance(mod, LoRALinear) for mod in m.modules()) > 0
    with torch.no_grad():
        assert torch.equal(ref, m(x, None, R=1))


def test_lora_wraps_only_block_and_decoder_and_skips_tiny_projections(tiny):
    m = build_model(tiny, gate="sigmoid", scope="lora", lora_rank=4, split=SPLIT)
    wrapped = [n for n, mod in m.named_modules() if isinstance(mod, LoRALinear)]
    assert wrapped and not any(".layers.0." in "." + n or ".layers.1." in "." + n for n in wrapped)
    assert not any(n.endswith(("in_proj_a", "in_proj_b")) for n in wrapped)
    assert any(n.endswith("mlp.down_proj") for n in wrapped)


def test_lora_scope_trains_only_adapters_and_gate(tiny):
    m = build_model(tiny, gate="sigmoid", scope="lora", lora_rank=4, split=SPLIT)
    params = set_trainable(m, "lora")
    names = [n for n, p in m.named_parameters() if p.requires_grad]
    assert len(params) == len(names)
    assert all(n.startswith("gate.") or n.endswith((".A", ".B")) for n in names)
    assert not any(".base." in n for n in names)


def test_lora_training_updates_adapters_not_base_and_reduces_loss(tiny):
    m = build_model(tiny, gate="sigmoid", scope="lora", lora_rank=4, split=SPLIT)
    conf = ConfidenceHead(tiny.config.hidden_size)
    before = {n: p.detach().clone() for n, p in m.named_parameters()}
    hist = train(m, conf, _batches(), steps=40,
                 cfg=TrainCfg(n_reasoning_steps=4, n_supervision=2, lr=3e-3, scope="lora", log_every=0))
    changed = {n for n, p in m.named_parameters() if not torch.equal(p, before[n])}
    assert any(n.endswith(".B") for n in changed)
    assert all(n.startswith("gate.") or n.endswith((".A", ".B")) for n in changed)
    assert sum(h["loss"] for h in hist[-5:]) < sum(h["loss"] for h in hist[:5])


def test_checkpoint_is_self_describing_and_roundtrips(tiny, tmp_path):
    m = build_model(tiny, gate="sigmoid", scope="lora", lora_rank=4, gate_kwargs=dict(g0=0.2), split=SPLIT)
    conf = ConfidenceHead(tiny.config.hidden_size)
    train(m, conf, _batches(), steps=3,
          cfg=TrainCfg(n_reasoning_steps=3, n_supervision=2, lr=1e-2, scope="lora", log_every=0))
    meta = dict(gate="sigmoid", scope="lora", lora_rank=4, lora_alpha=None, gate_kwargs=dict(g0=0.2), split=SPLIT)
    save_trainable(m, conf, str(tmp_path / "t.pt"), meta)
    fresh, _, got = load_checkpoint(build_tiny(), str(tmp_path / "t.pt"), "cpu")
    assert got["lora_rank"] == 4 and got["gate"] == "sigmoid"
    x = torch.randint(1, 256, (2, 12))
    with torch.no_grad():
        for R in (1, 3):
            assert torch.equal(m(x, None, R=R), fresh(x, None, R=R))
    assert sum(1 for _ in lora_parameters(fresh)) == sum(1 for _ in lora_parameters(m))
