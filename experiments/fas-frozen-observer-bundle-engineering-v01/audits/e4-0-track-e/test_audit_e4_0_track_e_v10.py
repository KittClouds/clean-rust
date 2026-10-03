from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v10.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v10", SCRIPT)
assert SPEC and SPEC.loader
audit_v10 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_v10)

PROJECT = Path(__file__).resolve().parents[2]
V06_CONTRACT_BYTES = (PROJECT / "contracts/e4-0-contract-v06-final.json").read_bytes()
V06_SEAL_BYTES = (PROJECT / "seals/e4-0-contract-v06-seal.json").read_bytes()
V07_CONTRACT_BYTES = (PROJECT / "contracts/e4-0-contract-v07-final.json").read_bytes()
V07_SEAL_BYTES = (PROJECT / "seals/e4-0-contract-v07-seal.json").read_bytes()
V07_SOURCE_MAP_BYTES = (PROJECT / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v06.md").read_bytes()
V07_POSTSEAL_AUDIT_BYTES = (PROJECT / "audits/e4-0-track-e/track-e-postseal-receipt-v07.json").read_bytes()
V07_STOP_BYTES = (PROJECT / "audits/e4-0-auth-issuer-v07/online-parity-precontact-stop-v01.json").read_bytes()
V07_BINDINGS_BYTES = (PROJECT / "audits/e4-0-auth-issuer-v07/online-parity-bindings-v01.json").read_bytes()
V07_BRIDGE_BYTES = (PROJECT / "audits/e4-0-track-e/e4-0-contract-audit-bridge-v02.json").read_bytes()
V08_CONTRACT_BYTES = (PROJECT / "contracts/e4-0-contract-v08-final.json").read_bytes()
V08_SEAL_BYTES = (PROJECT / "seals/e4-0-contract-v08-seal.json").read_bytes()
V08_SOURCE_MAP_BYTES = (PROJECT / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v07.md").read_bytes()
V08_POSTSEAL_AUDIT_BYTES = (PROJECT / "audits/e4-0-track-e/track-e-postseal-receipt-v08.json").read_bytes()
V08_STOP_BYTES = (PROJECT / "audits/e4-0-auth-issuer-v08/online-parity-precontact-stop-v01.json").read_bytes()
V08_BINDINGS_BYTES = (PROJECT / "audits/e4-0-auth-issuer-v08/online-parity-bindings-v01.json").read_bytes()
SEAL_SCHEMA_BYTES = (PROJECT / "contracts/e4-0-artifact-seal-schema-v01.json").read_bytes()
WDDM_BYTES = (PROJECT / "audits/e4-0-execution/wddm-gpu-lease-preflight-v02.json").read_bytes()
V09_CONTRACT_BYTES = (PROJECT / "contracts/e4-0-contract-v09-final.json").read_bytes()
V09_SOURCE_MAP_BYTES = (PROJECT / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v08.md").read_bytes()
V09_PRESEAL_BYTES = (PROJECT / "audits/e4-0-track-e/track-e-preseal-receipt-v09.json").read_bytes()
V08_PRESEAL_HISTORY_BYTES = {
    name: (PROJECT / binding["path"].removeprefix(audit_v10.PROJECT_REL + "/")).read_bytes()
    for name, binding in audit_v10.V08_PRESEAL_ATTEMPTS.items()
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> bytes:
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return encoded


class V10AuditFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.project = root / "experiments/fas-frozen-observer-bundle-engineering-v01"
        self.v06_contract_path = self.project / "contracts/e4-0-contract-v06-final.json"
        self.v06_seal_path = self.project / "seals/e4-0-contract-v06-seal.json"
        self.v10_contract_path = self.project / "contracts/e4-0-contract-v10-final.json"
        self.v09_contract_path = self.project / "contracts/e4-0-contract-v09-final.json"
        self.v09_source_map_path = self.project / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v08.md"
        self.v09_preseal_path = self.project / "audits/e4-0-track-e/track-e-preseal-receipt-v09.json"
        self.v08_contract_path = self.project / "contracts/e4-0-contract-v08-final.json"
        self.v08_seal_path = self.project / "seals/e4-0-contract-v08-seal.json"
        self.v08_map_path = self.project / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v07.md"
        self.v08_audit_path = self.project / "audits/e4-0-track-e/track-e-postseal-receipt-v08.json"
        self.v08_stop_path = self.project / "audits/e4-0-auth-issuer-v08/online-parity-precontact-stop-v01.json"
        self.v08_bindings_path = self.project / "audits/e4-0-auth-issuer-v08/online-parity-bindings-v01.json"
        self.wddm_path = self.project / "audits/e4-0-execution/wddm-gpu-lease-preflight-v02.json"
        self.v08_preseal_paths = {name: self.root / binding["path"] for name, binding in audit_v10.V08_PRESEAL_ATTEMPTS.items()}
        self.v07_contract_path = self.project / "contracts/e4-0-contract-v07-final.json"
        self.v07_seal_path = self.project / "seals/e4-0-contract-v07-seal.json"
        self.v07_map_path = self.project / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v06.md"
        self.v07_audit_path = self.project / "audits/e4-0-track-e/track-e-postseal-receipt-v07.json"
        self.v07_stop_path = self.project / "audits/e4-0-auth-issuer-v07/online-parity-precontact-stop-v01.json"
        self.v07_bindings_path = self.project / "audits/e4-0-auth-issuer-v07/online-parity-bindings-v01.json"
        self.v07_bridge_path = self.project / "audits/e4-0-track-e/e4-0-contract-audit-bridge-v02.json"
        self.map_path = self.project / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v09.md"
        self.seal_path = self.project / "seals/e4-0-contract-v10-seal.json"
        self.schema_path = self.project / "contracts/e4-0-artifact-seal-schema-v01.json"
        self.preseal_path = self.project / "audits/e4-0-track-e/track-e-preseal-receipt-v10.json"
        self.source_paths = [
            self.project / "source/e4-population-v02/src/fixture.rs",
            self.project / "source/scripts/e4_online_parity_v05.py",
            self.project / "source/scripts/e4_runner_common_v05.py",
            self.project / "source/scripts/e4_runner_artifacts_v05.py",
            self.project / "source/scripts/e4_runner_modes_v05.py",
            self.project / "source/scripts/e4_gpu_lease_v04.py",
            self.project / "source/tests/test_e4_runner_v05.py",
            self.project / "source/scripts/e4_fresh_scorer_v04/fixture.py",
            self.project / "source/scripts/e4_independent_audit_v04/fixture.py",
            self.project / "source/scripts/issue_e4_stage_authorization_v10.py",
            self.project / "source/tests/test_e4_stage_authorization_v10.py",
            self.project / "source/scripts/finalize_e4_0_contract_v10.py",
            self.project / "source/scripts/seal_e4_0_contract_v10.py",
            self.project / "source/scripts/build_e4_0_source_map_v08.py",
            self.project / "source/scripts/test_e4_0_contract_v10.py",
            self.project / "audits/e4-0-track-e/audit_e4_0_track_e_v10.py",
            self.project / "audits/e4-0-track-e/test_audit_e4_0_track_e_v10.py",
        ]
        self.receipt_paths: dict[str, Path] = {}
        for index, (track, (registered_path, status)) in enumerate(audit_v10.REGISTERED_SOURCE_TEST_RECEIPTS.items()):
            path = self.root / registered_path
            write_json(path, {"status": status, "synthetic_fixture": index})
            self.receipt_paths[track] = path
        self.receipt_path = self.receipt_paths["Track E v10 pre-map"]
        self.truth_path = self.project / "population/terminal-labels.jsonl"
        self.input_audit_path = self.project / "audits/e4-0-execution/population-independent-audit-receipt-v01.json"
        self.input_auth_path = self.project / "audits/e4-0-auth-issuer-v02/parity-panel-authorization-v01.json"
        self.input_panel_receipt_path = self.project / "audits/e4-0-execution/parity-panel-selection-receipt-v01.json"
        self.external = root.parent / (root.name + "-external")
        self.population_seal_path = self.external / "population-stage-seal.json"
        self.panel_seal_path = self.external / "parity-panel-stage-seal.json"
        self.project.mkdir(parents=True, exist_ok=True)
        self.v06_contract_path.parent.mkdir(parents=True, exist_ok=True)
        self.v06_seal_path.parent.mkdir(parents=True, exist_ok=True)
        self.v06_contract_path.write_bytes(V06_CONTRACT_BYTES)
        self.v06_seal_path.write_bytes(V06_SEAL_BYTES)
        for path, data in (
            (self.v08_contract_path, V08_CONTRACT_BYTES),
            (self.v09_contract_path, V09_CONTRACT_BYTES),
            (self.v09_source_map_path, V09_SOURCE_MAP_BYTES),
            (self.v09_preseal_path, V09_PRESEAL_BYTES),
            (self.v08_seal_path, V08_SEAL_BYTES),
            (self.v08_map_path, V08_SOURCE_MAP_BYTES),
            (self.v08_audit_path, V08_POSTSEAL_AUDIT_BYTES),
            (self.v08_stop_path, V08_STOP_BYTES),
            (self.v08_bindings_path, V08_BINDINGS_BYTES),
            (self.wddm_path, WDDM_BYTES),
            *[(self.v08_preseal_paths[name], data) for name, data in V08_PRESEAL_HISTORY_BYTES.items()],
            (self.v07_contract_path, V07_CONTRACT_BYTES),
            (self.v07_seal_path, V07_SEAL_BYTES),
            (self.v07_map_path, V07_SOURCE_MAP_BYTES),
            (self.v07_audit_path, V07_POSTSEAL_AUDIT_BYTES),
            (self.v07_stop_path, V07_STOP_BYTES),
            (self.v07_bindings_path, V07_BINDINGS_BYTES),
            (self.v07_bridge_path, V07_BRIDGE_BYTES),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.schema_path.parent.mkdir(parents=True, exist_ok=True)
        self.schema_path.write_bytes(SEAL_SCHEMA_BYTES)
        for index, path in enumerate(self.source_paths):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"synthetic source {index}\n".encode("utf-8"))
        # These are nontruth predecessor receipts copied or synthesized for
        # metadata-only root verification; no E4 labels are present here.
        actual_audit = PROJECT / "audits/e4-0-execution/population-independent-audit-receipt-v01.json"
        actual_auth = PROJECT / "audits/e4-0-auth-issuer-v02/parity-panel-authorization-v01.json"
        self.input_audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.input_audit_path.write_bytes(actual_audit.read_bytes())
        self.input_auth_path.parent.mkdir(parents=True, exist_ok=True)
        self.input_auth_path.write_bytes(actual_auth.read_bytes())
        selection = {
            "status": "PARITY_PANEL_SEALED",
            "authorization_sha256": audit_v10.INHERITED_PARITY_PANEL["selection_authorization_sha256"],
            "e4_contract_root_sha256": audit_v10.INHERITED_CONTRACT_ROOT,
            "labels_opened": False,
            "predictions_emitted": False,
        }
        self.input_panel_receipt_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.input_panel_receipt_path, selection)
        self.external.mkdir(parents=True, exist_ok=True)
        write_json(self.population_seal_path, {"status": "SEALED", "root_sha256": audit_v10.INHERITED_POPULATION["population_root_sha256"]})
        write_json(self.panel_seal_path, {"status": "SEALED", "root_sha256": audit_v10.INHERITED_PARITY_PANEL["panel_root_sha256"]})
        # Deliberately do not create the truth payload. A valid audit must not
        # open or require terminal truth while checking contract/seal metadata.
        self.preseal_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.preseal_path, {"status": "E4_0_TRACK_E_PRESEAL_PASS_V10_CONTRACT_AND_SOURCE_MAP_CLOSED", "pass": True})
        self.map_path.parent.mkdir(parents=True, exist_ok=True)
        self.map_path.write_text(self.source_map_text(), encoding="utf-8", newline="\n")
        self.v06 = json.loads(V06_CONTRACT_BYTES)
        self.contract = self.make_contract()
        contract_bytes = write_json(self.v10_contract_path, self.contract)
        map_bytes = self.map_path.read_bytes()
        write_json(self.preseal_path, {
            "receipt_id": "FAS_E4_0_TRACK_E_V10_PRESEAL_AUDIT_V01",
            "status": "E4_0_TRACK_E_PRESEAL_PASS_V10_CONTRACT_AND_SOURCE_MAP_CLOSED",
            "pass": True,
            "contract": {"path": self.v10_contract_path.relative_to(self.root).as_posix(), "bytes": len(contract_bytes), "sha256": sha(contract_bytes)},
            "source_map": {"path": self.map_path.relative_to(self.root).as_posix(), "bytes": len(map_bytes), "sha256": sha(map_bytes)},
        })
        self.write_seal()

    def source_map_text(self) -> str:
        truth = self.truth_path.relative_to(self.root).as_posix()
        source_lines = []
        for path in self.source_paths:
            data = path.read_bytes()
            source_lines.append(f"| `{path.relative_to(self.root).as_posix()}` | {len(data)} | `{sha(data)}` | implementation source |")
        input_files = [
            (self.v06_contract_path, "Immutable v06 scientific baseline contract.", False),
            (self.v06_seal_path, "Immutable v06 scientific baseline seal.", False),
            (self.v07_contract_path, "Immediate sealed v07 predecessor contract.", False),
            (self.v07_seal_path, "Immediate sealed v07 predecessor manifest.", False),
            (self.v07_map_path, "Exact source map sealed by v07.", False),
            (self.v07_audit_path, "Independent passing v07 postseal audit.", False),
            (self.v07_stop_path, "Preserved v07 precontact authorization stop.", False),
            (self.v07_bindings_path, "Preserved v07 attempted authorization bindings.", False),
            (self.v07_bridge_path, "Preserved v07 postseal audit bridge history.", False),
            (self.v08_contract_path, "Immutable v08 immediate-predecessor contract.", False),
            (self.v08_seal_path, "Immutable v08 immediate-predecessor seal.", False),
            (self.v08_map_path, "Exact source map sealed by v08.", False),
            (self.v08_audit_path, "Independent passing v08 postseal audit.", False),
            (self.v08_stop_path, "Preserved v08 precontact authorization stop.", False),
            (self.v08_bindings_path, "Preserved v08 attempted authorization bindings.", False),
            (self.wddm_path, "Read-only WDDM GPU lease preflight snapshot.", False),
            (self.v09_contract_path, "Unsealed v09 candidate contract preserved after preseal stop.", False),
            (self.v09_source_map_path, "Unsealed v09 source map preserved after preseal stop.", False),
            (self.v09_preseal_path, "Exact v09 failed-preseal stop receipt.", False),
            *[(self.v08_preseal_paths[name], "Preserved failed v08 preseal history.", False) for name in audit_v10.V08_PRESEAL_ATTEMPTS],
            (self.population_seal_path, "Inherited v06 population stage seal; root is immutable.", True),
            (self.panel_seal_path, "Inherited v06 tokenizer-only parity-panel seal; root is immutable.", True),
            (self.input_audit_path, "Independent model-free audit of inherited E4 population; labels unopened.", False),
            (self.input_auth_path, "Historical v06 tokenizer-only parity-panel authorization.", False),
            (self.input_panel_receipt_path, "Inherited label-free tokenizer-only panel selection receipt.", False),
        ]
        input_lines = []
        for path, role, external in input_files:
            data = path.read_bytes()
            rel = str(path).replace(chr(92), "/") if external else path.relative_to(self.root).as_posix()
            input_lines.append(f"| `{rel}` | {len(data)} | `{sha(data)}` | {role} |")
        input_lines.append(f"| `{truth}` | 4096 | `{'a' * 64}` | terminal labels (sealed reference only) |")
        receipt_lines = []
        for track, (registered_path, status) in audit_v10.REGISTERED_SOURCE_TEST_RECEIPTS.items():
            path = self.receipt_paths[track]
            data = path.read_bytes()
            receipt_lines.append(f"| {track} | `{registered_path}` | {len(data)} | `{sha(data)}` | `{status}` |")
        return "\n".join((
            "# Synthetic v10 implementation source map", "",
            "| Input Path | Bytes | SHA-256 | Role |", "| --- | ---: | --- | --- |", *input_lines, "",
            "| Path | Bytes | SHA-256 | Role |", "| --- | ---: | --- | --- |", *source_lines, "",
            "| Track | Path | Bytes | SHA-256 | Status |", "| --- | --- | ---: | --- | --- |",
            *receipt_lines, "",
        ))

    def make_contract(self) -> dict:
        result = copy.deepcopy(self.v06)
        result["contract_id"] = audit_v10.V10_CONTRACT_ID
        result["status"] = "SEALED"
        result["supersedes"] = audit_v10.expected_supersedes()
        v09_amendment = json.loads(V09_CONTRACT_BYTES)["engineering_amendment"]
        amendment = {
            "amendment_kind": "VERSIONED_PRESEAL_SCHEMA_AND_LINEAGE_AUDIT_REPAIR",
            "changed_scientific_fields": [],
            "scientific_baseline": {
                "contract_id": audit_v10.V06_CONTRACT_ID,
                "contract_sha256": audit_v10.V06_CONTRACT["sha256"],
                "seal_root_sha256": audit_v10.INHERITED_CONTRACT_ROOT,
                "contract_path": audit_v10.V06_CONTRACT["path"],
                "contract_bytes": audit_v10.V06_CONTRACT["bytes"],
                "seal_id": audit_v10.V06_SEAL_ID,
                "seal_manifest_sha256": audit_v10.V06_SEAL["manifest_sha256"],
                "seal_manifest_bytes": audit_v10.V06_SEAL["manifest_bytes"],
            },
            "immediate_predecessor": {
                "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V09",
                "contract_path": audit_v10.V09_FAILED_PRESEAL_ATTEMPT["contract"]["path"],
                "contract_bytes": audit_v10.V09_FAILED_PRESEAL_ATTEMPT["contract"]["bytes"],
                "contract_sha256": audit_v10.V09_FAILED_PRESEAL_ATTEMPT["contract"]["sha256"],
                "source_map_path": audit_v10.V09_FAILED_PRESEAL_ATTEMPT["source_map"]["path"],
                "source_map_bytes": audit_v10.V09_FAILED_PRESEAL_ATTEMPT["source_map"]["bytes"],
                "source_map_sha256": audit_v10.V09_FAILED_PRESEAL_ATTEMPT["source_map"]["sha256"],
                "preseal_receipt_path": audit_v10.V09_FAILED_PRESEAL_ATTEMPT["preseal_receipt"]["path"],
                "preseal_receipt_bytes": audit_v10.V09_FAILED_PRESEAL_ATTEMPT["preseal_receipt"]["bytes"],
                "preseal_receipt_sha256": audit_v10.V09_FAILED_PRESEAL_ATTEMPT["preseal_receipt"]["sha256"],
                "preseal_status": audit_v10.V09_FAILED_PRESEAL_ATTEMPT["preseal_receipt"]["status"],
            },
            "last_sealed_predecessor": {
                "contract": {"path": audit_v10.V08_CONTRACT["path"], "bytes": audit_v10.V08_CONTRACT["bytes"], "sha256": audit_v10.V08_CONTRACT["sha256"], "contract_id": audit_v10.V08_CONTRACT_ID},
                "seal": {"path": audit_v10.V08_SEAL["path"], "bytes": audit_v10.V08_SEAL["manifest_bytes"], "sha256": audit_v10.V08_SEAL["manifest_sha256"], "seal_id": audit_v10.V08_SEAL_ID, "root_sha256": audit_v10.V08_SEAL["root_sha256"]},
                "postseal_audit": {"path": audit_v10.V08_POSTSEAL_AUDIT["path"], "bytes": audit_v10.V08_POSTSEAL_AUDIT["bytes"], "sha256": audit_v10.V08_POSTSEAL_AUDIT["sha256"], "status": audit_v10.V08_POSTSEAL_AUDIT["status"], "root_sha256": audit_v10.V08_POSTSEAL_AUDIT["root_sha256"]},
            },
            "failed_v09_preseal_attempt": {
                "source_map": copy.deepcopy(audit_v10.V09_FAILED_PRESEAL_ATTEMPT["source_map"]),
                "contract": copy.deepcopy(audit_v10.V09_FAILED_PRESEAL_ATTEMPT["contract"]),
                "preseal_receipt": copy.deepcopy(audit_v10.V09_FAILED_PRESEAL_ATTEMPT["preseal_receipt"]),
                "issues": list(audit_v10.V09_FAILED_PRESEAL_ATTEMPT["issues"]),
                **copy.deepcopy(audit_v10.V09_NO_CONTACT_FLAGS),
            },
            "historical_v07_lineage": copy.deepcopy(v09_amendment["historical_v07_lineage"]),
            "failed_v08_authorization_attempt": copy.deepcopy(v09_amendment["failed_v08_authorization_attempt"]),
            "failed_v08_preseal_attempts": copy.deepcopy(v09_amendment["failed_v08_preseal_attempts"]),
            "wddm_gpu_lease_preflight": copy.deepcopy(audit_v10.WDDM_GPU_LEASE_PREFLIGHT),
            "failed_v06_parity_attempt": copy.deepcopy(v09_amendment["failed_v06_parity_attempt"]),
            "inherited_population": copy.deepcopy(v09_amendment["inherited_population"]),
            "inherited_parity_panel": copy.deepcopy(v09_amendment["inherited_parity_panel"]),
            "scope": "The v10 update preserves the v06 scientific object, v08 last-sealed state, and v09 failed-preseal history. It corrects only the source-map/auditor receipt identity registry and contract lineage representation identified by the v09 independent preseal stop; the WDDM lease classification and all scientific fields remain unchanged. No E4 authorization is granted.",
        }
        result["engineering_amendment"] = amendment
        design = result["design_inputs"]
        for key in list(design):
            if key.startswith("implementation_source_map_"):
                del design[key]
        map_rel = self.map_path.relative_to(self.root).as_posix()
        map_bytes = self.map_path.read_bytes()
        design.update({
            "implementation_source_map_v09_path": map_rel,
            "implementation_source_map_v09_sha256": sha(map_bytes),
            "implementation_source_map_v09_bytes": len(map_bytes),
        })
        result["implementation_sources"]["source_map"] = {
            "path": map_rel, "bytes": len(map_bytes), "sha256": sha(map_bytes),
        }
        source_rows = audit_v10.source_rows(audit_v10.parse_markdown_tables(self.map_path))
        predicates = {
            "e4_population_generator": lambda p: any(token in p for token in ("/source/e4-population-v02/", "/source/panel-generator-v04/", "/source/e4-support-plan-v11/")),
            "e4_online_feature_and_parity_runner": lambda p: any(p.endswith("/" + rel) for rel in audit_v10.TRACK_B_INTEGRATION_PATHS),
            "e4_fresh_scorer": lambda p: "/source/scripts/e4_fresh_scorer_v04/" in p,
            "e4_stage_authorization_issuer": lambda p: any(p.endswith("/" + rel) for rel in audit_v10.TRACK_E_ISSUER_PATHS),
            "e4_independent_auditor": lambda p: "/source/scripts/e4_independent_audit_v04/" in p or p.endswith("/audits/e4-0-track-e/audit_e4_0_track_e_v10.py") or p.endswith("/audits/e4-0-track-e/test_audit_e4_0_track_e_v10.py"),
            "e4_contract_seal_and_source_map_tooling": lambda p: any(p.endswith("/" + name) for name in ("finalize_e4_0_contract_v10.py", "seal_e4_0_contract_v10.py", "build_e4_0_source_map_v09.py", "test_e4_0_contract_v10.py")),
        }
        result["implementation_sources"] = {"source_map": result["implementation_sources"]["source_map"]}
        for name, predicate in predicates.items():
            result["implementation_sources"][name] = {"files": [row for row in source_rows if predicate(row["path"])]}
        result["source_test_receipts"] = [
            {
                "track": track, "path": registered_path,
                "bytes": len(self.receipt_paths[track].read_bytes()),
                "sha256": sha(self.receipt_paths[track].read_bytes()), "status": status,
            }
            for track, (registered_path, status) in audit_v10.REGISTERED_SOURCE_TEST_RECEIPTS.items()
        ]
        result["finalization"] = {
            "immutable_baseline_contract_path": audit_v10.V06_CONTRACT["path"],
            "immutable_baseline_contract_bytes": audit_v10.V06_CONTRACT["bytes"],
            "immutable_baseline_contract_sha256": audit_v10.V06_CONTRACT["sha256"],
            "source_map_path": map_rel, "source_map_bytes": len(map_bytes), "source_map_sha256": sha(map_bytes),
            "source_closure_entry_count": len(source_rows), "source_test_receipt_count": len(audit_v10.REGISTERED_SOURCE_TEST_RECEIPTS),
            "execution_authorization_conferred": False,
        }
        return result

    def seal_entries(self) -> list[dict]:
        contract_data = self.v10_contract_path.read_bytes()
        map_data = self.map_path.read_bytes()
        preseal_data = self.preseal_path.read_bytes()
        entries = [
            {"artifact_id": "E4_0_CONTRACT_V06_SCIENTIFIC_BASELINE", "path": audit_v10.V06_CONTRACT["path"], "bytes": len(V06_CONTRACT_BYTES), "sha256": sha(V06_CONTRACT_BYTES)},
            {"artifact_id": "E4_0_CONTRACT_V06_BASELINE_SEAL", "path": audit_v10.V06_SEAL["path"], "bytes": len(V06_SEAL_BYTES), "sha256": sha(V06_SEAL_BYTES)},
            {"artifact_id": "E4_0_CONTRACT_V07_SUPERSEDED", "path": audit_v10.V07_CONTRACT["path"], "bytes": len(V07_CONTRACT_BYTES), "sha256": sha(V07_CONTRACT_BYTES)},
            {"artifact_id": "E4_0_CONTRACT_V07_SEAL_SUPERSEDED", "path": audit_v10.V07_SEAL["path"], "bytes": len(V07_SEAL_BYTES), "sha256": sha(V07_SEAL_BYTES)},
            {"artifact_id": "E4_0_CONTRACT_V08_SUPERSEDED", "path": audit_v10.V08_CONTRACT["path"], "bytes": len(V08_CONTRACT_BYTES), "sha256": sha(V08_CONTRACT_BYTES)},
            {"artifact_id": "E4_0_CONTRACT_V08_SEAL_SUPERSEDED", "path": audit_v10.V08_SEAL["path"], "bytes": len(V08_SEAL_BYTES), "sha256": sha(V08_SEAL_BYTES)},
            {"artifact_id": "E4_0_CONTRACT_V10_FINAL", "path": self.v10_contract_path.relative_to(self.root).as_posix(), "bytes": len(contract_data), "sha256": sha(contract_data)},
            {"artifact_id": "E4_0_SOURCE_MAP_V09", "path": self.map_path.relative_to(self.root).as_posix(), "bytes": len(map_data), "sha256": sha(map_data)},
            {"artifact_id": "E4_0_TRACK_E_PRESEAL_RECEIPT_V10", "path": self.preseal_path.relative_to(self.root).as_posix(), "bytes": len(preseal_data), "sha256": sha(preseal_data)},
            {"artifact_id": "workspace-input/" + self.truth_path.relative_to(self.root).as_posix(), "path": self.truth_path.relative_to(self.root).as_posix(), "bytes": 4096, "sha256": "a" * 64},
        ]
        for track, path in self.receipt_paths.items():
            data = path.read_bytes()
            artifact_id = "SOURCE_TEST_RECEIPT_" + "_".join(track.upper().split())
            entries.append({"artifact_id": artifact_id, "path": path.relative_to(self.root).as_posix(), "bytes": len(data), "sha256": sha(data)})
        for index, path in enumerate(self.source_paths):
            data = path.read_bytes()
            entries.append({"artifact_id": f"workspace-source/{path.relative_to(self.root).as_posix()}", "path": path.relative_to(self.root).as_posix(), "bytes": len(data), "sha256": sha(data)})
        for path in (
            self.input_audit_path, self.input_auth_path, self.input_panel_receipt_path,
            self.v07_map_path, self.v07_audit_path, self.v07_stop_path, self.v07_bindings_path, self.v07_bridge_path,
            self.v08_map_path, self.v08_audit_path, self.v08_stop_path, self.v08_bindings_path, self.wddm_path,
            self.v09_contract_path, self.v09_source_map_path, self.v09_preseal_path,
            *self.v08_preseal_paths.values(),
        ):
            data = path.read_bytes()
            entries.append({"artifact_id": f"workspace-input/{path.relative_to(self.root).as_posix()}", "path": path.relative_to(self.root).as_posix(), "bytes": len(data), "sha256": sha(data)})
        return sorted(entries, key=lambda item: item["artifact_id"].encode("utf-8"))

    def write_seal(self) -> None:
        v07_seal = json.loads(V07_SEAL_BYTES)
        entries = self.seal_entries()
        contract_data = self.v10_contract_path.read_bytes()
        seal = {
            "schema": "FAS_E4_0_ARTIFACT_SEAL_V01",
            "status": "SEALED",
            "seal_id": audit_v10.V10_SEAL_ID,
            "stage": "E4_0_CONTRACT",
            "path_root_kind": "WORKSPACE_ROOT",
            "created_utc": "2026-09-26T00:00:00+00:00",
            "contract_sha256": sha(contract_data),
            "contract_seal_root_sha256": None,
            "exact_predecessor_roots": v07_seal["exact_predecessor_roots"],
            "entries": entries,
            "entry_count": len(entries),
            "root_sha256": audit_v10.artifact_root(entries),
        }
        write_json(self.seal_path, seal)

    def run_audit(self, mode: str = "postseal") -> dict:
        return audit_v10.audit(
            self.root,
            self.v10_contract_path,
            self.map_path,
            self.seal_path if mode == "postseal" else None,
            self.schema_path if mode == "postseal" else None,
            self.preseal_path.relative_to(self.root).as_posix(),
            mode,
        )


class TrackEV10Tests(unittest.TestCase):
    def test_bypass_status_cannot_pass_by_substring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            tables = audit_v10.parse_markdown_tables(fixture.map_path)
            receipt_rows = next(rows for headers, rows in tables if headers == ["track", "path", "bytes", "sha-256", "status"])
            row = next(row for row in receipt_rows if row["track"] == "Predecessor Track B v05")
            row["status"] = "BYPASS_PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS"
            issues = audit_v10.validate_contract_source_closure(
                fixture.root, fixture.contract, fixture.map_path, tables,
            )
            self.assertTrue(any("track/path/status differs from its registered identity" in issue for issue in issues), issues)

    def test_same_status_track_substitution_is_rejected_by_exact_path_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            tables = audit_v10.parse_markdown_tables(fixture.map_path)
            receipt_rows = next(rows for headers, rows in tables if headers == ["track", "path", "bytes", "sha-256", "status"])
            row = next(row for row in receipt_rows if row["track"] == "Predecessor Track B v05")
            row["track"] = "Track C v04"  # Both tracks have the same registered PASS status.
            issues = audit_v10.validate_contract_source_closure(fixture.root, fixture.contract, fixture.map_path, tables)
            self.assertTrue(any("track/path/status differs from its registered identity" in issue for issue in issues), issues)
            self.assertTrue(any("repeats a registered source-test receipt track or alias" in issue for issue in issues), issues)

    def test_receipt_payload_status_is_checked_against_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            write_json(fixture.receipt_paths["Predecessor Track B v05"], {
                "status": "BYPASS_PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
                "synthetic_fixture": True,
            })
            issues = audit_v10.validate_contract_source_closure(
                fixture.root, fixture.contract, fixture.map_path,
                audit_v10.parse_markdown_tables(fixture.map_path),
            )
            self.assertTrue(any("payload status differs from its registered identity" in issue for issue in issues), issues)

    def test_c_d_predecessor_receipt_aliases_accept_canonical_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            tables = audit_v10.parse_markdown_tables(fixture.map_path)
            receipt_rows = next(rows for headers, rows in tables if headers == ["track", "path", "bytes", "sha-256", "status"])
            for row in receipt_rows:
                if row["track"] in ("Predecessor Track C v04", "Predecessor Track D v04"):
                    row["track"] = row["track"].replace("Predecessor ", "")
            issues = audit_v10.validate_contract_source_closure(fixture.root, fixture.contract, fixture.map_path, tables)
            self.assertFalse(any("unregistered source-test receipt track" in issue for issue in issues), issues)
            self.assertFalse(any("omits registered source-test receipt tracks" in issue for issue in issues), issues)

    def test_v09_failed_preseal_history_is_exact_and_no_contact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            receipt = json.loads(fixture.v09_preseal_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["issues"], audit_v10.V09_FAILED_PRESEAL_ATTEMPT["issues"])
            self.assertIsNone(receipt["final_seal"])
            self.assertFalse(receipt["population_truth_files_opened"])
            receipt["model_contact"] = True
            write_json(fixture.v09_preseal_path, receipt)
            issues = audit_v10.validate_predecessor_map_bindings(fixture.root, audit_v10.parse_markdown_tables(fixture.map_path))
            self.assertTrue(any("v09 preseal stop records unexpected contact" in issue for issue in issues), issues)

    def test_markdown_audit_is_hash_only_and_e1_audit_is_not_e4_population_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            structural = fixture.project / "plans" / "structural-audit.md"
            e1_audit = fixture.project / "audits" / "e1-independent-audit-v04.json"
            structural.parent.mkdir(parents=True, exist_ok=True)
            e1_audit.parent.mkdir(parents=True, exist_ok=True)
            structural.write_text("model-free structural notes\n", encoding="utf-8")
            write_json(e1_audit, {"status": "PASS_E1"})
            original = fixture.source_map_text()
            needle = "| Input Path | Bytes | SHA-256 | Role |\n| --- | ---: | --- | --- |\n"
            additions = []
            for path, role in (
                (structural, "descriptive structural audit markdown"),
                (e1_audit, "independent E1 population audit"),
            ):
                data = path.read_bytes()
                rel = path.relative_to(fixture.root).as_posix()
                additions.append(f"| `{rel}` | {len(data)} | `{sha(data)}` | {role} |")
            self.assertIn(needle, original)
            fixture.map_path.write_text(
                original.replace(needle, needle + "\n".join(additions) + "\n", 1),
                encoding="utf-8", newline="\n",
            )
            checked, issues = audit_v10.validate_input_bindings(
                fixture.root, audit_v10.parse_markdown_tables(fixture.map_path),
            )
            self.assertEqual(issues, [], issues)
            self.assertTrue(any(row["path"].endswith("structural-audit.md") for row in checked))

    def test_runner_group_binds_exact_track_b_integration_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            runner_files = fixture.contract["implementation_sources"]["e4_online_feature_and_parity_runner"]["files"]
            paths = {row["path"] for row in runner_files}
            prefix = fixture.project.relative_to(fixture.root).as_posix() + "/"
            expected = {prefix + rel for rel in audit_v10.TRACK_B_INTEGRATION_PATHS}
            self.assertEqual(paths, expected)
            result = fixture.run_audit()
            self.assertTrue(result["pass"], result["issues"])

    def test_issuer_source_group_binds_v10_entrypoint_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            issuer_files = fixture.contract["implementation_sources"]["e4_stage_authorization_issuer"]["files"]
            paths = {row["path"] for row in issuer_files}
            prefix = fixture.project.relative_to(fixture.root).as_posix() + "/"
            self.assertEqual(paths, {prefix + rel for rel in audit_v10.TRACK_E_ISSUER_PATHS})
            self.assertFalse(any("authorization_v08.py" in path for path in paths))
            result = fixture.run_audit()
            self.assertTrue(result["pass"], result["issues"])

    def test_synthetic_full_contract_and_seal_pass_without_truth_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            result = fixture.run_audit()
            self.assertTrue(result["pass"], result["issues"])
            self.assertFalse(fixture.truth_path.exists())
            self.assertEqual(result["final_seal"]["root_sha256"], json.loads(fixture.seal_path.read_text())["root_sha256"])
            self.assertEqual(result["status"], "E4_0_TRACK_E_POSTSEAL_PASS_V10_SEAL_ROOT_AND_MEMBERS_RECOMPUTED")

    def test_synthetic_preseal_receipt_status_matches_v10_sealer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            result = fixture.run_audit(mode="preseal")
            self.assertTrue(result["pass"], result["issues"])
            self.assertEqual(result["status"], "E4_0_TRACK_E_PRESEAL_PASS_V10_CONTRACT_AND_SOURCE_MAP_CLOSED")

    def test_science_field_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            fixture.contract["parity"]["batch_size"] = 9
            write_json(fixture.v10_contract_path, fixture.contract)
            fixture.write_seal()
            result = fixture.run_audit()
            self.assertTrue(any("science field differs" in issue for issue in result["issues"]))

    def test_supersedes_and_inherited_root_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            fixture.contract["supersedes"]["seal"]["root_sha256"] = "0" * 64
            fixture.contract["engineering_amendment"]["inherited_population"]["population_root_sha256"] = "0" * 64
            write_json(fixture.v10_contract_path, fixture.contract)
            fixture.write_seal()
            result = fixture.run_audit()
            self.assertTrue(any("supersedes metadata" in issue for issue in result["issues"]))
            self.assertTrue(any("amendment" in issue for issue in result["issues"]))

    def test_immediate_predecessor_and_failed_authorization_lineage_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            fixture.contract["engineering_amendment"]["immediate_predecessor"]["root_sha256"] = "0" * 64
            fixture.contract["engineering_amendment"]["failed_v08_authorization_attempt"]["model_contact"] = True
            write_json(fixture.v10_contract_path, fixture.contract)
            fixture.write_seal()
            result = fixture.run_audit()
            self.assertTrue(any("amendment" in issue for issue in result["issues"]))

    def test_v07_stop_or_bridge_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            write_json(fixture.v07_stop_path, {"status": "PRECONTACT_STOP", "model_contact": True})
            result = fixture.run_audit()
            self.assertTrue(any("stop_receipt bytes/hash differ" in issue for issue in result["issues"]))

        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            write_json(fixture.v07_bridge_path, {"pass": True, "issues": [], "final_seal": {"root_sha256": "0" * 64}})
            result = fixture.run_audit()
            self.assertTrue(any("audit_bridge bytes/hash differ" in issue for issue in result["issues"]))

    def test_v08_stop_contact_or_status_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            stop = json.loads(fixture.v08_stop_path.read_text(encoding="utf-8"))
            stop["model_contact"] = True
            write_json(fixture.v08_stop_path, stop)
            result = fixture.run_audit()
            self.assertTrue(any("v08 authorization stop" in issue for issue in result["issues"]), result["issues"])

    def test_v08_preseal_attempt_history_is_exactly_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            changed = next(iter(fixture.v08_preseal_paths.values()))
            changed.write_bytes(b"tampered historical attempt\n")
            result = fixture.run_audit()
            self.assertTrue(any("v08 preseal history" in issue for issue in result["issues"]), result["issues"])

    def test_wddm_receipt_identity_and_semantics_are_required(self) -> None:
        self.assertEqual(audit_v10.WDDM_GPU_LEASE_PREFLIGHT["receipt"]["status"], "PNOM_SUPPORTED_TYPE_C_PROCESS_ACTIVE")
        self.assertEqual(audit_v10.WDDM_GPU_LEASE_PREFLIGHT["lease_semantics"]["active_process_type"], "C")
        self.assertEqual(audit_v10.WDDM_GPU_LEASE_PREFLIGHT["lease_semantics"]["ignored_graphics_process_types"], ["C+G", "G"])
        self.assertFalse(audit_v10.WDDM_GPU_LEASE_PREFLIGHT["gpu_lease_acquired"])
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            write_json(fixture.wddm_path, {"status": "different"})
            result = fixture.run_audit()
            self.assertTrue(any("WDDM GPU lease preflight receipt" in issue for issue in result["issues"]), result["issues"])

    def test_source_map_hash_and_receipt_bytes_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            fixture.receipt_path.write_bytes(b"tampered\n")
            result = fixture.run_audit()
            self.assertTrue(any("source/receipt identity mismatch" in issue for issue in result["issues"]))

    def test_missing_or_extra_seal_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            seal = json.loads(fixture.seal_path.read_text(encoding="utf-8"))
            seal["entries"].pop()
            seal["entry_count"] -= 1
            seal["root_sha256"] = audit_v10.artifact_root(seal["entries"])
            write_json(fixture.seal_path, seal)
            result = fixture.run_audit()
            self.assertTrue(any("omits required member paths" in issue for issue in result["issues"]))

    def test_member_byte_tampering_is_rejected_even_if_root_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            fixture.source_paths[0].write_bytes(b"changed source\n")
            seal = json.loads(fixture.seal_path.read_text(encoding="utf-8"))
            seal["root_sha256"] = audit_v10.artifact_root(seal["entries"])
            write_json(fixture.seal_path, seal)
            result = fixture.run_audit()
            self.assertTrue(any("member bytes/hash mismatch" in issue for issue in result["issues"]))

    def test_seal_root_recomputation_detects_manifest_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V10AuditFixture(Path(directory))
            seal = json.loads(fixture.seal_path.read_text(encoding="utf-8"))
            seal["entries"][0]["artifact_id"] += "-tampered"
            write_json(fixture.seal_path, seal)
            result = fixture.run_audit()
            self.assertTrue(any("root mismatch" in issue for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
