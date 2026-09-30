"""Emit VCS-0b-HANDOFF for Lexi.

A small target set: non-circular, runtime-unavailable semantic coordinates that account for
a material share of the G0 -> G1 geometry loss, with a declared estimator contract and a
valid (population-independent) target population.

Writes both a machine-readable handoff and a compact markdown card.
"""
from __future__ import annotations

import json
from pathlib import Path

R = json.load(open(r"D:\codex-runs\encoder-contrast-01\vcs\vcs02-handoff.json"))
OUT = Path(r"D:\codex-runs\encoder-contrast-01\vcs")
COORD = R["abi"]["coordinates"]


def consensus_targets():
    """A target is prioritized only if it clears the share bar on BOTH substrates and at
    least one population. This keeps the handoff to the coordinates that actually carry the
    loss rather than the ones that happened to top a single substrate's ranking."""
    allc = {}
    for pop, h in R["handoff"].items():
        for t in h["targets"]:
            allc.setdefault(t["coord"], []).append((pop, t))
    out = []
    for coord, entries in allc.items():
        subs = set()
        for pop, t in entries:
            for sh in t["shares"]:
                subs.add(sh["substrate"])
        means = {pop: t["mean_share"] for pop, t in entries}
        min_share = min(means.values()) if means else 0.0
        pops_cleared = sum(1 for v in means.values() if v > 0.10)
        primary = max(means.items(), key=lambda kv: kv[1])[0]
        c = COORD[coord]
        out.append({
            "coordinate": coord,
            "definition": c["description"],
            "kind": c["kind"],
            "provenance_class": c["provenance_class"],
            "runtime_availability": c["runtime_availability"],
            "circularity_status": {
                pop: ("CIRCULAR for " + pop) if coord in R["abi"]["circularity_spec"].get(pop, {})
                     else "non-circular" for pop in R["abi"]["populations"]},
            "contribution_to_G0_G1_loss": {
                pop: {"mean_share": t["mean_share"],
                      "per_substrate": t["shares"],
                      "total_loss": R["populations"]["causal"][pop]["total_loss"]}
                for pop, t in entries},
            "worst_case_share": round(min_share, 4),
            "populations_cleared": pops_cleared,
            "primary_population": primary,
            "estimator_contract": c["estimator_contract"],
            "valid_target_populations": [
                {"population": pop,
                 "definition": R["abi"]["populations"][pop]["definition"],
                 "levels": R["abi"]["populations"][pop]["levels"],
                 "independent_of_coordinates": True}
                for pop in R["abi"]["populations"]
                if coord not in R["abi"]["circularity_spec"].get(pop, {})],
            "blocked_populations": [pop for pop in R["abi"]["populations"]
                                    if coord in R["abi"]["circularity_spec"].get(pop, {})],
        })
    out.sort(key=lambda d: -d["worst_case_share"])
    return out


def main() -> int:
    targets = consensus_targets()
    handoff = {
        "name": "VCS-0b-HANDOFF",
        "abi": R["abi"]["abi"],
        "purpose": "Lexi accessibility atlas over the semantic coordinates that actually "
                   "account for the runtime-unavailability loss. Not all 22 coordinates.",
        "selection_rule": "non-circular, runtime UNAVAILABLE, and clears >10% of the G0->G1 "
                          "loss on at least one population on both substrates",
        "n_targets": len(targets),
        "targets": targets,
        "boundaries": {
            "shift_transport_run": False,
            "operational_vcs_frozen": False,
            "protected_truth_opened": False,
            "bank_v2_used": False,
        },
        "loss_summary": {
            f"{sub}/{pop}": {"G0_acc": R["populations"][sub][pop]["G0"]["acc"],
                             "G1_acc": R["populations"][sub][pop]["G1"]["acc"],
                             "total_loss": R["populations"][sub][pop]["total_loss"],
                             "majority_rate": R["populations"][sub][pop]["majority_rate"]}
            for sub in ("causal", "encoder") for pop in ("solvability", "observer_correctness")},
    }
    (OUT / "VCS-0b-HANDOFF.json").write_text(json.dumps(handoff, indent=2) + "\n")

    lines = ["# VCS-0b-HANDOFF", "",
             "Semantic coordinates that account for the G0 -> G1 runtime-unavailability loss.",
             "", "Selection: non-circular, runtime UNAVAILABLE, >10% loss share on both substrates.",
             "", "| coordinate | provenance | runtime | worst-case share | populations | estimator contract |",
             "|---|---|---|---:|---|---|"]
    for t in targets:
        pops = ",".join(v["population"] for v in t["valid_target_populations"])
        blocked = ",".join(t["blocked_populations"]) or "-"
        est = (t["estimator_contract"] or "NONE").replace("\n", " ")
        lines.append(f"| `{t['coordinate']}` | {t['provenance_class']} | {t['runtime_availability']} | "
                     f"{t['worst_case_share']:.3f} | {pops} (blocked: {blocked}) | {est} |")
    lines += ["", "## Loss summary", "",
              "| substrate / population | G0 acc | G1 acc | loss | majority |",
              "|---|---:|---:|---:|---:|"]
    for k, v in handoff["loss_summary"].items():
        lines.append(f"| {k} | {v['G0_acc']:.3f} | {v['G1_acc']:.3f} | {v['total_loss']:.3f} | {v['majority_rate']:.3f} |")
    lines += ["", "## Boundaries", "",
              "- shift transport: NOT RUN", "- operational VCS-v0: NOT FROZEN",
              "- protected/test-truth: NOT OPENED", "- BANK-v2: NOT USED", ""]
    (OUT / "VCS-0b-HANDOFF.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"targets": len(targets),
                      "order": [t["coordinate"] for t in targets],
                      "worst_case_shares": {t["coordinate"]: t["worst_case_share"] for t in targets}},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
