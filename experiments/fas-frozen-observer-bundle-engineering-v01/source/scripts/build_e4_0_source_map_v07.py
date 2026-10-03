from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[4]
PROJECT = WORKSPACE / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
PRIOR_MAP = PROJECT / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v06.md"
OUTPUT = PROJECT / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v07.md"
RUN_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-v01")
V07_CONTRACT_SHA256 = "33b56e95cbf083036f436b5496c2db3c0c052bacfdce593869a6f4aa3125a2d7"
V07_CONTRACT_BYTES = 48881
V06_ROOT_SHA256 = "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64"
V06_MAP_SHA256 = "3adf09a7f75839c7442bdf10586b7ae0acbb87b378b39ad993e2b8e504a2ea70"
V07_ROOT_SHA256 = "ee7339c3ab04272354b4cae03294c794a6e823fdb1766ad44f71978dfee0c62c"
V07_SEAL_SHA256 = "22e2d05255a87334d27713d222fc4023fd1cac61dafc4264c5de434bbf4c71ef"
V07_SEAL_BYTES = 52723
V07_POSTSEAL_AUDIT_SHA256 = "b328770fbdf25b96b40bac33ccec67ca1673c331328e5413727392d586f857f2"
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
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
}
CURRENT_RECEIPT_STATUSES = {
    "Track B v04": "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
    "Track C v04": "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
    "Track D v04": "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
    "Track E v08 pre-map": "TRACK_E_SOURCE_TESTS_PASS_V08_PREMAP_SYNTHETIC_AUDITOR",
    "Authorization issuer v08": "PASS_SYNTHETIC_TESTS",
    "Contract tooling v08": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
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
    elif track.startswith("Track E v08"):
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
            "e4_runner_common_v04.py", "e4_runner_artifacts_v04.py", "e4_gpu_lease_v03.py",
            "e4_runner_modes_v04.py", "e4_online_parity_v04.py", "test_e4_runner_v04.py",
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
    elif track.startswith("Authorization issuer"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/source/scripts/issue_e4_stage_authorization_v08.py",
            "/source/tests/test_e4_stage_authorization_v08.py",
        ))}
    elif track.startswith("Contract tooling"):
        names = {"build_e4_0_source_map_v07.py", "finalize_e4_0_contract_v08.py",
                 "seal_e4_0_contract_v08.py", "test_e4_0_contract_v08.py"}
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    else:
        return
    if seen != expected:
        missing, extra = sorted(expected - seen), sorted(seen - expected)
        raise RuntimeError(f"receipt source closure is not exact for {track}: missing={missing}, extra={extra}")


