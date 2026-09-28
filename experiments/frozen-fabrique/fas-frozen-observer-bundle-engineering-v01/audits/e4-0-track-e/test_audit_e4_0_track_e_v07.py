from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("audit_e4_0_track_e_v07.py")
SPEC = importlib.util.spec_from_file_location("audit_e4_0_track_e_v07", SCRIPT)
assert SPEC and SPEC.loader
audit_v07 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_v07)

PROJECT = Path(__file__).resolve().parents[2]
V06_CONTRACT_BYTES = (PROJECT / "contracts/e4-0-contract-v06-final.json").read_bytes()
V06_SEAL_BYTES = (PROJECT / "seals/e4-0-contract-v06-seal.json").read_bytes()
SEAL_SCHEMA_BYTES = (PROJECT / "contracts/e4-0-artifact-seal-schema-v01.json").read_bytes()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> bytes:
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return encoded


class V07AuditFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.project = root / "experiments/fas-frozen-observer-bundle-engineering-v01"
        self.v06_contract_path = self.project / "contracts/e4-0-contract-v06-final.json"
        self.v06_seal_path = self.project / "seals/e4-0-contract-v06-seal.json"
        self.v07_contract_path = self.project / "contracts/e4-0-contract-v07-final.json"
        self.map_path = self.project / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v06.md"
        self.seal_path = self.project / "seals/e4-0-contract-v07-seal.json"
        self.schema_path = self.project / "contracts/e4-0-artifact-seal-schema-v01.json"
        self.preseal_path = self.project / "audits/e4-0-track-e/track-e-preseal-receipt-v07.json"
        self.source_paths = [
            self.project / "source/e4-population-v02/src/fixture.rs",
            self.project / "source/scripts/e4_online_parity_v03.py",
            self.project / "source/scripts/e4_runner_common_v03.py",
            self.project / "source/scripts/e4_runner_artifacts_v03.py",
            self.project / "source/scripts/e4_runner_modes_v03.py",
            self.project / "source/scripts/e4_gpu_lease_v03.py",
            self.project / "source/tests/test_e4_runner_v03.py",
            self.project / "source/scripts/e4_fresh_scorer_v03/fixture.py",
            self.project / "source/scripts/issue_e4_stage_authorization_v07.py",
            self.project / "source/tests/test_e4_stage_authorization_v07.py",
            self.project / "source/scripts/finalize_e4_0_contract_v07.py",
            self.project / "audits/e4-0-track-e/audit_e4_0_track_e_v07.py",
            self.project / "audits/e4-0-track-e/test_audit_e4_0_track_e_v07.py",
        ]
        self.receipt_paths: dict[str, Path] = {}
        for index, (track, (registered_path, status)) in enumerate(audit_v07.REGISTERED_SOURCE_TEST_RECEIPTS.items()):
            path = self.root / registered_path
            write_json(path, {"status": status, "synthetic_fixture": index})
            self.receipt_paths[track] = path
        self.receipt_path = self.receipt_paths["Track E v07 pre-map"]
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
            "authorization_sha256": audit_v07.INHERITED_PARITY_PANEL["selection_authorization_sha256"],
            "e4_contract_root_sha256": audit_v07.INHERITED_CONTRACT_ROOT,
            "labels_opened": False,
            "predictions_emitted": False,
        }
        self.input_panel_receipt_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.input_panel_receipt_path, selection)
        self.external.mkdir(parents=True, exist_ok=True)
        write_json(self.population_seal_path, {"status": "SEALED", "root_sha256": audit_v07.INHERITED_POPULATION["population_root_sha256"]})
        write_json(self.panel_seal_path, {"status": "SEALED", "root_sha256": audit_v07.INHERITED_PARITY_PANEL["panel_root_sha256"]})
        # Deliberately do not create the truth payload. A valid audit must not
        # open or require terminal truth while checking contract/seal metadata.
        self.preseal_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.preseal_path, {"status": "E4_0_TRACK_E_PRESEAL_PASS_V07_CONTRACT_AND_SOURCE_MAP_CLOSED", "pass": True})
        self.map_path.parent.mkdir(parents=True, exist_ok=True)
        self.map_path.write_text(self.source_map_text(), encoding="utf-8", newline="\n")
        self.v06 = json.loads(V06_CONTRACT_BYTES)
        self.contract = self.make_contract()
        contract_bytes = write_json(self.v07_contract_path, self.contract)
        map_bytes = self.map_path.read_bytes()
        write_json(self.preseal_path, {
            "receipt_id": "FAS_E4_0_TRACK_E_V07_PRESEAL_AUDIT_V01",
            "status": "E4_0_TRACK_E_PRESEAL_PASS_V07_CONTRACT_AND_SOURCE_MAP_CLOSED",
            "pass": True,
            "contract": {"path": self.v07_contract_path.relative_to(self.root).as_posix(), "bytes": len(contract_bytes), "sha256": sha(contract_bytes)},
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
        for track, (registered_path, status) in audit_v07.REGISTERED_SOURCE_TEST_RECEIPTS.items():
            path = self.receipt_paths[track]
            data = path.read_bytes()
            receipt_lines.append(f"| {track} | `{registered_path}` | {len(data)} | `{sha(data)}` | `{status}` |")
        return "\n".join((
            "# Synthetic v07 implementation source map", "",
            "| Input Path | Bytes | SHA-256 | Role |", "| --- | ---: | --- | --- |", *input_lines, "",
            "| Path | Bytes | SHA-256 | Role |", "| --- | ---: | --- | --- |", *source_lines, "",
            "| Track | Path | Bytes | SHA-256 | Status |", "| --- | --- | ---: | --- | --- |",
            *receipt_lines, "",
        ))

    def make_contract(self) -> dict:
        result = copy.deepcopy(self.v06)
        result["contract_id"] = audit_v07.V07_CONTRACT_ID
        result["status"] = "SEALED"
        result["supersedes"] = audit_v07.expected_supersedes()
        amendment = {
            "amendment_kind": "VERSIONED_EXECUTION_PLUMBING_REPAIR",
            "baseline_contract_id": audit_v07.V06_CONTRACT_ID,
            "baseline_contract_path": audit_v07.V06_CONTRACT["path"],
            "baseline_contract_sha256": audit_v07.V06_CONTRACT["sha256"],
            "baseline_seal_root_sha256": audit_v07.INHERITED_CONTRACT_ROOT,
            "changed_scientific_fields": [],
            "inherited_population": copy.deepcopy(audit_v07.INHERITED_POPULATION),
            "inherited_parity_panel": copy.deepcopy(audit_v07.INHERITED_PARITY_PANEL),
            "failed_v06_parity_attempt": copy.deepcopy(audit_v07.V06_FAILED_PARITY_STOP),
        }
        result["engineering_amendment"] = amendment
        design = result["design_inputs"]
        for key in list(design):
            if key.startswith("implementation_source_map_"):
                del design[key]
        map_rel = self.map_path.relative_to(self.root).as_posix()
        map_bytes = self.map_path.read_bytes()
        design.update({
            "implementation_source_map_v06_path": map_rel,
            "implementation_source_map_v06_sha256": sha(map_bytes),
            "implementation_source_map_v06_bytes": len(map_bytes),
        })
        result["implementation_sources"]["source_map"] = {
            "path": map_rel, "bytes": len(map_bytes), "sha256": sha(map_bytes),
        }
        source_rows = audit_v07.source_rows(audit_v07.parse_markdown_tables(self.map_path))
        predicates = {
            "e4_population_generator": lambda p: any(token in p for token in ("/source/e4-population-v02/", "/source/panel-generator-v04/", "/source/e4-support-plan-v11/")),
            "e4_online_feature_and_parity_runner": lambda p: any(p.endswith("/" + rel) for rel in audit_v07.TRACK_B_INTEGRATION_PATHS),
            "e4_fresh_scorer": lambda p: "/source/scripts/e4_fresh_scorer_v03/" in p,
            "e4_stage_authorization_issuer": lambda p: any(p.endswith("/" + rel) for rel in audit_v07.TRACK_E_ISSUER_PATHS),
            "e4_independent_auditor": lambda p: p.endswith("/audits/e4-0-track-e/audit_e4_0_track_e_v07.py") or p.endswith("/audits/e4-0-track-e/test_audit_e4_0_track_e_v07.py"),
            "e4_contract_seal_and_source_map_tooling": lambda p: p.endswith("/finalize_e4_0_contract_v07.py"),
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
            for track, (registered_path, status) in audit_v07.REGISTERED_SOURCE_TEST_RECEIPTS.items()
        ]
        result["finalization"] = {
            "immutable_baseline_contract_path": audit_v07.V06_CONTRACT["path"],
            "immutable_baseline_contract_bytes": audit_v07.V06_CONTRACT["bytes"],
            "immutable_baseline_contract_sha256": audit_v07.V06_CONTRACT["sha256"],
            "source_map_path": map_rel, "source_map_bytes": len(map_bytes), "source_map_sha256": sha(map_bytes),
            "source_closure_entry_count": len(source_rows), "source_test_receipt_count": len(audit_v07.REGISTERED_SOURCE_TEST_RECEIPTS),
            "execution_authorization_conferred": False,
        }
        return result

    def seal_entries(self) -> list[dict]:
        contract_data = self.v07_contract_path.read_bytes()
        map_data = self.map_path.read_bytes()
        preseal_data = self.preseal_path.read_bytes()
        entries = [
            {"artifact_id": "E4_0_CONTRACT_V06_SUPERSEDED", "path": audit_v07.V06_CONTRACT["path"], "bytes": len(V06_CONTRACT_BYTES), "sha256": sha(V06_CONTRACT_BYTES)},
            {"artifact_id": "E4_0_CONTRACT_V06_SEAL_SUPERSEDED", "path": audit_v07.V06_SEAL["path"], "bytes": len(V06_SEAL_BYTES), "sha256": sha(V06_SEAL_BYTES)},
            {"artifact_id": "E4_0_CONTRACT_V07_FINAL", "path": self.v07_contract_path.relative_to(self.root).as_posix(), "bytes": len(contract_data), "sha256": sha(contract_data)},
            {"artifact_id": "E4_0_SOURCE_MAP_V06", "path": self.map_path.relative_to(self.root).as_posix(), "bytes": len(map_data), "sha256": sha(map_data)},
            {"artifact_id": "E4_0_TRACK_E_PRESEAL_RECEIPT_V07", "path": self.preseal_path.relative_to(self.root).as_posix(), "bytes": len(preseal_data), "sha256": sha(preseal_data)},
            {"artifact_id": "workspace-input/" + self.truth_path.relative_to(self.root).as_posix(), "path": self.truth_path.relative_to(self.root).as_posix(), "bytes": 4096, "sha256": "a" * 64},
        ]
        for track, path in self.receipt_paths.items():
            data = path.read_bytes()
            artifact_id = "SOURCE_TEST_RECEIPT_" + "_".join(track.upper().split())
            entries.append({"artifact_id": artifact_id, "path": path.relative_to(self.root).as_posix(), "bytes": len(data), "sha256": sha(data)})
        for index, path in enumerate(self.source_paths):
            data = path.read_bytes()
            entries.append({"artifact_id": f"workspace-source/{path.relative_to(self.root).as_posix()}", "path": path.relative_to(self.root).as_posix(), "bytes": len(data), "sha256": sha(data)})
        for path in (self.input_audit_path, self.input_auth_path, self.input_panel_receipt_path):
            data = path.read_bytes()
            entries.append({"artifact_id": f"workspace-input/{path.relative_to(self.root).as_posix()}", "path": path.relative_to(self.root).as_posix(), "bytes": len(data), "sha256": sha(data)})
        return sorted(entries, key=lambda item: item["artifact_id"].encode("utf-8"))

    def write_seal(self) -> None:
        v06_seal = json.loads(V06_SEAL_BYTES)
        entries = self.seal_entries()
        contract_data = self.v07_contract_path.read_bytes()
        seal = {
            "schema": "FAS_E4_0_ARTIFACT_SEAL_V01",
            "status": "SEALED",
            "seal_id": audit_v07.V07_SEAL_ID,
            "stage": "E4_0_CONTRACT",
            "path_root_kind": "WORKSPACE_ROOT",
            "created_utc": "2026-09-26T00:00:00+00:00",
            "contract_sha256": sha(contract_data),
            "contract_seal_root_sha256": None,
            "exact_predecessor_roots": v06_seal["exact_predecessor_roots"],
            "entries": entries,
            "entry_count": len(entries),
            "root_sha256": audit_v07.artifact_root(entries),
        }
        write_json(self.seal_path, seal)

    def run_audit(self, mode: str = "postseal") -> dict:
        return audit_v07.audit(
            self.root,
            self.v07_contract_path,
            self.map_path,
            self.seal_path if mode == "postseal" else None,
            self.schema_path if mode == "postseal" else None,
            self.preseal_path.relative_to(self.root).as_posix(),
            mode,
        )


class TrackEV07Tests(unittest.TestCase):
    def test_bypass_status_cannot_pass_by_substring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            tables = audit_v07.parse_markdown_tables(fixture.map_path)
            receipt_rows = next(rows for headers, rows in tables if headers == ["track", "path", "bytes", "sha-256", "status"])
            row = next(row for row in receipt_rows if row["track"] == "Track B v03")
            row["status"] = "BYPASS_PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS"
            issues = audit_v07.validate_contract_source_closure(
                fixture.root, fixture.contract, fixture.map_path, tables,
            )
            self.assertTrue(any("track/path/status differs from its registered identity" in issue for issue in issues), issues)

    def test_same_status_track_substitution_is_rejected_by_exact_path_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            tables = audit_v07.parse_markdown_tables(fixture.map_path)
            receipt_rows = next(rows for headers, rows in tables if headers == ["track", "path", "bytes", "sha-256", "status"])
            row = next(row for row in receipt_rows if row["track"] == "Track B v03")
            row["track"] = "Track C v03"  # Both tracks have the same registered PASS status.
            issues = audit_v07.validate_contract_source_closure(fixture.root, fixture.contract, fixture.map_path, tables)
            self.assertTrue(any("track/path/status differs from its registered identity" in issue for issue in issues), issues)
            self.assertTrue(any("repeats a registered source-test receipt track" in issue for issue in issues), issues)

    def test_receipt_payload_status_is_checked_against_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            write_json(fixture.receipt_paths["Track B v03"], {
                "status": "BYPASS_PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
                "synthetic_fixture": True,
            })
            issues = audit_v07.validate_contract_source_closure(
                fixture.root, fixture.contract, fixture.map_path,
                audit_v07.parse_markdown_tables(fixture.map_path),
            )
            self.assertTrue(any("payload status differs from its registered identity" in issue for issue in issues), issues)

    def test_markdown_audit_is_hash_only_and_e1_audit_is_not_e4_population_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
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
            checked, issues = audit_v07.validate_input_bindings(
                fixture.root, audit_v07.parse_markdown_tables(fixture.map_path),
            )
            self.assertEqual(issues, [], issues)
            self.assertTrue(any(row["path"].endswith("structural-audit.md") for row in checked))

    def test_runner_group_binds_exact_track_b_integration_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            runner_files = fixture.contract["implementation_sources"]["e4_online_feature_and_parity_runner"]["files"]
            paths = {row["path"] for row in runner_files}
            prefix = fixture.project.relative_to(fixture.root).as_posix() + "/"
            expected = {prefix + rel for rel in audit_v07.TRACK_B_INTEGRATION_PATHS}
            self.assertEqual(paths, expected)
            result = fixture.run_audit()
            self.assertTrue(result["pass"], result["issues"])

    def test_issuer_source_group_binds_v07_entrypoint_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            issuer_files = fixture.contract["implementation_sources"]["e4_stage_authorization_issuer"]["files"]
            paths = {row["path"] for row in issuer_files}
            prefix = fixture.project.relative_to(fixture.root).as_posix() + "/"
            self.assertEqual(paths, {prefix + rel for rel in audit_v07.TRACK_E_ISSUER_PATHS})
            self.assertFalse(any("authorization_v03.py" in path for path in paths))
            result = fixture.run_audit()
            self.assertTrue(result["pass"], result["issues"])

    def test_synthetic_full_contract_and_seal_pass_without_truth_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            result = fixture.run_audit()
            self.assertTrue(result["pass"], result["issues"])
            self.assertFalse(fixture.truth_path.exists())
            self.assertEqual(result["final_seal"]["root_sha256"], json.loads(fixture.seal_path.read_text())["root_sha256"])
            self.assertEqual(result["status"], "E4_0_TRACK_E_POSTSEAL_PASS_V07_SEAL_ROOT_AND_MEMBERS_RECOMPUTED")

    def test_synthetic_preseal_receipt_status_matches_v07_sealer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            result = fixture.run_audit(mode="preseal")
            self.assertTrue(result["pass"], result["issues"])
            self.assertEqual(result["status"], "E4_0_TRACK_E_PRESEAL_PASS_V07_CONTRACT_AND_SOURCE_MAP_CLOSED")

    def test_science_field_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            fixture.contract["parity"]["batch_size"] = 9
            write_json(fixture.v07_contract_path, fixture.contract)
            fixture.write_seal()
            result = fixture.run_audit()
            self.assertTrue(any("science field differs" in issue for issue in result["issues"]))

    def test_supersedes_and_inherited_root_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            fixture.contract["supersedes"]["seal"]["root_sha256"] = "0" * 64
            fixture.contract["engineering_amendment"]["inherited_population"]["population_root_sha256"] = "0" * 64
            write_json(fixture.v07_contract_path, fixture.contract)
            fixture.write_seal()
            result = fixture.run_audit()
            self.assertTrue(any("supersedes metadata" in issue for issue in result["issues"]))
            self.assertTrue(any("inherited population" in issue for issue in result["issues"]))

    def test_source_map_hash_and_receipt_bytes_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            fixture.receipt_path.write_bytes(b"tampered\n")
            result = fixture.run_audit()
            self.assertTrue(any("source/receipt identity mismatch" in issue for issue in result["issues"]))

    def test_missing_or_extra_seal_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            seal = json.loads(fixture.seal_path.read_text(encoding="utf-8"))
            seal["entries"].pop()
            seal["entry_count"] -= 1
            seal["root_sha256"] = audit_v07.artifact_root(seal["entries"])
            write_json(fixture.seal_path, seal)
            result = fixture.run_audit()
            self.assertTrue(any("omits required member paths" in issue for issue in result["issues"]))

    def test_member_byte_tampering_is_rejected_even_if_root_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            fixture.source_paths[0].write_bytes(b"changed source\n")
            seal = json.loads(fixture.seal_path.read_text(encoding="utf-8"))
            seal["root_sha256"] = audit_v07.artifact_root(seal["entries"])
            write_json(fixture.seal_path, seal)
            result = fixture.run_audit()
            self.assertTrue(any("member bytes/hash mismatch" in issue for issue in result["issues"]))

    def test_seal_root_recomputation_detects_manifest_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = V07AuditFixture(Path(directory))
            seal = json.loads(fixture.seal_path.read_text(encoding="utf-8"))
            seal["entries"][0]["artifact_id"] += "-tampered"
            write_json(fixture.seal_path, seal)
            result = fixture.run_audit()
            self.assertTrue(any("root mismatch" in issue for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
