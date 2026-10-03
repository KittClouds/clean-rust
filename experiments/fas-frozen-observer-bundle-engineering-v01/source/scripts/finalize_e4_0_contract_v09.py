#!/usr/bin/env python3
"""Finalize the E4-0 v09 contract-tooling successor from sealed v06 science."""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
BASELINE_REL = f"{PROJECT_REL}/contracts/e4-0-contract-v06-final.json"
MAP_REL = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v08.md"
OUTPUT_REL = f"{PROJECT_REL}/contracts/e4-0-contract-v09-final.json"
BASELINE_SHA256 = "ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958"
IMMUTABLE = ("purpose", "authorization", "predecessors", "representation_abi", "population", "parity",
             "fresh_qualification", "truth_access", "resources", "phase_gates",
             "stop_rule", "E4_A_dependency", "execution_identity", "identity_collision_correction")
V06_SEAL_REL = f"{PROJECT_REL}/seals/e4-0-contract-v06-seal.json"
V06_SEAL_SHA256 = "799d1535a16ea6fbf2269206443addf96736ef8a70ca5ab3373cdd5e6a44605c"
V06_ROOT_SHA256 = "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64"
V08_CONTRACT_SHA256 = "ec17befa2a65e0da589ee51792cde3c028e900aa919179b2c9c3365cc20c3e9b"
V08_CONTRACT_BYTES = 54286
V08_SEAL_SHA256 = "238d1fdb46ba3d8a9de1ae90e41a9b3c455ba65661bc98e8fe6fa5d21e3d3156"
V08_SEAL_BYTES = 68666
V08_ROOT_SHA256 = "e0093eacd70ce7cbf3b3a19045683ce5a7f4d4413748003e2d8e1446f131478d"
V08_AUDIT_SHA256 = "8e2fb068f0ce4acda3d91fe53f4f9b37fab9cffa49a2067ffdd939e95c862898"
V08_AUDIT_BYTES = 68220
V08_STOP_SHA256 = "99c937b1f8a2242609621b1210828b6ae1411e701cbe2074d655d90328904e4d"
V08_STOP_BYTES = 1997
V08_BINDINGS_SHA256 = "0c3e29a78d2d5eb14ffb573fdf1bc9baa91957488b2f95c7c0fe17412b550cdc"
V08_BINDINGS_BYTES = 4719
WDDM_SHA256 = "20ad334b87b3c6a36435f71382a906f6009e7427760d617d2d73a3baa380cc34"
WDDM_BYTES = 8151
V08_FIRST_MAP_SHA256 = "e065c482515e41f41e9bcd65b1b85e0bdda25f6ab9e3bd81d091d404f4043ea2"
V08_FIRST_MAP_BYTES = 53441
V08_AUDIT_STOP_MAP_SHA256 = "d1d9647c47743970cd5e9d8122fb2f4a5d25d2c07d19e37c4fbe0fcf25a35d3d"
V08_AUDIT_STOP_MAP_BYTES = 53442
V08_PRESEAL_STOP_SHA256 = "5defca6d7a23f1f767a0d03118594d34998107fdaed6e1db972daec0ed950385"
V08_PRESEAL_STOP_BYTES = 69728
V08_PRESEAL_CANDIDATE_SHA256 = "3fbb3f52d6f193b18abb93039e3eb8fb2606808005fddebdab2245b6603e724a"
V08_PRESEAL_CANDIDATE_BYTES = 54430
PASS_STATUSES = {
    "TRACK_A_COMPLETE_PREAUTHORIZATION",
    "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
    "TRACK_D_COMPLETE_PREAUTHORIZATION",
    "TRACK_E_SOURCE_TESTS_PASS_PREMAP_UNIT_TESTS",
    "PASS_SYNTHETIC_TESTS",
    "TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V08_PREMAP_SYNTHETIC_AUDITOR",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
}
CURRENT_TRACK_STATUS = {
    "Track B v05": "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
    "Track E v09 pre-map": "TRACK_E_SOURCE_TESTS_PASS_V09_PREMAP_SYNTHETIC_AUDITOR",
    "Authorization issuer v09": "PASS_SYNTHETIC_TESTS",
    "Contract tooling v09": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
}


