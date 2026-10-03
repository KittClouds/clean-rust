from __future__ import annotations

import csv
import io
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fit_integrity_repair as verifier
from fit_contract import FIT_HEADER


class ManifestParserRegressionTests(unittest.TestCase):
    def test_frozen_manifest_bytes_parse_to_exact_header_and_72_fit_ids(self) -> None:
        manifest_path = verifier.RUN / "FIT-MANIFEST.csv"
        raw = manifest_path.read_bytes()
        rows, row_hashes, manifest_sha = verifier._read_manifest_bytes(manifest_path)

        parsed = list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline="")))
        self.assertEqual(tuple(parsed[0].keys()), FIT_HEADER)
        self.assertEqual(len(rows), 72)
        self.assertEqual(len(row_hashes), 72)
        self.assertEqual(manifest_sha, verifier.sha256_bytes(raw))
        self.assertEqual(len({row["fit_id"] for row in rows}), 72)
        self.assertTrue(all(row["fit_id"] for row in rows))

    def test_character_iterable_input_is_rejected(self) -> None:
        text = (verifier.RUN / "FIT-MANIFEST.csv").read_text(encoding="utf-8")
        with self.assertRaisesRegex(TypeError, "line iterable"):
            verifier._parse_manifest_lines(text)


if __name__ == "__main__":
    unittest.main()
