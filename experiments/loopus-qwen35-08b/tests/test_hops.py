import random

import torch

from conftest import build_tiny
from src import hops as H
from src.looped import LoopedQwen35

SPLIT = dict(enc=(0, 1), reasoning=(2, 6), dec=(7, 7))


class CharTok:
    """Byte-level stand-in tokenizer; ids < 256 so the tiny model's vocab covers it."""
    pad_token_id = 0
    eos_token_id = 0

    def __call__(self, text, add_special_tokens=False):
        if len(text) == 2 and text[0] == " ":            # " X" is ONE token, like the real tokenizer
            return {"input_ids": [ord(text[1]) + 100]}
        return {"input_ids": list(text.encode())}


def _follow(prompt: str, k: int) -> str:
    edges = dict(e.split(">") for e in prompt.split("\n")[0].split(" "))
    cur = prompt.split("\n")[1].split(",")[0].split(" ")[1]
    for _ in range(k):
        cur = edges[cur]
    return cur


def test_answer_is_k_step_traversal_of_the_stated_graph():
    rng = random.Random(0)
    for k in range(1, 9):
        for _ in range(30):
            prompt, ans, kk = H.make_example(rng, k)
            assert kk == k and ans == " " + _follow(prompt, k)
            assert f"{k} steps" in prompt


def test_every_node_has_exactly_one_out_edge():
    prompt, _, _ = H.make_example(random.Random(1), 3, n_nodes=10)
    srcs = [e.split(">")[0] for e in prompt.split("\n")[0].split(" ")]
    assert len(srcs) == 10 == len(set(srcs))


def test_collate_labels_only_at_answer_and_masks_padding():
    tok = CharTok()
    ex = H.build_set(tok, 6, [1, 4], seed=3)
    x, m, y, ks = H.collate(ex, pad_id=0)
    assert ((y != -100).sum(1) == 1).all()                      # one supervised token per row
    for i, (ids, k) in enumerate(ex):
        n = len(ids)
        assert int(m[i].sum()) == n and y[i, n - 1] == ids[-1] and x[i, n - 1] == ids[-1]
        assert (m[i, n:] == 0).all() and int(ks[i]) == k


def test_train_batches_are_fresh_each_time():
    it = H.train_batches(CharTok(), [2], 4, seed=0)
    a, b = next(it)[0], next(it)[0]
    assert not torch.equal(a, b)


def test_evaluate_hops_readout_position_matches_full_forward():
    """The answer is predicted from index len-2: check against a plain full-logit forward."""
    tiny = build_tiny()
    m = LoopedQwen35(tiny, **SPLIT)
    tok = CharTok()
    ex = H.build_set(tok, 10, [1, 2, 3], seed=5)
    res = H.evaluate_hops(m, tok, ex, depths=[1, 3], batch_size=4, device="cpu")
    x, mask, y, ks = H.collate(ex, 0)
    with torch.no_grad():
        for R in (1, 3):
            logits = m(x, mask, R=R).float()
            nll, cor = {}, {}
            for i in range(x.shape[0]):
                n = int(mask[i].sum())
                lp = torch.log_softmax(logits[i, n - 2], -1)
                tgt = int(x[i, n - 1])
                k = int(ks[i])
                nll.setdefault(k, []).append(-float(lp[tgt]))
                cor.setdefault(k, []).append(float(lp.argmax() == tgt))
            for k in nll:
                assert abs(res[R][k]["nll"] - sum(nll[k]) / len(nll[k])) < 1e-4
                assert abs(res[R][k]["acc"] - sum(cor[k]) / len(cor[k])) < 1e-9
                assert res[R][k]["n"] == len(nll[k])
    assert res[1]["all"]["n"] == 10


def test_depth_matched_label_fn_masks_by_hops_and_depth():
    ks = torch.tensor([1, 3, 4, 7, 12])
    y = torch.arange(1, 6)[:, None].expand(5, 4).clone()          # every position labelled
    fn = H.depth_matched(3)
    for t, expect in [(1, [1, 1, 0, 0, 0]), (2, [1, 1, 1, 0, 0]), (3, [1, 1, 1, 1, 0]), (4, [1, 1, 1, 1, 1])]:
        out = fn(t, y, ks)
        assert [int((r != -100).all()) for r in out] == expect, t
        assert [int((r == -100).all()) for r in out] == [1 - e for e in expect]


def test_train_supports_aux_and_skips_depths_with_no_labels(tiny):
    from src.train_loopus import ConfidenceHead, TrainCfg, train
    m = LoopedQwen35(tiny, gate="sigmoid", **SPLIT)
    conf = ConfidenceHead(tiny.config.hidden_size)
    tok = CharTok()
    it = H.train_batches(tok, [1, 6], 4, seed=0, with_ks=True)
    # c=1: depth t supervises k<=t. Depth 1 only sees k=1 examples; a batch with none must not crash.
    hist = train(m, conf, it, steps=12, cfg=TrainCfg(n_reasoning_steps=3, n_supervision=2, lr=1e-3,
                                                     log_every=0, seed=0),
                 label_fn=H.depth_matched(1))
    assert len(hist) == 12 and all(torch.isfinite(torch.tensor(h["loss"])) for h in hist)


def test_loopcd_hops_base_matches_evaluate_and_zero_omega_is_identity():
    tiny = build_tiny()
    m = LoopedQwen35(tiny, gate="sigmoid", gate_kwargs=dict(g0=0.4), **SPLIT)
    tok = CharTok()
    ex = H.build_set(tok, 12, [1, 2, 3], seed=7)
    ref = H.evaluate_hops(m, tok, ex, [3], batch_size=5, device="cpu")[3]
    cd = H.evaluate_hops_loopcd(m, tok, ex, R=3, omegas=(0.0, 0.5), batch_size=5, device="cpu")
    for k in (1, 2, 3):
        if k in ref:
            assert abs(cd["base"][k]["nll"] - ref[k]["nll"]) < 1e-4
            for v in ("logits_w0.0", "hidden_w0.0"):               # omega = 0 must reproduce z_R exactly
                assert abs(cd[v][k]["nll"] - ref[k]["nll"]) < 1e-3, v
    assert set(cd) >= {"base", "logits_w0.5", "hidden_w0.5", "logits_adaptive", "hidden_adaptive"}
    assert cd["base"]["all"]["n"] == 12