def scientific_projection(contract: dict[str, Any]) -> dict[str, Any]:
    projection = {key: contract.get(key) for key in IMMUTABLE}
    design = contract.get("design_inputs", {})
    projection["design_inputs"] = {
        key: value for key, value in design.items()
        if not key.startswith("implementation_source_map_")
    }
    return projection


def require_scientific_invariance(candidate: dict[str, Any], baseline: dict[str, Any]) -> None:
    if scientific_projection(candidate) != scientific_projection(baseline):
        raise RuntimeError("frozen scientific fields differ from the sealed v06 baseline")


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def parse_tables(path: Path) -> list[tuple[list[str], list[list[str]]]]:
    result = []
    header = None
    rows: list[list[str]] = []

    def close() -> None:
        nonlocal header, rows
        if header is not None and rows:
            result.append((header, rows))
        header, rows = None, []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            close()
            continue
        cells = [part.strip().strip(chr(96) + " ") for part in line.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        if header is None:
            header = cells
        elif len(cells) == len(header):
            rows.append(cells)
    close()
    return result


def workspace_file(workspace: Path, rel: str) -> Path:
    if not rel or rel.startswith("/") or "\\" in rel or "\t" in rel or "\n" in rel or ".." in Path(rel).parts:
        raise RuntimeError(f"unsafe workspace-relative path: {rel!r}")
    path = (workspace / Path(rel)).resolve(strict=True)
    path.relative_to(workspace.resolve())
    return path


def source_rows(map_path: Path, workspace: Path) -> list[dict[str, Any]]:
    matches = [rows for head, rows in parse_tables(map_path)
               if [h.lower().replace("-", "") for h in head] == ["path", "bytes", "sha256", "role"]]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one source closure table, found {len(matches)}")
    result = []
    seen: set[str] = set()
    for rel, size_text, digest, role in matches[0]:
        path = workspace_file(workspace, rel)
        identity = unicodedata.normalize("NFC", str(path)).casefold()
        if identity in seen or not size_text.isdecimal() or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError(f"malformed or repeated source row: {rel}")
        size, actual = sha256_file(path)
        if size != int(size_text) or actual != digest:
            raise RuntimeError(f"source identity mismatch: {rel}")
        seen.add(identity)
        result.append({"path": rel, "bytes": size, "sha256": actual, "role": role})
    if not result:
        raise RuntimeError("source closure is empty")
    return result


def receipt_rows(map_path: Path, workspace: Path) -> list[dict[str, Any]]:
    matches = [rows for head, rows in parse_tables(map_path)
               if [h.lower().replace("-", "") for h in head] == ["track", "path", "bytes", "sha256", "status"]]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one source receipt table, found {len(matches)}")
    result = []
    seen_paths: set[str] = set()
    seen_tracks: set[str] = set()
    for track, rel, size_text, digest, status in matches[0]:
        if not size_text.isdecimal() or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError(f"malformed receipt row: {rel}")
        path = workspace_file(workspace, rel)
        path_key = unicodedata.normalize("NFC", str(path.resolve(strict=True))).casefold()
        if path_key in seen_paths or track in seen_tracks:
            raise RuntimeError(f"duplicate source receipt path or track: {track}: {rel}")
        size, actual = sha256_file(path)
        if size != int(size_text) or actual != digest:
            raise RuntimeError(f"receipt identity mismatch: {rel}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        actual_status = str(payload.get("status", ""))
        expected_current = CURRENT_TRACK_STATUS.get(track)
        status_allowed = status == expected_current if expected_current is not None else status in PASS_STATUSES
        if actual_status != status or not status_allowed:
            raise RuntimeError(f"receipt status mismatch or failure: {rel}")
        result.append({"track": track, "path": rel, "bytes": size, "sha256": actual, "status": status})
        seen_paths.add(path_key)
        seen_tracks.add(track)
    if not result:
        raise RuntimeError("source map binds no source validation receipts")
    return result


def grouped(rows: list[dict[str, Any]], predicate: Any, label: str) -> dict[str, Any]:
    selected = [row for row in rows if predicate(row["path"])]
    if not selected:
        raise RuntimeError(f"source closure is missing {label}")
    return {"files": selected}


def canonical_receipt_source_path(value: str) -> str:
    if value.startswith("experiments/"):
        return value
    return f"{PROJECT_REL}/{value}"


def receipt_bindings(payload: dict[str, Any], track: str) -> list[dict[str, Any]]:
    if track.startswith("Track B"):
        value = payload.get("bound_sources")
    elif track.startswith("Track C") or track.startswith("Track D") or track.startswith("Authorization issuer"):
        value = payload.get("source_files")
    elif track.startswith("Track E v08") or track.startswith("Track E v09"):
        value = payload.get("sources")
    elif track.startswith("Contract tooling"):
        value = payload.get("source_bindings")
    else:
        return []
    if isinstance(value, dict):
        value = [{"path": key, **item} for key, item in value.items()]
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"receipt has no source identity bindings: {track}")
    return value


def verify_receipt_source_closure(receipts: list[dict[str, Any]], sources: list[dict[str, Any]], workspace: Path) -> None:
    source_by_path = {row["path"]: row for row in sources}
    for receipt in receipts:
        path = workspace_file(workspace, receipt["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        bound: set[str] = set()
        for binding in receipt_bindings(payload, receipt["track"]):
            rel = canonical_receipt_source_path(str(binding.get("path", "")))
            source = source_by_path.get(rel)
            if source is None:
                raise RuntimeError(f"receipt source is not in source closure: {receipt['track']}: {rel}")
            if rel in bound:
                raise RuntimeError(f"receipt repeats a tested source: {receipt['track']}: {rel}")
            if binding.get("bytes") != source["bytes"] or binding.get("sha256") != source["sha256"]:
                raise RuntimeError(f"receipt tested source differs from source closure: {receipt['track']}: {rel}")
            bound.add(rel)
        track = receipt["track"]
        if track.startswith("Track B"):
            names = {"e4_runner_common_v05.py", "e4_runner_artifacts_v05.py", "e4_gpu_lease_v04.py",
                     "e4_runner_modes_v05.py", "e4_online_parity_v05.py", "test_e4_runner_v05.py"}
            expected = {rel for rel in source_by_path if any(rel.endswith("/" + name) for name in names)}
        elif track.startswith("Track C"):
            expected = {rel for rel in source_by_path if "/source/scripts/e4_fresh_scorer_v04/" in rel}
        elif track.startswith("Track D"):
            expected = {rel for rel in source_by_path if "/source/scripts/e4_independent_audit_v04/" in rel}
        elif track.startswith("Track E v08"):
            expected = {rel for rel in source_by_path if rel.endswith((
                "/audits/e4-0-track-e/audit_e4_0_track_e_v08.py",
                "/audits/e4-0-track-e/test_audit_e4_0_track_e_v08.py",
            ))}
        elif track.startswith("Track E v09"):
            expected = {rel for rel in source_by_path if rel.endswith((
                "/audits/e4-0-track-e/audit_e4_0_track_e_v09.py",
                "/audits/e4-0-track-e/test_audit_e4_0_track_e_v09.py",
            ))}
        elif track.startswith("Authorization issuer"):
            expected = {rel for rel in source_by_path if rel.endswith((
                "/source/scripts/issue_e4_stage_authorization_v09.py",
                "/source/tests/test_e4_stage_authorization_v09.py",
            ))}
        elif track.startswith("Contract tooling"):
            names = {"build_e4_0_source_map_v08.py", "finalize_e4_0_contract_v09.py",
                     "seal_e4_0_contract_v09.py", "test_e4_0_contract_v09.py"}
            expected = {rel for rel in source_by_path if any(rel.endswith("/" + name) for name in names)}
        else:
            continue
        if bound != expected:
            missing, extra = sorted(expected - bound), sorted(bound - expected)
            raise RuntimeError(f"receipt source closure is not exact for {track}: missing={missing}, extra={extra}")


def safe_output_path(path: Path, workspace: Path) -> None:
    root = workspace.resolve(strict=True)
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"refusing existing final contract path: {path}")
    try:
        relative = path.absolute().relative_to(workspace.absolute())
    except ValueError as exc:
        raise RuntimeError(f"final contract output escapes workspace: {path}") from exc
    cursor = workspace
    for part in relative.parts[:-1]:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", None)
        if cursor.is_symlink() or (callable(is_junction) and is_junction()):
            raise RuntimeError(f"final contract output traverses symlink or junction: {cursor}")
    parent = path.parent.resolve(strict=True)
    try:
        parent.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"final contract parent escapes workspace: {path.parent}") from exc
    cursor = root
    for part in path.parent.resolve().relative_to(root).parts:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", None)
        if cursor.is_symlink() or (callable(is_junction) and is_junction()):
            raise RuntimeError(f"final contract output traverses symlink or junction: {cursor}")


def build_final_contract(workspace: Path) -> dict[str, Any]:
    baseline_path = workspace / BASELINE_REL
    baseline_bytes, baseline_sha = sha256_file(baseline_path)
    if baseline_sha != BASELINE_SHA256:
        raise RuntimeError("immutable sealed v06 baseline hash mismatch")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06" or baseline.get("status") != "SEALED":
        raise RuntimeError("v06 baseline contract identity/status mismatch")
    prior_seal_path = workspace / V06_SEAL_REL
    prior_seal_bytes, prior_seal_sha = sha256_file(prior_seal_path)
    if prior_seal_bytes != 35340 or prior_seal_sha != V06_SEAL_SHA256:
        raise RuntimeError("sealed v06 predecessor manifest identity changed")
    prior_seal = json.loads(prior_seal_path.read_text(encoding="utf-8"))
    if prior_seal.get("seal_id") != "FAS_E4_0_CONTRACT_V06_SEAL" or prior_seal.get("root_sha256") != V06_ROOT_SHA256:
        raise RuntimeError("sealed v06 predecessor root/identity mismatch")
    map_path = workspace / MAP_REL
    map_bytes, map_sha = sha256_file(map_path)
    sources = source_rows(map_path, workspace)
    receipts = receipt_rows(map_path, workspace)
    verify_receipt_source_closure(receipts, sources, workspace)
    final = json.loads(json.dumps(baseline))
    v08_contract_path = workspace / f"{PROJECT_REL}/contracts/e4-0-contract-v08-final.json"
    v08_seal_path = workspace / f"{PROJECT_REL}/seals/e4-0-contract-v08-seal.json"
    v08_audit_path = workspace / f"{PROJECT_REL}/audits/e4-0-track-e/track-e-postseal-receipt-v08.json"
    v08_contract_bytes, v08_contract_sha = sha256_file(v08_contract_path)
    v08_seal_bytes, v08_seal_sha = sha256_file(v08_seal_path)
    v08_audit_bytes, v08_audit_sha = sha256_file(v08_audit_path)
    if (v08_contract_bytes != V08_CONTRACT_BYTES or v08_contract_sha != V08_CONTRACT_SHA256
            or v08_seal_bytes != V08_SEAL_BYTES or v08_seal_sha != V08_SEAL_SHA256
            or v08_audit_bytes != V08_AUDIT_BYTES or v08_audit_sha != V08_AUDIT_SHA256):
        raise RuntimeError("sealed v08 immediate predecessor identity changed")
    v08_seal = json.loads(v08_seal_path.read_text(encoding="utf-8"))
    v08_audit = json.loads(v08_audit_path.read_text(encoding="utf-8"))
    v08_contract = json.loads(v08_contract_path.read_text(encoding="utf-8"))
    if (v08_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V08"
            or v08_contract.get("status") != "SEALED"
            or v08_seal.get("seal_id") != "FAS_E4_0_CONTRACT_V08_SEAL"
            or v08_seal.get("root_sha256") != V08_ROOT_SHA256
            or v08_audit.get("pass") is not True
            or v08_audit.get("status") != "E4_0_TRACK_E_POSTSEAL_PASS_V08_SEAL_ROOT_AND_MEMBERS_RECOMPUTED"
            or v08_audit.get("final_seal", {}).get("root_sha256") != V08_ROOT_SHA256):
        raise RuntimeError("sealed v08 predecessor root/status/audit mismatch")
    final["contract_id"] = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V09"
    final["status"] = "SEALED"
    final["supersedes"] = {
        "contract": {
            "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V08",
            "path": f"{PROJECT_REL}/contracts/e4-0-contract-v08-final.json",
            "bytes": v08_contract_bytes,
            "sha256": v08_contract_sha,
        },
        "seal": {
            "seal_id": "FAS_E4_0_CONTRACT_V08_SEAL",
            "path": f"{PROJECT_REL}/seals/e4-0-contract-v08-seal.json",
            "manifest_bytes": v08_seal_bytes,
            "manifest_sha256": v08_seal_sha,
            "root_sha256": V08_ROOT_SHA256,
            "contract_member_artifact_id": "E4_0_CONTRACT_V08_FINAL",
        },
    }
    final["finalized_utc"] = datetime.now(timezone.utc).isoformat()
    design = final["design_inputs"]
    for key in tuple(design):
        if key.startswith(("implementation_source_map_v03_", "implementation_source_map_v04_", "implementation_source_map_v05_", "implementation_source_map_v06_", "implementation_source_map_v07_", "implementation_source_map_v08_")):
            design.pop(key, None)
    design["implementation_source_map_v08_path"] = MAP_REL
    design["implementation_source_map_v08_sha256"] = map_sha
    design["implementation_source_map_v08_bytes"] = map_bytes
    final.pop("implementation_sources_not_yet_bound", None)
    final.pop("draft_blockers_before_freeze", None)
    final["implementation_sources"] = {
        "source_map": {"path": MAP_REL, "bytes": map_bytes, "sha256": map_sha},
        "e4_population_generator": grouped(
            sources, lambda p: any(x in p for x in ("/source/e4-population-v02/",
            "/source/panel-generator-v04/", "/source/e4-support-plan-v11/")), "population generator"),
        "e4_online_feature_and_parity_runner": grouped(
            sources, lambda p: any(p.endswith("/" + name) for name in (
                "e4_online_parity_v05.py", "e4_runner_common_v05.py",
                "e4_runner_artifacts_v05.py", "e4_runner_modes_v05.py",
                "e4_gpu_lease_v04.py", "test_e4_runner_v05.py")),
            "online/parity runner"),
        "e4_fresh_scorer": grouped(
            sources, lambda p: "/source/scripts/e4_fresh_scorer_v04/" in p, "fresh scorer"),
        "e4_stage_authorization_issuer": grouped(
            sources, lambda p: "/source/scripts/issue_e4_stage_authorization_v09.py" in p
            or "/source/tests/test_e4_stage_authorization_v09.py" in p, "stage authorization issuer"),
        "e4_independent_auditor": grouped(
            sources, lambda p: "/source/scripts/e4_independent_audit_v04/" in p
            or p.endswith("/audits/e4-0-track-e/audit_e4_0_track_e_v09.py")
            or p.endswith("/audits/e4-0-track-e/test_audit_e4_0_track_e_v09.py"), "independent auditor"),
        "e4_contract_seal_and_source_map_tooling": grouped(
            sources, lambda p: any(p.endswith("/" + name) for name in (
                "finalize_e4_0_contract_v09.py", "seal_e4_0_contract_v09.py",
                "build_e4_0_source_map_v08.py", "test_e4_0_contract_v09.py")),
            "v09 contract/source-map/seal tooling"),
    }
    final["source_test_receipts"] = receipts
    final["finalization"] = {
        "immutable_baseline_contract_path": BASELINE_REL, "immutable_baseline_contract_bytes": baseline_bytes,
        "immutable_baseline_contract_sha256": baseline_sha, "source_map_path": MAP_REL,
        "source_map_bytes": map_bytes, "source_map_sha256": map_sha,
        "source_closure_entry_count": len(sources), "source_test_receipt_count": len(receipts),
        "execution_authorization_conferred": False,
    }
    require_scientific_invariance(final, baseline)
    if any(value is not False for value in final["authorization"].values()):
        raise RuntimeError("contract authorization must remain false")
    if any(value is not False for value in final["execution_identity"].values()):
        raise RuntimeError("execution identity must remain false")
    stop_rel = f"{PROJECT_REL}/audits/e4-0-auth-issuer-v08/online-parity-precontact-stop-v01.json"
    bindings_rel = f"{PROJECT_REL}/audits/e4-0-auth-issuer-v08/online-parity-bindings-v01.json"
    wddm_rel = f"{PROJECT_REL}/audits/e4-0-execution/wddm-gpu-lease-preflight-v02.json"
    stop = json.loads((workspace / stop_rel).read_text(encoding="utf-8"))
    stop_size, stop_sha = sha256_file(workspace / stop_rel)
    bindings_size, bindings_sha = sha256_file(workspace / bindings_rel)
    wddm_size, wddm_sha = sha256_file(workspace / wddm_rel)
    if (stop_size != V08_STOP_BYTES or stop_sha != V08_STOP_SHA256
            or bindings_size != V08_BINDINGS_BYTES or bindings_sha != V08_BINDINGS_SHA256
            or wddm_size != WDDM_BYTES or wddm_sha != WDDM_SHA256):
        raise RuntimeError("v08 stop or WDDM diagnostic identity changed")
    if (stop.get("status") != "E4_0_V08_AUTHORIZATION_STOP_POPULATION_AUDIT_SCHEMA_MISMATCH"
            or stop.get("stop_class") != "PRECONTACT_AUTHORIZATION_VERIFIER_SCHEMA_MISMATCH"
            or stop.get("authorization_output_written") is not False
            or stop.get("authorization_output_exists") is not False
            or stop.get("tokenizer_contact") is not False
            or stop.get("model_contact") is not False
            or stop.get("cuda_initialized") is not False
            or stop.get("gpu_lease_acquired") is not False
            or stop.get("feature_cache_created") is not False
            or stop.get("labels_opened") is not False):
        raise RuntimeError("v08 authorization stop is not the preserved no-contact stop")
    wddm = json.loads((workspace / wddm_rel).read_text(encoding="utf-8"))
    if (wddm.get("status") != "PNOM_SUPPORTED_TYPE_C_PROCESS_ACTIVE"
            or wddm.get("total_gpu_memory_claimed") is not False
            or wddm.get("gpu_lease_acquired") is not False
            or wddm.get("model_contact") is not False
            or wddm.get("tokenizer_contact") is not False
            or wddm.get("cuda_initialized_by_this_task") is not False
            or wddm.get("feature_cache_created") is not False
            or wddm.get("labels_opened") is not False):
        raise RuntimeError("WDDM diagnostic is not the read-only no-contact receipt")
    preseal_history = {
        "first_source_map": (f"{PROJECT_REL}/audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-first-build.md", V08_FIRST_MAP_BYTES, V08_FIRST_MAP_SHA256),
        "corrected_source_map_audit_stop": (f"{PROJECT_REL}/audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-predecessor-track-audit-stop.md", V08_AUDIT_STOP_MAP_BYTES, V08_AUDIT_STOP_MAP_SHA256),
        "preseal_stop_receipt": (f"{PROJECT_REL}/audits/e4-0-track-e/history/track-e-preseal-stop-v08-v01.json", V08_PRESEAL_STOP_BYTES, V08_PRESEAL_STOP_SHA256),
        "preseal_candidate_contract": (f"{PROJECT_REL}/audits/e4-0-track-e/history/e4-0-contract-v08-preseal-candidate-v01.json", V08_PRESEAL_CANDIDATE_BYTES, V08_PRESEAL_CANDIDATE_SHA256),
    }
    for name, (rel, expected_bytes, expected_sha) in preseal_history.items():
        actual_bytes, actual_sha = sha256_file(workspace / rel)
        if actual_bytes != expected_bytes or actual_sha != expected_sha:
            raise RuntimeError(f"preserved v08 preseal attempt changed: {name}")
        preseal_history[name] = {"path": rel, "bytes": actual_bytes, "sha256": actual_sha}
    preseal_stop = json.loads((workspace / preseal_history["preseal_stop_receipt"]["path"]).read_text(encoding="utf-8"))
    if preseal_stop.get("status") != "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V08":
        raise RuntimeError("preserved v08 preseal stop receipt has an unexpected status")
    preseal_history["preseal_stop_receipt"]["status"] = preseal_stop["status"]
    final["engineering_amendment"] = {
        "amendment_kind": "VERSIONED_AUTHORIZATION_VERIFIER_AND_GPU_LEASE_COMPATIBILITY_REPAIR",
        "changed_scientific_fields": [],
        "scientific_baseline": {
            "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06",
            "contract_sha256": baseline_sha,
            "seal_root_sha256": "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64",
            "contract_path": BASELINE_REL,
            "contract_bytes": baseline_bytes,
            "seal_id": "FAS_E4_0_CONTRACT_V06_SEAL",
            "seal_manifest_sha256": "799d1535a16ea6fbf2269206443addf96736ef8a70ca5ab3373cdd5e6a44605c",
            "seal_manifest_bytes": 35340,
        },
        "immediate_predecessor": {
            "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V08",
            "contract_sha256": v08_contract_sha,
            "contract_path": f"{PROJECT_REL}/contracts/e4-0-contract-v08-final.json",
            "contract_bytes": v08_contract_bytes,
            "seal_id": "FAS_E4_0_CONTRACT_V08_SEAL",
            "manifest_sha256": v08_seal_sha,
            "manifest_bytes": v08_seal_bytes,
            "root_sha256": V08_ROOT_SHA256,
            "postseal_audit": {
                "path": f"{PROJECT_REL}/audits/e4-0-track-e/track-e-postseal-receipt-v08.json",
                "bytes": v08_audit_bytes, "sha256": v08_audit_sha,
                "status": v08_audit["status"], "root_sha256": V08_ROOT_SHA256,
            },
        },
        "failed_v08_authorization_attempt": {
            "stop_receipt": {"path": stop_rel, "bytes": stop_size, "sha256": stop_sha},
            "bindings": {"path": bindings_rel, "bytes": bindings_size, "sha256": bindings_sha},
            "diagnostic": stop["error"], "root_cause": stop["root_cause"],
            "status": stop["status"], "stop_class": stop["stop_class"], "stage": stop["stage"],
            "authorization_written": False, "tokenizer_contact": False, "model_contact": False,
            "cuda_initialized": False, "gpu_lease_acquired": False,
            "feature_cache_created": False, "labels_opened": False,
        },
        "historical_v07_lineage": {
            "immediate_predecessor": v08_contract["engineering_amendment"]["immediate_predecessor"],
            "failed_v07_authorization_attempt": v08_contract["engineering_amendment"]["failed_v07_authorization_attempt"],
        },
        "failed_v08_preseal_attempts": preseal_history,
        "failed_v06_parity_attempt": v08_contract["engineering_amendment"]["failed_v06_parity_attempt"],
        "inherited_population": v08_contract["engineering_amendment"]["inherited_population"],
        "inherited_parity_panel": v08_contract["engineering_amendment"]["inherited_parity_panel"],
        "wddm_gpu_lease_preflight": {
            "receipt": {"path": wddm_rel, "bytes": wddm_size, "sha256": wddm_sha, "status": wddm["status"]},
            "lease_semantics": {
                "enumeration_source": "nvidia-smi pmon -i 0 -c 1",
                "active_process_type": "C", "ignored_graphics_process_types": ["C+G", "G"],
                "unknown_type": "STOP_FAIL_CLOSED", "unidentifiable_type_c": "STOP_FAIL_CLOSED",
            },
            "total_gpu_memory_claimed": False, "gpu_lease_acquired": False,
            "model_contact": False, "tokenizer_contact": False, "cuda_initialized": False,
            "feature_cache_created": False, "labels_opened": False,
        },
        "scope": "The v09 update preserves the v06 scientific object and v07/v08 history. It fixes the v08 population-audit schema compatibility stop without changing sealed inputs. The WDDM lease update uses nvidia-smi pmon to classify verified Type-C compute processes as contention, ignores C+G/G entries for blocking while retaining their snapshot rows, and fails closed for unidentifiable Type-C or unknown-type processes. No E4 authorization is granted.",
    }
    return final


def main() -> int:
    workspace = Path(__file__).resolve().parents[4]
    output = workspace / OUTPUT_REL
    safe_output_path(output, workspace)
    contract = build_final_contract(workspace)
    encoded = (json.dumps(contract, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
    print(json.dumps({"status": "FINAL_CONTRACT_CREATED_UNAUTHORIZED", "path": OUTPUT_REL,
                      "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest(),
                      "source_receipts": len(contract["source_test_receipts"])}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
