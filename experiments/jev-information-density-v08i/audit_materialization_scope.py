"""Post-hoc metadata/source audit for Phase-A evaluation-body isolation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUN = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v01")
V08G = Path(r"D:\codex-runs\jev-information-density-v08g")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    materialization_path = V08G / "materialized-inputs" / "materialization-receipt.json"
    materializer_path = ROOT / "experiments/jev-information-density-v08g/materialize_inputs.py"
    assembler_path = ROOT / "experiments/jev-information-density-v08i/assemble_phase_a.py"
    materialization = read_json(materialization_path)
    bank_receipt_path = RUN / "materialized" / "phase-a-bank-receipt.json"
    integrity_path = RUN / "materialized" / "phase-a-integrity-receipt.json"
    bank_receipt = read_json(bank_receipt_path)
    integrity = read_json(integrity_path)
    materializer_source = materializer_path.read_text(encoding="utf-8")
    assembler_source = assembler_path.read_text(encoding="utf-8")

    tables = materialization["representation_tables"]
    has_eval_source = "new_tight_eval" in materialization["group_files"]
    all_tables_unscoped = all(
        "source_banks" not in item and "source_scope" not in item
        for item in tables.values()
    )
    materializer_mixes_eval = (
        '"new_tight_eval": []' in materializer_source
        and "for bank_name in memberships[group_id]" in materializer_source
        and "bank_groups[bank_name].append(dict(compact))" in materializer_source
    )
    assembler_reads_all_tables = (
        'for name, item in receipt["representation_tables"].items()' in assembler_source
        and "tables[name] = read_indexed_table(path)" in assembler_source
    )
    breach = has_eval_source and all_tables_unscoped and materializer_mixes_eval and assembler_reads_all_tables

    eval_ref = materialization["group_files"].get("new_tight_eval", {})
    result = {
        "protocol": "jev-information-density/v0.8i-phase-a",
        "audit": "protected-evaluation-input-scope",
        "status": "NONPROMOTABLE_BOUNDARY_BREACH" if breach else "NO_BREACH_DETECTED",
        "reason": (
            "The shared v0.8G representation tables were built from random, curated, "
            "and NewTight-Eval groups; Phase-A assembly parsed every row of those tables."
            if breach else "The source metadata and code pattern did not establish the known mixed-scope path."
        ),
        "evidence": {
            "v08g_materialization_receipt": {
                "path": str(materialization_path),
                "sha256": sha256_file(materialization_path),
            },
            "new_tight_eval_group_reference": {
                "path": eval_ref.get("path"),
                "sha256_from_receipt_only": eval_ref.get("sha256"),
                "group_count_from_receipt_only": eval_ref.get("group_count"),
                "body_opened_by_this_audit": False,
            },
            "representation_tables": {
                name: {
                    "path": item["path"],
                    "sha256_from_receipt_only": item["sha256"],
                    "count_from_receipt_only": item["count"],
                    "scope_metadata_present": (
                        "source_banks" in item or "source_scope" in item
                    ),
                }
                for name, item in tables.items()
            },
            "v08g_materializer_source_sha256": sha256_file(materializer_path),
            "v08i_assembler_source_sha256": sha256_file(assembler_path),
            "phase_a_bank_receipt_sha256": sha256_file(bank_receipt_path),
            "phase_a_integrity_receipt_sha256": sha256_file(integrity_path),
            "assembler_mixed_table_read_pattern": assembler_reads_all_tables,
            "materializer_includes_eval_bank_in_shared_tables": materializer_mixes_eval,
        },
        "supersedes_for_promotion": {
            "bank_receipt_claim_newtight_eval_bodies_read": bank_receipt["banks"].get(
                "newtight_eval_bodies_read"
            ),
            "integrity_receipt_claim_protected_eval_bodies_opened": integrity.get(
                "protected_eval_bodies_opened"
            ),
        },
        "model_contact": False,
        "backbone_loaded": False,
        "feature_extraction": False,
        "head_training": False,
        "phoenix_access": False,
        "phase_b_authorized": False,
    }
    out = RUN / "materialized" / "phase-a-boundary-audit.json"
    temp = out.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(out)
    print(json.dumps({"status": result["status"], "path": str(out)}, separators=(",", ":")))
    return 0 if breach else 2


if __name__ == "__main__":
    raise SystemExit(main())
