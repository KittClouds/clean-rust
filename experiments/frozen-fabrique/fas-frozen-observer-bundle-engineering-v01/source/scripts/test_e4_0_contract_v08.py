from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "finalize_e4_0_contract_v08.py"
SPEC = importlib.util.spec_from_file_location("finalize_e4_0_contract_v08", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import v08 finalizer")
FINALIZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FINALIZER)
MAP_PATH = HERE / "build_e4_0_source_map_v07.py"
MAP_SPEC = importlib.util.spec_from_file_location("build_e4_0_source_map_v07", MAP_PATH)
if MAP_SPEC is None or MAP_SPEC.loader is None:
    raise RuntimeError("cannot import v07 source-map builder")
MAP_BUILDER = importlib.util.module_from_spec(MAP_SPEC)
MAP_SPEC.loader.exec_module(MAP_BUILDER)
SEAL_PATH = HERE / "seal_e4_0_contract_v08.py"
SEAL_SPEC = importlib.util.spec_from_file_location("seal_e4_0_contract_v08", SEAL_PATH)
if SEAL_SPEC is None or SEAL_SPEC.loader is None:
    raise RuntimeError("cannot import v08 sealer")
SEALER = importlib.util.module_from_spec(SEAL_SPEC)
SEAL_SPEC.loader.exec_module(SEALER)


