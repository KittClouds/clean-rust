from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts/REACH01-RUN1"


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    analysis = json.loads((RUN / "reach01-analysis.json").read_text(encoding="utf-8"))
    integrity = json.loads((RUN / "integrity-receipt.json").read_text(encoding="utf-8"))
    protected = ROOT.parent / "fly-pheno-00/provenance/PROTECTED-DH08A-TREE-RECEIPT.json"
    provenance = ROOT / "provenance"
    provenance.mkdir(parents=True, exist_ok=True)
    protected_copy = provenance / protected.name
    shutil.copy2(protected, protected_copy)
    paths = [
        ROOT / "manifests/REACH01-CONTRACT.json",
        ROOT / "manifests/REACH01-MANIFEST.json",
        ROOT / "inputs/banks/training.json",
        ROOT / "inputs/banks/competence.json",
        ROOT / "inputs/banks/evaluator-large.json",
        RUN / "outcomes.jsonl",
        RUN / "diagnostics.jsonl",
        RUN / "trajectories.jsonl",
        RUN / "collection-receipt.json",
        RUN / "integrity-receipt.json",
        RUN / "reach01-analysis.json",
        RUN / "reach01-summary.csv",
        RUN / "RESULTS.md",
        ROOT / "sealed/fly-reach-01.exe",
        protected_copy,
    ]
    receipt = {
        "schema": "FLY-REACH-01-terminal-receipt-v1",
        "study_id": "FLY-REACH-01",
        "run_id": "FLY-REACH-01-RUN1",
        "closed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "CLOSED_ENGINEERING_ONLY",
        "integrity_status": integrity["status"],
        "disposition": analysis["disposition"],
        "interpretation": analysis["interpretation"],
        "arm_means": analysis["arm_means"],
        "native_stage_summary": analysis["native_stage_summary"],
        "oracle_large_mean_below_threshold": analysis["oracle_large_mean_below_threshold"],
        "pheno_reseal_authorized": False,
        "no_biological_promotion": True,
        "no_lesions": True,
        "protected_dh08a_receipt_sha256": sha(protected_copy),
        "artifact_hashes": [
            {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "bytes": path.stat().st_size}
            for path in paths
        ],
    }
    output = RUN / "REACH01-TERMINAL-RECEIPT.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RUN / "REACH01-TERMINAL-RECEIPT.sha256").write_text(f"{sha(output)}  {output.name}\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "disposition": receipt["disposition"], "receipt_sha256": sha(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
