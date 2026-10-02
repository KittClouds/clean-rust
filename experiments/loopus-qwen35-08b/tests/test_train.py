import copy

import torch

from conftest import build_tiny
from src.looped import LoopedQwen35
from src.train_loopus import ConfidenceHead, TrainCfg, adaptive_exit, set_trainable, train, save_trainable, load_trainable

SPLIT = dict(enc=(0, 1), reasoning=(2, 6), dec=(7, 7))


def _batches(n=1, seed=0):
    g = torch.Generator().manual_seed(seed)
    x = torch.randint(1, 256, (4, 24), generator=g)
    while True:
        yield x, torch.ones_like(x), x.clone()


def test_scopes_freeze_the_right_things(tiny):
    m = LoopedQwen35(tiny, gate="sigmoid", **SPLIT)
    set_trainable(m, "gate")
    assert {n.split(".")[0] for n, p in m.named_parameters() if p.requires_grad} == {"gate"}
    set_trainable(m, "block+dec")
    names = [n for n, p in m.named_parameters() if p.requires_grad]
    assert any("layers.2." in n for n in names) and any("layers.7." in n for n in names)
    assert not any("embed_tokens" in n or "lm_head" in n or "layers.0." in n or "layers.1." in n for n in names)


def test_training_runs_updates_the_right_params_and_reduces_loss(tiny):
    m = LoopedQwen35(tiny, gate="sigmoid", **SPLIT)
    conf = ConfidenceHead(tiny.config.hidden_size)
    before = {n: p.detach().clone() for n, p in m.named_parameters()}
    cfg = TrainCfg(n_reasoning_steps=4, n_supervision=2, lr=3e-3, log_every=0, seed=0)
    hist = train(m, conf, _batches(), steps=40, cfg=cfg)
    first = sum(h["loss"] for h in hist[:5]) / 5
    last = sum(h["loss"] for h in hist[-5:]) / 5
    assert last < first
    changed = {n for n, p in m.named_parameters() if not torch.equal(p, before[n])}
    assert any(n.startswith("gate.") for n in changed)
    assert any("layers.3." in n for n in changed) and any("layers.7." in n for n in changed)
    assert not any("embed_tokens" in n or "layers.0." in n or "layers.1." in n for n in changed)
    assert all(torch.isfinite(torch.tensor(h["grad_norm"])) for h in hist)
    assert {d["depth"] for h in hist for d in h["per_depth"]} <= {1, 2, 3, 4}


def test_supervised_depths_are_sampled_without_replacement_and_cover_range(tiny):
    m = LoopedQwen35(tiny, gate="sigmoid", **SPLIT)
    conf = ConfidenceHead(tiny.config.hidden_size)
    cfg = TrainCfg(n_reasoning_steps=5, n_supervision=3, lr=1e-4, log_every=0, seed=1)
    hist = train(m, conf, _batches(), steps=30, cfg=cfg)
    assert all(len(h["supervised"]) == 3 == len(set(h["supervised"])) for h in hist)
    assert {d for h in hist for d in h["supervised"]} == {1, 2, 3, 4, 5}


def test_save_and_load_trainable_roundtrip(tiny, tmp_path):
    m = LoopedQwen35(tiny, gate="sigmoid", **SPLIT)
    conf = ConfidenceHead(tiny.config.hidden_size)
    train(m, conf, _batches(), steps=3, cfg=TrainCfg(n_reasoning_steps=3, n_supervision=2, lr=1e-2, log_every=0))
    save_trainable(m, conf, str(tmp_path / "t.pt"))
    fresh_hf = build_tiny()                                  # same seed -> same pretrained weights
    fresh = LoopedQwen35(fresh_hf, gate="sigmoid", **SPLIT)
    fresh_conf = ConfidenceHead(tiny.config.hidden_size)
    load_trainable(fresh, fresh_conf, str(tmp_path / "t.pt"))
    x = torch.randint(1, 256, (2, 12))
    with torch.no_grad():
        assert torch.equal(m(x, None, R=3), fresh(x, None, R=3))


class FakeHead(torch.nn.Module):
    """Confidence by call count: seq0 always confident, seq1 from the 3rd call, seq2 never."""
    def __init__(self):
        super().__init__()
        self.calls = 0

    def forward(self, h):
        self.calls += 1
        out = torch.full(h.shape[:2], -10.0)
        out[0] = 10.0
        if self.calls >= 3:
            out[1] = 10.0
        return out


def test_adaptive_exit_is_per_sequence_and_matches_fixed_depth(tiny):
    m = LoopedQwen35(tiny, gate="sigmoid", gate_kwargs=dict(g0=0.3), **SPLIT)
    x = torch.randint(1, 256, (3, 16))
    normed, depth, ctx = adaptive_exit(m, FakeHead(), x, None, max_R=5, threshold=0.5)
    assert depth.tolist() == [1, 3, 5]
    with torch.no_grad():
        for b, d in enumerate(depth.tolist()):
            st, c = m.states(x, None, depths=(d,))
            assert torch.allclose(normed[b], m.decode(st[d], c)[b], atol=1e-5)


def test_adaptive_exit_threshold_extremes(tiny):
    m = LoopedQwen35(tiny, gate="sigmoid", **SPLIT)
    conf = ConfidenceHead(tiny.config.hidden_size)
    x = torch.randint(1, 256, (2, 10))
    _, d0, _ = adaptive_exit(m, conf, x, None, max_R=4, threshold=0.0)
    _, d1, _ = adaptive_exit(m, conf, x, None, max_R=4, threshold=1.01)
    assert d0.tolist() == [1, 1] and d1.tolist() == [4, 4]
