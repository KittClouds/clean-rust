from __future__ import annotations
import hashlib,json
from pathlib import Path
ROOT=Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
C=ROOT/"bank"/"construction-01"; B=C/"scored-bank-a14"; OUT=C/"nuisance-audit-lock-a17-v1.json"
FILES=["amendments/bank-amendment-17.md","amendments/bank-amendment-17.json","scripts/audit_nuisance_baselines_e012_a17_v1.py","scripts/freeze_nuisance_audit_e012_a17_v1.py","bank/construction-01/a14-design-lock-v1.json","bank/construction-01/scored-check-run-lock-a14-v1.json","bank/construction-01/frame-projection-lock-a14-v1.json","bank/construction-01/paired-truth-audit-lock-a16-v1.json","bank/construction-01/scored-bank-a14/attempts/nuisance-audit-attempt-a14-01.json","bank/construction-01/scored-bank-a14/vault/paired-truth-audit-a14-v1.json","bank/construction-01/scored-bank-a14/vault/paired-truth-audit-a16-v1.json","bank/construction-01/scored-bank-a14/vault/task-source-fixtures-final-v3.json","bank/construction-01/scored-bank-a14/vault/candidate-check-labels-final-v3.json","bank/construction-01/scored-bank-a14/observer-frames.json","bank/construction-01/scored-bank-a14/vault/frame-truth-index.json"]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 if OUT.exists():raise SystemExit(f"refusing to overwrite {OUT}")
 rows=[]
 for x in FILES:
  p=ROOT/Path(x)
  if not p.is_file():raise SystemExit(f"missing A17 nuisance input: {x}")
  rows.append({"path":x,"sha256":digest(p),"bytes":p.stat().st_size})
 audit=ROOT/"scripts"/"audit_nuisance_baselines_e012_a17_v1.py"
 body={"schema_version":1,"experiment":"E012 Prospective Frame Decomposition","amendment":"E012-AUDIT-A17","state":"FROZEN_BEFORE_A17_NUISANCE_AUDIT","model_contact_authorized":False,"audit":"scripts/audit_nuisance_baselines_e012_a17_v1.py","audit_sha256":digest(audit),"files":rows,"sha256_self_excluded":True}
 OUT.write_text(json.dumps(body,indent=2)+"\n",encoding="utf-8",newline="\n")
 print(json.dumps({"state":body["state"],"files":len(rows),"lock":str(OUT)},indent=2))
if __name__=="__main__":main()
