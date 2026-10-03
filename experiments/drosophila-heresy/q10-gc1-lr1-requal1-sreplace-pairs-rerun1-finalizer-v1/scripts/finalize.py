from pathlib import Path
import hashlib
import json
import sys
sys.dont_write_bytecode = True
REPO = Path.cwd()
ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-finalizer-v1"
RERUN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-v1"
OLD = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-v1"
PROTOCOL = "REQUAL1-SREPLACE-PAIRS-RERUN1-FINALIZER"
IDENTITY = "q10-gc1-lr1-requal1-sreplace-pairs-rerun1-finalizer-v1"
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest().upper()
def require(ok, msg):
    if not ok: raise RuntimeError(msg)
def write_new(p, value):
    require(not p.exists(), f"sealed output exists: {p}")
    p.write_text(json.dumps(value, indent=2, sort_keys=True)+"\n", encoding="utf-8", newline="\n")
def main():
    c = json.loads((RERUN / "CONTRACT.json").read_text())
    e = json.loads((RERUN / "execution.json").read_text())
    s = json.loads((RERUN / "STATUS.json").read_text())
    checks=[]
    checks.append(("status_complete", e.get("status")=="SREPLACE_PAIRS_COMPLETE"))
    checks.append(("engineering_only", e.get("engineering_only") is True and e.get("scientific_promotion") is False and e.get("behavioral_probe") is False))
    h=e.get("execution_hygiene",{})
    checks.append(("hygiene_bound", h.get("PYTHONDONTWRITEBYTECODE")=="1" and h.get("python_flag_B") is True and h.get("unexpected_path_policy")=="FAIL_PROMOTION"))
    checks.append(("counts", e.get("counts")=={"contexts":8,"exact_alternative":0,"pair_records":4999,"valid_advantage_preserved":3968,"valid_any":4999}))
    checks.append(("status_hash", s.get("execution_sha256")==digest(RERUN/"execution.json")))
    checks.append(("runner_hash", c.get("runner_sha256")==digest(RERUN/"scripts/run_pairs.py")))
    checks.append(("plan_hash", c.get("plan_sha256")==digest(RERUN/"PLAN.md")))
    for b in c["parent_bindings"]:
        p=REPO/b["path"]; checks.append(("parent:"+b["label"], p.is_file() and digest(p)==b["sha256"]))
    expected={"PLAN.md","CONTRACT.json","execution.json","STATUS.json","scripts/run_pairs.py"}|{"shards/"+k+".jsonl" for k in e["shard_hashes"]}
    actual={str(p.relative_to(RERUN)).replace("\\","/") for p in RERUN.rglob("*") if p.is_file()}
    checks.append(("write_surface", actual==expected))
    parity=True
    for slug,hv in e["shard_hashes"].items():
        p=RERUN/"shards"/(slug+".jsonl"); q=OLD/"shards"/(slug+".jsonl")
        checks.append(("shard:"+slug,p.is_file() and digest(p)==hv))
        same=q.is_file() and p.read_bytes()==q.read_bytes(); parity=parity and same; checks.append(("byte_parity:"+slug,same))
    for name,ok in checks: require(ok,name)
    report={"protocol":PROTOCOL,"identity":IDENTITY,"status":"FINALIZER_PASS","rerun_identity":e["identity"],"counts":e["counts"],"checks":{name:True for name,_ in checks},"unexpected_files":sorted(actual-expected),"byte_parity_with_quarantined_run":parity,"scientific_promotion":False,"behavioral_probe":False}
    write_new(ROOT/"REPORT.json",report)
    write_new(ROOT/"STATUS.json",{"protocol":PROTOCOL,"identity":IDENTITY,"status":"FINALIZER_PASS","report_sha256":digest(ROOT/"REPORT.json")})
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__": main()
