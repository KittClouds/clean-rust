from __future__ import annotations

import json
from pathlib import Path

from s09_common import entry_for, tree_root


INCLUDED = (
    "FAS-S09-PROTOCOL.md",
    "contracts/analysis-correction-record-v08.json",
    "contracts/authorization-packet-v08.json",
    "contracts/s09-analysis-contract-v08.json",
    "source/audit_geometry_semantics_v08.py",
    "source/linear_core.py",
    "source/prepare_analysis_v08.py",
    "source/run_analysis.py",
    "source/s01_common_reference.py",
    "source/s09_common.py",
    "source/s09_math.py",
    "source/seal_protocol_v08.py",
    "source/seal_result.py",
    "tests/test_s09_math.py",
)


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    seal_path = project / "seals" / "protocol-seal-v08.json"
    if seal_path.exists():
        raise SystemExit("v08 protocol seal already exists; refusing overwrite")
    paths = [project.joinpath(*relative.split("/")) for relative in INCLUDED]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"v08 protocol source missing: {missing}")
    entries = [entry_for(path, project) for path in paths]
    entries.sort(key=lambda item: item["path"])
    seal = {
        "seal_id": "FAS_S09_ANALYSIS_PROTOCOL_SEAL_V08",
        "project_id": "fas-s09-depthwise-decision-subspace-emergence",
        "run_id": "fas-s09-depthwise-decision-subspace-emergence-v08",
        "entries": entries,
        "root_sha256": tree_root(entries),
        "model_loaded": False,
        "probe_fits_performed": False,
        "fas00_access": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    seal_path.write_text(json.dumps(seal, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"protocol_root_sha256={seal['root_sha256']} files={len(entries)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
