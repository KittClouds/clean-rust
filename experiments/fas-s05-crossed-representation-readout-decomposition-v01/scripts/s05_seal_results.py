from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from s05_common import RUN, FailClosed, read_json, sha_file, verify_protocol_bundle


OUTPUTS = (
    "preflight-receipt-v01.json",
    "event-populations-v01.json",
    "crossed-replay-ledger-v01.jsonl",
    "crossed-summary-v01.json",
    "prediction-transitions-v01.json",
    "execution-receipt-v01.json",
    "S05-RESULTS.md",
)
DISPOSITION = {
    "S05_RESULT_READY": True,
    "FAS00_SENSOR_PASS": False,
    "FAS00_PHASE4_AUTHORIZED": False,
    "S02_ADAPTIVE_MECHANISM_AUTHORIZED": False,
    "model_contact": False,
    "feature_extraction": False,
    "probe_fitting": False,
    "adaptive_mechanisms": False,
    "SAE_analysis": False,
}


def _root(entries: list[dict[str, Any]]) -> str:
    material = "".join(
        f"{item['path']} {item['sha256']}\n"
        for item in sorted(entries, key=lambda item: item["path"].casefold())
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _validate_unsealed_outputs() -> list[dict[str, Any]]:
    protocol = verify_protocol_bundle()
    preflight = read_json(RUN / "preflight-receipt-v01.json")
    populations = read_json(RUN / "event-populations-v01.json")
    summary = read_json(RUN / "crossed-summary-v01.json")
    transitions = read_json(RUN / "prediction-transitions-v01.json")
    receipt = read_json(RUN / "execution-receipt-v01.json")
    if (preflight.get("status") != "PASS" or preflight.get("protocol_root_sha256") != protocol["root_sha256"] or
            preflight.get("FAS00_ORIGINAL_unique_events") != 512 or preflight.get("S01_CONTROLLED_quartets") != 4933 or
            preflight.get("S01_CONTROLLED_events") != 19732):
        raise FailClosed("S05 preflight receipt does not satisfy its sealed counts")
    if (len(populations["FAS00_ORIGINAL"]["rows"]) != 512 or
            len(populations["S01_CONTROLLED"]["rows"]) != 19732 or
            len(populations["S01_CONTROLLED"]["quartets"]) != 4933):
        raise FailClosed("S05 serialized event populations have invalid counts")
    if summary.get("status") != "COMPLETE" or summary.get("decomposition", {}).get("identity_checked") is not True:
        raise FailClosed("S05 crossed summary is incomplete")
    for replay in receipt.get("replay_receipts", []):
        if replay.get("diagonal_gate") != "PASS" or replay.get("unique_events_replayed") not in (512, 19732):
            raise FailClosed("S05 diagonal replay receipt failed")
    if len(receipt.get("replay_receipts", [])) != 2:
        raise FailClosed("S05 execution receipt lacks both populations")
    for key, expected in DISPOSITION.items():
        if receipt.get(key) is not expected:
            raise FailClosed(f"S05 execution receipt violates disposition: {key}")
    for relative in OUTPUTS:
        path = RUN / relative
        if not path.is_file():
            raise FailClosed(f"Missing S05 result artifact: {relative}")
        if relative in receipt.get("outputs", {}):
            identity = receipt["outputs"][relative]
            if identity.get("sha256") != sha_file(path) or identity.get("bytes") != path.stat().st_size:
                raise FailClosed(f"S05 execution receipt output identity mismatch: {relative}")

    ledger_counts = {"FAS00_ORIGINAL": 0, "S01_CONTROLLED": 0}
    with (RUN / "crossed-replay-ledger-v01.jsonl").open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            dataset = row["dataset"]
            if dataset not in ledger_counts or set(row["cells"]) != {"MM", "FM", "MF", "FF"}:
                raise FailClosed(f"Malformed S05 ledger row {line_number}")
            for cell in row["cells"].values():
                values = cell["logits"] + list(cell["margins"].values())
                if not all(math.isfinite(float(value)) for value in values):
                    raise FailClosed(f"Non-finite S05 ledger value at row {line_number}")
            for margin in row["margin_decomposition"].values():
                error = (margin["representation_at_M_readout"] + margin["readout_at_M_representation"]
                         + margin["interaction"] - margin["diagonal_total"])
                if abs(float(error)) > 1e-10:
                    raise FailClosed(f"S05 event margin decomposition mismatch at row {line_number}")
            ledger_counts[dataset] += 1
    if ledger_counts != {"FAS00_ORIGINAL": 512, "S01_CONTROLLED": 19732}:
        raise FailClosed(f"S05 ledger population mismatch: {ledger_counts}")

    transition_payload = transitions.get("populations", {})
    for dataset, expected_names in (("FAS00_ORIGINAL", {"UNION", "CONTEXT_TERM_3", "ENTITY_TERM_7"}),
                                    ("S01_CONTROLLED", {"FACTORIAL_TEST"})):
        if set(transition_payload.get(dataset, {})) != expected_names:
            raise FailClosed(f"S05 transition slices differ for {dataset}")
        for slice_record in transition_payload[dataset].values():
            for pair in slice_record["cell_pairs"].values():
                matrix_total = sum(sum(int(value) for value in row) for row in pair["prediction_transition_counts_rows_first_columns_second"])
                correctness_total = sum(int(value) for value in pair["correctness_transitions"].values())
                if matrix_total != slice_record["n"] or correctness_total != slice_record["n"]:
                    raise FailClosed("S05 paired transition counts are not exhaustive")

    entries = []
    for relative in OUTPUTS:
        path = RUN / relative
        entries.append({"path": relative, "sha256": sha_file(path), "bytes": path.stat().st_size})
    entries.sort(key=lambda item: item["path"].casefold())
    return entries


def _verify_existing_seal() -> None:
    seal_path = RUN / "result-tree-seal-v01.json"
    seal = read_json(seal_path)
    entries = seal.get("entries", [])
    if seal.get("seal_id") != "FAS_S05_RESULT_TREE_SEAL_V01" or _root(entries) != seal.get("root_sha256"):
        raise FailClosed("S05 result seal root is malformed")
    for item in entries:
        path = RUN / Path(item["path"])
        if not path.is_file() or sha_file(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise FailClosed(f"S05 sealed result artifact changed: {item['path']}")
    expected = _validate_unsealed_outputs()
    if expected != entries:
        raise FailClosed("S05 result inventory differs from independent current verification")
    print(f"S05_RESULT_SEAL_VERIFY_PASS root={seal['root_sha256']} entries={len(entries)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="independently verify an existing result seal")
    args = parser.parse_args()
    seal_path = RUN / "result-tree-seal-v01.json"
    if args.verify:
        _verify_existing_seal()
        return
    if seal_path.exists():
        raise FailClosed("Refusing to overwrite S05 result seal")
    entries = _validate_unsealed_outputs()
    root = _root(entries)
    receipt = read_json(RUN / "execution-receipt-v01.json")
    seal = {
        "seal_id": "FAS_S05_RESULT_TREE_SEAL_V01",
        "status": "SEALED",
        "root_sha256": root,
        "protocol_root_sha256": receipt["protocol_root_sha256"],
        "parent_roots": receipt["parents"],
        "entries": entries,
        **DISPOSITION,
    }
    seal_path.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S05_RESULT_SEALED root={root} entries={len(entries)}")


if __name__ == "__main__":
    main()
