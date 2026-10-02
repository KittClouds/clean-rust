import torch
import torch.nn.functional as F

from src import data as D
from src.eval_depth import evaluate_depths
from src.looped import LoopedQwen35
from src.readout import mean_ce, shift, token_stats, finalize_stats

SPLIT = dict(enc=(0, 1), reasoning=(2, 6), dec=(7, 7))


def test_chunked_ce_matches_dense_value_and_grad():
    torch.manual_seed(0)
    h = torch.randn(2, 9, 16, requires_grad=True)
    w = torch.randn(50, 16)
    y = torch.randint(0, 50, (2, 9))
    y[0, 4] = -100
    hh, yy = shift(h, y)
    ce, _ = mean_ce(hh, w, yy, chunk=5, grad=True)
    ce.backward()
    g_chunked = h.grad.clone()
    h.grad = None
    dense = F.cross_entropy((h[:, :-1] @ w.t()).reshape(-1, 50), y[:, 1:].reshape(-1), ignore_index=-100)
    dense.backward()
    assert torch.allclose(ce, dense, atol=1e-6) and torch.allclose(g_chunked, h.grad, atol=1e-6)


def test_token_stats_sums_merge_exactly():
    torch.manual_seed(0)
    h, w = torch.randn(40, 8), torch.randn(30, 8)
    y = torch.randint(0, 30, (40,))
    whole = token_stats(h, w, y, chunk=40)
    parts = token_stats(h, w, y, chunk=7)
    assert whole["n"] == parts["n"] and abs(whole["nll"] - parts["nll"]) < 1e-4
    f = finalize_stats(whole)
    assert 0 <= f["top1"] <= 1 and f["entropy"] > 0


def test_eval_r1_nll_equals_hf_loss(tiny):
    """End-to-end check of the evaluator against HF's own loss at R=1."""
    g = torch.Generator().manual_seed(3)
    windows = torch.randint(1, 256, (4, 32), generator=g)
    m = LoopedQwen35(tiny, **SPLIT)
    res = evaluate_depths(m, windows, depths=(1, 2, 4), batch_size=4, chunk=17)
    x = windows
    with torch.no_grad():
        hf_loss = float(tiny(input_ids=x, labels=x).loss)
    assert abs(res["depths"][1]["nll"] - hf_loss) < 1e-4
    assert res["depths"][1]["rel_drift_vs_h1"] == 0.0 and abs(res["depths"][1]["cos_vs_h1"] - 1) < 1e-5
    assert res["depths"][4]["rel_drift_vs_h1"] > 0
    assert set(res["depths"]) == {1, 2, 4}


def test_eval_loopcd_sweep_runs_and_zero_omega_is_identity(tiny):
    g = torch.Generator().manual_seed(4)
    windows = torch.randint(1, 256, (4, 32), generator=g)
    m = LoopedQwen35(tiny, **SPLIT)
    res = evaluate_depths(m, windows, depths=(1, 3), batch_size=2, loopcd=True, omegas=(0.0, 0.5))
    base = res["depths"][3]["nll"]
    assert abs(res["loopcd"]["hidden_w0.0"][3]["nll"] - base) < 1e-4
    assert abs(res["loopcd"]["logits_w0.0"][3]["nll"] - base) < 1e-4
    assert "logits_adaptive_wmax1.0" in res["loopcd"] and "hidden_adaptive_wmax1.0" in res["loopcd"]
    assert set(res["premise_hR_beats_h1"]) == {3}


def test_data_pack_and_split_are_deterministic(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text('{"input_text": "hello world"}\n{"text": "second doc"}\n{"other": 1}\n')
    texts = D.read_texts(p)
    assert texts == ["hello world", "second doc"]
    w = D.pack(texts, D.byte_tokenize, 4)
    assert w.shape == (5, 4)
    a, b = D.split_windows(w, 0.2, seed=0)
    a2, b2 = D.split_windows(w, 0.2, seed=0)
    assert torch.equal(a, a2) and torch.equal(b, b2) and a.shape[0] + b.shape[0] == 5
