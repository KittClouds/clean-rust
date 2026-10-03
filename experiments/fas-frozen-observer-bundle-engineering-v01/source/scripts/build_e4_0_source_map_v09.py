from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[4]
PROJECT = WORKSPACE / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
PRIOR_MAP = PROJECT / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v08.md"
OUTPUT = PROJECT / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v09.md"
RUN_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-v01")
V08_CONTRACT_SHA256 = "ec17befa2a65e0da589ee51792cde3c028e900aa919179b2c9c3365cc20c3e9b"
V08_CONTRACT_BYTES = 54286
V06_ROOT_SHA256 = "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64"
V07_MAP_SHA256 = "2b8c88eef79eaa5dff840d6a04844861f6a9a048068a1b514c71642f37e8a02d"
V07_MAP_BYTES = 53298
V08_ROOT_SHA256 = "e0093eacd70ce7cbf3b3a19045683ce5a7f4d4413748003e2d8e1446f131478d"
V08_SEAL_SHA256 = "238d1fdb46ba3d8a9de1ae90e41a9b3c455ba65661bc98e8fe6fa5d21e3d3156"
V08_SEAL_BYTES = 68666
V08_POSTSEAL_AUDIT_SHA256 = "8e2fb068f0ce4acda3d91fe53f4f9b37fab9cffa49a2067ffdd939e95c862898"
V08_AUTH_BINDINGS_SHA256 = "0c3e29a78d2d5eb14ffb573fdf1bc9baa91957488b2f95c7c0fe17412b550cdc"
V08_AUTH_BINDINGS_BYTES = 4719
V08_AUTH_STOP_SHA256 = "99c937b1f8a2242609621b1210828b6ae1411e701cbe2074d655d90328904e4d"
V08_AUTH_STOP_BYTES = 1997
WDDM_PREFLIGHT_SHA256 = "20ad334b87b3c6a36435f71382a906f6009e7427760d617d2d73a3baa380cc34"
WDDM_PREFLIGHT_BYTES = 8151
V08_FIRST_MAP_SHA256 = "e065c482515e41f41e9bcd65b1b85e0bdda25f6ab9e3bd81d091d404f4043ea2"
V08_FIRST_MAP_BYTES = 53441
V08_AUDIT_STOP_MAP_SHA256 = "d1d9647c47743970cd5e9d8122fb2f4a5d25d2c07d19e37c4fbe0fcf25a35d3d"
V08_AUDIT_STOP_MAP_BYTES = 53442
V08_PRESEAL_STOP_SHA256 = "5defca6d7a23f1f767a0d03118594d34998107fdaed6e1db972daec0ed950385"
V08_PRESEAL_STOP_BYTES = 69728
V08_PRESEAL_CANDIDATE_SHA256 = "3fbb3f52d6f193b18abb93039e3eb8fb2606808005fddebdab2245b6603e724a"
V08_PRESEAL_CANDIDATE_BYTES = 54430
V09_MAP_SHA256 = "c79306de009e82a5bdd5bd650e64744d115b870c8c4309dd5863a4d7b339b267"
V09_MAP_BYTES = 65000
V09_CONTRACT_SHA256 = "f973bbd7d5bebeb6a60b8586060c8c65424deefdfce64ddcfd45246ebdfabd44"
V09_CONTRACT_BYTES = 61414
V09_PRESEAL_SHA256 = "7ee376b87c41f727274f58f72f2db524806206ea216b3c18a8d82843e94d1bf8"
V09_PRESEAL_BYTES = 84023
POPULATION_ROOT_SHA256 = "27731b483b8242aaef15ca22b97796b7b305a79db9bbb235765e13dcd9d08967"
POPULATION_AUDIT_SHA256 = "7dd3eea3133dbed779071fd14e22df06ff5a0ddce994e4446cf4c6ef7b9cbe5a"
PANEL_ROOT_SHA256 = "6ef00306df0df20ada7b7a86b09567ae46e07f112f66d974d7885e8f1e5d4d95"
PANEL_AUTHORIZATION_SHA256 = "3e3f06bbe12db1bb9608cf56cb1699039d70b6ed79aed757b056e87cc0209d59"
PASS_STATUSES = {
    "TRACK_A_COMPLETE_PREAUTHORIZATION",
    "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
    "TRACK_D_COMPLETE_PREAUTHORIZATION",
    "TRACK_E_SOURCE_TESTS_PASS_PREMAP_UNIT_TESTS",
    "PASS_SYNTHETIC_TESTS",
    "TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V08_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V09_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V10_PREMAP_SYNTHETIC_AUDITOR",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
}
CURRENT_RECEIPT_STATUSES = {
    "Track B v05": "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
    "Track E v10 pre-map": "TRACK_E_SOURCE_TESTS_PASS_V10_PREMAP_SYNTHETIC_AUDITOR",
    "Authorization issuer v10": "PASS_SYNTHETIC_TESTS",
    "Contract tooling v10": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
}


