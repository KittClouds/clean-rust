from __future__ import annotations
import hashlib,json
from pathlib import Path
ROOT=Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
C=ROOT/"bank"/"construction-01"
OUT=C/"a14-design-lock-v1.json"
FILES=[
 "amendments/bank-amendment-11.md","amendments/bank-amendment-11.json","amendments/bank-amendment-12.md","amendments/bank-amendment-12.json","amendments/bank-amendment-13.md","amendments/bank-amendment-13.json","amendments/bank-amendment-14.md","amendments/bank-amendment-14.json",
 "bank-construction-plan-v1.4.md","task-construction-spec-v1.2.md",
 "bank/construction-01/a12-design-lock-v1.json","bank/construction-01/scored-check-run-lock-a12-v1.json","bank/construction-01/a13-retry-design-lock-v1.json","bank/construction-01/scored-check-run-lock-a13-v1.json",
 "bank/construction-01/scored-bank-a12/attempts/scored-check-attempt-01.json","bank/construction-01/scored-bank-a12/attempts/label-finalization-attempt-a13-01.json","bank/construction-01/scored-bank-a12/vault/task-source-fixtures-precheck-v2.json","bank/construction-01/scored-bank-a12/vault/candidate-check-results-precheck-v2.json",
 "scripts/prepare_pair_locked_bank_e012_a14_v1.py","scripts/finalize_pair_locked_bank_e012_a14_v3.py","scripts/test_finalize_pair_locked_bank_a14.py","scripts/run_scored_checks_e012_a14_v3.py","scripts/freeze_scored_check_runner_e012_a14_v1.py","scripts/freeze_pair_locked_bank_e012_a14.py",
 "scripts/audit_paired_truth_e012_a14_v1.py","scripts/audit_nuisance_baselines_e012_a14_v1.py","scripts/project_frames_e012_a14_v1.py","scripts/freeze_frame_projection_e012_a14_v1.py","scripts/audit_task_bank_e012_a14_v1.py","scripts/freeze_precontact_audit_e012_a14_v1.py",
 "bank/construction-01/repository-source-inventory.json","bank/construction-01/repository-source-audit-v1.json","bank/construction-01/task-construction-lock-v1.1.json","bank/construction-01/label-finalization-lock-v1.json","bank/construction-01/frame-projection-lock-v1.1.json","bank/construction-01/precontact-audit-lock-v1.3.json","bank/construction-01/family-design-lock-v1.3.json","bank/construction-01/feasibility-input-manifest-v1.3.json",
 "bank/construction-01/scored-bank-v1/vault/task-source-fixtures-final-v1.json","bank/construction-01/scored-bank-v1/vault/candidate-check-labels-final-v1.json",
]
def main():
 if OUT.exists(): raise SystemExit(f"refusing to overwrite {OUT}")
 files=[]
 paths=[ROOT/Path(x) for x in FILES]
 paths.extend(sorted(p for p in (C/"task-harnesses-a14").rglob("*") if p.is_file()))
 for p in paths:
  if not p.is_file(): raise SystemExit(f"missing A14 frozen input: {p}")
  b=p.read_bytes(); files.append({"path":p.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)})
 body={"schema_version":1,"experiment":"E012 Prospective Frame Decomposition","amendment":"E012-BANK-A14","state":"FROZEN_BEFORE_A14_TASK_PREPARATION","model_contact_authorized":False,"design":"bank-construction-plan-v1.4.md","prior_finalization_failure_preserved":"bank/construction-01/scored-bank-a12/attempts/label-finalization-attempt-a13-01.json","files":files,"sha256_self_excluded":True}
 OUT.write_text(json.dumps(body,indent=2)+"\n",encoding="utf-8",newline="\n")
 print(json.dumps({"state":body["state"],"locked_files":len(files),"lock":str(OUT)},indent=2))
if __name__=="__main__": main()
