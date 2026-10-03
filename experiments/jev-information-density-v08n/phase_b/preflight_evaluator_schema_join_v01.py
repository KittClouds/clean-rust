"""Outcome-blind metadata-only preflight for the v0.8N evaluator schema join.

This audit intentionally does not load the evaluator, model, head checkpoints,
held-out text, held-out targets, predictions, or metric outputs. It checks
whether the sealed training candidate identities provide a unique exact binding
for every held-out schema identity. A missing exact binding is a hard failure;
this script never creates an alias or chooses a substitute.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


REPO = Path(__file__).resolve().parents[3]
PHASE = REPO / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
INPUTS = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-eval-panel-v01")

EXPECTED_SHA256 = {
    "run_contract": "da538aa03355732a2ba362da45d947e169b87aa644d0efd6ba7ef7a546306c1f",
    "frozen_evaluator": "fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4",
    "candidate_catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
    "primary_occurrence_manifest": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "heldout_neighborhoods": "031e834e784868c16e3a71cd8f1c5ccab88c81ff496c6b062d535266a33028ac",
    "heldout_panel_manifest": "80e09c0f203b8a6505e062a2091a594273dca808258ff2f4539ab8414db9eabe",
    "heldout_selected_panel": "6a2f2ab580f3e9fa247682bcba25d68f3ffe539f69062408eff58463f6c1fc5a",
    "panel_seal": "425cef320df94e2b47b448203f8a916ebcbb2019539b2d09e51f5b4ced92f614",
    "panel_unlock": "e8ff5e4548ab5e0b2b96433d844c64836aa03ff878034381c1933db913cb3ec0",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"non-object JSONL row: {path}:{line_number}")
                yield value


def schema_slug(value: str) -> str:
    if ":" not in value:
        raise ValueError(f"schema identity lacks namespace delimiter: {value!r}")
    return value.rsplit(":", 1)[1]


def main() -> int:
    run_contract_path = PHASE / "phase-b-run-contract-v01.json"
    evaluator_path = PHASE / "evaluate_phase_b_v01.py"
    catalog_path = INPUTS / "candidate-catalog.json"
    primary_path = INPUTS / "common-primary-occurrence-manifest.jsonl"
    neighborhoods_path = PANEL / "semantic-scope/heldout-neighborhoods.jsonl"
    panel_manifest_path = PANEL / "matched-panel-v02/heldout-matched-panel-manifest.jsonl"
    selected_path = PANEL / "matched-panel-v02/selected-heldout-matched-neutral.jsonl"
    panel_seal_path = PANEL / "seal/seal-manifest.json"
    unlock_path = RUN / "panel-unlock-receipt.json"
    sources = {
        "run_contract": run_contract_path,
        "frozen_evaluator": evaluator_path,
        "candidate_catalog": catalog_path,
        "primary_occurrence_manifest": primary_path,
        "heldout_neighborhoods": neighborhoods_path,
        "heldout_panel_manifest": panel_manifest_path,
        "heldout_selected_panel": selected_path,
        "panel_seal": panel_seal_path,
        "panel_unlock": unlock_path,
    }
    actual_hashes = {name: sha256(path) for name, path in sources.items()}
    hash_checks = {
        name: actual_hashes[name] == expected
        for name, expected in EXPECTED_SHA256.items()
    }
    if not all(hash_checks.values()):
        result = {
            "status": "FAIL_CLOSED_SOURCE_HASH_MISMATCH",
            "actual_sha256": actual_hashes,
            "expected_sha256": EXPECTED_SHA256,
            "hash_checks": hash_checks,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2

    run_contract = json.loads(run_contract_path.read_text(encoding="utf-8"))
    primary_binding = run_contract["head_input_and_architecture"]["arm_input_manifests"][
        "common_primary_occurrence_manifest"
    ]
    if primary_binding["sha256"] != actual_hashes["primary_occurrence_manifest"]:
        raise ValueError("common primary occurrence manifest is not bound by the run contract")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_ids = [str(row["candidate_semantic_id"]) for row in catalog["rows"]]
    catalog_prefixes: dict[str, set[str]] = {}
    for candidate_id in catalog_ids:
        prefix = candidate_id.split("::", 1)[0]
        catalog_prefixes.setdefault(prefix, set()).add(candidate_id)

    training_orders: dict[str, tuple[str, ...]] = {}
    training_counts: Counter[str] = Counter()
    training_order_hashes: dict[str, set[str]] = {}
    primary_count = 0
    for row in jsonl(primary_path):
        primary_count += 1
        ids = tuple(str(item) for item in row["candidate_semantic_ids"])
        if len(ids) != 4 or len(set(ids)) != 4:
            raise ValueError("training candidate order is not exactly four unique identities")
        prefix = ids[0].split("::", 1)[0]
        if any(item.split("::", 1)[0] != prefix for item in ids):
            raise ValueError("training candidate order crosses semantic namespaces")
        if prefix in training_orders and training_orders[prefix] != ids:
            raise ValueError(f"training candidate order is non-unique for {prefix}")
        if not set(ids).issubset(set(catalog_ids)):
            raise ValueError(f"training order references candidate absent from catalog: {prefix}")
        if catalog_prefixes.get(prefix, set()) != set(ids):
            raise ValueError(f"catalog candidate set does not exactly bind training order: {prefix}")
        training_orders[prefix] = ids
        training_counts[prefix] += 1
        training_order_hashes.setdefault(prefix, set()).add(str(row["candidate_order_hash"]))
    if primary_count != 10_000:
        raise ValueError(f"unexpected primary occurrence count: {primary_count}")
    if set(training_orders) != set(catalog_prefixes) or any(len(v) != 1 for v in training_order_hashes.values()):
        raise ValueError("training order namespaces do not uniquely reconcile with the candidate catalog")

    neighborhood_by_id: dict[str, str] = {}
    for row in jsonl(neighborhoods_path):
        neighborhood_id = str(row["anchor_id"])
        full_schema_id = str(row["schema_family_id"])
        if neighborhood_id in neighborhood_by_id:
            raise ValueError(f"duplicate held-out neighborhood identity: {neighborhood_id}")
        neighborhood_by_id[neighborhood_id] = full_schema_id
    panels = list(jsonl(panel_manifest_path))
    selected = list(jsonl(selected_path))
    if len(neighborhood_by_id) != 2_000 or len(panels) != 2_000 or len(selected) != 2_000:
        raise ValueError("held-out identity tables do not contain exactly 2,000 rows")
    if set(neighborhood_by_id) != {str(row["neighborhood_id"]) for row in panels}:
        raise ValueError("held-out neighborhood and panel identities do not reconcile")
    if {str(row["neighborhood_id"]) for row in panels} != {str(row["neighborhood_id"]) for row in selected}:
        raise ValueError("held-out panel and selected-control identities do not reconcile")

    heldout_counts: Counter[str] = Counter()
    heldout_full_ids: dict[str, str] = {}
    for neighborhood_id, full_id in neighborhood_by_id.items():
        slug = schema_slug(full_id)
        heldout_counts[slug] += 1
        heldout_full_ids[slug] = full_id

    join_rows = []
    for slug in sorted(heldout_counts):
        order = training_orders.get(slug)
        catalog_matches = sorted(catalog_prefixes.get(slug, set()))
        join_rows.append(
            {
                "heldout_schema_family_id": heldout_full_ids[slug],
                "heldout_neighborhood_count": heldout_counts[slug],
                "training_order_binding": list(order) if order else None,
                "candidate_catalog_matches": catalog_matches,
                "status": "EXACT_BINDING" if order and len(catalog_matches) == 4 else "UNRESOLVED",
            }
        )

    unlock = json.loads(unlock_path.read_text(encoding="utf-8"))
    evaluation_dir = RUN / "evaluation"
    output_absent = not evaluation_dir.exists()
    unlock_valid = (
        unlock.get("opening_count") == 1
        and unlock.get("panel_identity") == "v0.8N-eval-panel-v01/matched-panel-v02"
        and unlock.get("panel_seal_sha256") == EXPECTED_SHA256["panel_seal"]
    )
    unresolved = [row for row in join_rows if row["status"] != "EXACT_BINDING"]
    status = "FAIL_CLOSED_MAPPING_UNRESOLVED" if unresolved else "ALL_SCHEMA_JOINS_UNIQUE"
    result = {
        "status": status,
        "preflight_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "preflight_source_sha256": sha256(Path(__file__).resolve()),
        "scope": "identity/order metadata only; no head, prediction, target selection, or metric access",
        "actual_sha256": actual_hashes,
        "hash_checks": hash_checks,
        "candidate_catalog": {
            "rows": len(catalog_ids),
            "feature_dimension": catalog.get("feature_dimension"),
            "schema_namespaces": sorted(catalog_prefixes),
        },
        "training_primary_stream": {
            "rows": primary_count,
            "schema_namespaces": sorted(training_orders),
            "candidate_order_counts": dict(sorted(training_counts.items())),
        },
        "heldout_panel": {
            "rows": len(panels),
            "schema_counts": dict(sorted(heldout_counts.items())),
            "joins": join_rows,
        },
        "unlock": {
            "opening_count": unlock.get("opening_count"),
            "panel_identity": unlock.get("panel_identity"),
            "receipt_sha256": actual_hashes["panel_unlock"],
            "valid_existing_unlock": unlock_valid,
            "second_unlock_created": False,
        },
        "evaluation_outputs_absent_at_preflight": output_absent,
        "prediction_or_metric_artifacts_present": evaluation_dir.exists(),
        "correction_adapter_created": False,
        "continuation_performed": False,
        "unresolved_schemas": [row["heldout_schema_family_id"] for row in unresolved],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 3 if unresolved or not unlock_valid or not output_absent else 0


if __name__ == "__main__":
    raise SystemExit(main())
