"""Lepori causal lane -- BANK-v1 population, candidates, and canonical supervision.

Inherited from the encoder lane's hard-won lessons:
  * m_cap = 28, the MEASURED canonical maximum, never a typed constant. A cap is not a
    formatting detail: at 24 it silently dropped 21,016 canonical worlds and 567,254 candidates.
  * surface standardisation uses statistics fitted on TRAIN ONLY and frozen here, so DEV
    information never enters the DEV representation and the cache is replayable.
  * raw per-surface scale is preserved as permanent substrate metadata and is never compared
    across surfaces.

Unchanged from the shared contract: canonical split identity, the candidate ordering and padding
convention, and the target ontology. Those are properties of BANK-v1 truth, not of a substrate.
"""
from __future__ import annotations

import json
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[2]
BANK = REPO / "ff-s15-bank-01" / "releases" / "BANK-v1"
PRIM = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm\primitives")
SIM = REPO / "ff-s15-bank-01" / "src"

SURFACES = ["lt@24", "mf@24", "ms@24", "mf@18", "mf@12", "mf@6"]
M_CAP = 28
MAX_ARGS = 3

ACTION_TYPES = ["ASK", "MOVE", "ACTIVATE", "NOOP", "INSPECT", "RELEASE"]


def _sim():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bank_sim", SIM / "simulator.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _arg_entities(action, ents):
    out = []
    for v in (action.get("args") or {}).values():
        vs = v if isinstance(v, list) else [v]
        out.extend(x for x in vs if isinstance(x, str) and x in ents)
    return out


def _load_stats():
    d = torch.load(PRIM / "surface-stats.pt", map_location="cpu", weights_only=False)
    return d["stats"], d["fitted_on"], d["canonical_rows"]


