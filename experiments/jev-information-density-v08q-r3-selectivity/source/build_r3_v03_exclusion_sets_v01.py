"""Build opaque R3-v03 identity exclusions from exact sealed ancestry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
OUTPUT = RUN / "identity-exclusions-v01"
Q2_EXCLUSIONS = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\panel-v01\exclusions\five-field-exclusion-sets.json")
CAL_PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02\calibration-panel-v02\calibration-panel-views.jsonl")
EXPECTED = {
    "q2_exclusions": "47155233c933f28f6b122b6350cc7c11e6e77e71c13883f9958c203be8bb0f19",
    "calibration_panel": "6b813445b14bb8494962b2cc9b0cc8a229244177083c3a605d21ef4f880dbaef",
}
FIELDS = ("world_id", "root_id", "episode_id", "full_rendered_input_hash", "selector_input_hash")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_string(raw: bytes, start: int) -> tuple[str, int]:
    if raw[start] != 0x22:
        raise ValueError("expected JSON string")
    escaped = False
    end = start + 1
    while end < len(raw):
        byte = raw[end]
        if escaped:
            escaped = False
        elif byte == 0x5C:
            escaped = True
        elif byte == 0x22:
            token = raw[start : end + 1]
            return json.loads(token), end + 1
        end += 1
    raise ValueError("unterminated JSON string")


def skip_value(raw: bytes, start: int) -> int:
    """Skip one JSON value without deserializing arrays/objects such as targets."""
    if raw[start] == 0x22:
        return read_string(raw, start)[1]
    if raw[start] in (0x7B, 0x5B):
        stack = [raw[start]]
        i = start + 1
        in_string = False
        escaped = False
        while i < len(raw) and stack:
            byte = raw[i]
            if in_string:
                if escaped:
                    escaped = False
                elif byte == 0x5C:
                    escaped = True
                elif byte == 0x22:
                    in_string = False
            elif byte == 0x22:
                in_string = True
            elif byte in (0x7B, 0x5B):
                stack.append(byte)
            elif byte in (0x7D, 0x5D):
                opened = stack.pop()
                if (opened, byte) not in ((0x7B, 0x7D), (0x5B, 0x5D)):
                    raise ValueError("mismatched JSON container")
            i += 1
        if stack or in_string:
            raise ValueError("unterminated JSON container")
        return i
    i = start
    while i < len(raw) and raw[i] not in (0x2C, 0x7D, 0x20, 0x09, 0x0A, 0x0D):
        i += 1
    return i


def target_free_identity_fields(raw: bytes) -> dict[str, str]:
    """Read only named string fields; skip every unrelated value bytewise."""
    wanted = set(FIELDS)
    result: dict[str, str] = {}
    i = 0
    while i < len(raw) and raw[i] in b" \t\r\n":
        i += 1
    if i >= len(raw) or raw[i] != 0x7B:
        raise ValueError("panel row is not a JSON object")
    i += 1
    while True:
        while i < len(raw) and raw[i] in b" \t\r\n,":
            i += 1
        if i >= len(raw):
            raise ValueError("unterminated panel row")
        if raw[i] == 0x7D:
            i += 1
            break
        key, i = read_string(raw, i)
        while i < len(raw) and raw[i] in b" \t\r\n":
            i += 1
        if i >= len(raw) or raw[i] != 0x3A:
            raise ValueError("malformed JSON key/value separator")
        i += 1
        while i < len(raw) and raw[i] in b" \t\r\n":
            i += 1
        if key in wanted:
            value, i = read_string(raw, i)
            if key in result:
                raise ValueError(f"duplicate identity field: {key}")
            result[key] = value
        else:
            i = skip_value(raw, i)
    if any(byte not in b" \t\r\n" for byte in raw[i:]):
        raise ValueError("trailing data in panel row")
    if set(result) != wanted:
        raise ValueError("panel row lacks one or more contracted identity fields")
    return result


def domain_digest(field: str, value: str) -> str:
    return sha_bytes(f"jev-v08q-exclusion-v01:{field}:{value}".encode("utf-8"))


def write_new(path: Path, value: Any) -> None:
    data = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing existing exclusion output: {OUTPUT}")
    if sha_file(Q2_EXCLUSIONS) != EXPECTED["q2_exclusions"]:
        raise RuntimeError("sealed Q-R2 exclusion input hash mismatch")
    if sha_file(CAL_PANEL) != EXPECTED["calibration_panel"]:
        raise RuntimeError("sealed R3 calibration panel hash mismatch")

    prior = json.loads(Q2_EXCLUSIONS.read_text(encoding="utf-8"))
    if prior.get("schema") != "jev-v08q-r2-five-field-exclusions-v01":
        raise RuntimeError("unexpected sealed ancestry exclusion schema")
    if set(prior.get("training", {})) != set(FIELDS) or set(prior.get("prior_panel", {})) != set(FIELDS):
        raise RuntimeError("sealed ancestry does not provide all five identity fields")

    sets = {field: set(prior["training"][field]) | set(prior["prior_panel"][field]) for field in FIELDS}
    if any(any(len(value) != 64 for value in values) for values in sets.values()):
        raise RuntimeError("bound ancestry identity digest format mismatch")
    e1_hashes = sorted(set(prior.get("e1_neighborhood_hashes", [])))
    if len(e1_hashes) != 2_000 or any(len(value) != 64 for value in e1_hashes):
        raise RuntimeError("sealed E1 neighborhood denylist cardinality/format mismatch")

    panel_rows = 0
    neighborhood_hashes: set[str] = set()
    calibration_counts = {field: set() for field in FIELDS}
    with CAL_PANEL.open("rb") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = target_free_identity_fields(line.rstrip(b"\r\n"))
            panel_rows += 1
            for field in FIELDS:
                digest = domain_digest(field, row[field])
                calibration_counts[field].add(digest)
                sets[field].add(digest)
            # Count-only check; raw neighborhood identity is never emitted.
            # world_id is the contracted canonical world identity for this panel.
            neighborhood_hashes.add(domain_digest("world_id", row["world_id"]))

    if panel_rows != 4_000 or len(neighborhood_hashes) != 2_000:
        raise RuntimeError("sealed calibration panel identity cardinality mismatch")
    expected_unique = {"world_id": 2_000, "root_id": 2_000, "episode_id": 4_000,
                       "full_rendered_input_hash": 4_000, "selector_input_hash": 4_000}
    observed_unique = {field: len(calibration_counts[field]) for field in FIELDS}
    if observed_unique != expected_unique:
        raise RuntimeError(f"calibration identity uniqueness mismatch: {observed_unique}")

    OUTPUT.mkdir(parents=True, exist_ok=False)
    payload = {
        "schema": "jev-v08q-r3-field-exclusion-domain-hash-sets-v01",
        "fields": {field: sorted(values) for field, values in sets.items()},
        "e1_neighborhood_hashes": e1_hashes,
        "counts": {field: len(values) for field, values in sets.items()},
        "sources": {
            "sealed_q2_exclusions_sha256": EXPECTED["q2_exclusions"],
            "sealed_r3_calibration_panel_sha256": EXPECTED["calibration_panel"],
            "calibration_panel_rows_field_selectively_read": panel_rows,
            "target_or_metric_fields_materialized": False,
            "raw_historical_ids_emitted": False,
        },
    }
    payload_path = OUTPUT / "field-exclusion-domain-hashes.json"
    write_new(payload_path, payload)
    receipt = {
        "status": "R3_V03_IDENTITY_EXCLUSIONS_SEALED",
        "payload_sha256": sha_file(payload_path),
        "payload_bytes": payload_path.stat().st_size,
        "field_counts": payload["counts"],
        "calibration_panel_identity_unique_counts": observed_unique,
        "e1_neighborhood_hash_count": len(e1_hashes),
        "source_access": [
            {"path": str(Q2_EXCLUSIONS), "sha256": EXPECTED["q2_exclusions"], "purpose": "reuse sealed five-field training/prior exclusion hashes and E1 ID hashes"},
            {"path": str(CAL_PANEL), "sha256": EXPECTED["calibration_panel"], "purpose": "read only five identity string fields per row with a target-skipping parser"},
        ],
        "target_or_metric_fields_materialized": False,
        "raw_historical_ids_emitted": False,
    }
    receipt_path = OUTPUT / "exclusion-receipt.json"
    write_new(receipt_path, receipt)
    body = f"field-exclusion-domain-hashes.json\t{payload_path.stat().st_size}\t{sha_file(payload_path)}\nexclusion-receipt.json\t{receipt_path.stat().st_size}\t{sha_file(receipt_path)}\n"
    root = sha_bytes(body.encode("utf-8"))
    write_new(OUTPUT / "root-seal.json", {"status": "R3_V03_IDENTITY_EXCLUSION_ROOT_SEALED", "entries_root_sha256": root, "entry_count": 2})
    print(json.dumps({"status": receipt["status"], "root_sha256": root,
                      "payload_sha256": receipt["payload_sha256"], "field_counts": payload["counts"],
                      "calibration_panel_unique_counts": observed_unique, "target_fields_read": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
