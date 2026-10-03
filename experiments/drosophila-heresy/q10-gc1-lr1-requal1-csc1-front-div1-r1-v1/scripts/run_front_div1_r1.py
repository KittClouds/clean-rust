from __future__ import annotations

import hashlib
import json
import mmap
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
CTX = ("seed9731-R-tau4.json", 3)
BAND_MAX_MISMATCH = 128
MASK_BYTES = 98
RECORD_BYTES = 688
READOUT_WIDTH = 784

O3 = ROOT / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-o3-maskmat1-v1"
O2 = ROOT / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-front1-v2"
OUT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().upper()


def load_reference_mask() -> int:
    schema = json.loads((O3 / "schema.json").read_text(encoding="utf-8"))
    residual_indices = [int(index) for index in schema["residual_indices"]]
    if len(residual_indices) != 123:
        raise RuntimeError("O3 schema residual cardinality changed")
    return sum(1 << index for index in residual_indices)


def set_bits(value: int):
    while value:
        low = value & -value
        yield low.bit_length() - 1
        value ^= low


def hamming_stats(masks: list[int]) -> dict:
    unique = sorted(set(masks))
    counts = Counter(masks)
    pair_count = len(unique) * (len(unique) - 1) // 2
    if pair_count == 0:
        return {
            "mode": "exact",
            "unique_masks": len(unique),
            "pair_count": 0,
            "min": 0,
            "max": 0,
            "mean": 0.0,
            "median": 0.0,
            "mask_multiplicity_max": max(counts.values(), default=0),
        }

    exact_limit = 2_000_000
    values: list[int] = []
    if pair_count <= exact_limit:
        mode = "exact"
        for left_index, left in enumerate(unique):
            for right in unique[left_index + 1 :]:
                values.append((left ^ right).bit_count())
    else:
        mode = "deterministic_unique_mask_pair_sample"
        sample_count = min(1_000_000, pair_count)
        n = len(unique)
        for sample_index in range(sample_count):
            left_index = (sample_index * 1_000_003 + 17) % n
            offset = 1 + ((sample_index * 917_611 + 29) % (n - 1))
            right_index = (left_index + offset) % n
            if left_index == right_index:
                right_index = (right_index + 1) % n
            values.append((unique[left_index] ^ unique[right_index]).bit_count())
    values.sort()
    middle = len(values) // 2
    median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    return {
        "mode": mode,
        "unique_masks": len(unique),
        "pair_count": pair_count,
        "sample_count": len(values),
        "min": values[0],
        "max": values[-1],
        "mean": sum(values) / len(values),
        "median": median,
        "mask_multiplicity_max": max(counts.values()),
    }


