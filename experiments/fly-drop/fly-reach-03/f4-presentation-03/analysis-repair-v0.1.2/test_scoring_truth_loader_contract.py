from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BRANCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRANCH))

import presentation03_data

_ANALYZER_PATH = Path(__file__).resolve().parent / "analyze_results.py"
_SPEC = importlib.util.spec_from_file_location("f4pres03_analyze_repaired", _ANALYZER_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load the repaired analyzer source for the regression test")
analyzer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analyzer)


class ScoringTruthLoaderContractTests(unittest.TestCase):
    def test_analysis_passes_the_frozen_row_keys_to_truth_loader(self) -> None:
        raw = SimpleNamespace(keys=(b"row-key-0000000001", b"row-key-0000000002"))
        truth = SimpleNamespace(y=(1, -1))
        with tempfile.TemporaryDirectory() as temp:
            collection = Path(temp)
            truth_path = collection / "RAW-SCORING-TRUTH.bin"
            truth_path.write_bytes(b"opaque fixture bytes")
            with (
                patch.object(analyzer, "COLLECTION", collection),
                patch.object(analyzer, "sha_file", return_value="fixture-sha"),
                patch.object(presentation03_data, "load_raw_panel", return_value=raw),
                patch.object(presentation03_data, "load_scoring_truth", return_value=truth) as loader,
            ):
                actual_raw, actual_truth = analyzer._truth_and_rows({"truth_file_sha256": "fixture-sha"})
            self.assertIs(actual_raw, raw)
            self.assertIs(actual_truth, truth)
            loader.assert_called_once_with(raw.keys, truth_path)

    def test_truth_loader_is_not_called_when_integrity_hash_differs(self) -> None:
        raw = SimpleNamespace(keys=(b"row-key-0000000001",))
        with tempfile.TemporaryDirectory() as temp:
            collection = Path(temp)
            (collection / "RAW-SCORING-TRUTH.bin").write_bytes(b"opaque fixture bytes")
            with (
                patch.object(analyzer, "COLLECTION", collection),
                patch.object(analyzer, "sha_file", return_value="actual-sha"),
                patch.object(presentation03_data, "load_raw_panel", return_value=raw),
                patch.object(presentation03_data, "load_scoring_truth") as loader,
            ):
                with self.assertRaisesRegex(RuntimeError, "truth file changed"):
                    analyzer._truth_and_rows({"truth_file_sha256": "different-sha"})
            loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
