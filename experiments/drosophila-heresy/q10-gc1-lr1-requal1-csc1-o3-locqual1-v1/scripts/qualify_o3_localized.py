from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "drosophila-heresy"
FRONT2 = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-v3"
AUDIT = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-audit-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    if OUT.exists():
        allowed = {
            Path("PLAN.md"), Path("scripts"), Path("scripts/qualify_o3_localized.py"),
            Path("execution.json"), Path("STATUS.json"), Path("REPORT.md"),
        }
        existing = {path.relative_to(OUT) for path in OUT.rglob("*")}
        unexpected = existing - allowed
        if unexpected:
            raise RuntimeError(f"unexpected output files: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()
    front2_path = FRONT2 / "execution.json"
    audit_path = AUDIT / "execution.json"
    before = {str(front2_path): sha256(front2_path), str(audit_path): sha256(audit_path)}
    front2 = load(front2_path)
    audit = load(audit_path)
    if front2.get("status") != "ALG3_FRONT2_COMPLETE_NO_EXACT":
        raise RuntimeError("FRONT2 is not complete")
    if not front2.get("full_readout_audit_passed"):
        raise RuntimeError("FRONT2 localized full-readout audit did not pass")
    if int(front2["counts"]["audit_records"]) != 1621:
        raise RuntimeError("unexpected FRONT2 audit record count")
    if audit.get("status") != "FRONT2_AUDIT_COMPLETE":
        raise RuntimeError("independent FRONT2 audit is not complete")
    if int(audit.get("independent_full_replay_samples_verified", 0)) != 14:
        raise RuntimeError("unexpected independent FRONT2 sample count")
    if not audit.get("parent_bindings_verified") or not audit.get("range_hashes_and_counts_verified"):
        raise RuntimeError("FRONT2 independent audit integrity gates are incomplete")
    after = {str(front2_path): sha256(front2_path), str(audit_path): sha256(audit_path)}
    if before != after:
        raise RuntimeError("FRONT2 source changed during qualification")
    execution = {
        "identity": OUT.name,
        "protocol": "Q10-O3-LOCQUAL1",
        "status": "O3_LOCQUAL1_COMPLETE",
        "engineering_only": True,
        "replay_executed": False,
        "scientific_promotion": False,
        "front2_execution_sha256": before[str(front2_path)],
        "front2_audit_execution_sha256": before[str(audit_path)],
        "localized_audit_records": 1621,
        "independent_full_replay_samples": 14,
        "localized_readout_qualified": True,
    }
    (OUT / "execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "STATUS.json").write_text(json.dumps({
        "identity": OUT.name,
        "status": execution["status"],
        "replay_executed": False,
        "scientific_promotion": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "REPORT.md").write_text(
        "# O3-LOCQUAL1\n\n"
        "The existing order-3 localized-readout path is qualified for targeted semantic materialization: 1,621 deterministic full-replay comparisons passed, and the independent FRONT2 audit passed 14 additional full-replay reconstructions. This identity performed no replay.\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