def digest(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


def parse_tables(path: Path) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
    header: list[str] | None = None
    rows: list[list[str]] = []

    def close() -> None:
        nonlocal header, rows
        if header is not None and rows:
            tables.append((header, rows))
        header, rows = None, []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not (line.startswith("|") and line.endswith("|")):
            close()
            continue
        cells = [cell.strip().strip("` ") for cell in line.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        if header is None:
            header = cells
        elif len(cells) == len(header):
            rows.append(cells)
        else:
            raise RuntimeError(f"malformed Markdown table row in {path}")
    close()
    return tables


def table(path: Path, wanted: list[str]) -> list[list[str]]:
    norm = lambda items: ["".join(x.lower().split()).replace("-", "") for x in items]
    found = [rows for header, rows in parse_tables(path) if norm(header) == norm(wanted)]
    if len(found) != 1:
        raise RuntimeError(f"expected exactly one table {wanted} in {path}; found {len(found)}")
    return found[0]


def resolve_bound(value: str) -> Path:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else WORKSPACE / candidate
    return path.resolve(strict=True)


def verify_row(path_text: str, expected_size: str, expected_sha: str) -> tuple[int, str]:
    path = resolve_bound(path_text)
    size, actual = digest(path)
    if not expected_size.isdecimal() or size != int(expected_size) or actual != expected_sha:
        raise RuntimeError(f"carried predecessor identity changed: {path_text}")
    return size, actual


def project_rel(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE.resolve()).as_posix()


def canonical_key(path: Path) -> str:
    return unicodedata.normalize("NFC", str(path.resolve(strict=True))).casefold()


def receipt_source_bindings(track: str, payload: dict) -> list[dict]:
    if track.startswith("Track B"):
        bindings = payload.get("bound_sources")
    elif track.startswith("Track C") or track.startswith("Track D") or track.startswith("Authorization issuer"):
        bindings = payload.get("source_files")
    elif track.startswith("Track E v08") or track.startswith("Track E v09") or track.startswith("Track E v10"):
        bindings = payload.get("sources")
    elif track.startswith("Contract tooling"):
        bindings = payload.get("source_bindings")
    else:
        return []
    if isinstance(bindings, dict):
        bindings = [{"path": key, **value} for key, value in bindings.items()]
    if not isinstance(bindings, list) or not bindings:
        raise RuntimeError(f"source-test receipt has no source bindings: {track}")
    return bindings


def verify_receipt_source_bindings(track: str, payload: dict, source_rows: list[tuple[str, Path, str]]) -> None:
    by_rel = {rel: (path, *digest(path)) for rel, path, _role in source_rows}
    seen: set[str] = set()
    for row in receipt_source_bindings(track, payload):
        rel = str(row.get("path", ""))
        if rel.startswith("experiments/"):
            canonical_rel = rel
        else:
            canonical_rel = f"experiments/fas-frozen-observer-bundle-engineering-v01/{rel}"
        if canonical_rel not in by_rel:
            raise RuntimeError(f"receipt source is absent from current source closure: {track}: {rel}")
        if canonical_rel in seen:
            raise RuntimeError(f"receipt repeats a tested source identity: {track}: {rel}")
        _path, actual_size, actual_sha = by_rel[canonical_rel]
        if row.get("bytes") != actual_size or row.get("sha256") != actual_sha:
            raise RuntimeError(f"receipt tested source differs from current source closure: {track}: {rel}")
        seen.add(canonical_rel)
    expected: set[str]
    if track.startswith("Track B"):
        names = {
            "e4_runner_common_v05.py", "e4_runner_artifacts_v05.py", "e4_gpu_lease_v04.py",
            "e4_runner_modes_v05.py", "e4_online_parity_v05.py", "test_e4_runner_v05.py",
        }
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    elif track.startswith("Track C"):
        expected = {rel for rel in by_rel if "/source/scripts/e4_fresh_scorer_v04/" in rel}
    elif track.startswith("Track D"):
        expected = {rel for rel in by_rel if "/source/scripts/e4_independent_audit_v04/" in rel}
    elif track.startswith("Track E v08"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v08.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v08.py",
        ))}
    elif track.startswith("Track E v09"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v09.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v09.py",
        ))}
    elif track.startswith("Track E v10"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v10.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v10.py",
        ))}
    elif track.startswith("Authorization issuer"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/source/scripts/issue_e4_stage_authorization_v10.py",
            "/source/tests/test_e4_stage_authorization_v10.py",
        ))}
    elif track.startswith("Contract tooling"):
        names = {"build_e4_0_source_map_v09.py", "finalize_e4_0_contract_v10.py",
                 "seal_e4_0_contract_v10.py", "test_e4_0_contract_v10.py"}
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    else:
        return
    if seen != expected:
        missing, extra = sorted(expected - seen), sorted(seen - expected)
        raise RuntimeError(f"receipt source closure is not exact for {track}: missing={missing}, extra={extra}")


