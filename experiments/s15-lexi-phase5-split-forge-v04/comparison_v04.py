"""Root-paired, null-safe comparison for the frozen Lexi Phase 5 v03 run."""
from __future__ import annotations

import numpy as np


def paired_interval(values, *, seed=20261002, draws=2000):
    """Bootstrap a mean over canonical roots; values may be fractional per root."""
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1:
        raise ValueError("Expected one value per canonical root")
    if not np.isfinite(values).all():
        raise ValueError("Non-finite paired statistic")
    if not len(values):
        return {"roots": 0, "difference": None, "bootstrap95": None}
    rng = np.random.default_rng(seed)
    boot = np.empty(draws, dtype=np.float64)
    for i in range(draws):
        boot[i] = values[rng.integers(len(values), size=len(values))].mean()
    return {
        "roots": int(len(values)),
        "difference": float(values.mean()),
        "bootstrap95": np.quantile(boot, [0.025, 0.975]).tolist(),
    }


def _axis_groups(meta, axis):
    """Return stable display/value/root-index groups, retaining null as N/A."""
    root_meta = meta[0::2]
    if len(meta) % 2:
        raise ValueError("Renderer population is not paired")
    groups = {}
    for i, row in enumerate(root_meta):
        value = row["axes"][axis]
        key = "not_applicable" if value is None else str(value)
        groups.setdefault(key, {"value": value, "indices": []})["indices"].append(i)
    def order(item):
        key, entry = item
        value = entry["value"]
        return (value is None, value if isinstance(value, (int, float)) else key)
    return [(key, groups[key]["value"], np.asarray(groups[key]["indices"], dtype=np.int64))
            for key in sorted(groups, key=lambda key: order((key, groups[key])))]


def compare_depths(dev, a_report, b_report):
    """Compare saved A/B prediction identities, preserving each B draw separately."""
    root_count = len(dev.meta) // 2
    if len(dev.meta) != 2 * root_count:
        raise ValueError("Expected adjacent paired renderers")
    for i in range(root_count):
        if dev.meta[2 * i]["root"] != dev.meta[2 * i + 1]["root"]:
            raise ValueError("Renderer rows are not adjacent within canonical roots")

    y = np.asarray(dev.arrays["action"])
    if y.shape[0] != 2 * root_count:
        raise ValueError("Action labels do not align with metadata")
    y_pair = y.reshape(root_count, 2)
    valid_roots = (y_pair >= 0).all(axis=1)
    truth = y.reshape(-1, 2)
    seeds = [int(b_report["operational"]["seed"])] + [
        int(report["seed"]) for report in b_report["diagnostic_seeds"]
    ]
    if len(set(seeds)) != len(seeds):
        raise ValueError("Stochastic diagnostic seeds are not unique")

    cache = {}
    def prediction(identity, seed, depth):
        key = (identity, seed, depth)
        if key not in cache:
            path = dev.path.parent.parent / "predictions" / identity / f"{seed}-T{depth}.npz"
            with np.load(path, allow_pickle=False) as archive:
                cache[key] = archive["action"].astype(np.int64, copy=True)
        value = cache[key]
        if value.shape != y.shape:
            raise ValueError(f"Prediction shape mismatch for {key}: {value.shape}")
        return value

    root_correct = {}
    for seed in seeds:
        for depth in range(5):
            ap = prediction("A_DETERMINISTIC", int(a_report["seed"]), depth)
            bp = prediction("B_STOCHASTIC", seed, depth)
            ac = (ap == y).reshape(root_count, 2).mean(axis=1)
            bc = (bp == y).reshape(root_count, 2).mean(axis=1)
            root_correct[("A", seed, depth)] = ac
            root_correct[("B", seed, depth)] = bc

    curves = []
    high_depth_change = {"composition_depth": {}, "transition_depth": {}}
    for seed in seeds:
        for depth in range(5):
            delta = root_correct[("B", seed, depth)] - root_correct[("A", seed, depth)]
            row = {
                "seed": seed,
                "depth": depth,
                "B_minus_A_exact_action": paired_interval(delta[valid_roots], seed=seed + depth),
                "hard_slices": {},
                "depth_conditioned_gain_vs_T0": {},
            }
            for axis in ("composition_depth", "transition_depth"):
                for key, value, indices in _axis_groups(dev.meta, axis):
                    selected = indices[valid_roots[indices]]
                    mask = np.zeros(root_count, dtype=bool)
                    mask[selected] = True
                    row["hard_slices"][f"{axis}={key}"] = {
                        "value": value,
                        **paired_interval(delta[mask], seed=seed + depth + len(axis)),
                    }
                    if value is None or depth == 0:
                        continue
                    delta0 = root_correct[("B", seed, 0)] - root_correct[("A", seed, 0)]
                    change = delta - delta0
                    row["depth_conditioned_gain_vs_T0"][f"{axis}={key}"] = {
                        "value": value,
                        **paired_interval(change[mask], seed=seed + depth + len(axis) + 100),
                    }
                    if depth == 4 and isinstance(value, (int, float)) and value >= 2:
                        high_depth_change[axis].setdefault(str(seed), []).append(
                            row["depth_conditioned_gain_vs_T0"][f"{axis}={key}"]
                        )
            curves.append(row)

    terminal = [
        next(row for row in curves if row["seed"] == seed and row["depth"] == 4)
        ["B_minus_A_exact_action"] for seed in seeds
    ]
    terminal_means = [row["difference"] for row in terminal]

    high_depth_summary = {}
    for axis, per_seed in high_depth_change.items():
        high_depth_summary[axis] = {}
        for seed in seeds:
            strata = per_seed.get(str(seed), [])
            # Keep the individual strata. A weighted aggregate would conceal sparse cells.
            high_depth_summary[axis][str(seed)] = {
                "strata": strata,
                "any_stratum_lower_bound_above_zero": any(
                    v["bootstrap95"] is not None and v["bootstrap95"][0] > 0 for v in strata
                ),
            }

    if all(v is not None and v <= 0 for v in terminal_means):
        disposition = "B_RETIRE_NO_USEFUL_TERMINAL_COMPUTATION_GAIN"
    elif not all(v is not None and v > 0 for v in terminal_means):
        disposition = "B_RETIRE_NONREPEATABLE_TERMINAL_GAIN"
    else:
        repeatable = all(
            high_depth_summary[axis][str(seed)]["any_stratum_lower_bound_above_zero"]
            for axis in high_depth_summary
            for seed in seeds
        )
        if not repeatable:
            disposition = "B_RETIRE_NO_REPEATABLE_DEPTH_CONDITIONED_GAIN"
        else:
            disposition = "B_REQUIRES_STATE_PRESERVATION_REVIEW"

    return {
        "unit": "canonical root; two renderer descendants averaged within each root",
        "eligible_roots": int(valid_roots.sum()),
        "eligible_rows": int((y >= 0).sum()),
        "depth_differences": curves,
        "B_terminal_action_differences_by_seed": terminal,
        "high_depth_conditioned_gain": high_depth_summary,
        "disposition_before_semantic_preservation": disposition,
        "seed_policy": "one operational sampled trajectory plus two fixed-seed diagnostics; never averaged or selected",
        "axis_null_policy": "null capability-depth is retained as not_applicable and excluded from depth-gain claims",
        "bootstrap": {"draws": 2000, "unit": "paired canonical root", "seed_rule": "fixed seed derived from trajectory and depth"},
    }


