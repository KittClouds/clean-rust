from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT=Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION=ROOT/"bank"/"construction-01"
BANK=CONSTRUCTION/"scored-bank-a14"
OUT=CONSTRUCTION/"frame-projection-lock-a14-v1.json"
PRESENTER=Path(r"D:\rdc-e012-target\runtime-integration\release\e011-presentation.exe")
BLAKE3=Path(r"D:\rdc-e012-target\runtime-integration\release\e011-hash.exe")
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    if OUT.exists(): raise SystemExit(f"refusing to overwrite {OUT}")
    projected=[BANK/"observer-frames.json",BANK/"vault"/"frame-truth-index.json",BANK/"vault"/"presentation-receipts.json"]
    if any(path.exists() for path in projected): raise SystemExit("A14 frame artifacts already exist")
    paths=[
      ROOT/"bank"/"construction-01"/"a14-design-lock-v1.json",
      BANK/"vault"/"task-source-fixtures-final-v3.json",
      BANK/"vault"/"candidate-check-labels-final-v3.json",
      BANK/"vault"/"label-finalization-report-v3.json",
      ROOT/"scripts"/"project_frames_e012_a14_v1.py",
      ROOT/"scripts"/"freeze_frame_projection_e012_a14_v1.py",
      ROOT/"scripts"/"audit_paired_truth_e012_a14_v1.py",
      ROOT/"scripts"/"audit_nuisance_baselines_e012_a14_v1.py",
      PRESENTER,BLAKE3,
    ]
    records=[]
    for path in paths:
      label=path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else f"external::{path.as_posix()}"
      records.append({"path":label,"sha256":digest(path),"bytes":path.stat().st_size})
    body={"schema_version":1,"experiment":"E012 Prospective Frame Decomposition","state":"FROZEN_BEFORE_A14_FRAME_PROJECTION","model_contact_authorized":False,"task_count":48,"conditions_per_task":26,"expected_frame_count":1248,"projector":"scripts/project_frames_e012_a14_v1.py","projector_sha256":digest(ROOT/"scripts"/"project_frames_e012_a14_v1.py"),"presentation_binary_sha256":digest(PRESENTER),"hash_binary_sha256":digest(BLAKE3),"files":records,"sha256_self_excluded":True}
    OUT.write_text(json.dumps(body,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"state":body["state"],"locked_files":len(records),"lock":str(OUT)},indent=2))
if __name__=="__main__": main()
