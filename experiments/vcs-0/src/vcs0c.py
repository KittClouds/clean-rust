"""VCS-0c Operational Reconstruction.

Population: the exact 2,000-row R2a DEV export population. Paired-surface rows are kept as
separate observations and bootstrap is grouped by canonical `paired_world`.

Preflight: three-lane ID equality, published hash verification, paired_world recovery.
Fails hard, no substitution.

Arms: G2, G3-CHEAP, G3-BASE, G3-NER, G3-HYBRID-FIXED, G3-EVIDENCE-ONLY, G3-MISSING-ONLY,
O2 (G2 + truth versions of the same two coordinates), G0 (full non-circular oracle ceiling).
No encoder arm, no NLI arm: both failed the frozen R2a advancement gate.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import torch

from src.vcs_abi_v02 import (COORD_ORDER, PROV, RUNTIME, UNAVAILABLE, AVAILABLE,
                             circular_columns, numeric_columns, to_vector)
from src import vcs_pop_v01 as P

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
R2A = Path(r"C:\phoenix-target-overgraph\lexi-h2-rebuild-20260930\r2a-semantic-estimator-pair")
PRIM = Path(r"D:\codex-runs\encoder-contrast-01\primitives")
OUT = Path(r"D:\codex-runs\encoder-contrast-01\vcs")
EXPORT = R2A / "r2a-export-dev-predictions.jsonl"
MANIFEST = R2A / "r2a-export-dev-manifest.json"

TARGETS = ["n_evidence_facts", "n_missing_facts"]
ELIGIBLE = ["causal_base", "ner_lora_step500"]
CHEAP_LANE = "B1_count_statistics"


def sha_file(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sorted_id_hash(ids):
    """Matches the R2a-EXPORT-DEV convention: sorted ids, newline-joined, trailing newline."""
    return hashlib.sha256(("\n".join(sorted(ids)) + "\n").encode()).hexdigest()


def canonical_world(wid):
    return wid.split("@")[0] if "@" in wid else wid


# ------------------------------------------------------------------ preflight

def preflight():
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fails, checks = [], {}

    exp_hash = sha_file(EXPORT)
    checks["export_sha256"] = {"computed": exp_hash, "manifest": man["export_sha256"],
                               "ok": exp_hash == man["export_sha256"]}
    if exp_hash != man["export_sha256"]:
        fails.append("export hash mismatch")

    rows = [json.loads(l) for l in (BANK / "inputs" / "DEV.jsonl").open(encoding="utf-8") if l.strip()]
    head = rows[:man["dev_row_count"]]
    dev_ids = {r["world_id"] for r in head}
    checks["intended_population"] = {"rows": len(head), "unique_ids": len(dev_ids),
                                     "sorted_id_sha256": sorted_id_hash(dev_ids),
                                     "manifest_claim": man.get("dev_world_id_set_sha256_sorted"),
                                     "match": sorted_id_hash(dev_ids) == man.get("dev_world_id_set_sha256_sorted")}
    if not checks["intended_population"]["match"]:
        fails.append("intended population hash != manifest claim")

    lane_ids, order = {}, []
    for line in EXPORT.open(encoding="utf-8"):
        if not line.strip():
            continue
        d = json.loads(line)
        order.append(d["world_id"])
        for lane in d["estimates_by_lane"]:
            lane_ids.setdefault(lane, []).append(d["world_id"])
    for lane, ids in lane_ids.items():
        s = set(ids)
        checks.setdefault("lanes", {})[lane] = {
            "rows": len(ids), "unique": len(s), "dup": len(ids) - len(s),
            "equals_intended": s == dev_ids,
            "sorted_id_sha256": sorted_id_hash(s)}
        if s != dev_ids:
            fails.append(f"lane {lane} != intended population")
    for need in ELIGIBLE + [CHEAP_LANE]:
        if need not in lane_ids:
            fails.append(f"required lane absent: {need}")
    for bad in ("encoder_base", "nli_lora_step500"):
        if bad in lane_ids:
            fails.append(f"gate-failed lane present: {bad}")

    atlas = json.loads((R2A / "SEMANTIC-ESTIMATOR-ATLAS.json").read_text(encoding="utf-8"))
    bd = atlas["development"]["baseline_dev"]
    for coord, spec in man["b1_estimators"].items():
        a = sha_file(Path(spec["path"]))
        checks.setdefault("b1", {})[coord] = {"computed": a, "manifest": spec["sha256"],
                                              "atlas": bd[coord]["B1_artifact_sha256"],
                                              "agree": a == spec["sha256"] == bd[coord]["B1_artifact_sha256"]}
        if not checks["b1"][coord]["agree"]:
            fails.append(f"B1 hash disagreement: {coord}")

    groups = {}
    for r in head:
        groups[r["world_id"]] = r.get("paired_world") or canonical_world(r["world_id"])
    checks["grouping"] = {"rows": len(groups), "unique_groups": len(set(groups.values())),
                          "paired_rows": sum(1 for r in head if "@" in r["world_id"])}
    return fails, checks, head, groups


# ------------------------------------------------------------------ arms

def build_states(substrate, head, rows, groups, worlds_by_id, export_by_id):
    p = torch.load(PRIM / substrate / "DEV.pt", map_location="cpu", weights_only=False)
    row_of = {w: k for k, w in enumerate(p["row_ids"])}
    F = p["surfaces"]["final"]
    sim = P.sim
    key = lambda a: json.dumps({"a": a.get("type"), "g": a.get("args", {})}, sort_keys=True)

    out = []
    for r in rows:
        wid = r["world_id"]
        cw = groups[wid]
        w = worlds_by_id.get(cw)
        j = row_of.get(wid)
        if w is None or j is None or j >= F.shape[0]:
            continue
        st = P.new_state()
        text = r["input_text"]
        mentions = [b.get("mention") or "" for b in r.get("bindings", [])]
        ntok = len(P.AutoTokenizer.from_pretrained(
            r"D:\phoenix-models\lfm2.5-230m-base-9d2be55")(text, add_special_tokens=False)["input_ids"]) \
            if False else 0

        for k, v in P.observation_coords(text, 0).items():
            P.set_coord(st, "observation", k, v, "tokenizer+surface_scan")
        P.set_coord(st, "representation", "substrate", substrate, "modelcard")
        P.set_coord(st, "representation", "surface", "final", "modelcard")
        span = sum(len(m) for m in mentions if m and m in text)
        low = text.lower()
        P.set_coord(st, "derivation", "n_distinct_mentions", float(len({m for m in mentions if m})), "mention_scan")
        P.set_coord(st, "derivation", "n_mention_tokens", float(span), "mention_scan")
        P.set_coord(st, "derivation", "mention_density", span / max(len(text), 1), "mention_scan")
        P.set_coord(st, "derivation", "n_fact_lines", float(text.count("\n") + text.count(";")), "line_scan")
        P.set_coord(st, "derivation", "has_negation_word", 1.0 if any(x in low for x in P.NEGATION) else 0.0, "surface_scan")
        P.set_coord(st, "derivation", "n_predicate_words", float(sum(low.count(x) for x in P.PRED_WORDS)), "lexicon_scan")
        fam = set()
        for m in mentions:
            if not m:
                continue
            for suf in ("_object", "_switch", "_agent", "_chamber", "_hall", "_vault", "_crate", "_cell"):
                if m.endswith(suf):
                    fam.add(suf); break
            else:
                fam.add("bare")
        P.set_coord(st, "derivation", "n_distinct_entity_types", float(len(fam)), "mention_shape_scan")

        probs = head.probs(F[j].float().unsqueeze(0))[0]
        srt = torch.sort(probs, descending=True).values
        P.set_coord(st, "observer", "top_choice_prob", float(probs.max()), "head")
        P.set_coord(st, "observer", "margin", float(srt[0] - srt[1]) if len(srt) > 1 else 0.0, "head")
        P.set_coord(st, "observer", "entropy",
                    float(-(probs.clamp(min=1e-12) * probs.clamp(min=1e-12).log()).sum()), "head")
        legal = sim.legal_actions(w["initial_state"], w["available_actions"])
        lk = {key(a) for a in legal}
        P.set_coord(st, "observer", "legal_set_support",
                    float(sum(float(probs[c]) for c, n in enumerate(head.classes) if n in lk)), "head+simulator")

        gold = w.get("selected_action")
        gold_legal = bool(gold and gold in legal)
        plan = sim.shortest_plan(w["initial_state"], w["available_actions"], w["goal"], max_depth=5)
        n_repair = sum(1 for a in legal if sim.apply_action(w["initial_state"], a) != w["initial_state"])
        P.set_coord(st, "truth", "gold_action_legal", gold_legal, "simulator")
        P.set_coord(st, "truth", "n_legal_actions", float(len(legal)), "simulator")
        P.set_coord(st, "truth", "n_repair_alternatives", float(n_repair), "simulator")
        P.set_coord(st, "truth", "goal_distance", float(len(plan)) if plan is not None else -1.0, "simulator")
        P.set_coord(st, "truth", "has_contradiction", bool(w.get("contradictions")), "bank_world")
        P.set_coord(st, "truth", "n_missing_facts", float(len(w.get("missing_information") or [])), "bank_world")
        P.set_coord(st, "truth", "n_evidence_facts", float(len(w.get("evidence_facts") or [])), "bank_world")
        P.set_coord(st, "truth", "legal_set_size_minus_gold",
                    float(max(len(legal) - (1 if gold_legal else 0), 0)), "simulator")

        gold_key = key(gold) if gold else None
        solv, _ = P.solver_population(w)
        out.append({"world_id": wid, "group": cw, "state": st,
                    "pop_solvability": solv,
                    "pop_correctness": "CORRECT" if (gold_key and head.classes[int(probs.argmax())] == gold_key) else "INCORRECT",
                    "estimates": export_by_id[wid]})
    return out


# ------------------------------------------------------------------ metrics

def mat(vecs, sel, cols):
    sub = [[vecs[i][j] for j in cols] for i in sel]
    nc = numeric_columns(sub)
    if len(nc) < 2:
        return None, len(nc)
    return torch.tensor([[r[j] for j in nc] for r in sub], dtype=torch.float32), len(nc)


def loo_1nn(X, y):
    Xn = (X - X.mean(0)) / X.std(0).clamp(min=1e-6)
    D = torch.cdist(Xn, Xn)
    D.fill_diagonal_(float("inf"))
    return float((y[D.argmin(1)] == y).float().mean())


def knn_ratio(X, y, k=10):
    Xn = (X - X.mean(0)) / X.std(0).clamp(min=1e-6)
    D = torch.cdist(Xn, Xn)
    n = Xn.shape[0]
    eye = torch.eye(n, dtype=torch.bool)
    same = y[:, None] == y[None, :]
    Dm = D.clone(); Dm[eye] = float("inf")
    kk = min(k, max(2, n // 10))
    ins = torch.where(same & ~eye, Dm, torch.full_like(D, float("inf"))).topk(kk, largest=False).values
    ind = torch.where(~same, D, torch.full_like(D, float("inf"))).topk(kk, largest=False).values
    wi = float(ins[torch.isfinite(ins)].mean()); be = float(ind[torch.isfinite(ind)].mean())
    return wi / max(be, 1e-9)


def grouped_subsample(groups, n, frac=0.7, seed=0):
    """Subsample GROUPS WITHOUT replacement.

    With-replacement group sampling duplicates every row of a drawn group. A duplicated row
    then has its own copy as nearest neighbour, which inflates LOO 1-NN and produced
    bootstrap CIs near 0.89 against a point estimate of 0.617. Subsampling without
    replacement keeps the metric comparable to the point estimate.
    """
    gmap = {}
    for i, g in enumerate(groups):
        gmap.setdefault(g, []).append(i)
    keys = sorted(gmap)
    rng = random.Random(seed)
    rng.shuffle(keys)
    pick_keys, pick = [], []
    for k in keys:
        if len(pick) >= int(frac * n):
            break
        pick_keys.append(k)
        pick += gmap[k]
    return pick, pick_keys


def grouped_bootstrap_multi(vecs, labels, groups, arm_cols, n_boot=200, seed=0, frac=0.7):
    """Returns per-arm accuracy lists computed on the SAME group resamples, so differences
    between arms are paired."""
    n = len(vecs)
    out = {a: [] for a in arm_cols}
    ratios = {a: [] for a in arm_cols}
    for b in range(n_boot):
        pick, _ = grouped_subsample(groups, n, frac, seed * 100003 + b)
        if len(pick) < 12:
            continue
        labs = [labels[i] for i in pick]
        if len(set(labs)) < 2:
            continue
        lv = sorted(set(labs))
        y = torch.tensor([lv.index(l) for l in labs])
        if min(torch.bincount(y).tolist()) < 8:
            continue
        for arm, cols in arm_cols.items():
            X, nc = mat(vecs, pick, cols)
            if X is None:
                continue
            out[arm].append(loo_1nn(X, y))
            ratios[arm].append(knn_ratio(X, y))
    return out, ratios


def ci95(v):
    if len(v) < 20:
        return None
    v = sorted(v)
    return [round(v[int(0.025 * len(v))], 4), round(v[int(0.975 * len(v))], 4)]


def paired_diff_ci(a_list, b_list):
    """CI of (arm_a - arm_b) over identical resamples."""
    if len(a_list) < 20 or len(a_list) != len(b_list):
        return None
    d = [x - y for x, y in zip(a_list, b_list)]
    return {"mean_diff": round(sum(d) / len(d), 4), "ci95": ci95(d),
            "excludes_zero": bool(ci95(d) and (ci95(d)[0] > 0 or ci95(d)[1] < 0))}
