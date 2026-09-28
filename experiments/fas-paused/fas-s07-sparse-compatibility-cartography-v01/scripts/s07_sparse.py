from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np

from s07_common import FailClosed

WIDTH = 16_384


def candidate_slot_to_state(slot_to_state: np.ndarray, target_slot: int) -> int:
    mapping = np.asarray(slot_to_state, dtype=np.int64)
    if mapping.shape != (3,) or not np.array_equal(np.sort(mapping), np.arange(3)) or target_slot not in (0, 1, 2):
        raise FailClosed("Candidate-position target or slot-to-state mapping is invalid")
    return int(mapping[target_slot])


def _active(indices: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = np.broadcast_to(np.arange(len(indices), dtype=np.int64)[:, None], indices.shape)
    keep = values > 0
    return rows[keep], indices[keep].astype(np.int64, copy=False), values[keep].astype(np.float64, copy=False)


def feature_statistics(indices: np.ndarray, values: np.ndarray) -> dict[str, np.ndarray]:
    n = len(indices)
    _, feature_ids, active_values = _active(indices, values)
    count = np.bincount(feature_ids, minlength=WIDTH).astype(np.int64)
    sums = np.bincount(feature_ids, weights=active_values, minlength=WIDTH)
    squares = np.bincount(feature_ids, weights=active_values * active_values, minlength=WIDTH)
    mean = sums / max(n, 1)
    variance = np.maximum(0.0, squares / max(n, 1) - mean * mean)
    mean_nz = np.divide(sums, count, out=np.zeros(WIDTH, dtype=np.float64), where=count > 0)
    quantiles = np.zeros((3, WIDTH), dtype=np.float32)
    if len(feature_ids):
        order = np.argsort(feature_ids, kind="stable")
        sorted_values = active_values[order]
        starts = np.cumsum(count) - count
        for feature in np.flatnonzero(count):
            active_n = int(count[feature])
            positives = np.sort(sorted_values[int(starts[feature]):int(starts[feature]) + active_n])
            zeros = n - active_n
            for qi, q in enumerate((0.5, 0.9, 0.99)):
                rank = max(0, int(np.ceil(q * n)) - 1)
                quantiles[qi, feature] = 0.0 if rank < zeros else float(positives[min(active_n - 1, rank - zeros)])
    return {
        "activation_count": count,
        "activation_frequency": count.astype(np.float64) / max(n, 1),
        "zero_mass": 1.0 - count.astype(np.float64) / max(n, 1),
        "mean": mean,
        "variance": variance,
        "mean_nonzero": mean_nz,
        "nearest_rank_q50_q90_q99": quantiles,
        "n": np.asarray(n, dtype=np.int64),
    }


def conditional_statistics(indices: np.ndarray, values: np.ndarray, labels: np.ndarray, groups: int) -> dict[str, np.ndarray]:
    n = len(indices)
    labels = np.asarray(labels, dtype=np.int64)
    if len(labels) != n:
        raise FailClosed("Conditional activation label count mismatch")
    row_ids, feature_ids, active_values = _active(indices, values)
    valid = (labels[row_ids] >= 0) & (labels[row_ids] < groups)
    group_ids = labels[row_ids[valid]]
    feature_ids = feature_ids[valid]
    active_values = active_values[valid]
    key = group_ids * WIDTH + feature_ids
    count = np.bincount(key, minlength=groups * WIDTH).reshape(groups, WIDTH).astype(np.int64)
    sums = np.bincount(key, weights=active_values, minlength=groups * WIDTH).reshape(groups, WIDTH)
    group_n = np.bincount(labels[(labels >= 0) & (labels < groups)], minlength=groups).astype(np.int64)
    rate = np.divide(count, group_n[:, None], out=np.zeros_like(sums), where=group_n[:, None] > 0)
    mean = np.divide(sums, group_n[:, None], out=np.zeros_like(sums), where=group_n[:, None] > 0)
    return {"group_n": group_n, "activation_frequency": rate, "mean": mean}


def top_coactivation_partners(indices_by_surface: dict[str, np.ndarray], values_by_surface: dict[str, np.ndarray], frequencies: dict[str, np.ndarray], top_count: int = 256, partner_count: int = 10) -> dict[str, Any]:
    combined = frequencies["M"] + frequencies["F"]
    feature_ids = np.arange(WIDTH)
    selected = np.lexsort((feature_ids, -combined))[:top_count]
    lookup = np.full(WIDTH, -1, dtype=np.int16)
    lookup[selected] = np.arange(top_count, dtype=np.int16)
    result: dict[str, Any] = {"selected_feature_ids": selected.astype(int).tolist(), "surfaces": {}}
    for surface, indices in indices_by_surface.items():
        values = values_by_surface[surface]
        if values.shape != indices.shape:
            raise FailClosed("Coactivation index/value shape mismatch")
        matrix = np.zeros((top_count, top_count), dtype=np.int64)
        compact = lookup[indices.astype(np.int64)]
        for row, row_values in zip(compact, values):
            active = np.sort(row[(row >= 0) & (row_values > 0)].astype(np.int64))
            for left, right in combinations(active.tolist(), 2):
                matrix[left, right] += 1
                matrix[right, left] += 1
        partners = []
        for local, feature_id in enumerate(selected):
            counts = matrix[local].copy()
            counts[local] = -1
            rank = np.lexsort((selected, -counts))[:partner_count]
            partners.append({
                "feature_id": int(feature_id),
                "partners": [{"feature_id": int(selected[j]), "coactivation_count": int(matrix[local, j])} for j in rank if matrix[local, j] > 0],
            })
        result["surfaces"][surface] = {"partner_lists": partners, "pair_count_nonzero": int(np.count_nonzero(np.triu(matrix, 1)))}
    return result


def state_to_slot(slot_to_state: np.ndarray) -> np.ndarray:
    mapping = np.asarray(slot_to_state, dtype=np.int64)
    if mapping.ndim != 2 or mapping.shape[1] != 3 or not np.all(np.sort(mapping, axis=1) == np.arange(3)):
        raise FailClosed("Invalid candidate slot to semantic class map")
    result = np.empty_like(mapping)
    result[np.arange(len(mapping))[:, None], mapping] = np.arange(3)[None, :]
    return result


def semantic_kappa(weights: np.ndarray, decoder: np.ndarray, slot_map: np.ndarray, pair: tuple[int, int]) -> np.ndarray:
    slot = state_to_slot(slot_map)
    slots_a, slots_b = slot[:, pair[0]], slot[:, pair[1]]
    kappa_slots = np.asarray(weights) @ np.asarray(decoder)
    codes = slots_a * 3 + slots_b
    sums = np.zeros(WIDTH, dtype=np.float64)
    squares = np.zeros(WIDTH, dtype=np.float64)
    for code in np.unique(codes):
        mask = codes == code
        a, b = divmod(int(code), 3)
        vector = kappa_slots[a] - kappa_slots[b]
        count = int(mask.sum())
        sums += count * vector
        squares += count * vector * vector
    n = max(len(slot), 1)
    mean = sums / n
    variance = np.maximum(0.0, squares / n - mean * mean)
    return np.stack([mean, variance])


def paired_margin_contributions(
    code_m: dict[str, np.ndarray],
    code_f: dict[str, np.ndarray],
    decoder: np.ndarray,
    weights_m: np.ndarray,
    weights_f: np.ndarray,
    slot_map: np.ndarray,
) -> dict[str, np.ndarray]:
    ids_m = code_m["indices"].astype(np.int64)
    vals_m = code_m["values"].astype(np.float64)
    ids_f = code_f["indices"].astype(np.int64)
    vals_f = code_f["values"].astype(np.float64)
    if ids_m.shape != ids_f.shape or len(slot_map) != len(ids_m):
        raise FailClosed("Paired sparse code/mapping shape mismatch")
    state_slot = state_to_slot(slot_map)
    km = np.asarray(weights_m) @ np.asarray(decoder)
    kf = np.asarray(weights_f) @ np.asarray(decoder)
    result = {key: np.zeros((3, WIDTH), dtype=np.float64) for key in ("mean_m", "mean_f", "mean_delta", "mean_abs_delta", "delta_variance")}
    for boundary_index, (a, b) in enumerate(((0, 1), (0, 2), (1, 2))):
        slot_a = state_slot[:, a, None]
        slot_b = state_slot[:, b, None]
        c_m = vals_m * (km[slot_a, ids_m] - km[slot_b, ids_m])
        c_f = vals_f * (kf[slot_a, ids_f] - kf[slot_b, ids_f])
        n = len(ids_m)
        result["mean_m"][boundary_index] = np.bincount(ids_m.ravel(), weights=c_m.ravel(), minlength=WIDTH) / n
        result["mean_f"][boundary_index] = np.bincount(ids_f.ravel(), weights=c_f.ravel(), minlength=WIDTH) / n
        delta_sum = np.zeros(WIDTH, dtype=np.float64)
        absolute_delta_sum = np.zeros(WIDTH, dtype=np.float64)
        delta_square_sum = np.zeros(WIDTH, dtype=np.float64)
        for row in range(n):
            row_ids = np.concatenate((ids_m[row], ids_f[row])).astype(np.int64, copy=False)
            row_values = np.concatenate((-c_m[row], c_f[row]))
            order = np.argsort(row_ids, kind="stable")
            sorted_ids = row_ids[order]
            sorted_values = row_values[order]
            starts = np.r_[0, np.flatnonzero(sorted_ids[1:] != sorted_ids[:-1]) + 1]
            unique_ids = sorted_ids[starts]
            event_delta = np.add.reduceat(sorted_values, starts)
            delta_sum[unique_ids] += event_delta
            absolute_delta_sum[unique_ids] += np.abs(event_delta)
            delta_square_sum[unique_ids] += event_delta * event_delta
        result["mean_delta"][boundary_index] = delta_sum / n
        result["mean_abs_delta"][boundary_index] = absolute_delta_sum / n
        second = delta_square_sum / n
        result["delta_variance"][boundary_index] = np.maximum(0.0, second - result["mean_delta"][boundary_index] ** 2)
    return result


def choose_feature_groups(
    contributions: dict[str, np.ndarray],
    frequency_m: np.ndarray,
    frequency_f: np.ndarray,
    mean_nonzero_m: np.ndarray,
    mean_nonzero_f: np.ndarray,
    decoder: np.ndarray,
    count: int = 64,
) -> dict[str, Any]:
    feature_ids = np.arange(WIDTH)
    selected: dict[str, list[int]] = {}
    scores: dict[str, list[float]] = {}
    boundary_names = ("class_0_vs_1", "class_0_vs_2", "class_1_vs_2")
    for bi, name in enumerate(boundary_names):
        score = np.abs(contributions["mean_delta"][bi])
        order = np.lexsort((feature_ids, -score))[:count]
        selected[name] = order.astype(int).tolist()
        scores[name] = score[order].astype(float).tolist()
    selected_union = {feature for values in selected.values() for feature in values}
    decoder_norm = np.linalg.norm(decoder.astype(np.float64), axis=0)
    pooled_frequency = 0.5 * (frequency_m + frequency_f)
    pooled_nonzero = 0.5 * (mean_nonzero_m + mean_nonzero_f)
    raw = np.stack([pooled_frequency, pooled_nonzero, decoder_norm], axis=1)
    mean = raw.mean(axis=0)
    scale = raw.std(axis=0)
    scale[scale < 1e-6] = 1.0
    normalized = (raw - mean) / scale
    available = np.asarray([i for i in feature_ids if i not in selected_union], dtype=np.int64)
    used: set[int] = set()
    controls: dict[str, list[int]] = {}
    distances: dict[str, list[float]] = {}
    for name in boundary_names:
        group_controls: list[int] = []
        group_distances: list[float] = []
        for chosen in selected[name]:
            candidates = np.asarray([item for item in available if int(item) not in used], dtype=np.int64)
            if len(candidates) == 0:
                raise FailClosed("Matched-control feature inventory exhausted")
            delta = normalized[candidates] - normalized[chosen]
            d2 = np.einsum("ij,ij->i", delta, delta)
            best = int(np.argmin(d2))
            control = int(candidates[best])
            used.add(control)
            group_controls.append(control)
            group_distances.append(float(np.sqrt(d2[best])))
        controls[name] = group_controls
        distances[name] = group_distances
    return {
        "selected_groups": selected,
        "selected_training_scores": scores,
        "matched_control_groups": controls,
        "matched_control_distances": distances,
        "selected_feature_union_size": len(selected_union),
        "control_features_are_unique": len(used) == sum(map(len, controls.values())),
        "control_features_overlap_selected": bool(used & selected_union),
    }


def sparse_logits(
    codes: dict[str, np.ndarray],
    decoder: np.ndarray,
    decoder_bias: np.ndarray,
    probe: dict[str, np.ndarray],
    slot_map: np.ndarray | None = None,
    zero_features: list[int] | None = None,
) -> np.ndarray:
    indices = codes["indices"].astype(np.int64, copy=False)
    values = codes["values"].astype(np.float64, copy=True)
    if zero_features:
        values[np.isin(indices, np.asarray(zero_features, dtype=np.int64))] = 0.0
    weights = np.asarray(probe["weights"], dtype=np.float64)
    bias = np.asarray(probe["bias"], dtype=np.float64)
    decoder = np.asarray(decoder, dtype=np.float64)
    decoder_bias = np.asarray(decoder_bias, dtype=np.float64)
    kappa = weights @ decoder
    offset = weights @ decoder_bias + bias
    selected = kappa[:, indices]
    slot_logits = np.einsum("nk,cnk->nc", values, selected, optimize=True) + offset[None, :]
    if slot_map is None:
        return slot_logits
    mapping = np.asarray(slot_map, dtype=np.int64)
    result = np.empty_like(slot_logits)
    result[np.arange(len(mapping))[:, None], mapping] = slot_logits
    return result


def metric_transitions(before: np.ndarray, after: np.ndarray, targets: np.ndarray) -> dict[str, Any]:
    before = np.asarray(before, dtype=np.int64)
    after = np.asarray(after, dtype=np.int64)
    targets = np.asarray(targets, dtype=np.int64)
    matrix = np.zeros((3, 3), dtype=np.int64)
    np.add.at(matrix, (before, after), 1)
    correct_before = before == targets
    correct_after = after == targets
    return {
        "prediction_transition_counts_rows_before_columns_after": matrix.tolist(),
        "correctness_transitions": {
            "both_correct": int(np.count_nonzero(correct_before & correct_after)),
            "both_incorrect": int(np.count_nonzero(~correct_before & ~correct_after)),
            "before_only_correct": int(np.count_nonzero(correct_before & ~correct_after)),
            "after_only_correct": int(np.count_nonzero(~correct_before & correct_after)),
        },
    }
