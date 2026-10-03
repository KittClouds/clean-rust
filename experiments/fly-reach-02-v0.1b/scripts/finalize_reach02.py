from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts/REACH02-RUN2"


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    analysis = json.loads((RUN / "reach02-analysis.json").read_text(encoding="utf-8"))
    integrity = json.loads((RUN / "integrity-receipt.json").read_text(encoding="utf-8"))
    protected = ROOT.parent / "fly-pheno-00/provenance/PROTECTED-DH08A-TREE-RECEIPT.json"
    provenance = ROOT / "provenance"; provenance.mkdir(parents=True, exist_ok=True); protected_copy = provenance / protected.name; shutil.copy2(protected, protected_copy)
    paths = [ROOT / "manifests/REACH02-CONTRACT.json", ROOT / "manifests/REACH02-MANIFEST.json", *sorted((ROOT / "inputs/banks").glob("*.json")), RUN / "qualification-diagnostics.jsonl", RUN / "stable-inversion-masks.json", RUN / "outcomes.jsonl", RUN / "diagnostics.jsonl", RUN / "trajectories.jsonl", RUN / "collection-receipt.json", RUN / "integrity-receipt.json", RUN / "reach02-analysis.json", RUN / "reach02-summary.csv", RUN / "RESULTS.md", ROOT / "scripts/analyze_reach02.py", ROOT / "sealed/fly-reach-02-v0.1b.exe", protected_copy]
    receipt = {"schema": "FLY-REACH-02-v0.1b-terminal-receipt-v1", "study_id": "FLY-REACH-02-v0.1b", "run_id": "FLY-REACH-02-RUN2", "closed_at_utc": datetime.now(timezone.utc).isoformat(), "status": "CLOSED_ENGINEERING_ONLY", "integrity_status": integrity["status"], "disposition": analysis["disposition"], "sign_counterfactual_supported": analysis["sign_counterfactual_supported"], "inversion_interpretation": analysis["inversion_interpretation"], "cancellation_interpretation": analysis["cancellation_interpretation"], "arm_means": analysis["arm_means"], "native_stage_summary": analysis["native_stage_summary"], "stable_mask_fraction": analysis["stable_mask_fraction"], "pheno_reseal_authorized": False, "no_biological_promotion": True, "no_lesions": True, "protected_dh08a_receipt_sha256": sha(protected_copy), "artifact_hashes": [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "bytes": path.stat().st_size} for path in paths]}
    output = RUN / "REACH02-V0.1B-TERMINAL-RECEIPT.json"; output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"); (RUN / "REACH02-V0.1B-TERMINAL-RECEIPT.sha256").write_text(f"{sha(output)}  {output.name}\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "disposition": receipt["disposition"], "receipt_sha256": sha(output)}, sort_keys=True))


if __name__ == "__main__": main()
