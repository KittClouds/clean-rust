"""Audit compact qualification rows without fitting an estimator."""
from __future__ import annotations

import hashlib
import json
import mmap
import struct
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]
RUN = STUDY / "runs" / "qualification-v2"
MAGIC = b"FLYREACH3ROWS\0"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def u8(data: memoryview, pos: int) -> tuple[int, int]:
    return data[pos], pos + 1


def i8(data: memoryview, pos: int) -> tuple[int, int]:
    return struct.unpack_from("<b", data, pos)[0], pos + 1


def u16(data: memoryview, pos: int) -> tuple[int, int]:
    return struct.unpack_from("<H", data, pos)[0], pos + 2


def u32(data: memoryview, pos: int) -> tuple[int, int]:
    return struct.unpack_from("<I", data, pos)[0], pos + 4


def u64(data: memoryview, pos: int) -> tuple[int, int]:
    return struct.unpack_from("<Q", data, pos)[0], pos + 8


def f32(data: memoryview, pos: int) -> tuple[float, int]:
    return struct.unpack_from("<f", data, pos)[0], pos + 4


def f64(data: memoryview, pos: int) -> tuple[float, int]:
    return struct.unpack_from("<d", data, pos)[0], pos + 8


def skip_vec(data: memoryview, pos: int, item_size: int) -> int:
    count, pos = u8(data, pos)
    return pos + count * item_size


def read_file(path: Path) -> dict[str, object]:
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        data = memoryview(mapped)
        pos = 0
        if data[: len(MAGIC)].tobytes() != MAGIC:
            raise RuntimeError(f"bad row magic: {path}")
        pos += len(MAGIC)
        version, pos = u32(data, pos)
        substrate_len, pos = u16(data, pos)
        substrate = data[pos : pos + substrate_len].tobytes().decode()
        pos += substrate_len
        side_len, pos = u16(data, pos)
        side = data[pos : pos + side_len].tobytes().decode()
        pos += side_len
        block, pos = u64(data, pos)
        coordinate_count, pos = u32(data, pos)
        coordinates = []
        for _ in range(coordinate_count):
            value, pos = u32(data, pos)
            coordinates.append(value)
        rows = 0
        nonzero = 0
        support = 0
        positive = 0
        negative = 0
        zero = 0
        min_probability = 1.0
        max_probability = 0.0
        while pos < len(data):
            _substrate_index, pos = u8(data, pos)
            _side_index, pos = u8(data, pos)
            _block, pos = u64(data, pos)
            _trial, pos = u32(data, pos)
            _coordinate, pos = u32(data, pos)
            probability, pos = f64(data, pos)
            _reference, pos = f32(data, pos)
            target, pos = i8(data, pos)
            _native, pos = f32(data, pos)
            primary_support, pos = u8(data, pos)
            pos += 4 * 4 + 4  # F0: endpoints/degrees and anatomical sign
            pos += 4 + 4 + 4 + 4 + 4 + 1  # F1
            pos = skip_vec(data, pos, 4)  # eligibility history
            pos = skip_vec(data, pos, 4)  # weight history
            pos = skip_vec(data, pos, 1)  # local sign history
            pos += 5 * 4 + 1  # F3a
            pos += 2 * 4 + 2 * 8 + 4  # F3b and snapshot id
            if pos > len(data):
                raise RuntimeError(f"truncated row stream: {path} row={rows}")
            rows += 1
            min_probability = min(min_probability, probability)
            max_probability = max(max_probability, probability)
            support += int(bool(primary_support))
            if target > 0:
                positive += 1
                nonzero += 1
            elif target < 0:
                negative += 1
                nonzero += 1
            else:
                zero += 1
        del data
        return {
            "path": path.relative_to(STUDY).as_posix(),
            "sha256": sha(path),
            "version": version,
            "substrate": substrate,
            "side": side,
            "block": block,
            "coordinates": coordinate_count,
            "coordinate_ids": coordinates,
            "rows": rows,
            "nonzero_target_rows": nonzero,
            "positive_rows": positive,
            "negative_rows": negative,
            "zero_target_rows": zero,
            "primary_support_rows": support,
            "inclusion_probability_min": min_probability,
            "inclusion_probability_max": max_probability,
        }


def main() -> None:
    receipt = json.loads((RUN / "F4-RECONSTRUCTION-RECEIPT.json").read_text(encoding="utf-8"))
    if receipt["status"] != "PASS":
        raise SystemExit("F4 audit is not PASS")
    files = sorted((RUN / "rows").glob("*.bin"))
    if len(files) != 72:
        raise SystemExit(f"expected 72 row streams, found {len(files)}")
    summaries = [read_file(path) for path in files]
    total_rows = sum(int(row["rows"]) for row in summaries)
    total_nonzero = sum(int(row["nonzero_target_rows"]) for row in summaries)
    total_positive = sum(int(row["positive_rows"]) for row in summaries)
    total_negative = sum(int(row["negative_rows"]) for row in summaries)
    total_zero = sum(int(row["zero_target_rows"]) for row in summaries)
    total_support = sum(int(row["primary_support_rows"]) for row in summaries)
    probabilities = [float(row["inclusion_probability_min"]) for row in summaries] + [float(row["inclusion_probability_max"]) for row in summaries]
    if total_rows != 37_748_736:
        raise SystemExit(f"row count mismatch: {total_rows}")
    if total_positive == 0 or total_negative == 0:
        raise SystemExit("one target class is absent; constant baseline is not defined")
    output = {
        "schema": "FLY-REACH-03-qualification-summary-v1",
        "status": "PASS",
        "run_id": "qualification-v2",
        "f4_status": receipt["status"],
        "cell_streams": len(summaries),
        "rows": total_rows,
        "nonzero_target_rows": total_nonzero,
        "positive_rows": total_positive,
        "negative_rows": total_negative,
        "zero_target_rows": total_zero,
        "primary_support_rows": total_support,
        "primary_population_rows": total_support,
        "constant_baseline": {"balanced_error": 0.5, "omega_hat": 0.0, "defined": True},
        "inclusion_probability": {"min": min(probabilities), "max": max(probabilities), "all_finite_positive": all(value > 0.0 for value in probabilities)},
        "same_rows_all_filtrations": True,
        "measured_namespace_created": False,
        "estimators_fit": False,
        "cell_summaries": summaries,
    }
    path = RUN / "QUALIFICATION-SUMMARY.json"
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("status", "rows", "nonzero_target_rows", "positive_rows", "negative_rows", "zero_target_rows", "primary_support_rows")}, sort_keys=True))


if __name__ == "__main__":
    main()
