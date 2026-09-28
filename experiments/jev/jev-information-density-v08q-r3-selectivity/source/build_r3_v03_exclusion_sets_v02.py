"""Build R3-v03 identity exclusions including every R3 training occurrence.

Only identity metadata is materialized from the sealed training sidecars. JSON
values outside each explicit field allowlist are skipped bytewise, including
the co-located target arrays.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
OUTPUT = RUN / "identity-exclusions-v02"
CAL = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02\calibration-panel-v02\calibration-panel-views.jsonl")
Q_R2_PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\panel-v01\panel\panel-occurrence-identities.jsonl")
TRAIN_IDENTITIES = Path(r"D:\codex-runs\jev-information-density-v08p-r1\v0.8P-R1\replay-attempt-03\training-scope-identities.jsonl")
INPUTS = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02\calibration-inputs-v03")
Q2_EXCLUSIONS = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\panel-v01\exclusions\five-field-exclusion-sets.json")

EXPECTED = {
    "q2_exclusions": "47155233c933f28f6b122b6350cc7c11e6e77e71c13883f9958c203be8bb0f19",
    "calibration_panel": "6b813445b14bb8494962b2cc9b0cc8a229244177083c3a605d21ef4f880dbaef",
    "q_r2_panel_identities": "f05b8e65ef867a361f7cd531f1512f0934e01dae88e8385545467e9ac70914c1",
    "training_identities": "0f5cd945f965c291b13375b16367085a8c4f3dced4e5996b0e1ffbadf279d191",
    "balanced_primary": "8c75354d6225762e275552fcf279d65fb4870f382405bdbbccc36576a950a859",
    "balanced_sham": "98ec35a78fbf2a65d050b1086bbf6337acaaae743cd4208af89107d235247617",
    "reverse_sham": "d75104b5574ea52ad62fb0c72c1e778dc7d4f3da76d678cf2cb756fb39ec40d0",
}
FIELDS = ("world_id", "root_id", "episode_id", "full_rendered_input_hash", "selector_input_hash")
IDENTITY_FIELDS = set(FIELDS)


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
            return json.loads(raw[start : end + 1]), end + 1
        end += 1
    raise ValueError("unterminated JSON string")


def skip_value(raw: bytes, start: int) -> int:
    if raw[start] == 0x22:
        return read_string(raw, start)[1]
    if raw[start] in (0x7B, 0x5B):
        stack = [raw[start]]
        cursor = start + 1
        in_string = escaped = False
        while cursor < len(raw) and stack:
            byte = raw[cursor]
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
            cursor += 1
        if stack or in_string:
            raise ValueError("unterminated JSON container")
        return cursor
    cursor = start
    while cursor < len(raw) and raw[cursor] not in b",}:] \t\r\n":
        cursor += 1
    if cursor == start:
        raise ValueError("empty JSON primitive")
    return cursor


def selected_string_fields(raw: bytes, wanted: set[str]) -> dict[str, str]:
    """Parse only allowlisted top-level string fields; skip all other values."""
    result: dict[str, str] = {}
    cursor = 0
    while cursor < len(raw) and raw[cursor] in b" \t\r\n":
        cursor += 1
    if cursor >= len(raw) or raw[cursor] != 0x7B:
        raise ValueError("row is not a JSON object")
    cursor += 1
    while True:
        while cursor < len(raw) and raw[cursor] in b" \t\r\n,":
            cursor += 1
        if cursor >= len(raw):
            raise ValueError("unterminated JSON object")
        if raw[cursor] == 0x7D:
            cursor += 1
            break
        key, cursor = read_string(raw, cursor)
        while cursor < len(raw) and raw[cursor] in b" \t\r\n":
            cursor += 1
        if cursor >= len(raw) or raw[cursor] != 0x3A:
            raise ValueError("malformed JSON key/value separator")
        cursor += 1
        while cursor < len(raw) and raw[cursor] in b" \t\r\n":
            cursor += 1
        if key in wanted:
            if key in result:
                raise ValueError(f"duplicate field: {key}")
            result[key], cursor = read_string(raw, cursor)
        else:
            cursor = skip_value(raw, cursor)
    if any(byte not in b" \t\r\n" for byte in raw[cursor:]):
        raise ValueError("trailing row bytes")
    if set(result) != wanted:
        raise ValueError(f"required fields missing: {sorted(wanted - set(result))}")
    return result


def rows(path: Path, wanted: set[str]):
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield selected_string_fields(line.rstrip(b"\r\n"), wanted)
                except Exception as error:
                    raise RuntimeError(f"{path.name}:{line_number}: {error}") from error


def domain_digest(field: str, value: str) -> str:
    return sha_bytes(f"jev-v08q-exclusion-v01:{field}:{value}".encode("utf-8"))


def check_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or sha_file(path) != expected:
        raise RuntimeError(f"missing or hash-mismatched bound source: {label}")


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing existing exclusion output: {OUTPUT}")
    sources = {
        "q2_exclusions": Q2_EXCLUSIONS,
        "calibration_panel": CAL,
        "q_r2_panel_identities": Q_R2_PANEL,
        "training_identities": TRAIN_IDENTITIES,
        "balanced_primary": INPUTS / "balanced-primary-occurrences.jsonl",
        "balanced_sham": INPUTS / "balanced-sham-events.jsonl",
        "reverse_sham": INPUTS / "reverse-sham-texts.jsonl",
    }
    for name, path in sources.items():
        check_hash(path, EXPECTED[name], name)

    prior = json.loads(Q2_EXCLUSIONS.read_text(encoding="utf-8"))
    if prior.get("schema") != "jev-v08q-r2-five-field-exclusions-v01":
        raise RuntimeError("unexpected sealed Q-R2 exclusion schema")
    training_sets = {field: set(prior["training"][field]) for field in FIELDS}
    prior_sets = {field: set(prior["prior_panel"][field]) for field in FIELDS}
    if any(not training_sets[field] or not prior_sets[field] for field in FIELDS):
        raise RuntimeError("sealed ancestry has an empty identity field")
    e1_hashes = sorted(set(prior["e1_neighborhood_hashes"]))
    if len(e1_hashes) != 2_000:
        raise RuntimeError("sealed E1 neighborhood denylist cardinality mismatch")

    q2_panel_counts = {field: set() for field in FIELDS}
    q2_panel_rows = 0
    for row in rows(Q_R2_PANEL, IDENTITY_FIELDS):
        q2_panel_rows += 1
        for field in FIELDS:
            q2_panel_counts[field].add(domain_digest(field, row[field]))
            prior_sets[field].add(domain_digest(field, row[field]))
    if q2_panel_rows != 22_000:
        raise RuntimeError(f"Q-R2 panel identity row count mismatch: {q2_panel_rows}")

    calibration_counts = {field: set() for field in FIELDS}
    calibration_rows = 0
    for row in rows(CAL, IDENTITY_FIELDS):
        calibration_rows += 1
        for field in FIELDS:
            digest = domain_digest(field, row[field])
            calibration_counts[field].add(digest)
            prior_sets[field].add(digest)
    if calibration_rows != 4_000:
        raise RuntimeError(f"calibration identity row count mismatch: {calibration_rows}")

    source_identities: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows(TRAIN_IDENTITIES, IDENTITY_FIELDS | {"anchor_id", "role", "family_slug"}):
        key = (row["anchor_id"], row["role"])
        if key in source_identities:
            raise RuntimeError("duplicate source training identity key")
        source_identities[key] = row
    if len(source_identities) != 55_000:
        raise RuntimeError("training identity source row count mismatch")

    train_text_digests = training_sets["full_rendered_input_hash"]
    primary_n = 0
    primary_unbound = 0
    for row in rows(INPUTS / "balanced-primary-occurrences.jsonl", {"input_sha256"}):
        primary_n += 1
        primary_unbound += domain_digest("full_rendered_input_hash", row["input_sha256"]) not in train_text_digests
    if primary_n != 10_000 or primary_unbound:
        raise RuntimeError(f"balanced primary source not covered by sealed training identities: rows={primary_n}, unbound={primary_unbound}")

    reverse_by_neighborhood: dict[str, dict[str, str]] = {}
    reverse_rows = 0
    for row in rows(INPUTS / "reverse-sham-texts.jsonl", {"neighborhood_id", "family_slug", "source_anchor_episode_id", "input_sha256", "text"}):
        reverse_rows += 1
        if row["neighborhood_id"] in reverse_by_neighborhood:
            raise RuntimeError("duplicate reverse-SHAM neighborhood")
        if sha_bytes(row["text"].encode("utf-8")) != row["input_sha256"]:
            raise RuntimeError("reverse-SHAM exact text hash mismatch")
        reverse_by_neighborhood[row["neighborhood_id"]] = row
    if reverse_rows != 2_500:
        raise RuntimeError(f"reverse-SHAM row count mismatch: {reverse_rows}")

    sham_rows = 0
    reverse_aux_seen: set[str] = set()
    reverse_aux_bindings: dict[str, str] = {}
    for row in rows(INPUTS / "balanced-sham-events.jsonl", {"neighborhood_id", "source_episode_id", "input_sha256"}):
        sham_rows += 1
        reverse = reverse_by_neighborhood.get(row["neighborhood_id"])
        is_reverse = row["source_episode_id"].startswith("r3-low-sham:")
        if is_reverse:
            if reverse is None:
                raise RuntimeError("reverse-SHAM event has no exact text source")
            expected_id = f"r3-low-sham:{reverse['source_anchor_episode_id']}"
            if row["source_episode_id"] != expected_id or row["input_sha256"] != reverse["input_sha256"]:
                raise RuntimeError("reverse-SHAM event/source binding mismatch")
            if row["neighborhood_id"] in reverse_aux_seen:
                raise RuntimeError("duplicate reverse-SHAM auxiliary event")
            reverse_aux_seen.add(row["neighborhood_id"])
            reverse_aux_bindings[row["neighborhood_id"]] = row["source_episode_id"]
        elif domain_digest("full_rendered_input_hash", row["input_sha256"]) not in train_text_digests:
            raise RuntimeError("ordinary SHAM input absent from sealed training identities")
    if sham_rows != 5_000 or len(reverse_aux_seen) != 2_500 or reverse_aux_seen != set(reverse_by_neighborhood):
        raise RuntimeError("balanced SHAM source row/variant counts mismatch")

    extension_counts = {field: set() for field in FIELDS}
    for neighborhood, reverse in reverse_by_neighborhood.items():
        low = source_identities.get((neighborhood, "fact_flip"))
        sham = source_identities.get((neighborhood, "sham"))
        if low is None or sham is None or low["episode_id"] != reverse["source_anchor_episode_id"]:
            raise RuntimeError("reverse-SHAM identity cannot bind to exact low-pole source episode")
        if low["family_slug"] != reverse["family_slug"] or sham["family_slug"] != reverse["family_slug"]:
            raise RuntimeError("reverse-SHAM identity family mismatch")
        # The new occurrence is a nuisance/SHAM edit of the low-pole episode:
        # world/root remain its source world; selector identity is the same
        # training selector request for the neighborhood's SHAM candidate set.
        identity = {
            "world_id": low["world_id"],
            "root_id": low["root_id"],
            "episode_id": reverse_aux_bindings[neighborhood],
            "full_rendered_input_hash": reverse["input_sha256"],
            "selector_input_hash": sham["selector_input_hash"],
        }
        for field in FIELDS:
            digest = domain_digest(field, identity[field])
            extension_counts[field].add(digest)
            training_sets[field].add(digest)

    field_sets = {field: sorted(training_sets[field] | prior_sets[field]) for field in FIELDS}
    OUTPUT.mkdir(parents=True, exist_ok=False)
    payload = {
        "schema": "jev-v08q-r3-field-exclusion-domain-hash-sets-v02",
        "fields": field_sets,
        "e1_neighborhood_hashes": e1_hashes,
        "counts": {field: len(values) for field, values in field_sets.items()},
        "provenance": {
            "q2_training_and_prior_hash_sets_sha256": EXPECTED["q2_exclusions"],
            "q_r2_panel_identity_sha256": EXPECTED["q_r2_panel_identities"],
            "q_r2_panel_rows": q2_panel_rows,
            "calibration_panel_sha256": EXPECTED["calibration_panel"],
            "calibration_panel_rows": calibration_rows,
            "training_identity_source_sha256": EXPECTED["training_identities"],
            "balanced_primary_sha256": EXPECTED["balanced_primary"],
            "balanced_primary_rows_bound_to_sealed_training": primary_n,
            "balanced_sham_sha256": EXPECTED["balanced_sham"],
            "balanced_sham_rows": sham_rows,
            "reverse_sham_sha256": EXPECTED["reverse_sham"],
            "reverse_sham_rows": reverse_rows,
            "reverse_sham_identity_extension_counts": {field: len(values) for field, values in extension_counts.items()},
            "reverse_sham_identity_rule": "world/root from exact low-pole source episode; episode_id from the emitted r3-low-sham source_episode_id; exact rendered text hash; selector hash from same neighborhood's bound training SHAM selector row",
            "target_or_outcome_fields_materialized": False,
            "raw_historical_ids_emitted": False,
        },
    }
    payload_path = OUTPUT / "field-exclusion-domain-hashes.json"
    payload_bytes = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    payload_path.write_bytes(payload_bytes)
    receipt = {
        "status": "R3_V03_IDENTITY_EXCLUSIONS_SEALED",
        "schema_version": payload["schema"],
        "payload_sha256": sha_file(payload_path),
        "field_counts": payload["counts"],
        "training_extension_counts": payload["provenance"]["reverse_sham_identity_extension_counts"],
        "q_r2_panel_identity_counts": {field: len(values) for field, values in q2_panel_counts.items()},
        "calibration_panel_identity_counts": {field: len(values) for field, values in calibration_counts.items()},
        "input_bindings": [{"path": str(path), "sha256": EXPECTED[name]} for name, path in sources.items()],
        "application_access": "Only exact bound paths were opened; training sidecar JSON values outside explicit allowlisted identity/text-hash fields were skipped bytewise.",
        "target_or_outcome_fields_materialized": False,
        "raw_historical_ids_emitted": False,
    }
    receipt_path = OUTPUT / "exclusion-receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    manifest = "".join(f"{path.name}\t{path.stat().st_size}\t{sha_file(path)}\n" for path in (payload_path, receipt_path))
    root = sha_bytes(manifest.encode("utf-8"))
    (OUTPUT / "root-seal.json").write_text(json.dumps({"status": "R3_V03_IDENTITY_EXCLUSION_ROOT_SEALED", "entries_root_sha256": root, "entry_count": 2}, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "root_sha256": root, "payload_sha256": receipt["payload_sha256"], "field_counts": payload["counts"], "training_extension_counts": receipt["training_extension_counts"], "q_r2_panel_rows": q2_panel_rows, "calibration_rows": calibration_rows, "target_fields_materialized": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