def validate_v08_authorization_stop(payload: dict) -> None:
    """Validate the exact preserved diagnostic and its no-contact disposition."""
    if (payload.get("status") != "E4_0_V08_AUTHORIZATION_STOP_POPULATION_AUDIT_SCHEMA_MISMATCH"
            or payload.get("stop_class") != "PRECONTACT_AUTHORIZATION_VERIFIER_SCHEMA_MISMATCH"
            or payload.get("error") != "AuthorizationError: preserved population audit receipt is not the exact truth-closed pass"
            or payload.get("model_contact") is not False
            or payload.get("tokenizer_contact") is not False
            or payload.get("cuda_initialized") is not False
            or payload.get("gpu_lease_acquired") is not False
            or payload.get("feature_cache_created") is not False
            or payload.get("labels_opened") is not False
            or payload.get("authorization_output_written") is not False
            or payload.get("authorization_output_exists") is not False):
        raise RuntimeError("preserved v08 authorization attempt is not the exact no-contact preflight stop")


def collect_sources() -> list[tuple[str, Path, str]]:
    baseline_path = PROJECT / "contracts" / "e4-0-contract-v09-final.json"
    baseline_size, baseline_sha = digest(baseline_path)
    if baseline_size != V09_CONTRACT_BYTES or baseline_sha != V09_CONTRACT_SHA256:
        raise RuntimeError("preserved v09 preseal candidate identity changed")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    prior_map_size, prior_map_sha = digest(PRIOR_MAP)
    map_design = baseline.get("design_inputs", {})
    if (prior_map_sha != V09_MAP_SHA256 or prior_map_size != V09_MAP_BYTES
            or map_design.get("implementation_source_map_v08_sha256") != prior_map_sha
            or map_design.get("implementation_source_map_v08_bytes") != prior_map_size):
        raise RuntimeError("prior v08 source-map identity does not match the preserved v09 candidate")

    rows: dict[str, tuple[Path, str]] = {}
    for old_path, old_size, old_sha, role in table(PRIOR_MAP, ["Path", "Bytes", "SHA-256", "Role"]):
        verify_row(old_path, old_size, old_sha)
        if Path(old_path).is_absolute():
            continue
        rows[old_path] = (resolve_bound(old_path), "Preserved v08 predecessor source: " + role)

    directory_roles = {
        PROJECT / "source" / "scripts" / "e4_independent_audit_v04": "Track D v04 independent stage/replay auditor and tests",
        PROJECT / "source" / "scripts" / "e4_fresh_scorer_v04": "Track C v04 frozen fresh qualification scorer and tests",
    }
    for root, role in directory_roles.items():
        if not root.is_dir():
            raise RuntimeError(f"required inherited source directory missing: {root}")
        for path in root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".md", ".toml", ".lock", ".rs"}:
                rows[project_rel(path)] = (path, role)

    explicit_roles = {
        "source/scripts/e4_online_parity_v05.py": "Track B v05 parity/feature runner entrypoint",
        "source/scripts/e4_runner_common_v05.py": "Track B v05 stage identity and validation",
        "source/scripts/e4_runner_artifacts_v05.py": "Track B v05 artifact custody and sealing",
        "source/scripts/e4_runner_modes_v05.py": "Track B v05 parity and feature modes",
        "source/scripts/e4_gpu_lease_v04.py": "Track B v04 WDDM-aware Type-C CUDA lease/resource telemetry",
        "source/tests/test_e4_runner_v05.py": "Track B v05 synthetic-only runtime and WDDM lease tests",
        "source/scripts/issue_e4_stage_authorization_v10.py": "Track E v10 staged authorization issuer",
        "source/tests/test_e4_stage_authorization_v10.py": "Track E v10 authorization issuer tests",
        "source/scripts/build_e4_0_source_map_v09.py": "v10 implementation source-map builder",
        "source/scripts/finalize_e4_0_contract_v10.py": "v10 contract finalizer with v06 scientific invariance checks",
        "source/scripts/seal_e4_0_contract_v10.py": "v10 workspace-rooted contract sealer",
        "source/scripts/test_e4_0_contract_v10.py": "v10 contract finalizer/sealer synthetic tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v10.py": "Independent Track E v10 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v10.py": "Independent Track E v10 audit tests",
        "audits/e4-0-track-b-v03/attempt-note-v01.json": "Track B v03 repair lineage and unbound-v02 provenance note",
    }
    for rel, role in explicit_roles.items():
        path = PROJECT / rel
        if not path.is_file():
            raise RuntimeError(f"required source closure member missing: {path}")
        rows[project_rel(path)] = (path, role)

    return [(rel, path, role) for rel, (path, role) in sorted(rows.items(), key=lambda item: item[0].encode("utf-8"))]


