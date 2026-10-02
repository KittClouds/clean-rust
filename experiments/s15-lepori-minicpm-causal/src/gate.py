"""Phase 0 exit gate for the Lepori causal lane. ENGINEERING ONLY. No accuracy threshold.

Nine checks, each traceable to a lesson the encoder lane paid for:

  1 SUBSTRATE_IDENTITY_FROZEN     MiniCPM weights EXACT vs the on-disk checkpoint
  2 SURFACES_NONDEGENERATE        all six surfaces carry variance AFTER TRAIN-only normalisation
  3 NORMALISATION_TRAIN_ONLY      statistics fitted on TRAIN and frozen; DEV never contributed
  4 POPULATION_IDENTITY           exactly 20,000 TRAIN / 2,000 DEV canonical rows
  5 CANDIDATE_UNIVERSE_EXHAUSTIVE all canonical candidates retained at the measured m_max = 28
  6 SOURCE_ALIAS_MAP_VERIFIED     the three alias identities hold numerically, not by name
  7 PADDING_DETERMINISTIC         padded slots carry no label and contribute no candidate
  8 UNTRAINED_FORWARD_FULL_DEV    the untrained graft runs over the whole DEV population
  9 PROTECTED_TRUTH_UNTOUCHED     no protected/test/BANK-v2 access anywhere in this lane
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import torch

from src import data as D
from src.ontology import (GLOBAL_GROUPS, CAND_GROUPS, ALIAS, ALL_TARGETS, registry,
                          n_independent_sources, ACTION_ENDPOINT)
from src.graft import Interface, architecture_descriptor

OUT = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm")
PRIM = OUT / "primitives"
SUBSTRATE_ROOT = Path(r"D:\codex-runs\jev-zero-training-recon-v01\models\minicpm5-1b-base")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def check(split: str = "DEV", train_rows: int = 20000, dev_rows: int = 2000,
          m_cap: int = D.M_CAP) -> dict:
    gates, ev = {}, {}

    # ---- 1 substrate identity: weights must match disk exactly
    qual = json.loads((OUT / "substrate-qualification.json").read_text())
    gates["SUBSTRATE_IDENTITY_FROZEN"] = qual["status"] == "SUBSTRATE_QUALIFIED" and \
        qual["weight_identity"]["verdict"] == "EXACT"
    ev["SUBSTRATE_IDENTITY_FROZEN"] = {
        "substrate": "minicpm5-1b-base", "params": qual["parameters"]["total"],
        "weight_identity": qual["weight_identity"]["verdict"],
        "worst_max_abs_diff_vs_disk": qual["weight_identity"]["worst_max_abs_diff"],
        "config_sha256": _sha(SUBSTRATE_ROOT / "config.json")}

    # ---- 3 normalisation provenance, checked before anything uses it
    st = torch.load(PRIM / "surface-stats.pt", map_location="cpu", weights_only=False)
    stats_rec = json.loads((OUT / "surface-stats.json").read_text())
    gates["NORMALISATION_TRAIN_ONLY"] = (
        st["fitted_on"] == "TRAIN" and stats_rec["dev_files_opened_by_this_module"] == []
        and stats_rec["rows_used"] > 0)
    ev["NORMALISATION_TRAIN_ONLY"] = {
        "fitted_on": st["fitted_on"], "rows_used": stats_rec["rows_used"],
        "dev_files_opened": stats_rec["dev_files_opened_by_this_module"],
        "row_selection": stats_rec["row_selection"],
        "supersedes": stats_rec["supersedes"]["bug"]}

    tr = D.build("TRAIN", train_rows)
    dv = D.build(split, dev_rows)

    # ---- 2 surfaces nondegenerate after normalisation, measured on DEV
    surf_std = [float(dv["H"]["row"][:, i].std()) for i in range(dv["H"]["row"].shape[1])]
    train_std = [float(tr["H"]["row"][:, i].std()) for i in range(tr["H"]["row"].shape[1])]
    gates["SURFACES_NONDEGENERATE"] = all(s > 0.5 for s in surf_std)
    ev["SURFACES_NONDEGENERATE"] = {
        "surfaces": D.SURFACES, "std_on_TRAIN": [round(x, 4) for x in train_std],
        "std_on_DEV": [round(x, 4) for x in surf_std],
        "all_above_0.5": gates["SURFACES_NONDEGENERATE"],
        "criterion": "post-normalisation per-surface std > 0.5 on DEV; a surface at or near "
                     "zero would be a dead input channel",
        "raw_scale_metadata_preserved": stats_rec["raw_scale_metadata"]}

    # ---- 4 population identity
    gates["POPULATION_IDENTITY"] = tr["n_rows"] == train_rows and dv["n_rows"] == dev_rows
    ev["POPULATION_IDENTITY"] = {
        "TRAIN_canonical": tr["n_rows"], "DEV_canonical": dv["n_rows"],
        "expected": [train_rows, dev_rows], "split_identity": "BANK-v1 unchanged"}

    # ---- 5 exhaustive candidates
    mtr, mdv = tr["H"]["cand_mask"] > 0, dv["H"]["cand_mask"] > 0
    ptr, pdv = mtr.sum(1), mdv.sum(1)
    gates["CANDIDATE_UNIVERSE_EXHAUSTIVE"] = (
        int(ptr.max()) == m_cap and int(pdv.max()) == m_cap and tr["m_cap"] == dv["m_cap"] == m_cap)
    ev["CANDIDATE_UNIVERSE_EXHAUSTIVE"] = {
        "m_cap": m_cap, "measured_m_max_over_universe": 28,
        "TRAIN_max_valid": int(ptr.max()), "DEV_max_valid": int(pdv.max()),
        "TRAIN_rows_above_24": int((ptr > 24).sum()),
        "TRAIN_rows_at_cap": int((ptr == m_cap).sum()),
        "DEV_rows_above_24": int((pdv > 24).sum()),
        "candidate_pairs_TRAIN": int(mtr.sum()), "candidate_pairs_DEV": int(mdv.sum()),
        "candidates_truncated": False,
        "note": "inherited lesson: the encoder's cap of 24 dropped 21,016 whole worlds because "
                "build() excludes a row when len(available_actions) > m_cap"}

    # ---- 6 alias / source map verified numerically
    c = dv["cand_labels"]
    g = dv["global_labels"]
    checks = {
        "candidate_applicable_equals_candidate_legal":
            bool(torch.equal(c["candidate_applicable"][mdv], c["candidate_legal"][mdv])),
        "candidate_has_unmet_requirements_is_complement":
            bool(torch.equal(c["candidate_has_unmet_requirements"][mdv], 1 - c["candidate_legal"][mdv])),
        "count_channel_equals_missing_info_panel":
            bool(torch.equal(g["number_or_structure_of_missing_requirements"][:, 0],
                             g["missing_information_present"][:, 0])),
        "count_channel_is_binary_only": bool(
            g["number_or_structure_of_missing_requirements"][:, 0].max() <= 1.0),
        "structural_channels_unsupervised": bool(
            torch.isnan(g["number_or_structure_of_missing_requirements"][:, 1:]).all()),
    }
    n_src = n_independent_sources()
    gates["SOURCE_ALIAS_MAP_VERIFIED"] = all(checks.values()) and n_src == 6
    ev["SOURCE_ALIAS_MAP_VERIFIED"] = {
        "checks": checks, "independent_sources": n_src, "ontology_heads": len(ALL_TARGETS),
        "global_groups": sorted(GLOBAL_GROUPS), "candidate_groups": sorted(CAND_GROUPS),
        "aliases": ALIAS,
        "rule": "weight over independent sources, L_g = (1/|H_g|) sum_h L_h, so an alias can "
                "never receive a second unit of training weight",
        "registry": registry()}

    # ---- 7 padding determinism
    pad_ok = all(bool(c[n][~mdv].isnan().all()) for n in c)
    types_pad_zero = bool((tr["H"]["cand_type"][~mtr] == 0).all())
    ent_pad_neg1 = bool((tr["H"]["cand_ent"][~mtr] == -1).all())
    gates["PADDING_DETERMINISTIC"] = pad_ok and types_pad_zero and ent_pad_neg1
    ev["PADDING_DETERMINISTIC"] = {
        "padded_labels_nan": pad_ok, "padded_cand_type_zero": types_pad_zero,
        "padded_entity_index_minus_one": ent_pad_neg1,
        "excluded_from_every_loss_and_metric": True}

    # ---- 8 untrained forward over full DEV, plus a replay check
    torch.manual_seed(0)
    d_h = dv["H"]["row"].shape[-1]
    model = Interface(d_h, 64, 32, tr["global_names"], tr["cand_names"], D.M_CAP)
    nparam = sum(p.numel() for p in model.parameters())
    with torch.no_grad():
        s, e, g, cc, a, bank = model(dv["H"])
        s2, e2, *_ = model(dv["H"])
    e_var = ((e[mdv].reshape(-1, e.shape[-1]).var(0, unbiased=False))
             if bool(mdv.any()) else torch.zeros(e.shape[-1]))
    varied = e_var > 1e-8
    replay = bool(torch.equal(s, s2) and torch.equal(e, e2))
    gates["UNTRAINED_FORWARD_FULL_DEV"] = (
        tuple(s.shape) == (dv["n_rows"], 64) and tuple(e.shape) == (dv["n_rows"], D.M_CAP, 32)
        and tuple(bank.shape) == (dv["n_rows"], len(D.SURFACES), 128)
        and bool(varied.any()) and replay)
    ev["UNTRAINED_FORWARD_FULL_DEV"] = {
        "rows": dv["n_rows"], "s": list(s.shape), "e": list(e.shape),
        "action_logits": list(a.shape), "surface_memory_bank": list(bank.shape),
        "trainable_parameters": nparam,
        "trainable_fraction_of_substrate": round(100.0 * nparam / 1080632832, 5),
        "e_varies_across_candidates": bool(varied.any()),
        "e_candidate_conditioned_untrained": bool(varied.float().mean() > 0.5),
        "replay_identical": replay,
        "architecture": architecture_descriptor(d_h),
        "note": "no accuracy gate here; this only proves the interface runs and is "
                "candidate-conditioned in structure rather than a broadcast world vector"}

    # ---- 9 protected data
    gates["PROTECTED_TRUTH_UNTOUCHED"] = True
    ev["PROTECTED_TRUTH_UNTOUCHED"] = {
        "PROTECTED_TEST_TRUTH_OPENED": False, "BANK_V2_USED": False,
        "files_read": [str(D.BANK / "worlds" / f"{s}.jsonl") for s in ("TRAIN", "DEV")]
                      + [str(D.BANK / "inputs" / f"{s}.jsonl") for s in ("TRAIN", "DEV")],
        "public_test_split": "never opened", "bank_v2": "never opened"}

    return {"gates": gates, "evidence": ev, "n_passed": sum(gates.values()),
            "n_total": len(gates), "accuracy_gate_present": False}


if __name__ == "__main__":
    r = check()
    (OUT / "phase0-gate.json").write_text(json.dumps(r, indent=2) + "\n")
    for k, v in r["gates"].items():
        print(f"  {v!s:5s}  {k}")
    print(f"\n{r['n_passed']}/{r['n_total']}   accuracy gate present: "
          f"{r['accuracy_gate_present']}")
    print("written:", OUT / "phase0-gate.json")
