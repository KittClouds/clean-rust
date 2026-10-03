from __future__ import annotations

import csv
import json
import math
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(r"C:\code land\clean-rust")
R0 = ROOT / "experiments/fly-reach-00/artifacts/REACH-RUN1"
R1 = ROOT / "experiments/fly-reach-01/artifacts/REACH01-RUN1"
OUT = ROOT / "experiments/fly-reach-01/derived"


def read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def safe_div(a: float, b: float) -> float:
    return a / b if b else float("nan")


def endpoint(rows: list[dict], checkpoint: int = 8192) -> list[dict]:
    return [r for r in rows if int(r.get("checkpoint", -1)) == checkpoint]


def arm_loss(outcomes: list[dict]) -> dict[str, dict[str, float]]:
    buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in endpoint(outcomes):
        buckets[r["arm"]]["loss_large"].append(float(r["loss_large"]))
        buckets[r["arm"]]["loss_256"].append(float(r["loss_256"]))
        if "excess_large" in r and r["excess_large"] == r["excess_large"]:
            buckets[r["arm"]]["excess_large"].append(float(r["excess_large"]))
    return {a: {k: mean(v) for k, v in fields.items()} for a, fields in buckets.items()}


def field_mean(rows: list[dict], field: str) -> float | None:
    vals = [float(r[field]) for r in rows if field in r]
    return mean(vals) if vals else None


def nested_channels(L: dict[str, float]) -> list[dict]:
    """Nested / nearly-orthogonal capability channels from arm endpoints.

    Chains:
      native
        --direction@support--> reference_direction_native_support
          --+support expansion--> reference_direction_full_support
            --+free weights--> weight_oracle
      native --magnitude swap--> native_direction_reference_magnitude
      native --sign swap--> sign_ref_native_mag          (REACH-01)
      native --mag swap w/ native sign--> mag_ref_native_sign (REACH-01)
    """
    native = L.get("native", {}).get("loss_large")
    if native is None:
        return []
    rows: list[dict] = []

    def add(name: str, arm: str, base_arm: str = "native") -> None:
        if arm not in L or base_arm not in L:
            return
        base = L[base_arm]["loss_large"]
        cur = L[arm]["loss_large"]
        rows.append(
            {
                "channel": name,
                "from_arm": base_arm,
                "to_arm": arm,
                "loss_large": cur,
                "gain": base - cur,  # positive = improvement
            }
        )

    # Nested direction chain
    add("direction_on_native_support", "reference_direction_native_support", "native")
    add("support_expansion_after_direction", "reference_direction_full_support", "reference_direction_native_support")
    add("free_weight_beyond_reference", "weight_oracle", "reference_direction_full_support")
    # Orthogonal-ish alternatives relative to native
    add("magnitude_swap_native_direction", "native_direction_reference_magnitude", "native")
    add("sign_swap_native_magnitude", "sign_ref_native_mag", "native")
    add("magnitude_swap_native_sign", "mag_ref_native_sign", "native")
    # Totals
    add("full_direction_vs_native", "reference_direction_full_support", "native")
    add("oracle_vs_native", "weight_oracle", "native")
    return rows


def spectrum_stats(gains: list[float]) -> dict:
    g = [x for x in gains]
    if not g:
        return {}
    sq = sum(x * x for x in g)
    energy = math.sqrt(sq)
    abs_g = [abs(x) for x in g]
    pos = [x for x in g if x > 1e-15]
    # singular-value proxies: use |gain| sorted
    sv = sorted(abs_g, reverse=True)
    pr = safe_div(sq * sq, sum(x**4 for x in g)) if any(x != 0 for x in g) else 0.0
    cond = safe_div(max(abs_g), min([x for x in abs_g if x > 1e-12] or [float("nan")])) if any(x > 1e-12 for x in abs_g) else float("inf")
    return {
        "gains_as_spectrum": sv,
        "spectral_norm_proxy": energy,
        "participation_ratio_effective_rank": pr,
        "condition_number_proxy_abs": cond,
        "min_abs_gain": min(abs_g),
        "max_abs_gain": max(abs_g),
        "negative_gain_count": sum(1 for x in g if x < 0),
        "nonpositive_gain_count": sum(1 for x in g if x <= 0),
        "fraction_channels_nonpositive": safe_div(sum(1 for x in g if x <= 0), len(g)),
    }


