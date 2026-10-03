from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "source-recovery" / "tools" / "src01_parity.py"
SPEC = importlib.util.spec_from_file_location("src01_parity", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_missing_capture_is_explicit() -> None:
    result = MODULE.audit(Path("does-not-exist.tsv"))
    assert result["status"] == "NOT_EVALUABLE_CAPTURE_MISSING"


def test_same_row_legacy_cells_compare_exactly(tmp_path: Path) -> None:
    path = tmp_path / "capture.tsv"
    header = [*MODULE.KEY, *[f"{p}{i}" for p in ("original_b", "translated_b", "v2_legacy_b") for i in range(4)], "v2_lifecycle", "v2_geometry_known", "v2_interaction_eligible", "v2_location", "v2_grammar_event"]
    values = ["0", "COMPLETED_BAR", "US30", "M1", "1", "1", *(["NA"] * 12), "1", "1", "1", "1", "0"]
    path.write_text("\t".join(header) + "\n" + "\t".join(values) + "\n", encoding="cp1252")
    result = MODULE.audit(path)
    assert result["status"] == "CAPTURE_READ"
    assert all(item["status"] == "PASS" for item in result["legacy_parity"])