def collect_sources() -> list[tuple[str, Path, str]]:
    baseline_path = PROJECT / "contracts" / "e4-0-contract-v07-final.json"
    baseline_size, baseline_sha = digest(baseline_path)
    if baseline_size != 48881 or baseline_sha != V07_CONTRACT_SHA256:
        raise RuntimeError("sealed v07 immediate predecessor identity changed")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    prior_map_size, prior_map_sha = digest(PRIOR_MAP)
    map_design = baseline.get("design_inputs", {})
    if (prior_map_sha != V06_MAP_SHA256
            or map_design.get("implementation_source_map_v06_sha256") != prior_map_sha
            or map_design.get("implementation_source_map_v06_bytes") != prior_map_size):
        raise RuntimeError("prior v06 source-map identity does not match the sealed v07 contract")

    rows: dict[str, tuple[Path, str]] = {}
    for old_path, old_size, old_sha, role in table(PRIOR_MAP, ["Path", "Bytes", "SHA-256", "Role"]):
        verify_row(old_path, old_size, old_sha)
        if Path(old_path).is_absolute():
            continue
        rows[old_path] = (resolve_bound(old_path), "Preserved v07 predecessor source: " + role)

    directory_roles = {
        PROJECT / "source" / "scripts" / "e4_independent_audit_v04": "Track D v04 independent stage/replay auditor and tests",
        PROJECT / "source" / "scripts" / "e4_fresh_scorer_v04": "Track C v04 frozen fresh qualification scorer and tests",
    }
    for root, role in directory_roles.items():
        if not root.is_dir():
            raise RuntimeError(f"required v08 source directory missing: {root}")
        for path in root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".md", ".toml", ".lock", ".rs"}:
                rows[project_rel(path)] = (path, role)

    explicit_roles = {
        "source/scripts/e4_online_parity_v04.py": "Track B v04 parity/feature runner entrypoint",
        "source/scripts/e4_runner_common_v04.py": "Track B v04 stage identity and validation",
        "source/scripts/e4_runner_artifacts_v04.py": "Track B v04 artifact custody and sealing",
        "source/scripts/e4_runner_modes_v04.py": "Track B v04 parity and feature modes",
        "source/scripts/e4_gpu_lease_v03.py": "Track B v03 process-scoped GPU lease/resource telemetry",
        "source/tests/test_e4_runner_v04.py": "Track B v04 synthetic-only runtime tests",
        "source/scripts/issue_e4_stage_authorization_v08.py": "Track E v08 staged authorization issuer",
        "source/tests/test_e4_stage_authorization_v08.py": "Track E v08 authorization issuer tests",
        "source/scripts/build_e4_0_source_map_v07.py": "v08 implementation source-map builder",
        "source/scripts/finalize_e4_0_contract_v08.py": "v08 contract finalizer with v06 scientific invariance checks",
        "source/scripts/seal_e4_0_contract_v08.py": "v08 workspace-rooted contract sealer",
        "source/scripts/test_e4_0_contract_v08.py": "v08 contract finalizer/sealer synthetic tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v08.py": "Independent Track E v08 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v08.py": "Independent Track E v08 audit tests",
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
    if prior_map_size != 38628 or prior_map_sha != V06_MAP_SHA256:
        raise RuntimeError("sealed v07 source-map predecessor identity changed")
    rows[project_rel(PRIOR_MAP)] = (PRIOR_MAP, "Exact implementation source map sealed by v07.")

    inputs = {
        "audits/e4-0-execution/online-parity-precontact-stop-v01.json": "Preserved v06 pre-contact plumbing stop; no runtime/model/CUDA contact occurred.",
        "contracts/e4-0-contract-v06-final.json": "Immutable v06 scientific-baseline contract.",
        "seals/e4-0-contract-v06-seal.json": "Immutable v06 scientific-baseline seal manifest.",
        "contracts/e4-0-contract-v07-final.json": "Immutable v07 immediate-predecessor contract.",
        "seals/e4-0-contract-v07-seal.json": "Immutable v07 immediate-predecessor seal manifest.",
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
    }
    for rel, role in inputs.items():
        path = PROJECT / rel
        if not path.is_file():
            raise RuntimeError(f"required historical execution input missing: {path}")
        rows[project_rel(path)] = (path, role)

    v07_contract = PROJECT / "contracts" / "e4-0-contract-v07-final.json"
    v07_seal = PROJECT / "seals" / "e4-0-contract-v07-seal.json"
    v07_audit = PROJECT / "audits" / "e4-0-track-e" / "track-e-postseal-receipt-v07.json"
    contract_size, contract_sha = digest(v07_contract)
    seal_size, seal_sha = digest(v07_seal)
    audit_size, audit_sha = digest(v07_audit)
    if (contract_size != V07_CONTRACT_BYTES or contract_sha != V07_CONTRACT_SHA256
            or seal_size != V07_SEAL_BYTES or seal_sha != V07_SEAL_SHA256
            or audit_sha != V07_POSTSEAL_AUDIT_SHA256):
        raise RuntimeError("preserved v07 predecessor contract, seal, or audit identity changed")
    contract_payload = json.loads(v07_contract.read_text(encoding="utf-8"))
    seal_payload = json.loads(v07_seal.read_text(encoding="utf-8"))
    audit_payload = json.loads(v07_audit.read_text(encoding="utf-8"))
    if (contract_payload.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V07"
            or contract_payload.get("status") != "SEALED"
            or seal_payload.get("seal_id") != "FAS_E4_0_CONTRACT_V07_SEAL"
            or seal_payload.get("root_sha256") != V07_ROOT_SHA256
            or audit_payload.get("pass") is not True
            or "PASS" not in str(audit_payload.get("status", "")).upper()
            or audit_payload.get("final_seal", {}).get("root_sha256") != V07_ROOT_SHA256):
        raise RuntimeError("preserved v07 predecessor status or independent audit is invalid")
    stop_payload = json.loads((PROJECT / "audits/e4-0-auth-issuer-v07/online-parity-precontact-stop-v01.json").read_text(encoding="utf-8"))
    if ("PRECONTACT" not in str(stop_payload.get("status", "")).upper()
            or stop_payload.get("model_contact") is not False
            or stop_payload.get("tokenizer_contact") is not False
            or stop_payload.get("cuda_initialized") is not False
            or stop_payload.get("gpu_lease_acquired") is not False
            or stop_payload.get("feature_cache_created") is not False
            or stop_payload.get("labels_opened") is not False
            or stop_payload.get("authorization_written") is not False):
        raise RuntimeError("preserved v07 authorization attempt is not a no-contact preflight stop")

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
        ("Track B v04", "audits/e4-0-track-b-v04/track-b-source-tests-v04.json"),
        ("Track C v04", "audits/e4-0-track-c-v04/track-c-source-tests-v04.json"),
        ("Track D v04", "audits/e4-0-track-d-v04/track-d-source-tests-v04.json"),
        ("Track E v08 pre-map", "audits/e4-0-track-e/track-e-source-tests-v16.json"),
        ("Authorization issuer v08", "audits/e4-0-auth-issuer-v08/source-tests-v01.json"),
        ("Contract tooling v08", "audits/e4-0-track-e/contract-tooling-source-tests-v07.json"),
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
        raise RuntimeError(f"refusing to overwrite immutable v07 source map: {OUTPUT}")
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
        "# E4-0 Implementation Source Map v07",
        "",
        "Status: v08 authorization-verifier compatibility successor to sealed E4-0 v07, preserving sealed v06 as the immutable scientific baseline. The scientific object and all E0-E3 predecessors remain exactly those in v06. This map preserves v06 and v07 source/input/receipt identities and binds the v08 runner, scorer, authorization, contract tooling, and independent audit successors. It grants no model-contact or scoring authority.",
        "",
        "## Frozen semantic baseline",
        "",
        "- Immutable scientific baseline: `contracts/e4-0-contract-v06-final.json`, reached through sealed v07; v08 directly supersedes the exact sealed v07 contract and preserves exact science equality to v06.",
        "- Sealed v06 contract root: `7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64`; v06 contract SHA-256: `ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958`.",
        "- E0 v10, E1 v04, E2 v07, and E3 v02 roots and every population, parity, truth, resource, and simultaneous-scoring gate remain unchanged.",
        "- Inherited population root: `27731b483b8242aaef15ca22b97796b7b305a79db9bbb235765e13dcd9d08967`; independent population audit remains truth-closed.",
        "- Inherited tokenizer-only parity-panel root: `6ef00306df0df20ada7b7a86b09567ae46e07f112f66d974d7885e8f1e5d4d95`; the failed v06 online-parity attempt remains a pre-contact stop and is never reused.",
        "- v07 authorization stopped before model/runtime contact because its predecessor verifier rejected additional sealed E1 identity keys; v08 validates required root/hash identities as a subset and preserves that stopped attempt as history.",
        "- Track B v04 inherits the validated stage-output-root lease behavior; its preflight failures occur before CUDA/model contact and it uses only the pinned v03 GPU lease implementation.",
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
        "The closure includes inherited v06/v07 sources and receipts, every current v08 runtime/source unit, local imports, tests, contract tooling, and independent auditors. Bytecode, caches, and temporary output are excluded.",
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
        "Predecessor receipts remain visible as history. Current v08 receipts below must be passing and bind the listed source versions.",
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
        "This source map only closes the v08 contract/source identity. It does not itself authorize the online parity, fresh-feature extraction, held-out-label opening, scoring, E4-A, or any later phase. Each E4-0 execution stage still requires its own v08-bound scoped authorization.",
        "",
    ]
    encoded = "\n".join(content).encode("utf-8")
    safe_output_path(OUTPUT)
    with OUTPUT.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
    print(json.dumps({"status": "SOURCE_MAP_V07_CREATED_UNAUTHORIZED", "path": str(OUTPUT),
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
