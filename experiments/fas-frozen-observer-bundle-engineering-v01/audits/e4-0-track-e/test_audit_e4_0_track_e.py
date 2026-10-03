import hashlib
import tempfile
import unittest
from pathlib import Path

from audit_e4_0_track_e import artifact_root, parse_source_map


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


if __name__ == "__main__":
    unittest.main()
