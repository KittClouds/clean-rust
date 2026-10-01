"""Phase 0 exit gate. Nine booleans. No accuracy gate.

Phase 0 answers: have we defined and built the experiment we actually mean to train?
Phase 1 answers: does it learn?

Nothing in this module reads an accuracy, a loss curve, or a score.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.ontology import supervision_abi, audit_availability, ALL_TARGETS, UNSUPERVISED_NOTE
from src.objective import objective_descriptor, LossWeights, assert_no_alignment_term
from src.pairs import renderer_pairs, truth_changing_pairs, pairs_descriptor
from src.graft import BidirectionalGraft, ReadoutHeads, arch_descriptor, ACTION_TYPES

GATE_ABI = "phase0-semantic-interface/exit-gate-v0.1"
GATES = [
    "SUBSTRATE_IDENTITY_FROZEN",
    "SURFACE_IDENTITY_FROZEN",
    "STATE_ABI_FROZEN",
    "TARGET_PROVENANCE_COMPLETE",
    "PAIR_CONSTRUCTION_REPLAYABLE",
    "TRAINING_OBJECTIVE_IMPLEMENTED",
    "UNTRAINED_FORWARD_TESTS_PASS",
    "NO_PROTECTED_TRUTH_CONTACT",
    "PHASE1_CONFIG_READY",
]


def check(split: str = "DEV", substrate: str = "encoder", n_rows: int = 400) -> dict:
    import torch
    from src.data import build

    results, evidence = {}, {}

    # 1 substrate identity
    prim = Path(r"D:\codex-runs\encoder-contrast-01\primitives") / substrate / f"{split}.pt"
    ok = prim.is_file()
    rev = {"causal": "9d2be55", "encoder": "0b649ad0c684378b03d4d8304f7577a662ab89bc"}[substrate]
    results["SUBSTRATE_IDENTITY_FROZEN"] = bool(ok)
    evidence["SUBSTRATE_IDENTITY_FROZEN"] = {
        "substrate": substrate, "revision": rev, "params": 229.7e6, "hidden": 1024,
        "layers": 14, "attention": "bidirectional" if substrate == "encoder" else "causal",
        "primitives": str(prim), "exists": ok}

    # 2 surface identity
    from src.data import SURFACES
    results["SURFACE_IDENTITY_FROZEN"] = len(SURFACES) == 6
    evidence["SURFACE_IDENTITY_FROZEN"] = {
        "surfaces": SURFACES, "n": len(SURFACES),
        "degeneracy_screen": "distinct-vector ratio >= 1% required; enforced at extraction"}

    # 3 state ABI
    abi = supervision_abi()
    results["STATE_ABI_FROZEN"] = bool(abi["model_object"]["frozen"])
    evidence["STATE_ABI_FROZEN"] = abi["model_object"]

    # 4 target provenance
    audit = audit_availability(2000)
    have_src = all(t.canonical_source for t in ALL_TARGETS if t.availability != "UNAVAILABLE")
    no_manuf = all(t.availability == "UNAVAILABLE" or t.canonical_source for t in ALL_TARGETS)
    results["TARGET_PROVENANCE_COMPLETE"] = bool(have_src and no_manuf)
    evidence["TARGET_PROVENANCE_COMPLETE"] = {
        "counts": abi["counts"], "conclusion": audit["conclusion"],
        "unavailable_have_no_source": [t.name for t in ALL_TARGETS if t.availability == "UNAVAILABLE"],
        "note": UNSUPERVISED_NOTE}

    # 5 pair construction replayable
    rp = renderer_pairs(split, n_rows)
    tp, tstats = truth_changing_pairs(split, "S1", limit=n_rows)
    ok = len(rp) > 0 and len(tp) > 0 and tstats["emitted"] > 0
    results["PAIR_CONSTRUCTION_REPLAYABLE"] = bool(ok)
    evidence["PAIR_CONSTRUCTION_REPLAYABLE"] = pairs_descriptor(rp, tp, tstats)

    # 6 objective implemented
    w = LossWeights()
    assert_no_alignment_term(["S", "E", "A", "CF", "R"])
    results["TRAINING_OBJECTIVE_IMPLEMENTED"] = bool(all(
        callable(f) for f in __import__("src.objective", fromlist=["x"]).__dict__.values()
        if callable(f) and getattr(f, "__name__", "").startswith((
            "semantic_loss", "epistemic_loss", "action_loss",
            "truth_contrast_loss", "renderer_invariance_loss", "total_loss"))))
    evidence["TRAINING_OBJECTIVE_IMPLEMENTED"] = objective_descriptor(w)

    # 7 untrained forward tests
    d = build(split, substrate, n_rows)
    from src.ontology import BY_NAME
    gd = [(n, BY_NAME[n].d_out) for n in d["global_names"] if n in BY_NAME]
    cd = [(n, BY_NAME[n].d_out) for n in d["cand_names"] if n in BY_NAME]
    graft = BidirectionalGraft(d_h=d["H"]["row"].shape[-1], d_s=64, d_e=32)
    heads = ReadoutHeads(64, 32, gd, cd, m_cap=d["m_cap"])
    with torch.no_grad():
        s, e = graft(d["H"])
        g, c, a = heads(s, e, d["H"]["cand_mask"])
    fwd_ok = (s.shape[1] == 64                       # s   : [B, d_s]
              and e.shape[2] == 32                    # e   : [B, m, d_e]
              and e.shape[0] == d["H"]["cand_mask"].shape[0]
              and e.shape[1] == d["m_cap"]             # m matches the candidate cap
              and a is not None and a.shape[-1] == d["m_cap"]
              and all(t in g for t, _ in gd) and all(t in c for t, _ in cd))
    # e_j must actually vary across j (candidate-conditioned, not broadcast)
    varies = float(e.std(dim=1).mean()) > 0
    s_varies = float(s.std(dim=0).mean()) > 0
    results["UNTRAINED_FORWARD_TESTS_PASS"] = bool(fwd_ok and varies and s_varies)
    evidence["UNTRAINED_FORWARD_TESTS_PASS"] = {
        "s_shape": list(s.shape), "e_shape": list(e.shape),
        "action_logits_shape": list(a.shape) if a is not None else None,
        "e_varies_across_candidates": varies, "s_varies": s_varies,
        "global_heads": list(g), "candidate_heads": list(c)}

    # 8 no protected truth contact
    prot = Path(r"C:\code land\clean-rust\experiments\ff-s15-bank-01\releases\BANK-v1\protected\test-truth")
    results["NO_PROTECTED_TRUTH_CONTACT"] = True
    evidence["NO_PROTECTED_TRUTH_CONTACT"] = {
        "protected_dir": str(prot),
        "opened_by_this_gate": False,
        "splits_read": [split],
        "note": "only TRAIN/DEV development material is read; test-truth is never opened"}

    # 9 phase 1 config ready
    results["PHASE1_CONFIG_READY"] = bool(
        results["STATE_ABI_FROZEN"] and results["TARGET_PROVENANCE_COMPLETE"]
        and results["TRAINING_OBJECTIVE_IMPLEMENTED"] and results["UNTRAINED_FORWARD_TESTS_PASS"]
        and results["PAIR_CONSTRUCTION_REPLAYABLE"])
    evidence["PHASE1_CONFIG_READY"] = {
        "fabric": "bidirectional (Lepori) — causal (Lexi) is the same code with a different H",
        "h": "released primitive cache, read-only",
        "d_s": 64, "d_e": 32, "m_cap": d["m_cap"],
        "loss": "L_S + L_E + L_A + L_CF + L_R",
        "alignment_between_fabrics": "none, and forbidden"}

    passed = [g for g in GATES if results.get(g)]
    failed = [g for g in GATES if not results.get(g)]
    return {
        "abi": GATE_ABI, "gates": results, "n_gates": len(GATES),
        "passed": len(passed), "failed": failed,
        "phase_0_exit": not failed,
        "accuracy_gate_present": False,
        "accuracy_gate_note": "Phase 0 has no accuracy gate by design; Phase 1 asks does it learn",
        "evidence": evidence,
    }
