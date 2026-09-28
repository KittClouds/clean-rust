from __future__ import annotations

import json
from pathlib import Path

from s09_common import entry_for, tree_root


INCLUDED = (
    "FAS-S09-PROTOCOL.md",
    "contracts/authorization-packet-v03.json",
    "contracts/preflight-correction-record-v03.json",
    "contracts/s09-recovery-contract-v03.json",
    "source/linear_core.py",
    "source/recover_cache.py",
    "source/run_analysis.py",
    "source/s01_common_reference.py",
    "source/s09_common.py",
    "source/s09_math.py",
    "source/seal_protocol_v03.py",
    "source/seal_result.py",
    "tests/test_s09_math.py",
)


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    seal_path = project / "seals" / "protocol-seal-v03.json"
    if seal_path.exists():
        raise SystemExit("v03 protocol seal already exists; refusing overwrite")
    paths = [project.joinpath(*relative.split("/")) for relative in INCLUDED]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"v03 protocol source missing: {missing}")
    entries = [entry_for(path, project) for path in paths]
    entries.sort(key=lambda item: item["path"])
    seal = {
        "seal_id": "FAS_S09_PROTOCOL_SEAL_V03",
        "project_id": "fas-s09-depthwise-decision-subspace-emergence",
        "run_id": "fas-s09-depthwise-decision-subspace-emergence-v03",
        "entries": entries,
        "root_sha256": tree_root(entries),
        "model_loaded": False,
        "feature_cache_requalified": False,
        "probes_fitted": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    seal_path.write_text(json.dumps(seal, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"protocol_root_sha256={seal['root_sha256']} files={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
