from __future__ import annotations
import hashlib,json,pathlib,shutil
from datetime import datetime,timezone
ROOT=pathlib.Path(__file__).resolve().parents[1]; RUN=ROOT/"artifacts/REACH-RUN1"
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def main():
 a=json.loads((RUN/"reach-analysis.json").read_text(encoding="utf-8")); i=json.loads((RUN/"integrity-receipt.json").read_text(encoding="utf-8")); protected=ROOT.parent/"fly-pheno-00"/"provenance/PROTECTED-DH08A-TREE-RECEIPT.json"; prov=ROOT/"provenance";prov.mkdir(parents=True,exist_ok=True);shutil.copy2(protected,prov/protected.name)
 paths=[ROOT/"manifests/REACH-CONTRACT.json",ROOT/"manifests/REACH-MANIFEST.json",ROOT/"manifests/NULL-GRAPH-MANIFEST.json",ROOT/"inputs/banks/training.json",ROOT/"inputs/banks/competence.json",ROOT/"inputs/banks/evaluator-large.json",RUN/"outcomes.jsonl",RUN/"diagnostics.jsonl",RUN/"collection-receipt.json",RUN/"integrity-receipt.json",RUN/"reach-analysis.json",RUN/"reach-summary.csv",RUN/"RESULTS.md",ROOT/"sealed/fly-reach-00.exe",prov/protected.name]
 r={"schema":"FLY-REACH-00-terminal-receipt-v1","study_id":"FLY-REACH-00","run_id":"FLY-REACH-00-RUN1","closed_at_utc":datetime.now(timezone.utc).isoformat(),"status":"CLOSED_ENGINEERING_ONLY","integrity_status":i["status"],"disposition":a["disposition"],"interpretation":a["interpretation"],"arm_support":a["arm_support"],"oracle_large_mean_pass":a["oracle_large_mean_pass"],"native_large_mean":a["native_large_mean"],"native_support_reference_large_mean":a["native_support_reference_large_mean"],"full_support_reference_large_mean":a["full_support_reference_large_mean"],"pheno_reseal_authorized":False,"no_biological_promotion":True,"no_lesions":True,"protected_dh08a_receipt_sha256":sha(prov/protected.name),"artifact_hashes":[{"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":sha(p),"bytes":p.stat().st_size} for p in paths]}
 out=RUN/"REACH-TERMINAL-RECEIPT.json";out.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n",encoding="utf-8");(RUN/"REACH-TERMINAL-RECEIPT.sha256").write_text(f"{sha(out)}  {out.name}\n",encoding="utf-8");print(json.dumps({"status":r["status"],"disposition":r["disposition"],"receipt_sha256":sha(out)},sort_keys=True))
if __name__=="__main__":main()