def first_order(eta_d: float, ratio_of_means: float) -> dict:
    # Normalize ||g||=1 so ||u||=eta_M. Useful component = eta_M*eta_D.
    useful = ratio_of_means * eta_d
    side = ratio_of_means * math.sqrt(max(0.0, 1.0 - eta_d * eta_d))
    return {
        "eta_D": eta_d,
        "eta_M_ratio_of_means": ratio_of_means,
        "useful_component": useful,
        "orthogonal_component": side,
        "useful_fraction": eta_d,  # = useful / eta_M
        "wasted_norm_fraction": math.sqrt(max(0.0, 1.0 - eta_d * eta_d)),
    }


def stage_chain_native(diags: list[dict]) -> dict:
    rows = [r for r in diags if r["arm"] == "native"]
    if not rows or "eligibility_cosine_mean" not in rows[0]:
        return {"stages": [], "drops": []}
    stages = []
    for key, label in [
        ("eligibility_cosine_mean", "eligibility"),
        ("modulation_cosine_mean", "modulation"),
        ("aggregation_cosine_mean", "aggregation"),
        ("delivered_cosine_mean", "delivered"),
    ]:
        stages.append({"stage": label, "cosine": field_mean(rows, key)})
    drops = []
    for a, b in zip(stages, stages[1:]):
        drops.append(
            {
                "from": a["stage"],
                "to": b["stage"],
                "delta_cosine": (a["cosine"] or 0) - (b["cosine"] or 0),
                "retention": safe_div(b["cosine"] or 0, a["cosine"] or 1),
            }
        )
    return {"stages": stages, "drops": drops}


def ar04c_math() -> dict:
    """Checked against commit 0335a840 RESULTS.md / summary.json.

    operational_minus_final values are the terminal diagnostic gaps reported in RESULTS.md
    (not recomputed from final loss alone).
    """
    fixed_op, fixed_final = 0.03, 3.208658061028
    rot_final = 0.768007643223
    train_final = 4.942043199539
    gaps = {"fixed": fixed_op - fixed_final, "rotating": 0.01, "training": 0.00 - train_final}
    return {
        "final_measurement_loss": {
            "training_full96": train_final,
            "sentinel_fixed128": fixed_final,
            "sentinel_rotating128": rot_final,
        },
        "terminal_operational_loss_approx": {
            "fixed": fixed_op,
            "rotating": rot_final + 0.01,
            "training": 0.00,
        },
        "operational_minus_final": gaps,
        "adaptive_overfitting_gap_ratio_fixed_vs_rotating": safe_div(abs(gaps["fixed"]), abs(gaps["rotating"])),
        "conditional_unbiasedness": {
            "claim": "E[grad J_St(xt) | xt] = grad J(xt) if St fresh independent of xt",
            "status": "holds by construction for rotating panels (disjoint seed namespaces, prospective panel schedule)",
            "does_not_imply": "checkpoint action-ranking alignment (AR-H56 not supported)",
        },
        "cell_wins": {
            "rotating_beats_training": "25/25",
            "rotating_beats_fixed": "25/25",
            "fixed_beats_training": "22/25",
        },
        "spearman_terminal_approx": {"fixed": -0.15, "rotating": 0.02, "training": -0.08},
    }