def build(split: str, limit: int | None = None, prim_suffix: str = "-full",
          m_cap: int = M_CAP) -> dict:
    """Frozen features H, exhaustive candidate set A, and canonical supervision for one split."""
    stats, fitted_on, stats_rows = _load_stats()
    if fitted_on != "TRAIN":
        raise RuntimeError(f"surface statistics were fitted on {fitted_on}, not TRAIN")

    prim = torch.load(PRIM / f"{split}{prim_suffix}.pt", map_location="cpu", weights_only=False)
    row_of = {w: i for i, w in enumerate(prim["row_ids"])}

    # per-surface standardisation with the FROZEN TRAIN statistics
    std_surf = torch.stack(
        [((prim["surfaces"][s].float() - stats[s]["mean"]) / stats[s]["std"])
         for s in SURFACES], 1)                                  # [N, 6, d_h]
    ent_all = prim["entity_vectors"].float()

    row_ent, run = {}, 0
    for (bi, eids) in prim["entity_index"]:
        row_ent[prim["row_ids"][bi]] = (run, eids)
        run += len(eids)

    order = [x for x in prim["row_ids"] if "@" not in x][:limit] if prim_suffix else \
        [x for x in prim["row_ids"] if "@" not in x]

    worlds = {}
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                w = json.loads(line)
                worlds[w["world_id"]] = w
    input_rows = {}
    with (BANK / "inputs" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                input_rows.setdefault(r["world_id"], r)

    sim = _sim()
    Hrow, ent_list, cent, ctype, cmask, cact = [], [], [], [], [], []
    labels_global, labels_cand, world_ids = [], [], []
    off = 0
    for wid in order:
        w = worlds.get(wid)
        if w is None or wid not in row_of or wid not in input_rows:
            continue
        cand = w.get("available_actions") or []
        if not cand or len(cand) > m_cap:
            continue
        ents = {e["id"] for e in w["entities"]}
        base, eids = row_ent[wid]
        if not eids:
            continue
        local_of = {e: base + j for j, e in enumerate(eids)}
        eidx = [local_of[e] for e in eids if e in local_of]
        if not eidx:
            continue
        world_ids.append(wid)
        Hrow.append(std_surf[row_of[wid]])
        ent_list.extend(ent_all[i] for i in eidx)

        cm = []
        for a in cand:
            ids = [local_of[x] for x in _arg_entities(a, ents) if x in local_of]
            cm.append((ids, ACTION_TYPES.index(a["type"]) if a["type"] in ACTION_TYPES else 0))
        m = len(cm)
        ctype.append([c[1] for c in cm] + [0] * (m_cap - m))
        cmask.append([1.0] * m + [0.0] * (m_cap - m))
        cent.append([[e - off if e - off >= 0 else -1 for e in c[0]]
                     + [-1] * (MAX_ARGS - len(c[0])) for c in cm]
                    + [[-1] * MAX_ARGS] * (m_cap - m))
        cact.append(cand + [None] * (m_cap - m))
        off += len(eidx)

        st, av, goal = w["initial_state"], w["available_actions"], w["goal"]
        gs = sim.goal_satisfied(st, goal)
        plan = sim.shortest_plan(st, av, goal, max_depth=5)
        legal = sim.legal_actions(st, av)
        legal_keys = {json.dumps({"a": x.get("type"), "g": x.get("args", {})}, sort_keys=True)
                      for x in legal}
        n_missing = len(w.get("missing_information") or [])
        labels_global.append({
            "solvable": float(plan is not None and not gs),
            "goal_satisfied": float(gs),
            "missing_information_present": float(n_missing > 0),
            "contradiction_present": float(len(w.get("contradictions") or []) > 0),
            # d_out = 6: count on channel 0, structure on 1..5 which BANK-v1 does not source
            "number_or_structure_of_missing_requirements":
                [float(n_missing)] + [float("nan")] * 5,
        })
        rows_c = []
        for a in cand:
            k = json.dumps({"a": a.get("type"), "g": a.get("args", {})}, sort_keys=True)
            is_legal = k in legal_keys
            ns = sim.apply_action(st, a) if is_legal else st
            rows_c.append({
                "candidate_legal": float(is_legal),
                # IDENTICAL EXPRESSION to candidate_legal; one canonical source, two heads
                "candidate_applicable": float(is_legal),
                "candidate_satisfies_goal": float(sim.goal_satisfied(ns, goal)),
                # deterministic complement of candidate_legal, not an independent source
                "candidate_has_unmet_requirements": float(not is_legal),
            })
        labels_cand.append(rows_c + [None] * (m_cap - len(rows_c)))

    H = {
        "row": torch.stack(Hrow),                                   # [N, 6, d_h]
        "ent": torch.stack(ent_list) if ent_list else torch.zeros(0, std_surf.shape[-1]),
        "cand_ent": torch.tensor(cent, dtype=torch.long),
        "cand_type": torch.tensor(ctype, dtype=torch.long),
        "cand_mask": torch.tensor(cmask, dtype=torch.float32),
    }
    gnames = list(labels_global[0].keys())
    first = next((r[j] for r in labels_cand for j in range(len(r)) if r[j] is not None), None)
    cnames = list(first.keys())
    LG = {}
    for n in gnames:
        cols = labels_global[0][n]
        if not isinstance(cols, list):
            cols = [cols]
        LG[n] = torch.tensor([[r[n][k] if isinstance(r[n], list) else r[n]
                               for k in range(len(cols))] for r in labels_global],
                             dtype=torch.float32)
    LC = {n: torch.tensor([[(rows[j][n] if rows[j] else float("nan")) for j in range(m_cap)]
                           for rows in labels_cand], dtype=torch.float32) for n in cnames}

    action_index = torch.full((len(world_ids),), -1, dtype=torch.long)
    for i, (cand, wid) in enumerate(zip(cact, world_ids)):
        sel = worlds[wid].get("selected_action")
        if sel is None:
            continue
        for j, a in enumerate(cand):
            if a is None:
                continue
            if json.dumps({"a": a.get("type"), "g": a.get("args", {})}, sort_keys=True) == \
               json.dumps({"a": sel.get("type"), "g": sel.get("args", {})}, sort_keys=True):
                action_index[i] = j
                break

    ent_runs = {w: row_ent[w][0] for w in world_ids}
    return {
        "H": H, "global_labels": LG, "cand_labels": LC, "world_ids": world_ids,
        "cand_actions": cact, "n_rows": len(world_ids), "action_index": action_index,
        "ent_runs": ent_runs, "global_names": gnames, "cand_names": cnames,
        "surfaces": SURFACES, "m_cap": m_cap, "max_args": MAX_ARGS,
        "substrate": "minicpm5-1b-base", "fabric": "causal", "split": split,
        "normalisation": {"fitted_on": fitted_on, "canonical_rows": stats_rows,
                          "per_surface": True, "dev_statistics_used": False},
    }
