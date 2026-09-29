"""The 13 preregistered zero-training risk scores (plus a random control) over one surface's decision and action probability vectors."""
from __future__ import annotations

import numpy as np

from .common import SEED, c1fit

NAMES = ("c1_min", "p_act", "p_action", "product", "dec_margin", "act_margin", "neg_dec_entropy", "neg_act_entropy", "neg_p_abstain", "neg_p_ask",
         "min_margins", "margin_product", "rank_mean")
CONTROL = "random_control"


def candidates(dec_ppm: np.ndarray, act_ppm: np.ndarray, truth_decision: np.ndarray, truth_action: np.ndarray) -> dict:
    """Rows where the decision head's top class is ACT (C1's gating), as float probabilities, with which of them are safe."""
    v = c1fit.views(dec_ppm, act_ppm)
    cand = v["dec_top"] == c1fit.ACT
    safe = (truth_decision == c1fit.ACT) & (v["act_top"] == truth_action)
    return {"d": dec_ppm[cand] / 1_000_000.0, "a": act_ppm[cand] / 1_000_000.0, "safe": safe[cand], "rows": int(cand.sum())}


def _entropy(p: np.ndarray) -> np.ndarray:
    return -np.sum(np.where(p > 0, p * np.log(np.where(p > 0, p, 1.0)), 0.0), axis=1)


def _ranks(x: np.ndarray) -> np.ndarray:
    r = np.empty(len(x))
    r[np.argsort(x, kind="stable")] = np.arange(len(x))
    return r


def all_scores(d: np.ndarray, a: np.ndarray, seed: int = SEED) -> dict:
    """name -> float array over the candidates; higher means safer to execute."""
    p_act, abstain, ask = d[:, c1fit.ACT], d[:, c1fit.ABSTAIN], d[:, c1fit.ASK]
    a_sorted = np.sort(a, axis=1)
    top, second = a_sorted[:, -1], a_sorted[:, -2]
    dec_margin = p_act - np.maximum(abstain, ask)
    act_margin = top - second
    out = {
        "c1_min": np.minimum(p_act, top), "p_act": p_act, "p_action": top, "product": p_act * top, "dec_margin": dec_margin, "act_margin": act_margin,
        "neg_dec_entropy": -_entropy(d), "neg_act_entropy": -_entropy(a), "neg_p_abstain": -abstain, "neg_p_ask": -ask,
        "min_margins": np.minimum(dec_margin, act_margin), "margin_product": dec_margin * act_margin, "rank_mean": (_ranks(dec_margin) + _ranks(act_margin)) / 2.0,
    }
    out[CONTROL] = np.random.default_rng(seed).random(len(p_act))
    return out
