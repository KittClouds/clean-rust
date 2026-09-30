"""VCS-0.1 population builder: independent population labels + availability-typed coordinates.

Populations:
  solvability         - simulator BFS verdict on the latent world (REACHABLE / STUCK /
                        ALREADY_SATISFIED). Reads no ABI coordinate.
  observer_correctness - whether the fitted head's argmax equals the canonical answer class.
                        Reads the head output, not any ABI coordinate value.

Coordinates are filled by availability class, from strictly separate sources, so that the
G0..G3 ladder measures something real rather than re-partitioning one source.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import torch

from src.vcs_abi_v02 import new_state, set_coord

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
PRIM = Path(r"D:\codex-runs\encoder-contrast-01\primitives")

_spec = importlib.util.spec_from_file_location("vcs_readout", EXP.parent / "encoder-contrast-01" / "src" / "readout.py")
_ro = importlib.util.module_from_spec(_spec); sys.modules["vcs_readout"] = _ro; _spec.loader.exec_module(_ro)
fit_linear = _ro.fit_linear

_sim_spec = importlib.util.spec_from_file_location("vcs_bank_sim", EXP.parent / "ff-s15-bank-01" / "src" / "simulator.py")
sim = importlib.util.module_from_spec(_sim_spec); sys.modules["vcs_bank_sim"] = sim; _sim_spec.loader.exec_module(sim)

PRED_WORDS = ["is in", "connects to", "requires", "blocked", "is before", "part of",
              "enables", "owns", "is active", "is inactive", "has"]
NEGATION = ["not", "never", "no ", "cannot", "instead of", "exception"]


def read_jsonl(p, limit=None):
    out = []
    with p.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            if line.strip():
                out.append(json.loads(line))
    return out


class HeadBank:
    def __init__(self, substrate, surface, seed=0):
        self.substrate, self.surface, self.seed = substrate, surface, seed

    def fit(self, steps=300, train_limit=20000):
        p = torch.load(PRIM / self.substrate / "TRAIN.pt", map_location="cpu", weights_only=False)
        rows = read_jsonl(BANK / "inputs" / "TRAIN.jsonl", train_limit)
        idx, ys = [], []
        for i, r in enumerate(rows):
            pol = (r.get("labels") or {}).get("policy") or {}
            if pol.get("decision") == "ACT" and pol.get("action"):
                idx.append(i)
                ys.append(json.dumps({"a": pol["action"], "g": pol.get("arguments", {})}, sort_keys=True))
        self.classes = sorted(set(ys))
        lmap = {c: k for k, c in enumerate(self.classes)}
        X = p["surfaces"][self.surface].float()[idx]
        self.mu, self.sd = X.mean(0), X.std(0).clamp(min=1e-4)
        self.net = fit_linear((X - self.mu) / self.sd, torch.tensor([lmap[v] for v in ys]),
                              len(self.classes), steps=steps, seed=self.seed)
        return self

    def probs(self, F):
        with torch.no_grad():
            return torch.softmax(self.net((F - self.mu) / self.sd), 1)

    def descriptor(self):
        return {"substrate": self.substrate, "surface": self.surface, "seed": self.seed,
                "n_classes": len(self.classes)}


def solver_population(w):
    """INDEPENDENT of every ABI coordinate: a simulator verdict on the latent world."""
    state, avail, goal = w["initial_state"], w["available_actions"], w["goal"]
    if sim.goal_satisfied(state, goal):
        return "ALREADY_SATISFIED", 0
    plan = sim.shortest_plan(state, avail, goal, max_depth=5)
    if plan is None:
        return "STUCK", None
    return "REACHABLE", len(plan)


def observation_coords(text, token_count, tokenizer=None):
    low = text.lower()
    goal_at = low.find("goal")
    return {
        "n_tokens": float(token_count),
        "n_sentences": float(text.count(".") + text.count("\n")),
        "has_goal_clause": 1.0 if goal_at >= 0 else 0.0,
        "goal_position_frac": (goal_at / max(len(text), 1)) if goal_at >= 0 else -1.0,
    }


def build_population(substrate, surface, rows, worlds_by_id, cell, head, tokenizer):
    p = torch.load(PRIM / substrate / f"{cell}.pt", map_location="cpu", weights_only=False)
    row_of = {wid: k for k, wid in enumerate(p["row_ids"])}
    F = p["surfaces"][surface]
    out = []
    for r in rows:
        wid = r["world_id"]
        w = worlds_by_id.get(wid)
        if w is None:
            continue
        j = row_of.get(wid)
        if j is None or j >= F.shape[0]:
            continue
        text = r["input_text"]
        mentions = [b.get("mention") or "" for b in r.get("bindings", [])]
        low = text.lower()
        ntok = len(tokenizer(text, add_special_tokens=False)["input_ids"])

        st = new_state()
        # ---- DIRECT_OBSERVATION (rendering only) ----
        for k, v in observation_coords(text, ntok, tokenizer).items():
            set_coord(st, "observation", k, v, "tokenizer+surface_scan")
        set_coord(st, "representation", "substrate", substrate, "modelcard")
        set_coord(st, "representation", "surface", surface, "modelcard")
        # ---- DETERMINISTIC_DERIVATION (parse the rendering) ----
        span_chars = sum(len(m) for m in mentions if m and m in text)
        set_coord(st, "derivation", "n_distinct_mentions", float(len({m for m in mentions if m})), "mention_scan")
        set_coord(st, "derivation", "n_mention_tokens", float(span_chars), "mention_scan")
        set_coord(st, "derivation", "mention_density", span_chars / max(len(text), 1), "mention_scan")
        set_coord(st, "derivation", "n_fact_lines", float(text.count("\n") + text.count(";")), "line_scan")
        set_coord(st, "derivation", "has_negation_word", 1.0 if any(x in low for x in NEGATION) else 0.0, "surface_scan")
        set_coord(st, "derivation", "n_predicate_words", float(sum(low.count(x) for x in PRED_WORDS)), "lexicon_scan")
        # type families inferred from mention SHAPE only (suffix/prefix heuristics), no truth
        fam = set()
        for m in mentions:
            if not m:
                continue
            for suf in ("_object", "_switch", "_agent", "_chamber", "_hall", "_vault", "_crate", "_cell"):
                if m.endswith(suf):
                    fam.add(suf); break
            else:
                fam.add("bare")
        set_coord(st, "derivation", "n_distinct_entity_types", float(len(fam)), "mention_shape_scan")
        # ---- OBSERVER_ESTIMATE ----
        probs = head.probs(F[j].float().unsqueeze(0))[0]
        srt = torch.sort(probs, descending=True).values
        set_coord(st, "observer", "top_choice_prob", float(probs.max()), head.descriptor()["substrate"])
        set_coord(st, "observer", "margin", float(srt[0] - srt[1]) if len(srt) > 1 else 0.0, "head")
        set_coord(st, "observer", "entropy",
                  float(-(probs.clamp(min=1e-12) * probs.clamp(min=1e-12).log()).sum()), "head")
        legal = sim.legal_actions(w["initial_state"], w["available_actions"])
        key = lambda a: json.dumps({"a": a.get("type"), "g": a.get("args", {})}, sort_keys=True)
        lk = {key(a) for a in legal}
        set_coord(st, "observer", "legal_set_support",
                  float(sum(float(probs[c]) for c, n in enumerate(head.classes) if n in lk)), "head+simulator")
        # ---- TRUTH_ONLY ----
        gold = w.get("selected_action")
        gold_legal = bool(gold and gold in legal)
        plan = sim.shortest_plan(w["initial_state"], w["available_actions"], w["goal"], max_depth=5)
        n_repair = sum(1 for a in legal if sim.apply_action(w["initial_state"], a) != w["initial_state"])
        set_coord(st, "truth", "gold_action_legal", gold_legal, "simulator")
        set_coord(st, "truth", "n_legal_actions", float(len(legal)), "simulator")
        set_coord(st, "truth", "n_repair_alternatives", float(n_repair), "simulator")
        set_coord(st, "truth", "goal_distance", float(len(plan)) if plan is not None else -1.0, "simulator")
        set_coord(st, "truth", "has_contradiction", bool(w.get("contradictions")), "bank_world")
        set_coord(st, "truth", "n_missing_facts", float(len(w.get("missing_information") or [])), "bank_world")
        set_coord(st, "truth", "n_evidence_facts", float(len(w.get("evidence_facts") or [])), "bank_world")
        set_coord(st, "truth", "legal_set_size_minus_gold", float(max(len(legal) - (1 if gold_legal else 0), 0)), "simulator")
        # stated path length when the rendering states one; NaN-free sentinel otherwise
        import re as _re
        m = _re.search(r"in (\d+) step", text.lower())
        set_coord(st, "truth", "goal_distance_visible",
                  float(m.group(1)) if m else -1.0, "surface_scan_oracle_semantics")

        # ---- populations, computed independently ----
        solv, dist = solver_population(w)
        gold_key = key(gold) if gold else None
        pred_key = head.classes[int(probs.argmax())]
        out.append({"world_id": wid, "state": st,
                    "pop_solvability": solv,
                    "pop_correctness": "CORRECT" if (gold_key and pred_key == gold_key) else "INCORRECT"})
    return out
