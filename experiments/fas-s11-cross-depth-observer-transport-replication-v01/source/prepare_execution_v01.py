#!/usr/bin/env python3
"""Verify S11 ancestry and materialize a run-local, hash-bound execution packet."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

EXPECTED = {
    "protocol_root": "9f11fb59d0f01ed12ee9c9f1753ae990ce5bcb20cf4f799d35a11a39079a4598",
    "contract_sha256": "27e6f17b32e18c709023255498df529e2781a4422e12bec3614a1b1e97abf077",
    "amendment_json_sha256": "c53fdd8229c31814908c6c4975ddd6847c0b282136b41dcb5fcfa657a30341d8",
    "amendment_markdown_sha256": "3d06369bab3a9e18554ca904ba238ebfb8c1167e09dcf4e12afaad44f9570442",
    "panel_root": "9011d425faaac7c6c1bee0f619a696a4469816ebeae1c0df2c6d4f8516fde824",
    "s09_protocol_root": "c1cf07e8b04ac1a3deff583e10257dcd3c5f3040e48bd4b05738cb3c4d4794b2",
    "s09_result_root": "664af5b22f071b28d52a67d748e9f6f93ae3e67d587edec80b921dd529945880",
    "s09_feature_root": "82f9eb6ba0b9c37e58c415b03ec1bc4be00032f73cc43e70b3987ac4108f7653",
    "s10_protocol_root": "3df14974035839db8f58bd96c5063127a3a30680cfa3572cdce47a6df170982e",
    "s10_result_root": "549d906042979261ec68fd0727486c21f0d132d6281940cb9222993f3f1357b1",
    "s10_results_sha256": "50767e14745d8ae805c78afb2533f3ab8171796a33d1198adfa98ec8952ab62d",
    "linear_core_sha256": "b44ce0a2f8c31e5aebb2f13dde4e208424a29a98928d18aa31c6aa081aef2b50",
    "s10_runner_sha256": "c2a294bd38d6df040df82b4d5948062540dbcf9035db68e34c1570d6b47bc68b",
    "s09_math_sha256": "88fb8b771ca0d861ad111c10fefb370e7021b1836655171055762a11057daa92",
    "model_id": "LiquidAI/LFM2.5-1.2B-Base",
    "revision": "7453bca97ca1e67754c4035a4b4c584e1c9dd725",
    "model_parameter_sha256": "14b8ccb6c347eb5a91ccb718de39d70865f15410f5b6e62ca747aaf77f6bb9e5",
}


def sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_seal_entries(base: Path, seal_path: Path, expected_root: str) -> dict[str, Any]:
    seal = read_json(seal_path)
    entries = sorted(seal["entries"], key=lambda row: row["path"])
    root_hash = hashlib.sha256()
    total_bytes = 0
    for entry in entries:
        path = base.joinpath(*entry["path"].split("/"))
        digest, size = sha256_file(path)
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise RuntimeError(f"parent sealed entry mismatch: {path}")
        root_hash.update(f"{entry['path']}\t{size}\t{digest}\n".encode("utf-8"))
        total_bytes += size
    observed_root = root_hash.hexdigest()
    if observed_root != expected_root or seal.get("root_sha256") != expected_root:
        raise RuntimeError(f"parent tree root mismatch: {seal_path}; observed={observed_root}")
    return {"root_sha256": observed_root, "entries_verified": len(entries), "sealed_bytes": total_bytes}


def copy_checked(source: Path, destination: Path, expected_sha: str | None = None) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    source_sha, source_size = sha256_file(source)
    copied_sha, copied_size = sha256_file(destination)
    if source_sha != copied_sha or source_size != copied_size:
        raise RuntimeError(f"copy mismatch: {source} -> {destination}")
    if expected_sha is not None and source_sha != expected_sha:
        raise RuntimeError(f"unexpected source hash: {source}")
    return {"path": destination.as_posix(), "bytes": copied_size, "sha256": copied_sha}


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepare_execution_v01.py EXECUTION_ROOT")
    output = Path(sys.argv[1]).resolve()
    if output.exists():
        raise RuntimeError(f"S11 execution output already exists; refusing overwrite: {output}")

    repo = Path(__file__).resolve().parents[3]
    project = repo / "experiments" / "fas-s11-cross-depth-observer-transport-replication-v01"
    panel = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\panel-construction-v02")
    s09_run = Path(r"\\?\D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v09")
    s09_v02 = Path(r"D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v02")
    s10_run = Path(r"D:\codex-runs\fas-s10-cross-depth-observer-transport-v03")
    s01_tokenizer_run = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2a-tokenizer-alignment-v02")

    protocol_seal = read_json(project / "seals" / "protocol-seal-v01.json")
    protocol_check = verify_seal_entries(project, project / "seals" / "protocol-seal-v01.json", EXPECTED["protocol_root"])
    contract_path = project / "contracts" / "s11-confirmatory-contract-v01.json"
    amendment_json = project / "amendments" / "s11-panel-collision-admission-correction-v01.json"
    amendment_md = project / "amendments" / "S11-PANEL-COLLISION-ADMISSION-CORRECTION-V01.md"
    contract_sha = sha256_file(contract_path)[0]
    amendment_sha = sha256_file(amendment_json)[0]
    amendment_md_sha = sha256_file(amendment_md)[0]
    if contract_sha != EXPECTED["contract_sha256"] or amendment_sha != EXPECTED["amendment_json_sha256"] or amendment_md_sha != EXPECTED["amendment_markdown_sha256"]:
        raise RuntimeError("S11 contract or panel amendment identity mismatch")
    contract = read_json(contract_path)
    if contract["feature_and_observer_path"]["model_id"] != EXPECTED["model_id"] or contract["feature_and_observer_path"]["model_revision"] != EXPECTED["revision"]:
        raise RuntimeError("contract model identity differs from the pinned extraction")
    if contract["fresh_panel"]["selection"]["total_selected_quartets"] != 5318 or contract["fresh_panel"]["selection"]["total_selected_rows"] != 21272:
        raise RuntimeError("S11 fixed panel quotas differ from the frozen contract")

    panel_verify_script = repo / "experiments" / "fas-s11-cross-depth-observer-transport-replication-v01" / "source" / "verify_panel_tree_v02.py"
    subprocess.run([sys.executable, str(panel_verify_script), str(panel)], check=True)
    panel_seal_path = panel / "seals" / "panel-tree-seal-v02.json"
    panel_seal = read_json(panel_seal_path)
    panel_verify = read_json(panel / "verification" / "independent-verification-v02.json")
    if panel_seal.get("tree_root_sha256") != EXPECTED["panel_root"] or panel_verify.get("tree_root_sha256") != EXPECTED["panel_root"] or panel_verify.get("status") != "S11_PANEL_SEAL_VERIFY_PASS":
        raise RuntimeError("S11 panel v02 identity or independent verification mismatch")
    panel_validation = read_json(panel / "reports" / "panel-validation-report-v02.json")
    if panel_validation.get("status") != "S11_PANEL_CONSTRUCTION_VALID" or not all(value == "PASS" for value in panel_validation.get("gates", {}).values()):
        raise RuntimeError("S11 panel validation report is not a complete pass")
    panel_entries = {entry["path"]: entry for entry in panel_seal["entries"]}
    for relative in ("corpus/selected-events-v02.jsonl", "corpus/selected-quartets-v02.jsonl", "corpus/term-inventory-v02.json"):
        entry = panel_entries.get(relative)
        if entry is None:
            raise RuntimeError(f"panel seal lacks required execution input: {relative}")
        digest, size = sha256_file(panel / Path(*relative.split("/")))
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise RuntimeError(f"panel execution input differs from the panel seal: {relative}")

    s09_seal = verify_seal_entries(s09_run, s09_run / "result-tree-seal-v09.json", EXPECTED["s09_result_root"])
    s09_receipt = read_json(s09_run / "recovery-extraction-receipt-v03.json")
    s09_cache_seal = read_json(s09_run / "recovery-feature-cache-seal-v03.json")
    if s09_receipt.get("backbone_parameter_delta") != 0 or s09_receipt.get("model_id") != EXPECTED["model_id"] or s09_receipt.get("model_revision") != EXPECTED["revision"]:
        raise RuntimeError("S09 extraction receipt is inconsistent with the pinned model")
    if s09_cache_seal.get("root_sha256") != EXPECTED["s09_feature_root"]:
        raise RuntimeError("S09 feature-cache ancestry root mismatch")

    s10_seal = verify_seal_entries(s10_run, s10_run / "result-seal-v03.json", EXPECTED["s10_result_root"])
    s10_results = s10_run / "S10-TRANSPORT-RESULTS-V03.json"
    if sha256_file(s10_results)[0] != EXPECTED["s10_results_sha256"]:
        raise RuntimeError("S10 results identity mismatch")
    s10_receipt = read_json(s10_run / "parent-verification-receipt-v03.json")
    if s10_receipt.get("parent_result_tree", {}).get("root_sha256") != EXPECTED["s09_result_root"] or s10_receipt.get("parent_feature_cache", {}).get("root_sha256") != EXPECTED["s09_feature_root"]:
        raise RuntimeError("S10 parent verification receipt does not bind the S09 roots")

    s10_project = repo / "experiments" / "fas-s10-cross-depth-observer-transport-v03"
    source_files = {
        "linear_core.py": (s10_project / "source" / "linear_core.py", EXPECTED["linear_core_sha256"]),
        "run_s10_transport.py": (s10_project / "source" / "run_s10_transport.py", EXPECTED["s10_runner_sha256"]),
        "s09_math.py": (s10_project / "source" / "s09_math.py", EXPECTED["s09_math_sha256"]),
    }
    for name, (path, expected_hash) in source_files.items():
        if sha256_file(path)[0] != expected_hash:
            raise RuntimeError(f"S10/S09 frozen helper source mismatch: {name}")

    model_manifest_path = s09_v02 / "model-asset-manifest-v02.json"
    model_manifest = read_json(model_manifest_path)
    if model_manifest.get("model_id") != EXPECTED["model_id"] or model_manifest.get("resolved_revision") != EXPECTED["revision"] or model_manifest.get("asset_manifest_root_sha256") != "661a7e73c0804e98bfb4ca9d1786ca9126a0a21595fbd2d3aea517c342fba1b3":
        raise RuntimeError("pinned S09 model asset manifest mismatch")
    model_files = []
    for asset in model_manifest["assets"]:
        path = s09_v02.joinpath(*asset["path"].split("/"))
        digest, size = sha256_file(path)
        if digest != asset["sha256"] or size != asset["bytes"]:
            raise RuntimeError(f"pinned S09 model asset differs: {path}")
        model_files.append({"path": str(path), "bytes": size, "sha256": digest})
    model_identity = sha256_file(model_manifest_path)[0]

    tokenizer_manifest_path = s01_tokenizer_run / "tokenizer-assets-manifest-v01.json"
    tokenizer_identity_path = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2a-tokenizer-alignment-v01\tokenizer-identity-v01.json")
    tokenizer_manifest = read_json(tokenizer_manifest_path)
    tokenizer_identity = read_json(tokenizer_identity_path)
    if tokenizer_manifest.get("repo_id") != EXPECTED["model_id"] or tokenizer_manifest.get("resolved_commit") != EXPECTED["revision"] or tokenizer_identity.get("resolved_commit") != EXPECTED["revision"]:
        raise RuntimeError("pinned tokenizer identity mismatch")
    tokenizer_cache = s01_tokenizer_run / "tokenizer-cache" / "hub" / "models--LiquidAI--LFM2.5-1.2B-Base" / "snapshots" / EXPECTED["revision"]
    tokenizer_files = []
    for asset in tokenizer_manifest["loaded_snapshot_files"]:
        path = tokenizer_cache / Path(*asset["path"].split("/"))
        digest, size = sha256_file(path)
        if digest != asset["sha256"] or size != asset["bytes"]:
            raise RuntimeError(f"pinned tokenizer asset differs: {path}")
        tokenizer_files.append({"name": asset["path"], "bytes": size, "sha256": digest})

    if output.exists():
        raise RuntimeError("execution output appeared during preflight")
    output.mkdir(parents=True)
    input_root = output / "inputs"
    copies = []
    for name, path in (
        ("protocol/FAS-S11-PROTOCOL-V01.md", project / "FAS-S11-PROTOCOL-V01.md"),
        ("protocol/protocol-seal-v01.json", project / "seals" / "protocol-seal-v01.json"),
        ("protocol/s11-confirmatory-contract-v01.json", contract_path),
        ("amendment/s11-panel-collision-admission-correction-v01.json", amendment_json),
        ("amendment/S11-PANEL-COLLISION-ADMISSION-CORRECTION-V01.md", amendment_md),
        ("panel/panel-tree-seal-v02.json", panel_seal_path),
        ("panel/panel-validation-report-v02.json", panel / "reports" / "panel-validation-report-v02.json"),
        ("panel/independent-verification-v02.json", panel / "verification" / "independent-verification-v02.json"),
        ("panel/selected-events-v02.jsonl", panel / "corpus" / "selected-events-v02.jsonl"),
        ("panel/selected-quartets-v02.jsonl", panel / "corpus" / "selected-quartets-v02.jsonl"),
        ("panel/term-inventory-v02.json", panel / "corpus" / "term-inventory-v02.json"),
        ("parent/s09-model-asset-manifest-v02.json", model_manifest_path),
        ("parent/s09-recovery-extraction-receipt-v03.json", s09_run / "recovery-extraction-receipt-v03.json"),
        ("parent/s09-recovery-feature-cache-seal-v03.json", s09_run / "recovery-feature-cache-seal-v03.json"),
        ("parent/s10-result-seal-v03.json", s10_run / "result-seal-v03.json"),
        ("parent/s10-parent-verification-receipt-v03.json", s10_run / "parent-verification-receipt-v03.json"),
    ):
        copies.append(copy_checked(path, input_root / Path(*name.split("/"))))
    for filename in ("config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json"):
        source = tokenizer_cache / filename
        expected_hash = next(x["sha256"] for x in tokenizer_files if x["name"] == filename)
        copies.append(copy_checked(source, input_root / "tokenizer-snapshot" / filename, expected_hash))
    for name, (source, expected_hash) in source_files.items():
        copies.append(copy_checked(source, input_root / "parent-sources" / name, expected_hash))
    copies.append(copy_checked(tokenizer_manifest_path, input_root / "tokenizer-assets-manifest-v01.json"))
    copies.append(copy_checked(tokenizer_identity_path, input_root / "tokenizer-identity-v01.json"))

    panel_events = panel_entries["corpus/selected-events-v02.jsonl"]
    panel_quartets = panel_entries["corpus/selected-quartets-v02.jsonl"]
    manifest = {
        "execution_id": "FAS_S11_FULL_EXECUTION_V01",
        "status": "INPUTS_BOUND_BEFORE_TOKENIZATION",
        "explicit_authorization": "User authorization in current task: execute the complete frozen S11 packet through final seal, with the stated internal cache-before-observer boundary.",
        "authoritative_s11_ancestry": {
            "protocol_root_sha256": EXPECTED["protocol_root"],
            "collision_admission_amendment_json_sha256": amendment_sha,
            "panel_tree_root_sha256": EXPECTED["panel_root"],
            "panel_seal_file_sha256": sha256_file(panel_seal_path)[0],
            "panel_id": "fas-s11-fresh-quartet-panel-v02-uniqueness-conditioned",
            "panel_events_sha256": panel_events["sha256"],
            "panel_quartets_sha256": panel_quartets["sha256"],
        },
        "frozen_contract_sha256": contract_sha,
        "panel_amendment_markdown_sha256": amendment_md_sha,
        "parents": {
            "s09_protocol_root_sha256": EXPECTED["s09_protocol_root"],
            "s09_result_tree_root_sha256": EXPECTED["s09_result_root"],
            "s09_feature_cache_root_sha256": EXPECTED["s09_feature_root"],
            "s10_protocol_root_sha256": EXPECTED["s10_protocol_root"],
            "s10_result_tree_root_sha256": EXPECTED["s10_result_root"],
            "s10_results_sha256": EXPECTED["s10_results_sha256"],
            "s09_sealed_observer_bank": "32 S09 layer/surface probe states; byte identities are included in the verified S09 result tree and will be loaded only after the S11 feature-cache seal.",
        },
        "preflight": {
            "protocol_tree": protocol_check,
            "panel_tree": {"root_sha256": EXPECTED["panel_root"], "status": panel_verify["status"], "files_verified": panel_verify["verified_file_count"]},
            "s09_result_tree": s09_seal,
            "s10_result_tree": s10_seal,
            "model_assets": {"model_id": EXPECTED["model_id"], "revision": EXPECTED["revision"], "manifest_sha256": model_identity, "asset_manifest_root_sha256": model_manifest["asset_manifest_root_sha256"], "files": model_files},
            "tokenizer": {"repo_id": EXPECTED["model_id"], "revision": EXPECTED["revision"], "manifest_sha256": sha256_file(tokenizer_manifest_path)[0], "identity_sha256": sha256_file(tokenizer_identity_path)[0], "files": tokenizer_files},
            "runtime_expected": {"torch": "2.11.0+cu128", "transformers": "5.17.0", "numpy": "2.5.3", "tokenizers": "0.23.2", "device": "NVIDIA GeForce RTX 3080"},
        },
        "execution_order": ["tokenize fresh rows", "extract and seal 32 fresh feature matrices", "load sealed observer bank", "compute all 512 transport cells", "shared-plan bootstrap and frozen summaries", "independent verification and final seal"],
        "authority_state": {"tokenizer_execution_authorized": True, "model_contact_authorized": True, "feature_extraction_authorized": True, "observer_replay_authorized": True, "observer_load_before_feature_seal": False},
        "tokenizer_loaded": False,
        "model_loaded": False,
        "features_extracted": False,
        "observers_loaded": False,
        "copied_input_files": copies,
    }
    manifest_path = output / "execution-manifest-v01.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"S11_EXECUTION_INPUTS_BOUND manifest_sha256={sha256_file(manifest_path)[0]} output={output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
