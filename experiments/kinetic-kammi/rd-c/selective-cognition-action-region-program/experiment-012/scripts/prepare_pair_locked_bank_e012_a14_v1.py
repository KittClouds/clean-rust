from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any
ROOT=Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
C=ROOT/"bank"/"construction-01"
PRIOR=C/"scored-bank-a12"/"vault"/"task-source-fixtures-precheck-v2.json"
OUT=C/"scored-bank-a14"/"vault"/"task-source-fixtures-precheck-v3.json"
LOCK=C/"a14-design-lock-v1.json"
def sha(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def main()->None:
 if OUT.exists(): raise SystemExit(f"refusing to overwrite {OUT}")
 lock=json.loads(LOCK.read_text(encoding="utf-8"))
 if lock.get("state")!="FROZEN_BEFORE_A14_TASK_PREPARATION" or lock.get("model_contact_authorized") is not False: raise SystemExit("A14 design lock state is invalid")
 for item in lock["files"]:
  p=ROOT/Path(item["path"])
  if not p.is_file() or sha(p.read_bytes())!=item["sha256"]: raise SystemExit(f"A14 locked input drift: {item['path']}")
 prior=PRIOR.read_bytes(); source=json.loads(prior)
 if source.get("model_contact_authorized") is not False: raise SystemExit("prior source unexpectedly authorizes model contact")
 source["state"]="A14_TASK_FIXTURE_PREPARED_BEFORE_SCORING_NO_MODEL_CONTACT"
 source["source_fixture_version"]="a14-precheck-v3"
 source["construction_repair"]={"amendment":"E012-BANK-A14","test_harness":"bank/construction-01/task-harnesses-a14/serde-map-order-repair-02/tests/contract.rs","changed_case":"case-02","input":"{\"b\":1,\"a\":2,\"c\":3}","expected_insertion_order":["b","a","c"],"model_contact":False}
 source["derived_from_a14"]={"prior_precheck_sha256":sha(prior),"design_lock_sha256":sha(LOCK.read_bytes()),"preparation_script_sha256":sha(Path(__file__).read_bytes()),"model_contact":False}
 OUT.parent.mkdir(parents=True,exist_ok=True)
 OUT.write_bytes(json.dumps(source,indent=2,ensure_ascii=False).encode("utf-8")+b"\n")
 print(json.dumps({"state":source["state"],"tasks":source["task_count"],"sha256":sha(OUT.read_bytes()),"output":str(OUT)},indent=2))
if __name__=="__main__": main()
