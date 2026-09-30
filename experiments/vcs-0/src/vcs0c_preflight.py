"""VCS-0c preflight equality check. NOT geometry.

Required equality, for the intended population:
    DEV universe  ==  Base DEV  ==  NER DEV  ==  cheap(B1) DEV

If this fails, VCS-0c stops and reports. No substitution, no imputation, no refit.

This script only compares identifier sets and verifies published hashes. It never opens
protected/test-truth and never fits or predicts anything.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

BANK = Path(r"C:\code land\clean-rust\experiments\ff-s15-bank-01\releases\BANK-v1")
R2A = Path(r"C:\phoenix-target-overgraph\lexi-h2-rebuild-20260930\r2a-semantic-estimator-pair")
EXPORT = R2A / "r2a-export-dev-predictions.jsonl"
MANIFEST = R2A / "r2a-export-dev-manifest.json"

ELIGIBLE_NEURAL = ["causal_base", "ner_lora_step500"]
CHEAP = "B1_count_statistics"


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sorted_id_hash(ids) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def main() -> int:
    failures: list[str] = []
    checks: dict = {}

    man = json.loads(MANIFEST.read_text(encoding="utf-8"))

    # --- published hash verification (do not trust the manifest about itself) ---
    exp_hash = sha_file(EXPORT)
    checks["export_sha256_matches_manifest"] = {
        "computed": exp_hash, "manifest": man["export_sha256"],
        "ok": exp_hash == man["export_sha256"]}
    if exp_hash != man["export_sha256"]:
        failures.append("export file hash does not match manifest")

    dev_inputs = BANK / "inputs" / "DEV.jsonl"
    dev_hash = sha_file(dev_inputs)
    checks["dev_inputs_sha256_matches_manifest"] = {
        "computed": dev_hash, "manifest": man["dev_input_sha256"],
        "ok": dev_hash == man["dev_input_sha256"]}
    if dev_hash != man["dev_input_sha256"]:
        failures.append("DEV input hash does not match manifest")

    # --- DEV universe from BANK, independent of the export ---
    dev_ids, dev_rows = [], []
    with dev_inputs.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                dev_rows.append(r)
                dev_ids.append(r["world_id"])
    dev_universe = set(dev_ids)
    checks["dev_universe"] = {"rows": len(dev_rows), "unique_ids": len(dev_universe),
                              "duplicates": len(dev_rows) - len(dev_universe),
                              "sorted_id_sha256": sorted_id_hash(dev_universe)}
    if len(dev_universe) != len(dev_rows):
        failures.append("DEV input contains duplicate world_ids")

    # --- export lanes ---
    lane_ids: dict[str, list[str]] = {}
    lane_rowcount: dict[str, int] = {}
    row_world_ids: list[str] = []
    with EXPORT.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            row_world_ids.append(d["world_id"])
            lanes = d.get("estimates_by_lane") or d.get("lanes") or {}
            for lane, payload in lanes.items():
                lane_ids.setdefault(lane, []).append(d["world_id"])
                lane_rowcount[lane] = lane_rowcount.get(lane, 0) + 1

    if not lane_ids:
        # fall back: infer lanes from coordinate keys at top level
        with EXPORT.open(encoding="utf-8") as f:
            first = json.loads(f.readline())
        raise SystemExit(f"cannot locate lane structure; top-level keys = {list(first.keys())}")

    checks["export_rows"] = len(row_world_ids)
    checks["lanes_found"] = sorted(lane_ids)

    expected_lanes = set(ELIGIBLE_NEURAL) | {CHEAP}
    unexpected = expected_lanes - set(lane_ids)
    if unexpected:
        failures.append(f"required lanes absent from export: {sorted(unexpected)}")
    ineligible = {"encoder_base", "nli_lora_step500"} & set(lane_ids)
    if ineligible:
        failures.append(f"export contains gate-failed lanes: {sorted(ineligible)}")

    # --- the equality itself ---
    eq = {}
    exp_universe = set(row_world_ids)
    for lane, ids in sorted(lane_ids.items()):
        s = set(ids)
        missing = sorted(dev_universe - s)
        extra = sorted(s - dev_universe)
        dup = len(ids) - len(s)
        eq[lane] = {"rows": len(ids), "unique": len(s), "missing_vs_dev": len(missing),
                    "extra_vs_dev": len(extra), "duplicates": dup,
                    "sorted_id_sha256": sorted_id_hash(s),
                    "equals_dev_universe": s == dev_universe}
        if s != dev_universe or dup:
            failures.append(f"lane {lane} does not equal DEV universe "
                            f"(missing={len(missing)} extra={len(extra)} dup={dup})")
    checks["lane_equality"] = eq

    # --- published ID-set hash cross-check ---
    claimed = man.get("dev_world_id_set_sha256_sorted")
    checks["id_set_hash_cross_check"] = {
        "manifest_claim": claimed, "computed": sorted_id_hash(dev_universe),
        "ok": claimed == sorted_id_hash(dev_universe)}
    if claimed != sorted_id_hash(dev_universe):
        failures.append("DEV sorted ID-set hash does not match manifest claim")

    # --- B1 artifact hashes vs atlas ---
    atlas = json.loads((R2A / "SEMANTIC-ESTIMATOR-ATLAS.json").read_text(encoding="utf-8"))
    bd = atlas["development"]["baseline_dev"]
    b1 = {}
    for coord, spec in man.get("b1_estimators", {}).items():
        p = Path(spec["path"])
        actual = sha_file(p) if p.is_file() else None
        atlas_claim = bd[coord].get("B1_artifact_sha256")
        b1[coord] = {"path_exists": p.is_file(), "computed": actual,
                     "manifest": spec["sha256"], "atlas_B1": atlas_claim,
                     "all_agree": actual == spec["sha256"] == atlas_claim}
        if not b1[coord]["all_agree"]:
            failures.append(f"B1 artifact hash disagreement for {coord}")
    checks["b1_artifacts"] = b1

    result = {
        "check": "VCS-0c preflight equality",
        "status": "PASS" if not failures else "FAIL",
        "geometry_run": False,
        "protected_truth_opened": False,
        "failures": failures,
        "checks": checks,
    }
    out = Path(r"D:\codex-runs\encoder-contrast-01\vcs\vcs0c-preflight.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
