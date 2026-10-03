#!/usr/bin/env python3
"""Independent standard-library reviewer for the frozen Q10-RC audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
from pathlib import Path

PROTOCOL = "Q10-RC"
PARENT_HASHES = {
    "PLAN.md": "8A70CFADA7A833AA1110FDE5DBF0CFAFDDD4AFD4297A06AD846B1959439B8B9D",
    "CONTRACT.json": "5A7CD7E15724F6260C2D42296BED5FF3667CA32FA1D8D48E5408EFFA2A0F35BF",
    "STATUS.json": "D19D051DA550BCDED9C436F9A7164AF0C4322D8BB16C418D7C4CA9E04217A9C4",
    "RESULT.md": "68200D7F49B8A4B943150A1C3A5AB4B46DF4ED8EB1EBBE7A3DF45F8BEEBBD337",
    "Q10-SM-SUMMARY.json": "2B64FF590E226CD393EBCFF6A5147728BAC931F395D76970567EBD6061EDA113",
}
RANK_MULTIPLIER = 1000.0
POST_MOVE_RESERVE = 31


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def from_bits(value: int) -> float:
    return struct.unpack("<f", struct.pack("<I", value))[0]


def sequential_row(weights: list[float], ids: list[int], override=None) -> float:
    total = f32(0.0)
    coordinate = replacement = None
    if override is not None:
        coordinate, replacement = override
    for index in ids:
        value = replacement if index == coordinate else weights[index]
        total = f32(total + value)
    return total


def sequential(operator: dict, weights: list[float]) -> list[float]:
    return [sequential_row(weights, row) for row in operator["rows"]]


def nextafter32(value: float, lower: bool) -> float | None:
    if not math.isfinite(value) or value <= 0.0 or value >= 2.0:
        return None
    raw = bits(value)
    return from_bits(raw - 1 if lower else raw + 1)


def remaining_steps(value: float, lower: bool, cap: int) -> int:
    current = value
    steps = 0
    while steps < cap:
        nxt = nextafter32(current, lower)
        if nxt is None or not math.isfinite(nxt) or nxt <= 0.0 or nxt >= 2.0:
            break
        current = nxt
        steps += 1
    return steps


def ordered_f32(raw: int) -> int:
    return (~raw) & 0xFFFFFFFF if raw & 0x80000000 else raw | 0x80000000


def ulp_distance(a: float, b: float) -> int:
    return abs(ordered_f32(bits(a)) - ordered_f32(bits(b)))


def hash_f32(values: list[float]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(struct.pack("<I", bits(value)))
    return digest.hexdigest()


def hash_bool(values: list[bool]) -> str:
    return hashlib.sha256(bytes(1 if value else 0 for value in values)).hexdigest()


def hash_rows(operator: dict) -> str:
    digest = hashlib.sha256()
    for value in (operator["cues"], operator["posts"], operator["coordinates"]):
        digest.update(struct.pack("<Q", value))
    for row in operator["rows"]:
        digest.update(struct.pack("<Q", len(row)))
        for coordinate in row:
            digest.update(struct.pack("<Q", coordinate))
    return digest.hexdigest()


def jacobi_eigh(matrix: list[list[float]]) -> tuple[list[float], list[list[float]]]:
    n = len(matrix)
    a = [row[:] for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    scale = max((abs(value) for row in a for value in row), default=0.0)
    tolerance = max(scale * 1e-15, 1e-300)
    for _ in range(200 * n * n):
        p = q = 0
        maximum = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                if abs(a[i][j]) > maximum:
                    maximum = abs(a[i][j])
                    p, q = i, j
        if maximum <= tolerance:
            break
        phi = 0.5 * math.atan2(2.0 * a[p][q], a[q][q] - a[p][p])
        c, s = math.cos(phi), math.sin(phi)
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        for k in range(n):
            if k == p or k == q:
                continue
            akp, akq = a[k][p], a[k][q]
            a[k][p] = a[p][k] = c * akp - s * akq
            a[k][q] = a[q][k] = s * akp + c * akq
        a[p][p] = c * c * app - 2.0 * s * c * apq + s * s * aqq
        a[q][q] = s * s * app + 2.0 * s * c * apq + c * c * aqq
        a[p][q] = a[q][p] = 0.0
        for k in range(n):
            vkp, vkq = vectors[k][p], vectors[k][q]
            vectors[k][p] = c * vkp - s * vkq
            vectors[k][q] = s * vkp + c * vkq
    else:
        raise AssertionError("Jacobi reviewer did not converge")
    pairs = sorted(
        ((max(a[i][i], 0.0), [vectors[row][i] for row in range(n)]) for i in range(n)),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def enumerate_replay(replay: dict) -> dict:
    snapshot = replay["snapshot"]
    operator = replay["operator"]
    alternate = [f32(value) for value in replay["alternate_state"]]
    true_state = [f32(value) for value in snapshot["target"]]
    interior = replay["interior_indices"]
    posts = operator["posts"]
    rows = operator["rows"]
    g_n = sequential(operator, alternate)
    g_t = sequential(operator, true_state)
    errors = [float(n) - float(t) for n, t in zip(g_n, g_t)]
    coord_rows = [[] for _ in range(operator["coordinates"])]
    for row_index, row in enumerate(rows):
        for coordinate in row:
            coord_rows[coordinate].append(row_index)
    digest = hashlib.sha256()
    columns = [[] for _ in range(posts)]
    legal = active = numerical = zero = minus = plus = 0
    illegal = [0, 0, 0, 0]
    minimum_down = minimum_up = POST_MOVE_RESERVE
    for coordinate in interior:
        old = alternate[coordinate]
        for direction in (-1, 1):
            new = nextafter32(old, direction < 0)
            legality = 0
            affected = []
            if new is None:
                legality = 1
                illegal[0] += 1
            elif not math.isfinite(new) or new <= 0.0 or new >= 2.0:
                legality = 2
                illegal[1] += 1
            elif new == 0.0 or new == 2.0:
                legality = 3
                illegal[2] += 1
            down = remaining_steps(new, True, POST_MOVE_RESERVE) if new is not None else 0
            up = remaining_steps(new, False, POST_MOVE_RESERVE) if new is not None else 0
            if legality == 0 and (down < POST_MOVE_RESERVE or up < POST_MOVE_RESERVE):
                legality = 4
                illegal[3] += 1
            bitwise_changed = numerically_changed = False
            effects = [0.0] * 16
            if legality == 0:
                legal += 1
                minus += direction < 0
                plus += direction > 0
                minimum_down = min(minimum_down, down)
                minimum_up = min(minimum_up, up)
                for row_index in coord_rows[coordinate]:
                    moved = sequential_row(alternate, rows[row_index], (coordinate, new))
                    affected.append((row_index, moved))
                    delta = float(moved) - float(g_n[row_index])
                    effects[row_index // posts] = delta
                    bitwise_changed |= bits(moved) != bits(g_n[row_index])
                    numerically_changed |= delta != 0.0
                if bitwise_changed:
                    active += 1
                    numerical += numerically_changed
                    post = coord_rows[coordinate][0] % posts if coord_rows[coordinate] else 0
                    columns[post].append(effects)
                else:
                    zero += 1
            digest.update(struct.pack("<Q", coordinate))
            digest.update(struct.pack("<b", direction))
            digest.update(struct.pack("<I", bits(old)))
            digest.update(struct.pack("<I", 0xFFFFFFFF if new is None else bits(new)))
            digest.update(bytes([legality]))
            digest.update(struct.pack("<I", len(affected)))
            for row_index, output in affected:
                digest.update(struct.pack("<I", row_index))
                digest.update(struct.pack("<I", bits(output)))

    all_sigma = []
    block_data = []
    for post, block_columns in enumerate(columns):
        gram = [[0.0] * 16 for _ in range(16)]
        for column in block_columns:
            for i in range(16):
                for j in range(i, 16):
                    gram[i][j] += column[i] * column[j]
        for i in range(16):
            for j in range(i):
                gram[i][j] = gram[j][i]
        eigenvalues, eigenvectors = jacobi_eigh(gram)
        sigma = [math.sqrt(value) for value in eigenvalues]
        all_sigma.extend(sigma)
        block_data.append((post, block_columns, sigma, eigenvectors))
    all_sigma.sort(reverse=True)
    sigma_max = all_sigma[0] if all_sigma else 0.0
    threshold = sigma_max * max(len(errors), active) * (2.0 ** -52) * RANK_MULTIPLIER
    rank = sum(value > threshold for value in all_sigma)
    reachable = [0.0] * len(errors)
    unreachable = [0.0] * len(errors)
    coefficients = []
    reconstructed = [0.0] * len(errors)
    for post, block_columns, sigma, eigenvectors in block_data:
        block_error = [errors[cue * posts + post] for cue in range(16)]
        inverse_image = [0.0] * 16
        for value, vector in zip(sigma, eigenvectors):
            if value <= threshold:
                continue
            alpha = sum(vector[row] * block_error[row] for row in range(16))
            for row in range(16):
                reachable[row * posts + post] += vector[row] * alpha
                inverse_image[row] += vector[row] * alpha / (value * value)
        for cue in range(16):
            row = cue * posts + post
            unreachable[row] = errors[row] - reachable[row]
        for column in block_columns:
            coefficient = -sum(column[row] * inverse_image[row] for row in range(16))
            coefficients.append(coefficient)
            for cue in range(16):
                reconstructed[cue * posts + post] += column[cue] * coefficient
    error_l2 = math.sqrt(sum(value * value for value in errors))
    error_linf = max((abs(value) for value in errors), default=0.0)
    unreachable_l2 = math.sqrt(sum(value * value for value in unreachable))
    unreachable_linf = max((abs(value) for value in unreachable), default=0.0)
    return {
        "baseline_bits": [bits(value) for value in g_n],
        "true_bits": [bits(value) for value in g_t],
        "error": errors,
        "ulp": [ulp_distance(n, t) for n, t in zip(g_n, g_t)],
        "candidate": len(interior) * 2,
        "legal": legal,
        "illegal": illegal,
        "active": active,
        "numerical": numerical,
        "zero": zero,
        "minus": minus,
        "plus": plus,
        "minimum_down": minimum_down,
        "minimum_up": minimum_up,
        "digest": digest.hexdigest(),
        "rank": rank,
        "threshold": threshold,
        "rho_2": unreachable_l2 / error_l2 if error_l2 else 0.0,
        "rho_inf": unreachable_linf / error_linf if error_linf else 0.0,
        "l1": sum(abs(value) for value in coefficients),
        "l2": math.sqrt(sum(value * value for value in coefficients)),
        "linf": max((abs(value) for value in coefficients), default=0.0),
        "reconstructed_l2": math.sqrt(
            sum((rx + error) ** 2 for rx, error in zip(reconstructed, errors))
        ),
    }


def close(actual: float, expected: float, relative: float = 2e-6, absolute: float = 1e-15) -> None:
    require(
        math.isclose(actual, expected, rel_tol=relative, abs_tol=absolute),
        f"numeric mismatch: actual={actual!r} expected={expected!r}",
    )


def verify_replay(path: Path) -> dict:
    replay = json.loads(path.read_text(encoding="utf-8"))
    require(replay["protocol"] == PROTOCOL, "replay protocol mismatch")
    event = replay["event"]
    capacity = event["capacity"]
    require(capacity is not None, "replay event is not applicable")
    require(hash_f32(replay["snapshot"]["base"]) == event["state_hashes"]["base_sha256"], "base hash mismatch")
    require(hash_f32(replay["snapshot"]["target"]) == event["state_hashes"]["true_sha256"], "true hash mismatch")
    require(hash_f32(replay["alternate_state"]) == event["state_hashes"]["alternate_sha256"], "alternate hash mismatch")
    require(hash_bool(replay["snapshot"]["permitted"]) == event["state_hashes"]["support_sha256"], "support hash mismatch")
    require(hash_rows(replay["operator"]) == event["state_hashes"]["row_order_sha256"], "row-order hash mismatch")
    actual = enumerate_replay(replay)
    baseline = capacity["baseline"]
    bank = capacity["move_bank"]
    rank = capacity["rank_projection"]
    require(actual["baseline_bits"] == baseline["alternate_bits"], "alternate readout bits mismatch")
    require(actual["true_bits"] == baseline["true_bits"], "true readout bits mismatch")
    require(actual["ulp"] == baseline["ulp_distance"], "ULP distance mismatch")
    require(actual["candidate"] == bank["candidate_moves"], "candidate count mismatch")
    require(actual["legal"] == bank["legal_moves"], "legal count mismatch")
    require(actual["illegal"] == [bank["illegal_non_adjacent"], bank["illegal_nonfinite_or_bounds"], bank["illegal_boundary"], bank["illegal_reserve"]], "illegal reason mismatch")
    require(actual["active"] == bank["active_moves"], "active count mismatch")
    require(actual["numerical"] == bank["numerical_nonzero_moves"], "numerical count mismatch")
    require(actual["zero"] == bank["zero_effect_moves"], "zero-effect count mismatch")
    require(actual["minus"] == bank["minus_legal"] and actual["plus"] == bank["plus_legal"], "direction count mismatch")
    require(actual["minimum_down"] == bank["minimum_remaining_down_steps_capped"], "down-reserve mismatch")
    require(actual["minimum_up"] == bank["minimum_remaining_up_steps_capped"], "up-reserve mismatch")
    require(actual["digest"] == bank["move_digest_sha256"], "move digest mismatch")
    require(actual["rank"] == rank["rank"], "rank mismatch")
    close(actual["threshold"], rank["rank_threshold"], relative=5e-5)
    close(actual["rho_2"], rank["rho_2"], relative=5e-5)
    close(actual["rho_inf"], rank["rho_inf"], relative=5e-5)
    relaxed = capacity["relaxed_budget"]
    if relaxed is not None:
        close(actual["l1"], relaxed["l1"], relative=2e-3)
        close(actual["l2"], relaxed["l2"], relative=2e-3)
        close(actual["linf"], relaxed["linf"], relative=2e-3)
        close(actual["reconstructed_l2"], relaxed["reconstructed_residual_l2"], relative=2e-3)
    return {
        "seed": replay["seed"],
        "side": replay["side"],
        "tau": replay["tau"],
        "trial": event["trial"],
        "legal_moves": actual["legal"],
        "rank": actual["rank"],
        "rho_2": actual["rho_2"],
        "digest": actual["digest"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    contract = json.loads((root / "CONTRACT.json").read_text(encoding="utf-8"))
    require(contract["protocol"] == PROTOCOL, "contract protocol mismatch")
    require(sha256(root / "PLAN.md").upper() == contract["plan_sha256"], "plan hash mismatch")
    parent = root.parent / "q10-safety-margin-v1"
    for name, expected in PARENT_HASHES.items():
        require(sha256(parent / name).upper() == expected, f"parent hash mismatch: {name}")
    pre = json.loads((output / "pre-execution.json").read_text(encoding="utf-8"))
    execution = json.loads((output / "execution.json").read_text(encoding="utf-8"))
    require(pre["protocol"] == PROTOCOL and execution["protocol"] == PROTOCOL, "execution protocol mismatch")
    require(pre["contract_sha256"] == sha256(root / "CONTRACT.json"), "contract receipt mismatch")
    for entry in pre["source"]:
        relative = entry["path"].replace("\\", os.sep).replace("/", os.sep)
        require(sha256(root / relative) == entry["sha256"], f"source hash mismatch: {relative}")
    expected_seeds = [9601] if execution["stage"] == "stage-a" else [9602, 9603, 9604, 9605]
    expected_states = 1024 if execution["stage"] == "stage-a" else 4096
    require(pre["seeds"] == expected_seeds, "seed set mismatch")
    counters = {
        "states": 0,
        "applicable": 0,
        "dominated": 0,
        "already": 0,
        "legal": 0,
        "active": 0,
        "zero_rows": 0,
        "no_helpful": 0,
        "rank": 0,
    }
    bundle_files = sorted(output.glob("seed*-*-tau*.jsonl"))
    require(len(bundle_files) == len(expected_seeds) * 4, "bundle file count mismatch")
    for path in bundle_files:
        with path.open("r", encoding="utf-8") as handle:
            header = json.loads(handle.readline())
            require(header["protocol"] == PROTOCOL and header["events"] == 256, "bundle header mismatch")
            require(header["seed"] in expected_seeds, "bundle seed mismatch")
            events = 0
            for line in handle:
                event = json.loads(line)
                events += 1
                counters["states"] += 1
                capacity = event["capacity"]
                if capacity is None:
                    counters["dominated"] += 1
                    require(event["state_hashes"]["alternate_sha256"] is None, "dominated event has alternate hash")
                    continue
                counters["applicable"] += 1
                require(capacity["learner_mutation"] is False, "learner mutation recorded")
                require(capacity["simulation_rng_consumed_by_audit"] is False, "audit consumed RNG")
                require(capacity["repairs_applied"] == 0, "repair applied")
                require(capacity["multi_move_evaluations"] == 0, "multi-move evaluation applied")
                counters["already"] += capacity["status"] == "ALREADY_EQUAL"
                counters["legal"] += capacity["move_bank"]["legal_moves"]
                counters["active"] += capacity["move_bank"]["active_moves"]
                counters["rank"] += capacity["rank_projection"]["rank"]
                counters["zero_rows"] += sum(flag & 1 != 0 for flag in capacity["rows"]["flags"])
                counters["no_helpful"] += sum(flag & 4 != 0 for flag in capacity["rows"]["flags"])
                require(capacity["move_bank"]["minimum_remaining_down_steps_capped"] >= 31, "down reserve failed")
                require(capacity["move_bank"]["minimum_remaining_up_steps_capped"] >= 31, "up reserve failed")
                require(capacity["rank_projection"]["normalized_projection_reconstruction_error"] <= 2e-10, "projection reconstruction failed")
                require(capacity["rank_projection"]["normalized_projection_orthogonality_error"] <= 2e-10, "projection orthogonality failed")
                relaxed = capacity["relaxed_budget"]
                if relaxed is not None:
                    require(relaxed["normalized_reconstruction_error"] <= 2e-10, "relaxed reconstruction failed")
            require(events == 256, "bundle event count mismatch")
    require(counters["states"] == expected_states, "stage state count mismatch")
    mapping = {
        "applicable": "applicable_safe_endpoints",
        "dominated": "safety_margin_dominated_events",
        "already": "already_equal_events",
        "legal": "legal_isolated_moves",
        "active": "active_isolated_moves",
        "zero_rows": "zero_capacity_rows",
        "no_helpful": "no_helpful_rows",
        "rank": "rank_sum",
    }
    for local, reported in mapping.items():
        require(counters[local] == execution[reported], f"execution counter mismatch: {reported}")
    require(execution["repairs_applied"] == 0 and execution["multi_move_evaluations"] == 0, "forbidden operation in execution")
    require(execution["scientific_seed_bundles"] == 0 and execution["behavioral_inference"] is False, "science firewall failed")
    replay = verify_replay(output / "replay-first-applicable.json") if counters["applicable"] else None
    receipt = {
        "protocol": PROTOCOL,
        "schema_version": 1,
        "stage": execution["stage"],
        "status": "VERIFIED",
        "reviewer": "PYTHON_STDLIB_INDEPENDENT_F32_AND_JACOBI",
        "audited_states": counters["states"],
        "applicable_safe_endpoints": counters["applicable"],
        "safety_margin_dominated_events": counters["dominated"],
        "contract_sha256": sha256(root / "CONTRACT.json"),
        "plan_sha256": sha256(root / "PLAN.md"),
        "execution_sha256": sha256(output / "execution.json"),
        "replay": replay,
        "repairs_applied": 0,
        "multi_move_evaluations": 0,
        "scientific_seed_bundles": 0,
        "behavioral_inference": False,
    }
    destination = output / "reviewer-receipt.json"
    require(not destination.exists(), "reviewer receipt already exists")
    destination.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
