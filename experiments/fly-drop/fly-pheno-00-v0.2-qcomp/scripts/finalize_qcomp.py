from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts" / "QCOMP-RUN1"


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> None:
    analysis = json.loads((RUN / "frontier-analysis.json").read_text(encoding="utf-8"))
    receipt = json.loads((RUN / "integrity-receipt.json").read_text(encoding="utf-8"))
    contract = ROOT / "manifests/QCOMP-CONTRACT.json"
    protected = ROOT.parent / "fly-pheno-00" / "provenance/PROTECTED-DH08A-TREE-RECEIPT.json"
    prov = ROOT / "provenance"
    prov.mkdir(parents=True, exist_ok=True)
    shutil.copy2(protected, prov / protected.name)
    files = [
        contract, ROOT / "manifests/QCOMP-MANIFEST.json", ROOT / "manifests/NULL-GRAPH-MANIFEST.json",
        ROOT / "inputs/banks/training.json", ROOT / "inputs/banks/competence.json",
        RUN / "competence-frontier.jsonl", RUN / "collection-receipt.json", RUN / "integrity-receipt.json",
        RUN / "frontier-analysis.json", RUN / "frontier-summary.csv", RUN / "RESULTS.md",
        ROOT / "sealed/fly-pheno-00-v0.2-qcomp.exe", prov / protected.name,
    ]
    terminal = {
        "schema": "FLY-PHENO-00-v0.2-QCOMP-terminal-receipt-v1",
        "study_id": "FLY-PHENO-00-v0.2-QCOMP",
        "run_id": "FLY-PHENO-00-v0.2-QCOMP-RUN1",
        "closed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "CLOSED_QUALIFICATION_ONLY",
        "integrity_status": receipt["status"],
        "disposition": analysis["disposition"],
        "interpretation": analysis["interpretation"],
        "competence_threshold": analysis["threshold"],
        "support_requirement": analysis["competence_rate_requirement"],
        "common_supported_horizons": analysis["common_supported_horizons"],
        "max_rate_by_substrate": analysis["max_rate_by_substrate"],
        "measured_v0_2_reseal_authorized": False,
        "scientific_pheno_execution_authorized": False,
        "no_threshold_relaxation": True,
        "no_seed_replacement": True,
        "no_lesion_outcomes": True,
        "no_recovery_comparison": True,
        "protected_dh08a_receipt_sha256": sha(prov / protected.name),
        "artifact_hashes": [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(p), "bytes": p.stat().st_size} for p in files],
    }
    out = RUN / "QCOMP-TERMINAL-RECEIPT.json"
    out.write_text(json.dumps(terminal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RUN / "QCOMP-TERMINAL-RECEIPT.sha256").write_text(f"{sha(out)}  {out.name}\n", encoding="utf-8")
    print(json.dumps({"status": terminal["status"], "disposition": terminal["disposition"], "receipt_sha256": sha(out)}, sort_keys=True))


if __name__ == "__main__":
    main()
