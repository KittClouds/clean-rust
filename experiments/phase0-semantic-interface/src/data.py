"""Phase 0 data construction: H, candidate sets A, and canonical supervision.

Every label here is derived from BANK-v1 canonical truth or the executable simulator.
Nothing is manufactured. Targets the ontology marks UNAVAILABLE have no label array at all,
so a head cannot be trained on them by accident.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import torch

EXP = Path(__file__).resolve().parents[1]
BANK = EXP.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
PRIM = Path(r"D:\codex-runs\encoder-contrast-01\primitives")
SURFACES = ["first", "final", "mean", "full_mean", "layer-4", "middle"]
MAX_ARGS = 3
M_CAP = 24

_spec = importlib.util.spec_from_file_location("p0_sim", EXP.parent / "ff-s15-bank-01" / "src" / "simulator.py")
sim = importlib.util.module_from_spec(_spec)
sys.modules["p0_sim"] = sim
_spec.loader.exec_module(sim)

from src.graft import ACTION_TYPES


def _arg_entities(a: dict, ents: set[str]) -> list[str]:
    """Entity ids referenced by an action, in a fixed slot order."""
    out = []
    for k in ("entity", "src", "dst", "agent", "loc", "object", "from", "to", "target"):
        v = a.get("args", {}).get(k)
        if v in ents:
            out.append(v)
    return out[:MAX_ARGS]


def build(split: str, substrate: str, limit: int | None = None, seed: int = 0,
          prim_suffix: str = "", m_cap: int | None = None) -> dict:
    """Return frozen features H, candidate set A, and canonical supervision for one split.

    `prim_suffix` selects a topped-up primitive cache (e.g. "-full"). With a suffix the
    population is defined by the cache's own canonical row order rather than by the first
    `limit` lines of the world file, which is what makes the 20k/2k canonical contract
    reachable. The default path is unchanged.

    `m_cap` defaults to the frozen Phase 1 value of 24. The Phase 2 candidate preflight
    measured the true canonical maximum as 28, so Phase 2 passes 28. NOTE: build() DROPS a
    whole row when len(available_actions) > m_cap, so raising the cap changes which rows exist
    at all -- it is not partial truncation of a retained row.
    """
    M_CAP_EFF = m_cap if m_cap is not None else M_CAP
    prim = torch.load(PRIM / substrate / f"{split}{prim_suffix}.pt", map_location="cpu", weights_only=False)
    row_of = {w: i for i, w in enumerate(prim["row_ids"])}
    surf = torch.stack([prim["surfaces"][s] for s in SURFACES], 1).float()  # [N,6,d_h]
    ent_all = prim["entity_vectors"].float()
    # per-row entity slices
    row_ent, row_ent_ptr = {}, []
    run = 0
    for (bi, eids) in prim["entity_index"]:
        wid = prim["row_ids"][bi]
        row_ent[wid] = (run, eids)
        run += len(eids)

    worlds = {}
    wlimit = None if prim_suffix else limit
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if wlimit and i >= wlimit:
                break
            if line.strip():
                w = json.loads(line)
                worlds[w["world_id"]] = w

    input_rows = {}
    with (BANK / "inputs" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                input_rows.setdefault(r["world_id"], r)

    keep, Hrow, Hent, eptr, cent, ctype, cmask, cact, world_ids = \
        [], [], [], [], [], [], [], [], []
    ent_list, off = [], 0
    cand_recs = []
    labels_global, labels_cand = [], []

    order = ([x for x in prim["row_ids"] if "@" not in x][:limit] if prim_suffix
             else list(worlds.keys()))
    for wid in order:
        w = worlds.get(wid)
        if w is None or wid not in row_of or wid not in input_rows:
            continue
        cand = w.get("available_actions") or []
        if not cand or len(cand) > M_CAP_EFF:
            continue
        ents = {e["id"] for e in w["entities"]}
        base, eids = row_ent[wid]
        if not eids:
            continue
        local_of = {e: base + j for j, e in enumerate(eids)}
        eidx = [local_of[e] for e in eids if e in local_of]
        if not eidx:
            continue
        keep.append(row_of[wid])
        world_ids.append(wid)
        Hrow.append(surf[row_of[wid]])
        ent_list.extend(ent_all[i] for i in eidx)
        eptr.append(list(range(len(eidx))))
        cm = []
        for a in cand:
            ids = [local_of[x] for x in _arg_entities(a, ents) if x in local_of]
            cm.append((ids, ACTION_TYPES.index(a["type"]) if a["type"] in ACTION_TYPES else 0))
        cand_recs.append(cm)
        m = len(cm)
        ctype.append([c[1] for c in cm] + [0] * (M_CAP_EFF - m))
        cmask.append([1.0] * m + [0.0] * (M_CAP_EFF - m))
        cent.append([[e - off if e - off >= 0 else -1 for e in c[0]] + [-1] * (MAX_ARGS - len(c[0]))
                     for c in cm] + [[-1] * MAX_ARGS] * (M_CAP_EFF - m))
        eptr[-1] = [off + j for j in range(len(eidx))]
        off += len(eidx)
        cact.append(cand + [None] * (M_CAP_EFF - m))

        # ---------------- canonical supervision ----------------
        st, av, goal = w["initial_state"], w["available_actions"], w["goal"]
        gs = sim.goal_satisfied(st, goal)
        plan = sim.shortest_plan(st, av, goal, max_depth=5)
        legal = sim.legal_actions(st, av)
        legal_keys = {json.dumps({"a": x.get("type"), "g": x.get("args", {})}, sort_keys=True) for x in legal}
        n_missing = len(w.get("missing_information") or [])
        labels_global.append({
            "solvable": float(plan is not None and not gs),
            "goal_satisfied": float(gs),
            "missing_information_present": float(n_missing > 0),
            "contradiction_present": float(len(w.get("contradictions") or []) > 0),
            # d_out = 6 (count + structure). Only the count is canonically sourceable in
            # BANK-v1; structure channels are NaN so their BCE weight is zero.
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
                "candidate_applicable": float(is_legal),          # duplicate by construction
                "candidate_satisfies_goal": float(sim.goal_satisfied(ns, goal)),
                "candidate_has_unmet_requirements": float(not is_legal),
                # supported / counterevidence / requires_missing_information: UNAVAILABLE
            })
        rows_c = rows_c + [None] * (M_CAP_EFF - len(rows_c))
        labels_cand.append(rows_c)

    pad = M_CAP_EFF
    H = {
        "row": torch.stack(Hrow),
        "ent": torch.stack(ent_list) if ent_list else torch.zeros(0, surf.shape[-1]),
        "ent_ptr": None,
        "cand_ent": torch.tensor(cent, dtype=torch.long),
        "cand_type": torch.tensor(ctype, dtype=torch.long),
        "cand_mask": torch.tensor(cmask, dtype=torch.float32),
    }
    gnames = list(labels_global[0].keys()) if labels_global else []
    first_cell = next((r[j] for r in labels_cand for j in range(len(r))
                       if r[j] is not None), None)
    cnames = list(first_cell.keys()) if first_cell else []
    LG = {}
    for n in gnames:
        cols = labels_global[0][n]
        if not isinstance(cols, list):
            cols = [cols] * 1
        LG[n] = torch.tensor([[r[n][k] if isinstance(r[n], list) else r[n]
                               for k in range(len(cols))] for r in labels_global],
                             dtype=torch.float32)
    LC = {n: torch.tensor([[(rows[j][n] if rows[j] else float("nan")) for j in range(pad)]
                           for rows in labels_cand], dtype=torch.float32) for n in cnames}
    # action endpoint a*: index of canonical selected_action within available_actions, -1 = none
    action_index = torch.full((len(world_ids),), -1, dtype=torch.long)
    for i, (cand, wid) in enumerate(zip(cact, world_ids)):
        w0 = worlds[wid]
        sel = w0.get("selected_action")
        if sel is None:
            continue
        for j, a in enumerate(cand):
            if a is None:
                continue
            if json.dumps({"a": a.get("type"), "g": a.get("args", {})}, sort_keys=True) == \
               json.dumps({"a": sel.get("type"), "g": sel.get("args", {})}, sort_keys=True):
                action_index[i] = j
                break

    ent_runs = {}
    for wid, (run, eids) in row_ent.items():
        ent_runs[wid] = (run, len(eids))
    keep_ent_runs = {w: ent_runs[w] for w in world_ids if w in ent_runs}
    return {"H": H, "global_labels": LG, "cand_labels": LC, "world_ids": world_ids,
            "cand_actions": cact, "n_rows": len(world_ids), "action_index": action_index,
            "ent_runs": keep_ent_runs,
            "global_names": gnames, "cand_names": cnames,
            "surfaces": SURFACES, "m_cap": M_CAP_EFF, "max_args": MAX_ARGS,
            "substrate": substrate, "split": split}
