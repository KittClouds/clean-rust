"""Joint surface / global-path ablation on the trained Lepori MiniCPM graft.

Why this exists. The single-surface ablation in PHASE1.md showed that zeroing any ONE u_i
changes almost nothing. That is compatible with two very different worlds:

  (a) the six surfaces carry REDUNDANT information, so any one can go;
  (b) the global path s contributes almost nothing to candidate state at all, so all six could
      go together with little effect -- because e_j is being driven almost entirely by c_j, the
      candidate/entity representation.

Those have very different consequences. (a) means depth diversity is genuinely used and
redundantly. (b) means the transferable capability is specifically the CANDIDATE-LOCAL branch,
and any global-path mechanism is aimed at the wrong place.

Discriminating them needs two JOINT ablations, both inference-only, no retraining:

  all_u_zero   every projected u_i set to 0 before rho_s  -> global state destroyed
  s_zero_in_e  the global-state half of rho_e's input set to 0 -> s removed from the candidate
               path ONLY, leaving c_j and the surfaces intact

Plus a per-action-type breakdown on the endpoint, because an aggregate endpoint number can be
entirely explained by a majority action type and this lane's endpoint is a NOOP detector.
"""
from __future__ import annotations

import json
from pathlib import Path

import torch

from src import data as D
from src.phase1 import Interface, pack, eval_head
from src.ontology import GLOBAL_GROUPS, CAND_GROUPS

OUT = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm")
RECEIPT = OUT / "phase1-receipt.json"


def load_trained():
    r = json.loads(RECEIPT.read_text())
    ep = r["selection"]["best_epoch"]
    tr = D.build("TRAIN", 20000)
    dv = D.build("DEV", 2000)
    d_h = tr["H"]["row"].shape[-1]
    model = Interface(d_h, 64, 32, tr["global_names"], tr["cand_names"], D.M_CAP)
    model.load_state_dict(torch.load(OUT / f"phase1-ckpt-epoch-{ep}.pt",
                                     map_location="cpu", weights_only=False))
    model.eval()
    return model, dv, r


def prevs(tr):
    g, c, m = tr["global_labels"], tr["cand_labels"], tr["H"]["cand_mask"] > 0
    pi_g = {sid: float((g[n][:, 0] == 1).float().mean())
            for sid, ns in GLOBAL_GROUPS.items() for n in ns
            if n != "number_or_structure_of_missing_requirements"}
    pi_g["SRC-MISSING-INFO-PANEL"] = float(
        (g["missing_information_present"][:, 0] == 1).float().mean())
    pi_c = {n: float((c[n][m] == 1).float().mean()) for ns in CAND_GROUPS.values() for n in ns}
    return pi_g, pi_c


@torch.no_grad()
def run(model, dv, pi_g, pi_c, mode):
    H, g, c = pack(dv, torch.arange(dv["n_rows"]))
    m = H["cand_mask"]
    valid = m > 0

    u = model.graft.surfaces(H["row"])                    # [B, 6, d_u]
    if mode == "all_u_zero":
        u = torch.zeros_like(u)
    s = model.graft.rho_s(u.reshape(u.shape[0], -1))
    if mode == "s_zero":
        s = torch.zeros_like(s)
    cj = model.graft.candidate_states(H)                  # [B, m, 256]
    s_in = s if mode != "s_zero_in_e" else torch.zeros_like(s)
    e = model.graft.rho_e(torch.cat(
        [cj, s_in.unsqueeze(1).expand(-1, cj.shape[1], -1)], -1)) * m.unsqueeze(-1)
    go, co, a = model.heads(s, e, m)

    out = {}
    for sid, names in CAND_GROUPS.items():
        n = "candidate_legal" if sid == "SRC-CANDIDATE-LEGALITY" else "candidate_satisfies_goal"
        sel = (~torch.isnan(c[n])) & valid
        out[sid] = eval_head(co[n][sel], c[n][sel], pi_c[n])
    for sid, names in GLOBAL_GROUPS.items():
        n = names[0]
        y = g[n][:, 0]; sup = ~torch.isnan(y)
        if "balanced_accuracy" in eval_head(go[n][:, 0][sup], y[sup], pi_g[sid]):
            out[sid] = eval_head(go[n][:, 0][sup], y[sup], pi_g[sid])

    astar = dv["action_index"]; sel = astar >= 0
    rows = sel.nonzero().flatten().tolist()
    ep = {}
    if int(sel.sum()):
        pred = a[sel].argmax(1); tgt = astar[sel]
        ep["action_top1"] = round(float((pred == tgt).float().mean()), 4)
        ca = dv["cand_actions"]
        for t in D.ACTION_TYPES:
            hit = torch.tensor([ca[i][int(j)] is not None and ca[i][int(j)].get("type") == t
                                for i, j in zip(rows, tgt.tolist())])
            if int(hit.sum()):
                ep[t] = {"n": int(hit.sum()),
                         "acc": round(float((pred[hit] == tgt[hit]).float().mean()), 4)}
        ep["predicted_type_histogram"] = {}
        for t in D.ACTION_TYPES:
            k = int(torch.tensor([ca[i][int(j)] is not None
                                  and ca[i][int(j)].get("type") == t
                                  for i, j in zip(rows, pred.tolist())]).sum())
            if k:
                ep["predicted_type_histogram"][t] = k
    out["endpoint"] = ep
    return out


