import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit_e4_0_track_e import (
    artifact_root,
    parse_source_map,
    verify_map_unique_path_bindings,
    verify_source_rows,
)


PROJECT = Path(__file__).resolve().parents[2]
SEALER_PATH = PROJECT / "source" / "scripts" / "seal_e4_0_contract_v05.py"
_spec = importlib.util.spec_from_file_location("e4_contract_sealer", SEALER_PATH)
assert _spec is not None and _spec.loader is not None
sealer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sealer)


class TrackEAuditUnitTests(unittest.TestCase):
    def test_artifact_root_sorts_by_utf8_artifact_id_and_binds_all_columns(self) -> None:
        entries = [
            {"artifact_id": "z-last", "path": "b/file", "bytes": 3, "sha256": "b" * 64},
            {"artifact_id": "a-first", "path": "a/file", "bytes": 1, "sha256": "a" * 64},
        ]
        digest = hashlib.sha256()
        for entry in sorted(entries, key=lambda item: item["artifact_id"].encode("utf-8")):
            digest.update(
                f"{entry['artifact_id']}\t{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n".encode("utf-8")
            )
        self.assertEqual(artifact_root(entries), digest.hexdigest())

    def test_source_map_parser_selects_the_source_file_table_only(self) -> None:
        content = (
            "# Example\n\n"
            "| Path | Bytes | SHA-256 | Role |\n"
            "| --- | ---: | --- | --- |\n"
            f"| `src/generator.py` | 3 | {'a' * 64} | population generator |\n\n"
            "| Receipt path | SHA-256 | Status |\n"
            "| --- | --- | --- |\n"
            f"| audits/track-c.json | {'b' * 64} | PASS |\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.md"
            path.write_text(content, encoding="utf-8")
            rows, tables = parse_source_map(path)
        self.assertEqual(rows, [{"path": "src/generator.py", "bytes": 3, "sha256": "a" * 64, "role": "population generator"}])
        self.assertEqual(len(tables), 2)

    def test_sealer_checks_symlink_before_resolving_member_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alias = root / "alias"
            target = root / "target"
            target.write_bytes(b"target")
            path_type = type(root)
            original_is_symlink = path_type.is_symlink
            original_resolve = path_type.resolve

            def is_symlink(candidate):
                if candidate == alias:
                    return True
                return original_is_symlink(candidate)

            def resolve(candidate, *args, **kwargs):
                if candidate == alias:
                    return original_resolve(target, strict=True)
                return original_resolve(candidate, *args, **kwargs)

            with mock.patch.object(path_type, "is_symlink", autospec=True, side_effect=is_symlink):
                with mock.patch.object(path_type, "resolve", autospec=True, side_effect=resolve):
                    with self.assertRaisesRegex(RuntimeError, "symlink or junction"):
                        sealer.safe_path(root, "alias")

    def test_sealer_rejects_duplicate_member_path_even_with_identical_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            member = root / "member.bin"
            content = b"same bytes"
            member.write_bytes(content)
            sha = hashlib.sha256(content).hexdigest()
            entries = {}
            sealer.add_member(root, entries, "first", "member.bin", len(content), sha)
            with self.assertRaisesRegex(RuntimeError, "duplicate seal member path"):
                sealer.add_member(root, entries, "second", "member.bin", len(content), sha)

    def test_sealer_finds_input_path_table_with_whitespace_normalization(self) -> None:
        content = (
            "| Input Path | Bytes | SHA-256 | Role |\n"
            "| --- | ---: | --- | --- |\n"
            f"| `experiments/x.bin` | 3 | {'a' * 64} | frozen input |\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.md"
            path.write_text(content, encoding="utf-8")
            rows = sealer.find_table(path, ["inputpath", "bytes", "sha256", "role"])
        self.assertEqual(rows, [["experiments/x.bin", "3", "a" * 64, "frozen input"]])
    def test_actual_generated_v04_map_source_and_receipt_tables(self) -> None:
        workspace = PROJECT.parents[1]
        source_map = PROJECT / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v04.md"
        if not source_map.is_file():
            self.skipTest("final v04 source map is not present yet")
        rows, tables = parse_source_map(source_map)
        checked, issues = verify_source_rows(workspace, rows)
        self.assertGreater(len(checked), 0)
        self.assertEqual(issues, [])
        self.assertEqual(verify_map_unique_path_bindings(tables), [])
        self.assertEqual(sum(headers == ["track", "path", "bytes", "sha256", "status"] for headers, _ in tables), 1)


if __name__ == "__main__":
    unittest.main()