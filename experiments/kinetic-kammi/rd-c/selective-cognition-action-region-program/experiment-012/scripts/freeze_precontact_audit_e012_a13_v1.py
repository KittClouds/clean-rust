from __future__ import annotations
import hashlib,json
from pathlib import Path
ROOT=Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION=ROOT/"bank"/"construction-01"
BANK=CONSTRUCTION/"scored-bank-a12"
OUT=CONSTRUCTION/"precontact-audit-lock-a13-v1.json"
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 if OUT.exists(): raise SystemExit(f"refusing to overwrite {OUT}")
 audit=ROOT/"scripts"/"audit_task_bank_e012_a13_v1.py"
 paths=[ROOT/"bank"/"construction-01"/"frame-projection-lock-a13-v1.json",audit,ROOT/"scripts"/"freeze_precontact_audit_e012_a13_v1.py",ROOT/"scripts"/"audit_paired_truth_e012_a13_v1.py",ROOT/"scripts"/"audit_nuisance_baselines_e012_a13_v1.py",BANK/"observer-frames.json",BANK/"vault"/"frame-truth-index.json",BANK/"vault"/"presentation-receipts.json",BANK/"vault"/"task-source-fixtures-final-v2.json",BANK/"vault"/"candidate-check-labels-final-v2.json",BANK/"vault"/"candidate-check-results-precheck-v2.json"]
 files=[{"path":path.relative_to(ROOT).as_posix(),"sha256":digest(path),"bytes":path.stat().st_size} for path in paths]
 body={"schema_version":1,"state":"FROZEN_BEFORE_A13_PRECONTACT_AUDIT","model_contact_authorized":False,"audit":"scripts/audit_task_bank_e012_a13_v1.py","audit_sha256":digest(audit),"frame_count":1248,"files":files,"sha256_self_excluded":True}
 OUT.write_text(json.dumps(body,indent=2)+"\n",encoding="utf-8",newline="\n")
 print(json.dumps({"state":body["state"],"files":len(files),"lock":str(OUT)},indent=2))
if __name__=="__main__": main()