class ContractV08Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[4]
        cls.project = root / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
        cls.v06 = json.loads((cls.project / "contracts" / "e4-0-contract-v06-final.json").read_text(encoding="utf-8"))

    def test_v06_baseline_is_sealed_and_exact_hash(self) -> None:
        path = self.project / "contracts" / "e4-0-contract-v06-final.json"
        size, sha = FINALIZER.sha256_file(path)
        self.assertEqual(size, 43208)
        self.assertEqual(sha, FINALIZER.BASELINE_SHA256)
        self.assertEqual(self.v06["contract_id"], "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06")
        self.assertEqual(self.v06["status"], "SEALED")

    def test_source_map_metadata_is_excluded_from_science_projection(self) -> None:
        candidate = copy.deepcopy(self.v06)
        candidate["design_inputs"].pop("implementation_source_map_v05_path", None)
        candidate["design_inputs"]["implementation_source_map_v07_path"] = "different-map.md"
        self.assertEqual(FINALIZER.scientific_projection(candidate), FINALIZER.scientific_projection(self.v06))
        FINALIZER.require_scientific_invariance(candidate, self.v06)

    def test_any_registered_scientific_field_change_fails_closed(self) -> None:
        for field in FINALIZER.IMMUTABLE:
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.v06)
                candidate[field] = {"tampered": True}
                with self.assertRaises(RuntimeError):
                    FINALIZER.require_scientific_invariance(candidate, self.v06)

    def test_design_input_change_other_than_map_metadata_fails_closed(self) -> None:
        candidate = copy.deepcopy(self.v06)
        candidate["design_inputs"]["template_manifest_sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            FINALIZER.require_scientific_invariance(candidate, self.v06)

    def test_predecessor_map_parser_finds_unique_source_receipt_tables(self) -> None:
        predecessor_map = self.project / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v06.md"
        sources = MAP_BUILDER.table(predecessor_map, ["Path", "Bytes", "SHA-256", "Role"])
        receipts = MAP_BUILDER.table(predecessor_map, ["Track", "Path", "Bytes", "SHA-256", "Status"])
        inputs = MAP_BUILDER.table(predecessor_map, ["Input Path", "Bytes", "SHA-256", "Role"])
        self.assertGreater(len(sources), 30)
        self.assertGreater(len(receipts), 8)
        self.assertGreater(len(inputs), 10)

    def test_predecessor_track_names_are_not_double_prefixed(self) -> None:
        self.assertEqual(MAP_BUILDER.predecessor_track("Track A v03"), "Predecessor Track A v03")
        self.assertEqual(MAP_BUILDER.predecessor_track("Predecessor Track A v03"), "Predecessor Track A v03")

    def test_table_parser_fails_closed_when_requested_table_is_absent(self) -> None:
        with self.assertRaises(RuntimeError):
            MAP_BUILDER.table(Path(__file__), ["Track", "Path", "Bytes", "SHA-256", "Status"])

    def test_finalizer_rejects_bypass_and_track_status_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = root / "receipt.json"
            map_path = root / "map.md"
            for track, status in (("Prior X", "BYPASS_PASS"), ("Track B v04", "PASS_SYNTHETIC_TESTS")):
                receipt.write_text(json.dumps({"status": status}), encoding="utf-8")
                size, sha = FINALIZER.sha256_file(receipt)
                map_path.write_text(
                    "| Track | Path | Bytes | SHA-256 | Status |\n| --- | --- | ---: | --- | --- |\n"
                    f"| {track} | `receipt.json` | {size} | `{sha}` | `{status}` |\n",
                    encoding="utf-8",
                )
                with self.assertRaises(RuntimeError):
                    FINALIZER.receipt_rows(map_path, root)

    def test_finalizer_accepts_preserved_v07_track_e_pre_map_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = root / "receipt.json"
            status = "TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR"
            receipt.write_text(json.dumps({"status": status}), encoding="utf-8")
            size, sha = FINALIZER.sha256_file(receipt)
            map_path = root / "map.md"
            map_path.write_text(
                "| Track | Path | Bytes | SHA-256 | Status |\n| --- | --- | ---: | --- | --- |\n"
                f"| Predecessor Track E | `receipt.json` | {size} | `{sha}` | `{status}` |\n",
                encoding="utf-8",
            )
            rows = FINALIZER.receipt_rows(map_path, root)
            self.assertEqual(rows[0]["status"], status)

    def test_finalizer_reconstructs_receipt_source_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = "experiments/fas-frozen-observer-bundle-engineering-v01"
            names = {
                "e4_runner_common_v04.py", "e4_runner_artifacts_v04.py", "e4_gpu_lease_v03.py",
                "e4_runner_modes_v04.py", "e4_online_parity_v04.py", "test_e4_runner_v04.py",
            }
            source_rows, bindings = [], []
            for name in sorted(names):
                rel = f"{project}/source/{'tests' if name.startswith('test_') else 'scripts'}/{name}"
                source = root / rel
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(name.encode("utf-8"))
                size, sha = FINALIZER.sha256_file(source)
                source_rows.append({"path": rel, "bytes": size, "sha256": sha})
                bindings.append({"path": rel.removeprefix(project + "/"), "bytes": size, "sha256": sha})
            builder_rows = [(row["path"], root / row["path"], "synthetic") for row in source_rows]
            MAP_BUILDER.verify_receipt_source_bindings("Track B v04", {"bound_sources": bindings}, builder_rows)
            receipt_path = root / "receipt.json"
            receipt_path.write_text(json.dumps({"bound_sources": bindings}), encoding="utf-8")
            receipts = [{"track": "Track B v04", "path": "receipt.json"}]
            FINALIZER.verify_receipt_source_closure(receipts, source_rows, root)
            bindings[-1]["sha256"] = "0" * 64
            with self.assertRaises(RuntimeError):
                MAP_BUILDER.verify_receipt_source_bindings("Track B v04", {"bound_sources": bindings}, builder_rows)
            receipt_path.write_text(json.dumps({"bound_sources": bindings}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                FINALIZER.verify_receipt_source_closure(receipts, source_rows, root)

    def test_sealer_rejects_casefolded_duplicate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / "MixedCase.bin"
            artifact.write_bytes(b"sealed")
            size, sha = SEALER.digest(artifact)
            by_path, by_identity = {}, set()
            SEALER.add_member(root, by_path, by_identity, "first", "MixedCase.bin", size, sha)
            with self.assertRaises(RuntimeError):
                SEALER.add_member(root, by_path, by_identity, "second", "MIXEDCASE.BIN", size, sha)

    def test_fixed_output_paths_reject_traversal_and_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "seals").mkdir()
            self.assertEqual(SEALER.safe_output_path(root, "seals/out.json"), root / "seals" / "out.json")
            with self.assertRaises(RuntimeError):
                SEALER.safe_output_path(root, "../escape.json")
            (root / "seals" / "out.json").write_text("exists", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                SEALER.safe_output_path(root, "seals/out.json")

    def test_builder_and_finalizer_reject_symlinked_output_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            alias = root / "plans"
            alias.mkdir()
            real_is_symlink = Path.is_symlink
            def simulated_symlink(path: Path) -> bool:
                return path.name == "plans" or real_is_symlink(path)
            with patch.object(MAP_BUILDER, "WORKSPACE", root):
                with patch.object(Path, "is_symlink", autospec=True, side_effect=simulated_symlink):
                    with self.assertRaises(RuntimeError):
                        MAP_BUILDER.safe_output_path(alias / "map.md")
                    with self.assertRaises(RuntimeError):
                        FINALIZER.safe_output_path(alias / "contract.json", root)

    def test_builder_accepts_safe_existing_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plans = root / "plans"
            plans.mkdir()
            with patch.object(MAP_BUILDER, "WORKSPACE", root):
                MAP_BUILDER.safe_output_path(plans / "map.md")

    def test_builder_rejects_output_parent_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "inside"
            outside = Path(temp) / "outside"
            root.mkdir()
            outside.mkdir()
            with patch.object(MAP_BUILDER, "WORKSPACE", root):
                with self.assertRaises(RuntimeError):
                    MAP_BUILDER.safe_output_path(outside / "map.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)
