from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from s06_common import RUN, FailClosed, canonical_root, read_json, sha_file, verify_protocol


OUTPUTS = (
    "preflight-receipt-v01.json",
    "crossed-cube-ledger-v01.jsonl",
    "compatibility-summary-v01.json",
    "prediction-transitions-v01.json",
    "effective-geometry-v01.json",
    "execution-receipt-v01.json",
    "S06-RESULTS.md",
)
DISPOSITION = {
    "S06_PARENT_BINDING_PASS": True,
    "S06_EIGHT_CELL_CUBE_COMPLETE": True,
    "S06_CENTER_SCALE_CONTROLS_COMPLETE": True,
    "S06_RESULT_READY": True,
    "FAS00_SENSOR_PASS": False,
    "FAS00_PHASE4_AUTHORIZED": False,
    "SAE_ANALYSIS_AUTHORIZED": False,
}


def _entries() -> list[dict[str, Any]]:
    out = []
    for relative in OUTPUTS:
        path = RUN / relative
        if not path.is_file():
            raise FailClosed(f"Missing S06 result artifact: {relative}")
        out.append({"path": relative, "sha256": sha_file(path), "bytes": path.stat().st_size})
    return sorted(out, key=lambda item: item["path"].casefold())


def _validate() -> list[dict[str, Any]]:
    protocol = verify_protocol()
    preflight = read_json(RUN / "preflight-receipt-v01.json")
    summary = read_json(RUN / "compatibility-summary-v01.json")
    transitions = read_json(RUN / "prediction-transitions-v01.json")
    receipt = read_json(RUN / "execution-receipt-v01.json")
    if (preflight.get("status") != "PASS" or preflight.get("protocol_root_sha256") != protocol["root_sha256"] or
            summary.get("status") != "COMPLETE" or len(summary.get("cell_order", [])) != 16 or
            len(summary.get("bundled_scaler_cells", [])) != 8 or len(summary.get("center_scale_control_cells", [])) != 8):
        raise FailClosed("S06 preflight or cube summary does not satisfy frozen contract")
    for key, expected in DISPOSITION.items():
        if receipt.get(key) is not expected:
            raise FailClosed(f"S06 execution disposition mismatch: {key}")
    if len(receipt.get("replay_receipts", [])) != 2 or any(x.get("diagonal_gate") != "PASS" or x.get("cells") != 16 for x in receipt["replay_receipts"]):
        raise FailClosed("S06 replay receipt is missing a dataset/cell gate")

    counts = {"FAS00_ORIGINAL": 0, "S01_CONTROLLED": 0}
    with (RUN / "crossed-cube-ledger-v01.jsonl").open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            dataset = row["dataset"]
            if dataset not in counts or set(row["cells"]) != set(summary["cell_order"]):
                raise FailClosed(f"Malformed S06 ledger row {line_no}")
            for cell in row["cells"].values():
                values = cell["logits"] + list(cell["margins"].values())
                if len(cell["logits"]) != 3 or not all(math.isfinite(float(value)) for value in values):
                    raise FailClosed(f"Invalid/non-finite S06 ledger cell at row {line_no}")
            counts[dataset] += 1
    if counts != {"FAS00_ORIGINAL": 512, "S01_CONTROLLED": 19732}:
        raise FailClosed(f"S06 ledger count mismatch: {counts}")

    for dataset, slices, expected_sizes in (
        ("FAS00_ORIGINAL", {"UNION", "CONTEXT_TERM_3", "ENTITY_TERM_7"}, {"UNION": 512, "CONTEXT_TERM_3": 412, "ENTITY_TERM_7": 212}),
        ("S01_CONTROLLED", {"FACTORIAL_TEST"}, {"FACTORIAL_TEST": 19732}),
    ):
        if set(transitions["populations"][dataset]) != slices:
            raise FailClosed(f"S06 transition slice inventory mismatch: {dataset}")
        for name, data in transitions["populations"][dataset].items():
            if data["n"] != expected_sizes[name] or len(data["cell_pairs"]) != 120:
                raise FailClosed(f"S06 transition count mismatch: {dataset}/{name}")
            for pair in data["cell_pairs"].values():
                if sum(map(sum, pair["prediction_transition_counts_rows_first_columns_second"])) != data["n"] or sum(pair["correctness_transitions"].values()) != data["n"]:
                    raise FailClosed(f"S06 paired transition counts are incomplete: {dataset}/{name}")
    entries = _entries()
    for item in entries:
        got = receipt.get("outputs", {}).get(item["path"])
        if got and (got.get("sha256") != item["sha256"] or got.get("bytes") != item["bytes"]):
            raise FailClosed(f"S06 execution output identity mismatch: {item['path']}")
    return entries


def _verify_existing() -> None:
    seal_path = RUN / "result-tree-seal-v01.json"
    seal = read_json(seal_path)
    entries = seal.get("entries", [])
    if (seal.get("seal_id") != "FAS_S06_RESULT_TREE_SEAL_V01" or
            canonical_root(entries) != seal.get("root_sha256")):
        raise FailClosed("S06 result-tree root mismatch")
    actual = _validate()
    if actual != entries:
        raise FailClosed("S06 result inventory differs from sealed output inventory")
    print(f"S06_RESULT_VERIFY_PASS root={seal['root_sha256']} entries={len(entries)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    seal_path = RUN / "result-tree-seal-v01.json"
    if args.verify:
        _verify_existing()
        return
    if seal_path.exists():
        raise FailClosed("Refusing to overwrite S06 result seal")
    entries = _validate()
    root = canonical_root(entries)
    receipt = read_json(RUN / "execution-receipt-v01.json")
    seal = {
        "seal_id": "FAS_S06_RESULT_TREE_SEAL_V01", "status": "SEALED", "root_sha256": root,
        "protocol_root_sha256": receipt["protocol_root_sha256"], "parent_binding": receipt["parents"],
        "entries": entries, **DISPOSITION,
    }
    seal_path.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S06_RESULT_SEALED root={root} entries={len(entries)}")


if __name__ == "__main__":
    main()