def one_bit_components(masks: list[int]) -> dict:
    unique = sorted(set(masks))
    index = {mask: i for i, mask in enumerate(unique)}
    parent = list(range(len(unique)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        left = find(left)
        right = find(right)
        if left != right:
            parent[right] = left

    edge_count = 0
    for mask, left_index in index.items():
        for bit in range(READOUT_WIDTH):
            right_index = index.get(mask ^ (1 << bit))
            if right_index is not None:
                edge_count += 1
                union(left_index, right_index)

    components = Counter(find(i) for i in range(len(unique)))
    return {
        "adjacency": "Hamming distance exactly 1",
        "unique_masks": len(unique),
        "edges_counted_directed": edge_count,
        "component_count": len(components),
        "largest_component": max(components.values(), default=0),
        "component_sizes_desc": sorted(components.values(), reverse=True)[:20],
    }


def main() -> None:
    semantic = O3 / "semantic.jsonl"
    binary = O3 / "semantic.bin"
    schema = O3 / "schema.json"
    reference_mask = load_reference_mask()
    residual_indices = list(set_bits(reference_mask))
    residual_positions = {row: position for position, row in enumerate(residual_indices)}
    residual_mask = sum(1 << row for row in residual_indices)

    band_masks: list[int] = []
    band_changed_masks: list[int] = []
    band_records = 0
    all_records = 0
    mismatch_counts = Counter()
    row_mismatch = [0] * READOUT_WIDTH
    row_changed = [0] * len(residual_indices)
    row_repaired = [0] * len(residual_indices)
    row_damaged = [0] * len(residual_indices)
    residual_error_masks: list[int] = []

    with binary.open("rb") as raw, mmap.mmap(raw.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        for line in semantic.open("r", encoding="utf-8"):
            record = json.loads(line)
            all_records += 1
            mismatch_count = int(record["mismatch_count"])
            if mismatch_count > BAND_MAX_MISMATCH:
                continue
            offset = int(record["binary_offset"])
            mapped.seek(offset)
            mismatch_mask = int.from_bytes(mapped.read(MASK_BYTES), "little")
            changed_mask = int.from_bytes(mapped.read(MASK_BYTES), "little")
            band_records += 1
            band_masks.append(mismatch_mask)
            band_changed_masks.append(changed_mask)
            mismatch_counts[mismatch_count] += 1

            for row in set_bits(mismatch_mask):
                if row < READOUT_WIDTH:
                    row_mismatch[row] += 1

            residual_error_mask = 0
            for row, position in residual_positions.items():
                if changed_mask & (1 << row):
                    row_changed[position] += 1
                if mismatch_mask & (1 << row):
                    residual_error_mask |= 1 << position
                else:
                    row_repaired[position] += 1
                if not (reference_mask & (1 << row)) and mismatch_mask & (1 << row):
                    row_damaged[position] += 1
            residual_error_masks.append(residual_error_mask)

    # Exact co-error uses one Python big-int bitset per residual row. A bit
    # position denotes one near-frontier state, so pair counts reduce to C-level
    # big-int AND/popcount operations instead of a per-state quadratic loop.
    row_presence = [0] * len(residual_indices)
    for state_index, residual_error_mask in enumerate(residual_error_masks):
        state_bit = 1 << state_index
        for position in set_bits(residual_error_mask):
            row_presence[position] |= state_bit
    co_error = [[0] * len(residual_indices) for _ in residual_indices]
    for left in range(len(residual_indices)):
        co_error[left][left] = row_presence[left].bit_count()
        for right in range(left + 1, len(residual_indices)):
            value = (row_presence[left] & row_presence[right]).bit_count()
            co_error[left][right] = value
            co_error[right][left] = value

    hamming = hamming_stats(band_masks)
    components = one_bit_components(band_masks)
    residual_rows = []
    for position, row in enumerate(residual_indices):
        residual_rows.append(
            {
                "row": row,
                "mismatch_frequency": row_mismatch[row],
                "mismatch_fraction": row_mismatch[row] / band_records if band_records else 0.0,
                "changed_from_reference_frequency": row_changed[position],
                "repaired_reference_residual_frequency": row_repaired[position],
                "damaged_reference_correct_frequency": row_damaged[position],
            }
        )

    co_nonzero_off_diagonal = sum(
        1
        for left in range(len(residual_indices))
        for right in range(left + 1, len(residual_indices))
        if co_error[left][right] > 0
    )
    max_co = max(
        (co_error[left][right] for left in range(len(residual_indices)) for right in range(left + 1, len(residual_indices))),
        default=0,
    )

    parent_paths = [semantic, binary, schema, O2 / "shards" / "seed9731-R-tau4__set3.jsonl"]
    execution = {
        "identity": "q10-gc1-lr1-requal1-csc1-front-div1-r1-v1",
        "protocol": "Q10-FRONT-DIV1-R1",
        "context": list(CTX),
        "replay_executed": False,
        "scientific_promotion": False,
        "band_rule": "mismatch_count <= 128",
        "all_order3_records": all_records,
        "near_frontier_records": band_records,
        "mismatch_count_distribution": dict(sorted(mismatch_counts.items())),
        "reference_mismatch_count": reference_mask.bit_count(),
        "reference_residual_rows": len(residual_indices),
        "hamming_stats": hamming,
        "one_bit_components": components,
        "co_error_nonzero_off_diagonal_pairs": co_nonzero_off_diagonal,
        "co_error_max_count": max_co,
        "row_stats_sha256": None,
        "co_error_matrix_sha256": None,
        "parent_sha256": {str(path): sha256(path) for path in parent_paths},
        "status": "FRONT_DIV1_R1_COMPLETE",
    }

    row_stats = {
        "context": list(CTX),
        "band_rule": "mismatch_count <= 128",
        "reference_residual_indices": residual_indices,
        "rows": residual_rows,
        "all_row_mismatch_frequency": row_mismatch,
    }
    co_payload = {
        "context": list(CTX),
        "residual_indices": residual_indices,
        "matrix": co_error,
    }
    row_bytes = json.dumps(row_stats, sort_keys=True, separators=(",", ":")).encode()
    co_bytes = json.dumps(co_payload, sort_keys=True, separators=(",", ":")).encode()
    execution["row_stats_sha256"] = hashlib.sha256(row_bytes).hexdigest().upper()
    execution["co_error_matrix_sha256"] = hashlib.sha256(co_bytes).hexdigest().upper()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "row-stats.json").write_bytes(row_bytes)
    (OUT / "co-error.json").write_bytes(co_bytes)
    (OUT / "execution.json").write_text(json.dumps(execution, indent=2) + "\n", encoding="utf-8")
    (OUT / "STATUS.json").write_text(json.dumps({
        "identity": execution["identity"],
        "replay_executed": False,
        "scientific_promotion": False,
        "status": execution["status"],
    }, indent=2) + "\n", encoding="utf-8")
    report = "\n".join([
        "# FRONT-DIV1-R1 mismatch-mask topology audit",
        "",
        f"Scope: `{CTX[0]}`, set `{CTX[1]}`, order-3 valid frontier.",
        f"Near-frontier rule: `mismatch_count <= {BAND_MAX_MISMATCH}`.",
        f"Near-frontier states: `{band_records}` of `{all_records}`.",
        f"Unique mismatch masks: `{hamming['unique_masks']}`; exact pairwise Hamming mean `{hamming['mean']:.6f}`, median `{hamming['median']}`, max `{hamming['max']}`.",
        f"One-bit mask components: `{components['component_count']}`; largest `{components['largest_component']}`.",
        f"Residual co-error: `{co_nonzero_off_diagonal}` nonzero off-diagonal pairs; maximum count `{max_co}`.",
        "",
        "This is read-only engineering evidence. It does not open order 4 or scientific promotion.",
        "",
    ])
    (OUT / "REPORT.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
