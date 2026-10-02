import math

import torch

from src.gate import LoopUSGate, SigmoidGate, build_gate
from src.loopcd import adaptive_strength, contrast_hidden, contrast_logits
from src.looped import LoopedQwen35
from src.readout import contrast_logit_stats, token_stats

SPLIT = dict(enc=(0, 1), reasoning=(2, 6), dec=(7, 7))


def test_build_gate():
    assert build_gate("none", 8) is None
    assert isinstance(build_gate("loopus", 32), LoopUSGate)
    assert isinstance(build_gate("sigmoid", 32), SigmoidGate)


def test_loopus_gate_is_convex_combination_and_mixed_at_init():
    torch.manual_seed(0)
    g = LoopUSGate(64)
    h_old, h_new = torch.randn(2, 5, 64), torch.randn(2, 5, 64)
    out = g(h_new, h_old)
    frac = (out - h_old) / (h_new - h_old)
    assert frac.min() >= -1e-4 and frac.max() <= 1 + 1e-4          # A_bar in (0, 1) per channel
    # S4D-real spread: low-index channels accept the update, high-index channels hold the old state
    a = torch.exp(torch.nn.functional.softplus(g.delta_proj.bias) * -torch.exp(g.A_log))
    assert ((a > 0) & (a < 1)).all() and a[:16].mean() > a[-16:].mean() + 0.2
    assert 0 < g.mean_gate() < 1


def test_sigmoid_gate_identity_init_is_uniform_g0():
    g = SigmoidGate(64, g0=0.05)
    h_old, h_new = torch.randn(2, 5, 64), torch.randn(2, 5, 64)
    assert torch.allclose(g(h_new, h_old), h_old + 0.05 * (h_new - h_old), atol=1e-6)
    assert math.isclose(g.mean_gate(), 0.05, rel_tol=1e-5)


def test_tiny_g0_loop_is_near_baseline(tiny):
    m = LoopedQwen35(tiny, gate="sigmoid", gate_kwargs=dict(g0=1e-6), **SPLIT)
    x = torch.randint(1, 256, (2, 12))
    with torch.no_grad():
        assert torch.allclose(m(x, None, R=1), m(x, None, R=6), atol=1e-3)


def test_gate_stays_finite_when_ungated_loop_blows_up(tiny):
    """Mechanism the experiment relies on: damping bounds the state norm growth of repeated passes."""
    x = torch.randint(1, 256, (2, 12))
    with torch.no_grad():
        plain = LoopedQwen35(tiny, **SPLIT)
        gated = LoopedQwen35(tiny, gate="sigmoid", gate_kwargs=dict(g0=0.05), **SPLIT)
        n_plain = plain.states(x, None, depths=(1, 8))[0]
        n_gated = gated.states(x, None, depths=(1, 8))[0]
        grow_p = n_plain[8].norm() / n_plain[1].norm()
        grow_g = n_gated[8].norm() / n_gated[1].norm()
    assert torch.isfinite(grow_g) and grow_g <= grow_p + 1e-6


def test_loopcd_identities():
    h1, hr = torch.randn(2, 4, 8), torch.randn(2, 4, 8)
    assert torch.equal(contrast_hidden(h1, hr, 0.0), hr)
    assert torch.allclose(contrast_hidden(h1, hr, 1.0), 2 * hr - h1)
    assert torch.allclose(contrast_logits(h1, hr, 0.5), hr + 0.5 * (hr - h1))
    w = torch.rand(2, 4, 1)
    assert torch.allclose(contrast_hidden(h1, hr, w), hr + w * (hr - h1))


def test_adaptive_strength_bounds_and_direction():
    confident = torch.tensor([[[10.0, 0.0, 0.0, 0.0]]])
    unsure = torch.tensor([[[1.0, 1.0, 0.0, 0.0]]])
    wc, wu = adaptive_strength(confident, 2.0), adaptive_strength(unsure, 2.0)
    assert wu > wc and 0.0 <= float(wc) <= 2.0 and abs(float(wu) - 2.0) < 1e-6   # p1 == p2 -> full strength


def test_contrast_logit_stats_matches_direct(tiny):
    torch.manual_seed(0)
    w = torch.randn(32, 8)
    h1, hr = torch.randn(10, 8), torch.randn(10, 8)
    y = torch.randint(0, 32, (10,))
    y[3] = -100
    s0 = contrast_logit_stats(h1, hr, w, y, omega=0.0)
    ref = token_stats(hr, w, y)
    assert s0["n"] == ref["n"] == 9 and abs(s0["nll"] - ref["nll"]) < 1e-4 and s0["correct"] == ref["correct"]
    s1 = contrast_logit_stats(h1, hr, w, y, omega=0.7)
    z = (hr @ w.t()) + 0.7 * ((hr @ w.t()) - (h1 @ w.t()))
    m = y != -100
    direct = torch.nn.functional.cross_entropy(z[m], y[m], reduction="sum")
    assert abs(s1["nll"] - float(direct)) < 1e-4


def test_contrast_hidden_keeps_state_dtype_with_fp32_per_token_strength():
    """Regression: adaptive strength is fp32; the contrast must not promote a bf16 state."""
    from src.loopcd import contrast_hidden
    h1 = torch.randn(2, 5, 8).bfloat16()
    hR = torch.randn(2, 5, 8).bfloat16()
    w = torch.rand(2, 5, 1)                       # fp32, like adaptive_strength() returns
    out = contrast_hidden(h1, hR, w)
    assert out.dtype == torch.bfloat16
    ref = hR.float() + w * (hR.float() - h1.float())
    assert torch.allclose(out.float(), ref, atol=2e-2, rtol=2e-2)