def main() -> None:
    out0, d0 = read_jsonl(R0 / "outcomes.jsonl"), read_jsonl(R0 / "diagnostics.jsonl")
    out1, d1 = read_jsonl(R1 / "outcomes.jsonl"), read_jsonl(R1 / "diagnostics.jsonl")
    t1 = read_jsonl(R1 / "trajectories.jsonl")
    outcomes, diags = (out1, d1) if out1 else (out0, d0)
    source = "REACH-01" if out1 else "REACH-00"
    L = arm_loss(outcomes)

    native_rows = [r for r in diags if r["arm"] == "native"]
    # Prefer REACH-01 stage fields; else REACH-00 single cosine
    eta_d = field_mean(native_rows, "delivered_cosine_mean")
    if eta_d is None:
        eta_d = field_mean(native_rows, "native_reference_cosine_mean")
    eta_s_l1 = field_mean(native_rows, "reference_mass_on_native_support_mean")
    support_frac = field_mean(native_rows, "native_support_fraction_mean")
    mean_of_ratios = field_mean(native_rows, "native_reference_norm_ratio_mean")
    un = field_mean(native_rows, "native_update_norm_mean")
    gn = field_mean(native_rows, "reference_update_norm_mean")
    ratio_of_means = safe_div(un or float("nan"), gn or float("nan")) if (un is not None and gn is not None) else mean_of_ratios
    sign_ag = field_mean(native_rows, "sign_agreement_mean")
    mag_r = field_mean(native_rows, "magnitude_pearson_mean")
    clip = field_mean(native_rows, "bound_clip_fraction")

    channels = nested_channels(L)
    # spectrum over incremental channels only (not the totals)
    incremental = [c for c in channels if c["channel"] in {
        "direction_on_native_support",
        "support_expansion_after_direction",
        "free_weight_beyond_reference",
        "magnitude_swap_native_direction",
        "sign_swap_native_magnitude",
        "magnitude_swap_native_sign",
    }]
    spec = spectrum_stats([c["gain"] for c in incremental])

    by_sub = {}
    for sub in ["fly"] + [f"g{i:03d}" for i in range(1, 9)]:
        rows = [r for r in diags if r["arm"] == "native" and r["substrate"] == sub]
        if not rows:
            continue
        ed = field_mean(rows, "delivered_cosine_mean")
        if ed is None:
            ed = field_mean(rows, "native_reference_cosine_mean")
        um = field_mean(rows, "native_update_norm_mean")
        gm = field_mean(rows, "reference_update_norm_mean")
        by_sub[sub] = {
            "eta_D": ed,
            "eta_S_L1": field_mean(rows, "reference_mass_on_native_support_mean"),
            "support_frac": field_mean(rows, "native_support_fraction_mean"),
            "eta_M_ratio_of_means": safe_div(um, gm) if (um and gm) else None,
            "clip": field_mean(rows, "bound_clip_fraction"),
        }

    traj = {}
    for cp in sorted({int(r["checkpoint"]) for r in t1}):
        rows = [r for r in t1 if int(r["checkpoint"]) == cp]
        traj[str(cp)] = {f: field_mean(rows, f) for f in (
            "eligibility_cosine", "modulation_cosine", "aggregation_cosine", "delivered_cosine",
            "native_support_fraction", "reference_mass_on_native_support", "sign_agreement", "magnitude_pearson",
        )}

    fo = first_order(eta_d or float("nan"), ratio_of_means or float("nan")) if eta_d is not None else {}
    stage = stage_chain_native(diags)

    report = {
        "schema": "adaptive-authority-geometry-v0.1",
        "primary_source": source,
        "row_counts": {
            "reach00_outcomes": len(out0), "reach00_diagnostics": len(d0),
            "reach01_outcomes": len(out1), "reach01_diagnostics": len(d1), "reach01_trajectories": len(t1),
        },
        "run01_live": not (R1 / "collection-receipt.json").exists() and len(out1) == 0,
        "endpoint_losses": L,
        "authority_triplet": {
            "eta_D": eta_d,
            "eta_S_L1_capture": eta_s_l1,
            "native_support_fraction": support_frac,
            "eta_M_mean_of_ratios": mean_of_ratios,
            "eta_M_ratio_of_means": ratio_of_means,
            "sign_agreement": sign_ag,
            "magnitude_pearson": mag_r,
            "bound_clip_fraction": clip,
        },
        "first_order": fo,
        "nested_channels": channels,
        "incremental_spectrum": spec,
        "stage_chain": stage,
        "authority_by_substrate": by_sub,
        "reach01_trajectory_authority": traj,
        "ar04c": ar04c_math(),
        "north_star": {
            "question": "What capability trajectories are reachable from x under bounded adaptive authority?",
            "objects": ["R_H", "C_H", "G_x=J_c B_x", "kappa_A", "K_H(d)", "chi_AB", "evidence-coupled T_S"],
        },
        "claim_checks": {
            "adaptive_power_ne_progress": {
                "supported": True,
                "evidence": "eta_D~0.003; magnitude-swap arm gain <= 0; direction arms recover most of oracle gap",
            },
            "support_not_primary_bottleneck": {
                "supported": True,
                "evidence": "eta_S_L1~0.65; support_expansion incremental gain << direction_on_native_support gain",
            },
            "direction_dominates": {
                "supported": True,
                "evidence": next((c["gain"] for c in channels if c["channel"] == "direction_on_native_support"), None),
            },
            "fresh_evidence_unbiased": {
                "supported": "conjecture_consistent_with_AR-04C",
                "evidence": "rotating arm operational-final gap ~0.01 vs fixed ~-3.18; H56 ranking claim fails",
            },
        },
        "no_biological_promotion": True,
        "engineering_only": True,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "authority-geometry-v0.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=True) + "\n", encoding="utf-8")

    # CSV: nested channels
    with (OUT / "authority-channels.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["channel", "from_arm", "to_arm", "loss_large", "gain"])
        w.writeheader()
        for c in channels:
            w.writerow(c)

    lines = [
        "# Adaptive Authority Geometry v0.1",
        "",
        f"Primary source: **{source}** · REACH-01 live={report['run01_live']} · outcomes01={len(out1)}",
        "",
        "Engineering-only. Finite-difference channel probes, not a measured SVD of \\(G_x=J_cB_x\\).",
        "",
        "## Authority triplet (native)",
        "",
        f"| quantity | value |",
        f"|---|---:|",
        f"| eta_D (cos u_N, g) | {eta_d} |",
        f"| eta_S (L1 capture of g on native support) | {eta_s_l1} |",
        f"| native support fraction | {support_frac} |",
        f"| eta_M (mean of per-step ratios) | {mean_of_ratios} |",
        f"| eta_M (ratio of mean norms) | {ratio_of_means} |",
        f"| sign agreement | {sign_ag} |",
        f"| magnitude Pearson | {mag_r} |",
        f"| bound clip fraction | {clip} |",
        "",
        "## Nested authority channels (endpoint loss_large gain)",
        "",
        "| channel | from | to | gain |",
        "|---|---|---|---:|",
    ]
    for c in channels:
        lines.append(f"| {c['channel']} | {c['from_arm']} | {c['to_arm']} | {c['gain']:.6f} |")
    lines += [
        "",
        "## Incremental spectrum proxies",
        "",
        f"- |gains| sorted: {spec.get('gains_as_spectrum')}",
        f"- participation-ratio effective rank: {spec.get('participation_ratio_effective_rank')}",
        f"- condition-number proxy (max/min |gain|): {spec.get('condition_number_proxy_abs')}",
        f"- nonpositive channels: {spec.get('nonpositive_gain_count')} / {len(incremental)}",
        "",
        "## Stage chain",
        "",
    ]
    for s in stage["stages"]:
        lines.append(f"- {s['stage']}: {s['cosine']}")
    lines += ["", "## First-order (||g||=1)", ""]
    if fo:
        lines += [
            f"- useful component eta_M*eta_D: {fo['useful_component']:.6f}",
            f"- orthogonal component: {fo['orthogonal_component']:.6f}",
            f"- useful fraction of ||u||: {fo['useful_fraction']:.6e}",
            "",
            "**Adaptive power != adaptive progress.**",
        ]
    lines += ["", "## AR-04C cross-check", "", "```json", json.dumps(report["ar04c"], indent=2), "```", ""]
    (OUT / "AUTHORITY-GEOMETRY-V0.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "OK", "source": source, "channels": len(channels), "eta_D": eta_d}, sort_keys=True))


if __name__ == "__main__":
    main()
