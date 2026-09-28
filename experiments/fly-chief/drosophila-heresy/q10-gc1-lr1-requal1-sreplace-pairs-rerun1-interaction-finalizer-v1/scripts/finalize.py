from pathlib import Path
import hashlib,json,math,statistics,sys
sys.dont_write_bytecode=True
REPO=Path.cwd(); ROOT=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-interaction-finalizer-v1"; PARENT=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-interaction-v1"; RERUN=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-v1"
PROTOCOL="REQUAL1-SREPLACE-PAIRS-RERUN1-INTERACTION-FINALIZER"; IDENTITY="q10-gc1-lr1-requal1-sreplace-pairs-rerun1-interaction-finalizer-v1"
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest().upper()
def require(ok,msg):
    if not ok: raise RuntimeError(msg)
def write_new(p,v):
    require(not p.exists(),f"sealed output exists {p}"); p.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
def main():
    c=json.loads((PARENT/"CONTRACT.json").read_text()); e=json.loads((PARENT/"execution.json").read_text()); s=json.loads((PARENT/"STATUS.json").read_text()); checks=[]; vals=[]; total=0
    checks += [("status_complete",e.get("status")=="INTERACTION_REPLAY_COMPLETE"),("counts",e.get("counts")=={"axis_nonzero":0,"contexts":8,"linear_drive_nonzero":0,"norm_nonzero":1878,"pair_records":4999,"readout_nonzero":0,"weight_nonzero":0}),("status_hash",s.get("execution_sha256")==digest(PARENT/"execution.json")),("runner_hash",c.get("runner_sha256")==digest(PARENT/"scripts/interaction.py")),("plan_hash",c.get("plan_sha256")==digest(PARENT/"PLAN.md"))]
    for b in c["parent_bindings"]:
        p=REPO/b["path"]; checks.append(("parent:"+b["label"],p.is_file() and digest(p)==b["sha256"]))
    expected={"PLAN.md","CONTRACT.json","execution.json","STATUS.json","scripts/interaction.py"}|{"shards/"+k+".jsonl" for k in e["shard_hashes"]}; actual={str(p.relative_to(PARENT)).replace("\\","/") for p in PARENT.rglob("*") if p.is_file()}; checks.append(("write_surface",actual==expected))
    for slug,h in e["shard_hashes"].items():
        p=PARENT/"shards"/(slug+".jsonl"); q=RERUN/"shards"/(slug+".jsonl"); checks.append(("shard:"+slug,p.is_file() and digest(p)==h)); ir=json.loads(p.read_text()); rr=json.loads(q.read_text()); checks.append(("pair_index_coverage:"+slug,[x["pair_index"] for x in ir]==[x["pair_index"] for x in rr])); total+=len(ir)
        for x in ir:
            vals.append(abs(float(x["norm_interaction"]))); checks.append(("non_norm_zero:"+slug, x["weight"]["l0_exact"]==0 and x["readout"]["l0_exact"]==0 and x["linear_drive"]["l0_exact"]==0 and x["axis_interaction"]==0.0))
    checks.append(("record_count",total==4999))
    for name,ok in checks: require(ok,name)
    report={"protocol":PROTOCOL,"identity":IDENTITY,"status":"INTERACTION_FINALIZER_PASS","parent_execution_sha256":digest(PARENT/"execution.json"),"checks_passed":len(checks),"checks_total":len(checks),"counts":e["counts"],"non_norm_interaction_all_exact_zero":True,"norm_interaction":{"nonzero":sum(v!=0.0 for v in vals),"max_abs":max(vals,default=0.0),"median_abs":statistics.median(vals) if vals else 0.0,"p95_abs":statistics.quantiles(vals,n=20)[18] if len(vals)>=20 else 0.0,"mean_abs":statistics.fmean(vals) if vals else 0.0},"scientific_promotion":False,"behavioral_probe":False}
    write_new(ROOT/"REPORT.json",report); write_new(ROOT/"STATUS.json",{"protocol":PROTOCOL,"identity":IDENTITY,"status":"INTERACTION_FINALIZER_PASS","report_sha256":digest(ROOT/"REPORT.json")}); print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__": main()
