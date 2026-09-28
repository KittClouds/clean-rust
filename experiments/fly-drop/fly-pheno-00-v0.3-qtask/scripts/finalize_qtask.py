from __future__ import annotations
import hashlib
import json
import pathlib
import shutil
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts" / "QTASK-RUN1"

def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def main() -> None:
    analysis = json.loads((RUN / "task-analysis.json").read_text(encoding="utf-8"))
    integrity = json.loads((RUN / "integrity-receipt.json").read_text(encoding="utf-8"))
    protected = ROOT.parent / "fly-pheno-00" / "provenance/PROTECTED-DH08A-TREE-RECEIPT.json"
    prov = ROOT / "provenance"; prov.mkdir(parents=True, exist_ok=True)
    shutil.copy2(protected, prov / protected.name)
    paths = [ROOT / "manifests/QTASK-CONTRACT.json", ROOT / "manifests/QTASK-MANIFEST.json", ROOT / "manifests/NULL-GRAPH-MANIFEST.json", ROOT / "inputs/banks/training.json", ROOT / "inputs/banks/competence.json", RUN / "task-frontier.jsonl", RUN / "collection-receipt.json", RUN / "integrity-receipt.json", RUN / "task-analysis.json", RUN / "task-summary.csv", RUN / "RESULTS.md", ROOT / "sealed/fly-pheno-00-v0.3-qtask.exe", prov / protected.name]
    receipt = {
        "schema":"FLY-PHENO-00-v0.3-QTASK-terminal-receipt-v1", "study_id":"FLY-PHENO-00-v0.3-QTASK", "run_id":"FLY-PHENO-00-v0.3-QTASK-RUN1", "closed_at_utc":datetime.now(timezone.utc).isoformat(), "status":"CLOSED_QUALIFICATION_ONLY", "integrity_status":integrity["status"], "disposition":analysis["disposition"], "interpretation":analysis["interpretation"], "selected_rung":analysis["selected_rung"], "passes_by_rung":analysis["passes_by_rung"], "threshold":analysis["threshold"], "margin_threshold":analysis["margin_threshold"], "support_requirement":analysis["support_requirement"], "measured_pheno_reseal_authorized":False, "no_lesion_outcomes":True, "no_recovery_comparison":True, "no_threshold_relaxation":True, "no_seed_replacement":True, "protected_dh08a_receipt_sha256":sha(prov / protected.name), "artifact_hashes":[{"path":str(p.relative_to(ROOT)).replace("\\", "/"), "sha256":sha(p), "bytes":p.stat().st_size} for p in paths]
    }
    out = RUN / "QTASK-TERMINAL-RECEIPT.json"; out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RUN / "QTASK-TERMINAL-RECEIPT.sha256").write_text(f"{sha(out)}  {out.name}\n", encoding="utf-8")
    print(json.dumps({"status":receipt["status"],"disposition":receipt["disposition"],"receipt_sha256":sha(out)},sort_keys=True))

if __name__ == "__main__": main()
