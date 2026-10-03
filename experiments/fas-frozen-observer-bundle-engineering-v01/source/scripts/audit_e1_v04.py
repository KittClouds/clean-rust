from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT = "fas-frozen-observer-bundle-engineering-v01"
E0_STATUS = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"
E1_STATUS = "E1_PANEL_SEALED_MODEL_CONTACT_NOT_AUTHORIZED"
E0_ROOT = "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e0-seal-v04.json"
E0_FREEZE = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e0-freeze-v04.json"
WORLD_CONTRACT = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/panel-world-contract-v03.json"
SPLIT_SEED = 2_026_092_502
EXPECTED_QUARTETS = 26_624
EXPECTED_ROWS = 106_496
MIN_TEST_ROWS = 200


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def verify_seal(root: Path, seal_path: Path, expected_status: str) -> dict[str, Any]:
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("status") != expected_status:
        raise RuntimeError(f"unexpected status in {seal_path}")
    if seal.get("entry_count") != len(seal.get("entries", [])):
        raise RuntimeError(f"entry count mismatch in {seal_path}")
    for entry in seal["entries"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe sealed path: {relative}")
        digest, size = sha256_file(root / relative)
        if (digest, size) != (entry["sha256"], entry["bytes"]):
            raise RuntimeError(f"sealed file changed: {relative}")
    if tree_root(seal["entries"]) != seal.get("root_sha256"):
        raise RuntimeError(f"tree root mismatch in {seal_path}")
    return seal


def load_rows(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def target_stratum(context_id: int, entity_id: int) -> str:
    return {
        (False, False): "IN_DOMAIN",
        (True, False): "CONTEXT_NOVEL",
        (False, True): "ENTITY_NOVEL",
        (True, True): "BOTH_NOVEL",
    }[(context_id >= 16, entity_id >= 16)]


def endpoint_name(stratum: str) -> str:
    return {
        "IN_DOMAIN": "EXACT_TARGET_IN_DOMAIN",
        "CONTEXT_NOVEL": "EXACT_TARGET_CONTEXT_NOVEL",
        "ENTITY_NOVEL": "EXACT_TARGET_ENTITY_NOVEL",
        "BOTH_NOVEL": "EXACT_TARGET_BOTH_NOVEL",
    }[stratum]


def run(repo_root: Path, run_root: Path, output_path: Path) -> dict[str, Any]:
    e0 = verify_seal(repo_root, repo_root / E0_ROOT, E0_STATUS)
    freeze = json.loads((repo_root / E0_FREEZE).read_text(encoding="utf-8"))
    world_path = repo_root / WORLD_CONTRACT
    world_sha, _ = sha256_file(world_path)
    if world_sha != freeze["panel_world_contract_sha256"]:
        raise RuntimeError("E0 freeze does not bind the current world contract")
    e1 = verify_seal(run_root, run_root / "e1-seal-v01.json", E1_STATUS)
    if e1.get("e0_root_sha256") != e0["root_sha256"] or e1.get("model_contact_authorized") is not False:
        raise RuntimeError("E1 does not bind E0 or has an invalid authority state")
    copied_e0_sha, _ = sha256_file(run_root / "contracts/e0-seal-manifest-v01.json")
    actual_e0_sha, _ = sha256_file(repo_root / E0_ROOT)
    if copied_e0_sha != actual_e0_sha:
        raise RuntimeError("E1's copied E0 manifest differs from the active sealed E0")
    copied_world_sha, _ = sha256_file(run_root / "contracts/panel-world-contract-v01.json")
    if copied_world_sha != world_sha:
        raise RuntimeError("E1's copied panel contract differs from the frozen world contract")

    support = json.loads((run_root / "receipts/support-receipt-v01.json").read_text(encoding="utf-8"))
    build = json.loads((run_root / "receipts/panel-build-receipt-v01.json").read_text(encoding="utf-8"))
    preflight = json.loads((run_root / "resource-preflight-v01.json").read_text(encoding="utf-8"))
    for key in ("model_loaded", "tokenizer_loaded", "feature_extraction_performed", "observer_fitting_performed"):
        if build.get(key) is not False:
            raise RuntimeError(f"unexpected model-contact or fitting state: {key}")
    if build.get("feature_rows") != 0 or support.get("support_gate_pass") is not True:
        raise RuntimeError("E1 feature/contact or support gate state is invalid")
    if preflight.get("e0_root_sha256") != e0["root_sha256"]:
        raise RuntimeError("resource preflight names a different E0 root")
    reserve = build["required_free_reserve_bytes"]
    projected = build["projected_peak_bytes"]
    if build["target_volume_free_bytes_before"] < projected + reserve:
        raise RuntimeError("pre-build target free-space gate does not pass")
    if build["target_volume_free_bytes_after"] < projected + reserve:
        raise RuntimeError("post-build target free-space gate does not pass")

    input_path = run_root / "panel/panel-inputs-v01.jsonl"
    row_manifest_path = run_root / "panel/row-manifest-v01.jsonl"
    fit_path = run_root / "labels/fit-labels-v01.jsonl"
    eval_path = run_root / "labels/eval-labels-v01.jsonl"
    split_path = run_root / "panel/split-manifest-v01.jsonl"

    input_ids: list[str] = []
    input_quartet_counts: Counter[str] = Counter()
    quartet_variant_order: dict[str, list[str]] = defaultdict(list)
    for row in load_rows(input_path):
        if set(row) != {"row_id", "quartet_id", "variant_id", "input_text"}:
            raise RuntimeError("model-input file contains labels or unexpected fields")
        input_ids.append(row["row_id"])
        input_quartet_counts[row["quartet_id"]] += 1
        quartet_variant_order[row["quartet_id"]].append(row["variant_id"])
    if len(input_ids) != EXPECTED_ROWS or len(set(input_ids)) != EXPECTED_ROWS:
        raise RuntimeError("model-input row count or uniqueness failed")
    if len(input_quartet_counts) != EXPECTED_QUARTETS or set(input_quartet_counts.values()) != {4}:
        raise RuntimeError("panel is not 26,624 complete four-row quartets")
    if any(order != ["A", "C", "E", "P"] for order in quartet_variant_order.values()):
        raise RuntimeError("quartet variant order differs from the frozen contract")
    for index, (row, expected_id) in enumerate(zip(load_rows(row_manifest_path), input_ids, strict=True)):
        if row["row_index"] != index or row["row_id"] != expected_id:
            raise RuntimeError("row manifest does not align exactly to model input rows")

    split_rows = list(load_rows(split_path))
    if len(split_rows) != EXPECTED_QUARTETS:
        raise RuntimeError("quartet split manifest row count differs")
    qsplit: dict[str, str] = {}
    strata: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for row in split_rows:
        qid = row["quartet_id"]
        if qid in qsplit:
            raise RuntimeError("duplicate quartet in split manifest")
        qsplit[qid] = row["split"]
        order_key = f"{SPLIT_SEED}|EXACT_TARGET_STRATIFIED_TEST|{qid}".encode("utf-8")
        strata[row["exact_target_stratum"]].append((hashlib.sha256(order_key).hexdigest(), qid))
    if set(qsplit) != set(input_quartet_counts):
        raise RuntimeError("split manifest quartets differ from model inputs")
    for class_id, rows in strata.items():
        rows.sort()
        test_ids = {qid for _, qid in rows[: len(rows) // 5]}
        if any((qsplit[qid] == "TEST") != (qid in test_ids) for _, qid in rows):
            raise RuntimeError(f"test assignment differs from frozen hash split for class {class_id}")

    fit_ids: list[str] = []
    eval_ids: list[str] = []
    fit_support: dict[str, Counter[int]] = defaultdict(Counter)
    eval_support: dict[str, Counter[int]] = defaultdict(Counter)
    for path, row_ids, split_name in ((fit_path, fit_ids, "FIT"), (eval_path, eval_ids, "TEST")):
        for row in load_rows(path):
            row_ids.append(row["row_id"])
            if qsplit.get(row["quartet_id"]) != split_name:
                raise RuntimeError("label row does not follow its whole-quartet split")
            context_id, entity_id = row["context_term_id"], row["entity_term_id"]
            in_domain = context_id < 16 and entity_id < 16
            if row["both_terms_train_side"] != in_domain:
                raise RuntimeError("fit/evaluation domain marker differs from term IDs")
            if split_name == "FIT":
                fit_support["CONTEXT_IDENTITY"][context_id] += 1
                fit_support["ENTITY_IDENTITY"][entity_id] += 1
                if in_domain:
                    fit_support["RELATION_IDENTITY"][row["relation_id"]] += 1
                    fit_support["OBSERVED_STATE"][row["state_id"]] += 1
                    fit_support["EXACT_TARGET"][row["exact_target"]] += 1
            else:
                eval_support["CONTEXT_IDENTITY"][context_id] += 1
                eval_support["ENTITY_IDENTITY"][entity_id] += 1
                if in_domain:
                    eval_support["RELATION_IDENTITY"][row["relation_id"]] += 1
                if in_domain:
                    eval_support["OBSERVED_STATE"][row["state_id"]] += 1
                eval_support[endpoint_name(target_stratum(context_id, entity_id))][row["exact_target"]] += 1
    if len(fit_ids) + len(eval_ids) != EXPECTED_ROWS:
        raise RuntimeError("fit and evaluation labels do not cover every panel row")
    if set(fit_ids) & set(eval_ids) or set(fit_ids) | set(eval_ids) != set(input_ids):
        raise RuntimeError("fit/evaluation label identities overlap or omit panel rows")

    for task, counts in fit_support.items():
        actual = [counts[i] for i in range(len(support["fit_class_support"][task]))]
        if actual != support["fit_class_support"][task] or min(actual) < 1:
            raise RuntimeError(f"fit support mismatch: {task}")
    for task, counts in eval_support.items():
        actual = [counts[i] for i in range(len(support["test_class_support"][task]))]
        if actual != support["test_class_support"][task] or min(actual) < MIN_TEST_ROWS:
            raise RuntimeError(f"test support mismatch: {task}")

    terms = json.loads((run_root / "corpus/term-inventory-v01.json").read_text(encoding="utf-8"))
    all_terms = terms["context_terms"] + terms["entity_terms"]
    if len(set(all_terms)) != 64 or len(terms["context_terms"]) != 32 or len(terms["entity_terms"]) != 32:
        raise RuntimeError("fresh term inventory is not 64 unique role-local terms")
    if terms["generator_seed"] != 2_026_092_501:
        raise RuntimeError("term inventory generator seed mismatch")

    return {
        "audit_id": "FAS_FROZEN_OBSERVER_BUNDLE_E1_INDEPENDENT_AUDIT_V04",
        "status": "PASS",
        "audited_utc": datetime.now(timezone.utc).isoformat(),
        "e0_root_sha256": e0["root_sha256"],
        "e1_root_sha256": e1["root_sha256"],
        "e0_entry_count": e0["entry_count"],
        "e1_entry_count": e1["entry_count"],
        "quartets": len(input_quartet_counts),
        "rows": len(input_ids),
        "fit_rows": len(fit_ids),
        "test_rows": len(eval_ids),
        "support_endpoints": len(eval_support),
        "minimum_test_rows_per_class": min(min(counts.values()) for counts in eval_support.values()),
        "all_test_support_matches_sealed_receipt": True,
        "whole_quartet_split_verified": True,
        "input_labels_absent_and_row_identity_aligned": True,
        "fresh_term_inventory_verified": True,
        "resource_preflight_and_postflight_verified": True,
        "model_loaded": False,
        "tokenizer_loaded": False,
        "feature_extraction_performed": False,
        "observer_fitting_performed": False,
        "audit_script_sha256": sha256_file(Path(__file__).resolve())[0],
        "audit_receipt_is_post_seal_and_outside_e1_tree": True,
    }


def main() -> int:
    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[4]
    output = script_path.parents[2] / "audits" / "e1-independent-audit-v04.json"
    parser = argparse.ArgumentParser(description="Independent post-seal audit of FAS observer-bundle E1")
    parser.add_argument("--run-root", type=Path, default=Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04"))
    parser.add_argument("--output", type=Path, default=output)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite audit receipt: {args.output}")
    receipt = run(repo_root, args.run_root.resolve(strict=True), args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