def source_balanced_interval(dev, a_pred, b_pred, family, channel):
    """Root-paired bootstrap of B-A balanced-accuracy change for a source target."""
    ys = "cy" if family == "candidate" else "gy"
    valid_key = "ca" if family == "candidate" else "ga"
    y = np.asarray(dev.arrays[ys][..., channel], dtype=bool)
    valid = np.asarray(dev.arrays[valid_key][..., channel], dtype=bool).copy()
    if family == "candidate":
        valid &= np.asarray(dev.arrays["mask"], dtype=bool)
    if a_pred.shape != y.shape or b_pred.shape != y.shape:
        raise ValueError("Target predictions do not align with canonical labels")
    nroots = len(dev.meta) // 2

    def confusion(pred):
        bits = (y & pred, y & ~pred, ~y & ~pred, ~y & pred)
        return np.stack([
            (bit & valid).reshape(nroots, 2, -1).sum(axis=(1, 2)) for bit in bits
        ], axis=1).astype(np.float64)

    ac, bc = confusion(a_pred.astype(bool)), confusion(b_pred.astype(bool))
    def balanced(counts):
        tp, fn, tn, fp = counts.T
        pos = tp + fn
        neg = tn + fp
        return 0.5 * (tp / np.maximum(pos, 1) + tn / np.maximum(neg, 1))
    # Resampling over roots requires aggregating the class counts, not averaging root BAs.
    def delta_for(indices):
        ca, cb = ac[indices].sum(axis=0), bc[indices].sum(axis=0)
        return float(balanced(cb[None, :])[0] - balanced(ca[None, :])[0])

    rng = np.random.default_rng(20261002 + channel + (0 if family == "global" else 50))
    boot = np.empty(2000, dtype=np.float64)
    for i in range(len(boot)):
        boot[i] = delta_for(rng.integers(nroots, size=nroots))
    return {
        "roots": nroots,
        "difference": delta_for(np.arange(nroots)),
        "bootstrap95": np.quantile(boot, [0.025, 0.975]).tolist(),
    }


def count_mae_improvement(dev, a_count, b_count):
    target = np.asarray(dev.arrays["gy"][:, 5], dtype=np.float64)
    improvement = (np.abs(a_count - target) - np.abs(b_count - target)).reshape(-1, 2).mean(axis=1)
    eligible = np.asarray(dev.arrays["ga"][:, 5], dtype=bool).reshape(-1, 2).all(axis=1)
    return paired_interval(improvement[eligible], seed=20261002 + 151)