def collect_inputs() -> list[tuple[str, Path, str]]:
    rows: dict[str, tuple[Path, str]] = {}
    for old_path, old_size, old_sha, role in table(PRIOR_MAP, ["Input Path", "Bytes", "SHA-256", "Role"]):
        verify_row(old_path, old_size, old_sha)
        rows[old_path] = (resolve_bound(old_path), "Preserved v06 predecessor input: " + role)

    prior_map_size, prior_map_sha = digest(PRIOR_MAP)
    if prior_map_size != V09_MAP_BYTES or prior_map_sha != V09_MAP_SHA256:
        raise RuntimeError("preserved v09 source-map candidate identity changed")
    rows[project_rel(PRIOR_MAP)] = (PRIOR_MAP, "Preserved v09 source map from the failed preseal attempt.")

    inputs = {
        "audits/e4-0-execution/online-parity-precontact-stop-v01.json": "Preserved v06 pre-contact plumbing stop; no runtime/model/CUDA contact occurred.",
        "contracts/e4-0-contract-v06-final.json": "Immutable v06 scientific-baseline contract.",
        "seals/e4-0-contract-v06-seal.json": "Immutable v06 scientific-baseline seal manifest.",
        "contracts/e4-0-contract-v07-final.json": "Immutable v07 historical lineage contract.",
        "seals/e4-0-contract-v07-seal.json": "Immutable v07 historical lineage seal manifest.",
        "audits/e4-0-execution/population-independent-audit-receipt-v01.json": "Independent model-free audit of inherited E4 population; labels unopened.",
        "audits/e4-0-auth-issuer-v02/population-authorization-v01.json": "Historical v06 population-only scoped authorization.",
        "audits/e4-0-auth-issuer-v02/population-bindings-v01.json": "Historical v06 population source/identity bindings.",
        "audits/e4-0-auth-issuer-v02/parity-panel-authorization-v01.json": "Historical v06 tokenizer-only parity-panel authorization.",
        "audits/e4-0-auth-issuer-v02/parity-panel-bindings-v01.json": "Historical v06 tokenizer-only panel selection bindings.",
        "audits/e4-0-auth-issuer-v02/online-parity-authorization-v01.json": "Failed v06 parity authorization; preserved and never reused.",
        "audits/e4-0-auth-issuer-v02/online-parity-bindings-v01.json": "Failed v06 parity stage bindings; preserved as history.",
        "audits/e4-0-track-e/track-e-postseal-receipt-v07.json": "Independent passing audit of immutable v07 contract/seal.",
        "audits/e4-0-auth-issuer-v07/online-parity-precontact-stop-v01.json": "Preserved v07 precontact issuer stop; model/runtime contact did not occur.",
        "audits/e4-0-auth-issuer-v07/online-parity-bindings-v01.json": "Preserved exact attempted v07 authorization bindings.",
        "audits/e4-0-track-e/e4-0-contract-audit-bridge-v02.json": "Preserved v07 audit bridge; not used to authorize execution.",
        "contracts/e4-0-contract-v08-final.json": "Immutable last-sealed v08 predecessor contract.",
        "seals/e4-0-contract-v08-seal.json": "Immutable last-sealed v08 predecessor seal manifest.",
        "audits/e4-0-track-e/track-e-postseal-receipt-v08.json": "Independent passing audit of immutable v08 contract/seal.",
        "audits/e4-0-auth-issuer-v08/online-parity-precontact-stop-v01.json": "Preserved v08 issuer stop; no authorization or model/runtime contact occurred.",
        "audits/e4-0-auth-issuer-v08/online-parity-bindings-v01.json": "Preserved exact attempted v08 authorization bindings.",
        "audits/e4-0-execution/wddm-gpu-lease-preflight-v02.json": "Read-only WDDM pmon process-type snapshot motivating Type-C-only contention classification; no lease/model/runtime contact.",
        "audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-first-build.md": "Preserved first v08 source-map attempt; not authoritative.",
        "audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-predecessor-track-audit-stop.md": "Preserved corrected-map attempt associated with the failed independent audit; not authoritative.",
        "audits/e4-0-track-e/history/track-e-preseal-stop-v08-v01.json": "Preserved v08 preseal stop receipt; not authoritative.",
        "audits/e4-0-track-e/history/e4-0-contract-v08-preseal-candidate-v01.json": "Preserved nonauthoritative v08 preseal contract candidate.",
        "contracts/e4-0-contract-v09-final.json": "Preserved v09 contract candidate stopped at independent preseal; no seal exists.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v09.json": "Immutable v09 failed-preseal receipt; not authorization or a seal.",
    }
    for rel, role in inputs.items():
        path = PROJECT / rel
        if not path.is_file():
            raise RuntimeError(f"required historical execution input missing: {path}")
        rows[project_rel(path)] = (path, role)

    v09_contract_path = PROJECT / "contracts/e4-0-contract-v09-final.json"
    v09_stop_path = PROJECT / "audits/e4-0-track-e/track-e-preseal-receipt-v09.json"
    v09_contract_size, v09_contract_sha = digest(v09_contract_path)
    v09_stop_size, v09_stop_sha = digest(v09_stop_path)
    v09_stop = json.loads(v09_stop_path.read_text(encoding="utf-8"))
    if (v09_contract_size != V09_CONTRACT_BYTES or v09_contract_sha != V09_CONTRACT_SHA256
            or v09_stop_size != V09_PRESEAL_BYTES or v09_stop_sha != V09_PRESEAL_SHA256
            or v09_stop.get("status") != "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V09"
            or v09_stop.get("pass") is not False or v09_stop.get("final_seal") is not None
            or v09_stop.get("population_truth_files_opened") is not False
            or v09_stop.get("template_or_joint_truth_opened") is not False):
        raise RuntimeError("preserved v09 failed-preseal attempt identity or no-contact disposition differs")
    for key, expected_status in (
            ("preserved_v07_authorization_stop", "PRECONTACT_STOP"),
            ("preserved_v08_authorization_stop", "E4_0_V08_AUTHORIZATION_STOP_POPULATION_AUDIT_SCHEMA_MISMATCH")):
        stop = v09_stop.get(key)
        if (not isinstance(stop, dict) or stop.get("status") != expected_status
                or any(stop.get(flag) is not False for flag in (
                    "authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                    "gpu_lease_acquired", "feature_cache_created", "labels_opened"))):
            raise RuntimeError(f"preserved v09 nested no-contact authorization stop differs: {key}")

    wddm_path = PROJECT / "audits/e4-0-execution/wddm-gpu-lease-preflight-v02.json"
    wddm_size, wddm_sha = digest(wddm_path)
    wddm = json.loads(wddm_path.read_text(encoding="utf-8"))
    if (wddm_size != WDDM_PREFLIGHT_BYTES or wddm_sha != WDDM_PREFLIGHT_SHA256
            or wddm.get("total_gpu_memory_claimed") is not False
            or wddm.get("gpu_lease_acquired") is not False
            or wddm.get("model_contact") is not False
            or wddm.get("tokenizer_contact") is not False
            or wddm.get("cuda_initialized_by_this_task") is not False
            or wddm.get("feature_cache_created") is not False
            or wddm.get("labels_opened") is not False):
        raise RuntimeError("WDDM preflight diagnostic identity or no-contact flags differ")

    historical = (
        ("audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-first-build.md", V08_FIRST_MAP_BYTES, V08_FIRST_MAP_SHA256),
        ("audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-predecessor-track-audit-stop.md", V08_AUDIT_STOP_MAP_BYTES, V08_AUDIT_STOP_MAP_SHA256),
        ("audits/e4-0-track-e/history/track-e-preseal-stop-v08-v01.json", V08_PRESEAL_STOP_BYTES, V08_PRESEAL_STOP_SHA256),
        ("audits/e4-0-track-e/history/e4-0-contract-v08-preseal-candidate-v01.json", V08_PRESEAL_CANDIDATE_BYTES, V08_PRESEAL_CANDIDATE_SHA256),
    )
    for rel, expected_bytes, expected_sha in historical:
        path = PROJECT / Path(rel)
        size, sha = digest(path)
        if size != expected_bytes or sha != expected_sha:
            raise RuntimeError(f"preserved v08 preseal-history identity changed: {rel}")
    preseal_stop = json.loads((PROJECT / "audits/e4-0-track-e/history/track-e-preseal-stop-v08-v01.json").read_text(encoding="utf-8"))
    if preseal_stop.get("status") != "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V08":
        raise RuntimeError("preserved v08 preseal stop status differs")

    v08_contract = PROJECT / "contracts" / "e4-0-contract-v08-final.json"
    v08_seal = PROJECT / "seals" / "e4-0-contract-v08-seal.json"
    v08_audit = PROJECT / "audits" / "e4-0-track-e" / "track-e-postseal-receipt-v08.json"
    contract_size, contract_sha = digest(v08_contract)
    seal_size, seal_sha = digest(v08_seal)
    audit_size, audit_sha = digest(v08_audit)
    if (contract_size != V08_CONTRACT_BYTES or contract_sha != V08_CONTRACT_SHA256
            or seal_size != V08_SEAL_BYTES or seal_sha != V08_SEAL_SHA256
            or audit_size != 68220 or audit_sha != V08_POSTSEAL_AUDIT_SHA256):
        raise RuntimeError("preserved v08 predecessor contract, seal, or audit identity changed")
    contract_payload = json.loads(v08_contract.read_text(encoding="utf-8"))
    seal_payload = json.loads(v08_seal.read_text(encoding="utf-8"))
    audit_payload = json.loads(v08_audit.read_text(encoding="utf-8"))
    if (contract_payload.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V08"
            or contract_payload.get("status") != "SEALED"
            or seal_payload.get("seal_id") != "FAS_E4_0_CONTRACT_V08_SEAL"
            or seal_payload.get("root_sha256") != V08_ROOT_SHA256
            or audit_payload.get("pass") is not True
            or "PASS" not in str(audit_payload.get("status", "")).upper()
            or audit_payload.get("final_seal", {}).get("root_sha256") != V08_ROOT_SHA256):
        raise RuntimeError("preserved v08 predecessor status or independent audit is invalid")
    bindings_path = PROJECT / "audits/e4-0-auth-issuer-v08/online-parity-bindings-v01.json"
    stop_path = PROJECT / "audits/e4-0-auth-issuer-v08/online-parity-precontact-stop-v01.json"
    bindings_size, bindings_sha = digest(bindings_path)
    stop_size, stop_sha = digest(stop_path)
    if (bindings_size != V08_AUTH_BINDINGS_BYTES or bindings_sha != V08_AUTH_BINDINGS_SHA256
            or stop_size != V08_AUTH_STOP_BYTES or stop_sha != V08_AUTH_STOP_SHA256):
        raise RuntimeError("preserved v08 authorization attempt identity changed")
    stop_payload = json.loads(stop_path.read_text(encoding="utf-8"))
    validate_v08_authorization_stop(stop_payload)

    population_audit = PROJECT / "audits" / "e4-0-execution" / "population-independent-audit-receipt-v01.json"
    audit_size, audit_sha = digest(population_audit)
    audit = json.loads(population_audit.read_text(encoding="utf-8"))
    if (audit_size != 858 or audit_sha != POPULATION_AUDIT_SHA256
            or audit.get("status") != "PASS_POPULATION_FRESHNESS_SUPPORT"
            or audit.get("population_root_sha256") != POPULATION_ROOT_SHA256
            or audit.get("all_checks_passed") is not True
            or audit.get("population_truth_files_opened") is not False
            or audit.get("primary_support", {}).get("heldout_or_joint_support_read") is not False):
        raise RuntimeError("inherited population audit is not a model-free truth-closed pass")

    runtime_inputs = (
        (RUN_ROOT / "stage-seal-v01.json", "Inherited v06 population stage seal; root is immutable.", "population stage seal"),
        (RUN_ROOT / "parity-panel" / "stage-seal-v01.json", "Inherited v06 tokenizer-only parity-panel seal; root is immutable.", "parity panel stage seal"),
        (RUN_ROOT / "parity-panel" / "selection-receipt-v01.json", "Inherited label-free tokenizer-only panel selection receipt.", "parity panel receipt"),
    )
    panel_auth_path = PROJECT / "audits" / "e4-0-auth-issuer-v02" / "parity-panel-authorization-v01.json"
    parity_auth_path = PROJECT / "audits" / "e4-0-auth-issuer-v02" / "online-parity-authorization-v01.json"
    panel_auth = json.loads(panel_auth_path.read_text(encoding="utf-8"))
    parity_auth = json.loads(parity_auth_path.read_text(encoding="utf-8"))
    audit_auth_size, audit_auth_sha = digest(population_audit)
    for auth in (panel_auth, parity_auth):
        entry = auth.get("artifacts", {}).get("population_audit")
        if not isinstance(entry, dict) or (
            Path(str(entry.get("path", ""))).resolve() != population_audit.resolve()
            or entry.get("sha256") != audit_auth_sha or entry.get("bytes") != audit_auth_size
        ):
            raise RuntimeError("inherited population audit differs from its preserved v06 authorization")
    auth_bindings = {
        "population stage seal": ((panel_auth, "population_seal"), (parity_auth, "population_seal")),
        "parity panel stage seal": ((parity_auth, "parity_panel_seal"),),
    }
    for path, role, label in runtime_inputs:
        if not path.is_file():
            raise RuntimeError(f"required inherited runtime artifact missing ({label}): {path}")
        size, sha = digest(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for auth, artifact_name in auth_bindings.get(label, ()):
            entry = auth.get("artifacts", {}).get(artifact_name)
            if not isinstance(entry, dict):
                raise RuntimeError(f"preserved v06 authorization omits the inherited artifact: {artifact_name}")
            bound_path = Path(str(entry.get("path", "")))
            if (not bound_path.is_absolute() or bound_path.resolve() != path.resolve()
                    or entry.get("sha256") != sha or entry.get("bytes") != size):
                raise RuntimeError(f"inherited artifact differs from its preserved v06 authorization: {label}")
        if label != "parity panel receipt" and payload.get("status") != "SEALED":
            raise RuntimeError(f"inherited artifact is not sealed ({label})")
        if label == "population stage seal" and (
            payload.get("stage") != "POPULATION_GENERATION"
            or payload.get("root_sha256") != POPULATION_ROOT_SHA256
            or payload.get("contract_seal_root_sha256") != V06_ROOT_SHA256
            or any(payload.get("exact_predecessor_roots", {}).get(key) != value for key, value in {
                "e0_v10_root_sha256": "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
                "e1_v04_root_sha256": "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
                "e2_v07_root_sha256": "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
                "e3_v02_bundle_root_sha256": "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1",
            }.items())
        ):
            raise RuntimeError("inherited population seal identity differs from frozen v06 roots")
        if label == "parity panel stage seal" and (
            payload.get("stage") != "PARITY_PANEL_MATERIALIZATION"
            or payload.get("root_sha256") != PANEL_ROOT_SHA256
            or payload.get("contract_seal_root_sha256") != V06_ROOT_SHA256
            or payload.get("exact_predecessor_roots", {}).get("e4_population_root_sha256") != POPULATION_ROOT_SHA256
            or payload.get("exact_predecessor_roots", {}).get("e4_population_audit_root_sha256") != POPULATION_AUDIT_SHA256
        ):
            raise RuntimeError("inherited parity-panel seal identity differs from frozen v06 roots")
        if label == "parity panel receipt" and (
            payload.get("status") != "PARITY_PANEL_SEALED"
            or payload.get("e4_contract_root_sha256") != V06_ROOT_SHA256
            or payload.get("authorization_sha256") != PANEL_AUTHORIZATION_SHA256
            or payload.get("labels_opened") is not False
            or payload.get("predictions_emitted") is not False
            or payload.get("model_contact_performed") is not False
            or payload.get("model_loaded") is not False
            or payload.get("cuda_initialized") is not False
            or payload.get("tokenizer_contact_performed") is not True
            or payload.get("tokenizer_loaded") is not True
        ):
            raise RuntimeError("inherited parity panel is not the exact label-free tokenizer-only v06 selection")
        rows[canonical_key(path)] = (path, role + f" SHA-256={sha}, bytes={size}")

    return [(rel, path, role) for rel, (path, role) in sorted(rows.items(), key=lambda item: item[0].encode("utf-8"))]


def collect_receipts() -> list[tuple[str, str, Path, str]]:
    prior = []
    for track, path_text, size_text, sha, status in table(PRIOR_MAP, ["Track", "Path", "Bytes", "SHA-256", "Status"]):
        verify_row(path_text, size_text, sha)
        prior.append((predecessor_track(track), path_text, resolve_bound(path_text), status))

    current = [
        ("Track E v10 pre-map", "audits/e4-0-track-e/track-e-source-tests-v18.json"),
        ("Authorization issuer v10", "audits/e4-0-auth-issuer-v10/source-tests-v01.json"),
        ("Contract tooling v10", "audits/e4-0-track-e/contract-tooling-source-tests-v09.json"),
    ]
    result = prior
    seen_paths: set[str] = set()
    seen_tracks: set[str] = set()
    for track, rel, path, status in prior:
        key = canonical_key(path)
        if key in seen_paths or track in seen_tracks:
            raise RuntimeError(f"duplicate predecessor receipt path or track: {track}: {rel}")
        if status not in PASS_STATUSES:
            raise RuntimeError(f"predecessor receipt status is not an exact accepted status: {track}: {status}")
        seen_paths.add(key)
        seen_tracks.add(track)
    for track, rel in current:
        path = PROJECT / rel
        if not path.is_file():
            raise RuntimeError(f"required passing source/test receipt missing for {track}: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        status = str(payload.get("status", ""))
        if status != CURRENT_RECEIPT_STATUSES.get(track):
            raise RuntimeError(f"source/test receipt has an unregistered status for {track}: {status}")
        key = canonical_key(path)
        if key in seen_paths or track in seen_tracks:
            raise RuntimeError(f"duplicate source/test receipt path or track: {track}: {rel}")
        seen_paths.add(key)
        seen_tracks.add(track)
        verify_receipt_source_bindings(track, payload, collect_sources())
        result.append((track, project_rel(path), path, status))
    return result


def predecessor_track(track: str) -> str:
    return track if track.startswith("Predecessor ") else "Predecessor " + track


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite immutable v09 source map: {OUTPUT}")
    source_rows = collect_sources()
    input_rows = collect_inputs()
    receipt_rows = collect_receipts()

    def source_line(rel: str, path: Path, role: str) -> str:
        size, sha = digest(path)
        return f"| `{rel}` | {size} | `{sha}` | {role} |"

    def receipt_line(track: str, rel: str, path: Path, status: str) -> str:
        size, sha = digest(path)
        return f"| {track} | `{rel}` | {size} | `{sha}` | `{status}` |"

    content = [
        "# E4-0 Implementation Source Map v09",
        "",
        "Status: v10 contract-tooling successor to the failed v09 preseal candidate. The v06 scientific baseline and v08 last-sealed contract remain unchanged. This map preserves v06-v09 lineage and binds the v05 runner/v04 WDDM-aware lease, v10 issuer, v10 contract tooling, and independent v10 auditor. It grants no model-contact or scoring authority.",
        "",
        "## Frozen semantic baseline",
        "",
        "- Immutable scientific baseline: `contracts/e4-0-contract-v06-final.json`; v10 supersedes the exact sealed v08 state and preserves exact science equality to v06. The v09 candidate is retained only as failed-preseal history.",
        "- Sealed v06 contract root: `7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64`; v06 contract SHA-256: `ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958`.",
        "- E0 v10, E1 v04, E2 v07, and E3 v02 roots and every population, parity, truth, resource, and simultaneous-scoring gate remain unchanged.",
        "- Inherited population root: `27731b483b8242aaef15ca22b97796b7b305a79db9bbb235765e13dcd9d08967`; independent population audit remains truth-closed.",
        "- Inherited tokenizer-only parity-panel root: `6ef00306df0df20ada7b7a86b09567ae46e07f112f66d974d7885e8f1e5d4d95`; the failed v06 online-parity attempt remains a pre-contact stop and is never reused.",
        "- v08 authorization stopped before authorization write or model/runtime contact because the issuer expected a top-level population-audit field; its exact contract, seal, postseal audit, stop, and bindings remain sealed lineage.",
        "- v09 stopped at independent preseal with no final seal or model/runtime contact; its exact map, contract candidate, and stop receipt are bound as history.",
        "- The independent Track E v10 auditor recomputes the v08 sealed lineage and v09 failed-preseal identity, then checks the v10 source closure independently.",
        "- The read-only WDDM pmon snapshot identified an active Type-C Python process and C+G desktop processes; lease v04 waits only on verified Type-C processes, retains C+G/G rows diagnostically, and fails closed on unidentifiable Type-C or unknown-type processes.",
        "",
        "## Bound frozen inputs",
        "",
        "Absolute paths are used only for inherited run-root receipts on D:. Workspace paths use canonical POSIX syntax.",
        "",
        "| Input Path | Bytes | SHA-256 | Role |",
        "| --- | ---: | --- | --- |",
    ]
    for rel, path, role in input_rows:
        size, sha = digest(path)
        content.append(f"| `{rel}` | {size} | `{sha}` | {role} |")
    content += [
        "",
        "## Bound source and build closure",
        "",
        "The closure includes inherited v06-v09 sources and receipts, Track B v05/v04 runtime units, v10 issuer and tooling, local imports, tests, contract tooling, and independent auditors. Bytecode, caches, and temporary output are excluded.",
        "",
        "| Path | Bytes | SHA-256 | Role |",
        "| --- | ---: | --- | --- |",
    ]
    for rel, path, role in source_rows:
        content.append(source_line(rel, path, role))
    content += [
        "",
        "## Source and preauthorization test receipts",
        "",
        "Predecessor receipts remain visible as history. Current Track E v10 auditor, authorization issuer v10, and contract tooling v10 receipts below must pass and bind the listed source versions.",
        "",
        "| Track | Path | Bytes | SHA-256 | Status |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for track, rel, path, status in receipt_rows:
        content.append(receipt_line(track, rel, path, status))
    content += [
        "",
        "## Boundary",
        "",
        "This source map only closes the v10 contract/source identity. It does not itself authorize the online parity, fresh-feature extraction, held-out-label opening, scoring, E4-A, or any later phase. Each E4-0 execution stage still requires its own v10-bound scoped authorization.",
        "",
    ]
    encoded = "\n".join(content).encode("utf-8")
    safe_output_path(OUTPUT)
    with OUTPUT.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
    print(json.dumps({"status": "SOURCE_MAP_V09_CREATED_UNAUTHORIZED", "path": str(OUTPUT),
                      "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest(),
                      "source_rows": len(source_rows), "input_rows": len(input_rows),
                      "receipt_rows": len(receipt_rows)}, sort_keys=True))
    return 0


def safe_output_path(path: Path) -> None:
    root = WORKSPACE.resolve(strict=True)
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"refusing existing source-map output path: {path}")
    try:
        relative = path.absolute().relative_to(WORKSPACE.absolute())
    except ValueError as exc:
        raise RuntimeError(f"source-map output path escapes workspace: {path}") from exc
    cursor = WORKSPACE
    for part in relative.parts[:-1]:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", None)
        if cursor.is_symlink() or (callable(is_junction) and is_junction()):
            raise RuntimeError(f"source-map output traverses symlink or junction: {cursor}")
    resolved_parent = path.parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"source-map output parent escapes workspace: {parent}") from exc
    cursor = root
    for part in resolved_parent.relative_to(root).parts:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", None)
        if cursor.is_symlink() or (callable(is_junction) and is_junction()):
            raise RuntimeError(f"source-map output traverses symlink or junction: {cursor}")


if __name__ == "__main__":
    raise SystemExit(main())
