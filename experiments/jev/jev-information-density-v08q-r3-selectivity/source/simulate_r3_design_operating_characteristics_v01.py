"""Outcome-blind R3 design simulation using sealed pilot and S80 calibration."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02")
PILOT_DIR = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\evaluation-v03\criterion-discriminability-sizing-v01")
PILOT_PATH = PILOT_DIR / "criterion-discriminability-sizing-v01.json"
PILOT_SEAL_PATH = PILOT_DIR / "criterion-discriminability-sizing-seal-v01.json"
S80_PATH = RUN / "calibration-training-v02" / "pretreatment-s80-calibration-v02.json"
S80_SEAL_PATH = RUN / "calibration-training-v02" / "pretreatment-s80-calibration-v02-seal.json"
OUTPUT = RUN / "design-simulation-v03"
SIMULATION_SEED = 20260926
OUTER_REPLICATES = 5_000
BOOTSTRAP_OUTER = 800
BOOTSTRAP_INNER = 400
N_GRID = (24, 48, 96, 192, 384)
FLOORS = (0.001, 0.005, 0.010, 0.020)
R_CI_LOW = math.log(0.9)
R_CI_HIGH = math.log(1.1)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def verify_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    pilot_seal = json.loads(PILOT_SEAL_PATH.read_text(encoding="utf-8"))
    pilot = json.loads(PILOT_PATH.read_text(encoding="utf-8"))
    s80_seal = json.loads(S80_SEAL_PATH.read_text(encoding="utf-8"))
    s80 = json.loads(S80_PATH.read_text(encoding="utf-8"))
    if pilot_seal.get("status") != "Q_R2_DESIGN_ONLY_SIZING_OUTPUTS_SEALED":
        raise RuntimeError("R2 design-only sizing artifact is not sealed")
    if sha_file(PILOT_PATH) != next(row["sha256"] for row in pilot_seal["files"] if row["path"].endswith("criterion-discriminability-sizing-v01.json")):
        raise RuntimeError("R2 pilot sizing artifact hash mismatch")
    if s80_seal.get("status") != "SEALED_PRETREATMENT_ONLY_R3_S80_CALIBRATION" or sha_file(S80_PATH) != s80_seal["summary_sha256"]:
        raise RuntimeError("R3 pre-treatment S80 calibration is not sealed or hash-identical")
    if s80.get("treatment_outcomes_opened") is not False or s80.get("confirmatory_panel_opened") is not False:
        raise RuntimeError("S80 design input is not pre-treatment-only")
    return pilot, s80, pilot_seal


def ots_rank(n: int, alpha: float = 0.05) -> tuple[int, float]:
    """Narrowest symmetric order-statistic interval with coverage >= 1-alpha."""
    tail = 0.0
    best = 1
    best_coverage = 1.0
    for k in range(1, n // 2 + 1):
        tail += math.comb(n, k - 1) / (2 ** n)
        coverage = 1.0 - 2.0 * tail
        if coverage >= 1.0 - alpha:
            best, best_coverage = k, coverage
        else:
            break
    return best, best_coverage


def interval_matrix(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = values.shape[1]
    k, _coverage = ots_rank(n)
    ordered = np.sort(values, axis=1)
    return ordered[:, k - 1], ordered[:, n - k], np.median(values, axis=1)


def t975_approx(df: int) -> float:
    z = 1.959963984540054
    d = float(df)
    return z + (z**3 + z) / (4 * d) + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * d**2)


def hc3_slope(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = x.shape[1]
    centered = x - x.mean(axis=1, keepdims=True)
    sxx = np.square(centered).sum(axis=1, keepdims=True)
    if np.any(sxx <= 0):
        raise RuntimeError("S80 moderator has no within-cohort support")
    slope = (centered * (y - y.mean(axis=1, keepdims=True))).sum(axis=1, keepdims=True) / sxx
    intercept = y.mean(axis=1, keepdims=True) - slope * x.mean(axis=1, keepdims=True)
    residual = y - intercept - slope * x
    leverage = 1.0 / n + np.square(centered) / sxx
    adjusted = residual / (1.0 - leverage)
    variance = (np.square(centered * adjusted).sum(axis=1, keepdims=True) / np.square(sxx))
    se = np.sqrt(variance)
    return slope[:, 0], se[:, 0] * t975_approx(n - 2)


def simulate_cohorts(
    *,
    n: int,
    repetitions: int,
    attenuation: float,
    c_center: float,
    gamma_per_sd: float,
    beta_per_s80_q10_q90_span: float = 0.0,
    pilot_b: np.ndarray,
    pilot_c: np.ndarray,
    pilot_r: np.ndarray,
    s80_values: np.ndarray,
    rng: np.random.Generator,
    upper_variance_factor: float = 1.0,
    high_state_reversal: float = 0.0,
) -> dict[str, np.ndarray]:
    idx = rng.integers(0, len(pilot_b), size=(repetitions, n))
    c_residual = pilot_c[idx] - np.median(pilot_c)
    m_role = c_center + c_residual
    r_residual = pilot_r[idx] - np.median(pilot_r)
    x_idx = rng.integers(0, len(s80_values), size=(repetitions, n))
    s80 = s80_values[x_idx]
    x_sd = (s80 - s80_values.mean()) / s80_values.std(ddof=1)
    robust_span = np.quantile(s80_values, 0.90, method="linear") - np.quantile(s80_values, 0.10, method="linear")
    x_span = (s80 - s80_values.mean()) / robust_span
    if upper_variance_factor != 1.0:
        threshold = np.quantile(s80_values, 0.90, method="linear")
        r_residual = r_residual * np.where(s80 >= threshold, upper_variance_factor, 1.0)
    r = math.log1p(-attenuation) + r_residual + gamma_per_sd * x_sd
    if high_state_reversal:
        threshold = np.quantile(s80_values, 0.90, method="linear")
        r = r + np.where(s80 >= threshold, high_state_reversal, 0.0)
    baseline = pilot_b[idx]
    half = baseline * np.exp(r)
    d = half - baseline + beta_per_s80_q10_q90_span * x_span
    half = baseline + d
    observed_r = np.full_like(d, np.nan)
    positive = half > 0
    observed_r[positive] = np.log(half[positive] / baseline[positive])
    return {"M": m_role, "R": observed_r, "D": d, "B": baseline, "HALF_S": half,
            "S80": s80, "X80": x_span, "X80_SD": x_sd}


def coverage_and_width_comparison(
    population: np.ndarray, rng: np.random.Generator, n_values: tuple[int, ...]
) -> list[dict[str, Any]]:
    truth = float(np.median(population))
    result = []
    outer = BOOTSTRAP_OUTER
    inner = BOOTSTRAP_INNER
    for n in n_values:
        draw = rng.integers(0, len(population), size=(outer, n))
        cohorts = population[draw]
        ordered = np.sort(cohorts, axis=1)
        k, ots_nominal_coverage = ots_rank(n)
        ots_low, ots_high = ordered[:, k - 1], ordered[:, n - k]
        boot_low = np.empty(outer)
        boot_high = np.empty(outer)
        for i in range(outer):
            boot_index = rng.integers(0, n, size=(inner, n))
            boot_median = np.median(cohorts[i][boot_index], axis=1)
            boot_low[i], boot_high[i] = np.quantile(boot_median, (0.025, 0.975), method="linear")
        ots_width = ots_high - ots_low
        boot_width = boot_high - boot_low
        result.append({
            "n": n,
            "target_median_empirical_pseudopopulation": truth,
            "order_statistic_nominal_minimum_coverage": ots_nominal_coverage,
            "order_statistic_empirical_coverage": float(np.mean((ots_low <= truth) & (truth <= ots_high))),
            "order_statistic_median_width": float(np.median(ots_width)),
            "bootstrap_percentile_empirical_coverage": float(np.mean((boot_low <= truth) & (truth <= boot_high))),
            "bootstrap_percentile_median_width": float(np.median(boot_width)),
            "bootstrap_width_fraction_of_order_width": float(np.median(boot_width) / np.median(ots_width)) if np.median(ots_width) else None,
            "outer_replicates": outer,
            "inner_bootstrap_replicates": inner,
        })
    return result


def run_main_simulation() -> dict[str, Any]:
    pilot, s80, pilot_seal = verify_inputs()
    rows = pilot["history_rows"]
    baseline = np.asarray([row["baseline_B_1x_fact_minus_anchor_logodds"] for row in rows], dtype=np.float64)
    criterion = np.asarray([row["criterion_C_anchor_HALF_minus_1X_logodds"] for row in rows], dtype=np.float64)
    delta = np.asarray([row["discriminability_D_HALF_minus_1X_fact_minus_anchor_logodds"] for row in rows], dtype=np.float64)
    if np.any(baseline <= 0) or np.any(baseline + delta <= 0):
        raise RuntimeError("R2 pilot has nonpositive branch separation")
    ratio = np.log((baseline + delta) / baseline)
    s80_values = np.asarray([row["S80_role_oriented"] for row in s80["histories"]], dtype=np.float64)
    if len(s80_values) != 48 or np.any(s80_values <= 0):
        raise RuntimeError("balanced-training S80 calibration sample invalid")

    rng = np.random.default_rng(SIMULATION_SEED)
    by_n = []
    for n in N_GRID:
        scenarios = []
        for attenuation in (0.0, 0.05, 0.10, 0.15, 0.20):
            values = simulate_cohorts(
                n=n, repetitions=OUTER_REPLICATES, attenuation=attenuation, c_center=0.12,
                gamma_per_sd=0.0, pilot_b=baseline, pilot_c=criterion, pilot_r=ratio,
                s80_values=s80_values, rng=rng,
            )
            m_lo, m_hi, _ = interval_matrix(values["M"])
            d_lo, d_hi, _ = interval_matrix(values["D"])
            r_lo, r_hi, _ = interval_matrix(values["R"])
            beta, beta_margin = hc3_slope(values["X80"], values["D"])
            m_pass = m_lo > 0
            d_pass = d_hi < 0
            r_pass = r_hi < 0
            beta_pass = (beta - beta_margin > 0) | (beta + beta_margin < 0)
            r_equivalent = (r_lo >= R_CI_LOW) & (r_hi <= R_CI_HIGH)
            scenarios.append({
                "scenario": "location_shifted_R2_whole_history_resampling",
                "true_median_log_ratio_scenario": math.log1p(-attenuation),
                "attenuation_fraction": attenuation,
                "M_median_positive_interval_probability": float(np.mean(m_pass)),
                "D_median_upper_below_zero_probability": float(np.mean(d_pass)),
                "R_median_upper_below_zero_probability": float(np.mean(r_pass)),
                "R_median_equivalence_interval_probability": float(np.mean(r_equivalent)),
                "ratio_scope_assumption": "all histories eligible; no S_min applied in this primary scenario table",
                "beta_nonzero_HC3_interval_probability": float(np.mean(beta_pass)),
                "fixed_sequence_through_R_probability": float(np.mean(m_pass & d_pass & r_pass)),
                "fixed_sequence_through_beta_probability": float(np.mean(m_pass & d_pass & r_pass & beta_pass)),
                "median_width_M_D_R": {
                    "M": float(np.median(m_hi - m_lo)),
                    "D": float(np.median(d_hi - d_lo)),
                    "R": float(np.median(r_hi - r_lo)),
                },
            })

        # Stress the actual primary moderator with a coherent state-dependent R -> D construction.
        moderator_cases = []
        for gamma in (-0.20, -0.10, 0.0, 0.10, 0.20):
            values = simulate_cohorts(
                n=n, repetitions=OUTER_REPLICATES, attenuation=0.10, c_center=0.12,
                gamma_per_sd=gamma, pilot_b=baseline, pilot_c=criterion, pilot_r=ratio,
                s80_values=s80_values, rng=rng,
            )
            beta, margin = hc3_slope(values["X80"], values["D"])
            lo, hi, _ = interval_matrix(values["D"])
            moderator_cases.append({
                "log_ratio_change_per_calibration_SD": gamma,
                "beta_nonzero_HC3_interval_probability": float(np.mean((beta - margin > 0) | (beta + margin < 0))),
                "median_beta_hat": float(np.median(beta)),
                "median_beta_interval_width": float(np.median(2 * margin)),
                "D_median_upper_below_zero_probability": float(np.mean(hi < 0)),
            })
        for beta_value in (-0.02, -0.01, -0.005, 0.0, 0.005, 0.01, 0.02):
            values = simulate_cohorts(
                n=n, repetitions=OUTER_REPLICATES, attenuation=0.10, c_center=0.12,
                gamma_per_sd=0.0, beta_per_s80_q10_q90_span=beta_value, pilot_b=baseline,
                pilot_c=criterion, pilot_r=ratio, s80_values=s80_values, rng=rng,
            )
            beta, margin = hc3_slope(values["X80"], values["D"])
            moderator_cases.append({
                "direct_D_change_across_calibration_S80_q10_q90_span": beta_value,
                "beta_nonzero_HC3_interval_probability": float(np.mean((beta - margin > 0) | (beta + margin < 0))),
                "median_beta_hat": float(np.median(beta)),
                "median_beta_interval_width": float(np.median(2 * margin)),
                "fraction_nonpositive_HALF_separation": float(np.mean(values["HALF_S"] <= 0)),
            })
        for label, variance_factor, reversal in (
            ("upper_decile_variance_doubled", 2.0, 0.0),
            ("upper_decile_positive_sign_reversal", 1.0, 0.20),
        ):
            values = simulate_cohorts(
                n=n, repetitions=OUTER_REPLICATES, attenuation=0.10, c_center=0.12,
                gamma_per_sd=0.0, pilot_b=baseline, pilot_c=criterion, pilot_r=ratio,
                s80_values=s80_values, rng=rng, upper_variance_factor=variance_factor,
                high_state_reversal=reversal,
            )
            beta, margin = hc3_slope(values["X80"], values["D"])
            moderator_cases.append({
                "stress_case": label,
                "log_ratio_change_per_calibration_SD": 0.0,
                "beta_nonzero_HC3_interval_probability": float(np.mean((beta - margin > 0) | (beta + margin < 0))),
                "median_beta_hat": float(np.median(beta)),
                "median_beta_interval_width": float(np.median(2 * margin)),
                "median_R": float(np.median(values["R"])),
            })
        by_n.append({"n_histories": n, "minimum_expected_count_at_calibration_q95": n * 0.05,
                     "median_interval_scenarios": scenarios, "S80_moderation_scenarios": moderator_cases})

    m_sensitivity = []
    for n in N_GRID:
        for m_center in (0.0, 0.03, 0.06, 0.12):
            values = simulate_cohorts(
                n=n, repetitions=OUTER_REPLICATES, attenuation=0.10, c_center=m_center,
                gamma_per_sd=0.0, pilot_b=baseline, pilot_c=criterion, pilot_r=ratio,
                s80_values=s80_values, rng=rng,
            )
            lo, _hi, _median = interval_matrix(values["M"])
            m_sensitivity.append({"n": n, "M_median_scenario": m_center,
                                  "M_median_interval_lower_above_zero_probability": float(np.mean(lo > 0))})

    # Ratio coverage sensitivity. The numeric floors are candidates for sizing only, not locked values.
    coverage_rows = []
    for n in (48, 96, 192, 384):
        for attenuation in (0.0, 0.10, 0.20):
            values = simulate_cohorts(
                n=n, repetitions=OUTER_REPLICATES, attenuation=attenuation, c_center=0.12,
                gamma_per_sd=0.0, pilot_b=baseline, pilot_c=criterion, pilot_r=ratio,
                s80_values=s80_values, rng=rng,
            )
            for floor in FLOORS:
                eligible = (values["B"] >= floor) & (values["HALF_S"] >= floor)
                fractions = eligible.mean(axis=1)
                row = {"n": n, "attenuation_fraction": attenuation, "candidate_S_min": floor,
                       "median_eligible_fraction": float(np.median(fractions)),
                       "q05_eligible_fraction": float(np.quantile(fractions, 0.05, method="linear"))}
                for threshold in (0.80, 0.90, 0.95):
                    row[f"P_coverage_ge_{int(threshold * 100)}pct"] = float(np.mean(fractions >= threshold))
                coverage_rows.append(row)

    # Same-generation null, role, and pole simulations for the semantic/polarity decomposition.
    n = 96
    iterations = OUTER_REPLICATES
    idx = rng.integers(0, len(criterion), size=(iterations, n))
    c_residual = criterion[idx] - np.median(criterion)
    role_m = 0.12 + c_residual
    absent_m = c_residual
    pole_m = c_residual
    pole_p = 0.12 + c_residual
    role_lo, role_hi, _ = interval_matrix(role_m)
    absent_lo, absent_hi, _ = interval_matrix(absent_m)
    pole_m_lo, pole_m_hi, _ = interval_matrix(pole_m)
    pole_p_lo, pole_p_hi, _ = interval_matrix(pole_p)
    pole_high_to_low = pole_m + pole_p
    pole_low_to_high = pole_m - pole_p
    m_pole_recovered = (pole_high_to_low + pole_low_to_high) / 2
    p_pole_recovered = (pole_high_to_low - pole_low_to_high) / 2
    role_p = np.zeros_like(role_m)
    result = {
        "status": "R3_OUTCOME_BLIND_DESIGN_SIMULATION_COMPLETE",
        "scope": "planning only; no R3 confirmatory panel or HALF branch outcomes; whole history is the simulation unit",
        "inputs": {
            "R2_design_sizing_file_sha256": sha_file(PILOT_PATH),
            "R2_design_sizing_root_sha256": pilot_seal["output_root_sha256"],
            "R3_S80_summary_sha256": sha_file(S80_PATH),
            "R3_S80_seal_sha256": sha_file(S80_SEAL_PATH),
            "pilot_histories": len(rows),
            "balanced_pretreatment_S80_histories": len(s80_values),
        },
        "simulation": {
            "rng": "NumPy PCG64",
            "seed": SIMULATION_SEED,
            "outer_replicates": OUTER_REPLICATES,
            "history_counts": list(N_GRID),
            "R_equivalence_band": [R_CI_LOW, R_CI_HIGH],
            "attenuation_scenarios": [0.0, 0.05, 0.10, 0.15, 0.20],
            "moderator_scenarios": [-0.20, -0.10, 0.0, 0.10, 0.20],
            "interpretation_note": "R2 residuals are deliberately a planning pseudo-population, not an assumed balanced-R3 response law.",
        },
        "order_statistic_vs_bootstrap": {
            "rule": "narrowest symmetric order-statistic interval with at least 95% binomial coverage; compared with percentile whole-history bootstrap using linear quantiles",
            "decision_rule": "retain order-statistic default unless bootstrap coverage is calibrated and its median width is materially smaller; this simulation makes no inferential claim",
            "metrics": {
                name: coverage_and_width_comparison(array, rng, (24, 48, 96, 192))
                for name, array in (("C", criterion), ("D", delta), ("R", ratio))
            },
        },
        "decision_operating_characteristics": by_n,
        "M_effect_sensitivity": m_sensitivity,
        "ratio_coverage_sensitivity": coverage_rows,
        "role_pole_scenarios_at_N96": {
            "role_following_M_median_positive_probability": float(np.mean(role_lo > 0)),
            "role_following_P_median_positive_probability": float(np.mean(interval_matrix(role_p)[0] > 0)),
            "balanced_training_C_absent_M_false_positive_probability": float(np.mean(absent_lo > 0)),
            "balanced_training_C_absent_P_false_positive_probability": float(np.mean(interval_matrix(np.zeros_like(absent_m))[0] > 0)),
            "pole_following_M_positive_probability": float(np.mean(pole_m_lo > 0)),
            "pole_following_P_positive_probability": float(np.mean(pole_p_lo > 0)),
            "definition": "M=(C_HL+C_LH)/2 role component; P=(C_HL-C_LH)/2 low-pole component",
            "simulation_note": "R2 C is reused only as a location/dispersion scale; role/pole assignment scenarios are synthetic because R2 observed one polarity only.",
        },
        "S80_distribution": {
            "median": float(np.median(s80_values)),
            "mean": float(np.mean(s80_values)),
            "sd": float(np.std(s80_values, ddof=1)),
            "q90": float(np.quantile(s80_values, 0.90, method="linear")),
            "q10": float(np.quantile(s80_values, 0.10, method="linear")),
            "q10_q90_span": float(np.quantile(s80_values, 0.90, method="linear") - np.quantile(s80_values, 0.10, method="linear")),
            "q95": float(np.quantile(s80_values, 0.95, method="linear")),
            "count_ge_0_05": int(np.sum(s80_values >= 0.05)),
            "one_extreme_history_max": float(np.max(s80_values)),
            "calibration_histories_confirmatory_eligible": False,
        },
        "moderation_measurement_error": {
            "between_history_variance": float(np.var(s80_values, ddof=1)),
            "mean_within_history_measurement_variance": float(np.mean([row["within_history_measurement_se"] ** 2 for row in s80["histories"]])),
            "reliability_ratio_estimate": float(np.var(s80_values, ddof=1) / (np.var(s80_values, ddof=1) + np.mean([row["within_history_measurement_se"] ** 2 for row in s80["histories"]]))),
        },
        "outputs": "scenario probabilities and precision summaries are design inputs only; no thresholds, sample size, bridge arm, or treatment result are sealed by this simulation",
    }
    return result


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing existing design simulation namespace: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    result = run_main_simulation()
    output_path = OUTPUT / "design-operating-characteristics.json"
    write_json(output_path, result)
    seal = {
        "status": result["status"],
        "source_sha256": sha_file(Path(__file__).resolve()),
        "input_r2_pilot_sha256": sha_file(PILOT_PATH),
        "input_r2_seal_sha256": sha_file(PILOT_SEAL_PATH),
        "input_s80_sha256": sha_file(S80_PATH),
        "input_s80_seal_sha256": sha_file(S80_SEAL_PATH),
        "output_path": output_path.name,
        "output_bytes": output_path.stat().st_size,
        "output_sha256": sha_file(output_path),
        "seed": SIMULATION_SEED,
        "outer_replicates": OUTER_REPLICATES,
        "confirmatory_data_opened": False,
        "training_performed": False,
    }
    write_json(OUTPUT / "design-simulation-seal.json", seal)
    print(json.dumps({"status": seal["status"], "output_sha256": seal["output_sha256"],
                      "output_root": str(OUTPUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