def main() -> int:
    model, dv, rec = load_trained()
    tr = D.build("TRAIN", 20000)
    pi_g, pi_c = prevs(tr)
    modes = [("baseline", "intact"), ("all_u_zero", "every projected u_i -> 0 before rho_s"),
             ("s_zero_in_e", "global-state half of rho_e input -> 0, c_j intact"),
             ("s_zero", "s -> 0 everywhere, including the global heads")]
    res = {}
    for name, desc in modes:
        r = run(model, dv, pi_g, pi_c, "baseline" if name == "baseline" else name)
        res[name] = {"description": desc, "metrics": r}
        print(f"\n--- {name}: {desc}")
        for k in ("SRC-CANDIDATE-LEGALITY", "SRC-CANDIDATE-SATISFIES-GOAL",
                  "SRC-SOLVABILITY", "SRC-GOAL-SATISFIED", "SRC-MISSING-INFO-PANEL",
                  "SRC-CONTRADICTION-PANEL"):
            if k in r:
                print(f"    {k:32s} balAcc {r[k]['balanced_accuracy']:.4f}  "
                      f"acc {r[k]['accuracy']:.4f}")
        print(f"    endpoint top-1 {r['endpoint'].get('action_top1')}  "
              + "  ".join(f"{t}={r['endpoint'][t]['acc']:.4f}"
                          for t in ("MOVE", "ACTIVATE", "NOOP") if t in r['endpoint']))
        print(f"    predicted type histogram: {r['endpoint'].get('predicted_type_histogram')}")

    b = res["baseline"]["metrics"]
    au = res["all_u_zero"]["metrics"]
    se = res["s_zero_in_e"]["metrics"]
    verdict = {
        "question_1_is_depth_redundant_or_is_the_global_path_unused": None,
        "question_2_is_candidate_legality_driven_by_c_j_alone": None,
    }
    drop_all = b["SRC-CANDIDATE-LEGALITY"]["balanced_accuracy"] - \
        au["SRC-CANDIDATE-LEGALITY"]["balanced_accuracy"]
    drop_s = b["SRC-CANDIDATE-LEGALITY"]["balanced_accuracy"] - \
        se["SRC-CANDIDATE-LEGALITY"]["balanced_accuracy"]
    verdict["candidate_legality_baseline"] = b["SRC-CANDIDATE-LEGALITY"]["balanced_accuracy"]
    verdict["drop_when_all_surfaces_removed"] = round(drop_all, 4)
    verdict["drop_when_s_removed_from_candidate_path_only"] = round(drop_s, 4)
    if drop_all < 0.05:
        verdict["question_1_is_depth_redundant_or_is_the_global_path_unused"] = (
            "GLOBAL PATH BARELY USED. Removing all six surfaces together costs almost nothing, so "
            "the single-surface result was NOT evidence of depth redundancy: candidate legality "
            "is being produced almost entirely by c_j, the candidate/entity branch.")
    else:
        verdict["question_1_is_depth_redundant_or_is_the_global_path_unused"] = (
            "GENUINE REDUNDANCY supported: the surfaces carry the information jointly, since "
            "removing all of them together still degrades candidate legality materially.")
    if drop_s < 0.05:
        verdict["question_2_is_candidate_legality_driven_by_c_j_alone"] = (
            "YES. Zeroing s inside rho_e leaves candidate legality essentially unchanged, so e_j "
            "is candidate-local. The transferable capability is the CANDIDATE-LOCAL BRANCH, not "
            "the whole interface, and the identical cross-substrate legality numbers are "
            "explained by both lanes having the same c_j construction rather than by the global "
            "path doing transferable work.")
    else:
        verdict["question_2_is_candidate_legality_driven_by_c_j_alone"] = (
            "NO. s contributes materially to candidate legality, so the candidate path is not "
            "purely local.")

    out = {"abi": "s15-lepori-minicpm/joint-surface-ablation-v0.1",
           "trained_checkpoint": {"best_epoch": rec["selection"]["best_epoch"],
                                  "file": f"phase1-ckpt-epoch-{rec['selection']['best_epoch']}.pt"},
           "method": "inference-only joint ablations on the trained graft; no retraining",
           "claim_scope": "descriptive and causal-within-this-model; not a claim about the "
                          "substrate's internal use of depth",
           "results": res, "verdict": verdict}
    p = OUT / "joint-surface-ablation.json"
    p.write_text(json.dumps(out, indent=2) + "\n")
    print("\n" + "=" * 84)
    print("VERDICT")
    for k, v in verdict.items():
        print(f"  {k}: {v}")
    print("\nwritten:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
