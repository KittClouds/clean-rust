from pathlib import Path
import hashlib
import json
import sys
import collections
sys.dont_write_bytecode = True
REPO=Path.cwd()
ROOT=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-morphology-v1"
PARENT=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-v1"
REF=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
PROTOCOL="REQUAL1-SREPLACE-PAIRS-RERUN1-MORPHOLOGY"
IDENTITY="q10-gc1-lr1-requal1-sreplace-pairs-rerun1-morphology-v1"
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest().upper()
def score_key(s): return (int(s["mismatch_count"]),int(s["total_ulp_distance"]),float(s["residual_l2"]),float(s["maximum_absolute_residual"]))
def write_new(p,v):
    if p.exists(): raise RuntimeError(f"sealed output exists: {p}")
    p.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
def main():
    parent_exec=json.loads((PARENT/"execution.json").read_text())
    refs={(x["endpoint"],int(x["set_index"])):x["best_valid"]["score"] for x in json.loads((REF/"execution.json").read_text())["results"]}
    rows=[]
    for p in sorted((PARENT/"shards").glob("*.jsonl")): rows.extend(json.loads(p.read_text()))
    counts=collections.Counter(); cases=collections.defaultdict(collections.Counter)
    for r in rows:
        v=refs[(r["case"][0],int(r["case"][1]))]; a=r["a"]; b=r["b"]; ab=r["ab"]
        av=bool(a["final_geometry_pass"]); bv=bool(b["final_geometry_pass"]); cls=("V" if av else "I")+("V" if bv else "I")
        k_a=score_key(a["score"]); k_b=score_key(b["score"]); k_ab=score_key(ab["score"]); k_v=score_key(v)
        rel=lambda k: "BETTER_V" if k<k_v else ("TIE_V" if k==k_v else "WORSE_V")
        c=cases[r["case"][0]+"|"+str(r["case"][1])]; c["pairs"]+=1; c["pair_"+cls]+=1; c["pair_"+cls+"_"+rel(k_ab)]+=1
        counts["pairs"]+=1; counts["pair_"+cls]+=1; counts["pair_"+cls+"_"+rel(k_ab)]+=1
        best=min(k_a,k_b)
        if k_ab<best: counts["ab_better_than_best_single"]+=1
        elif k_ab==best: counts["ab_equal_best_single"]+=1
        else: counts["ab_worse_than_both"]+=1
        if k_ab<k_a: counts["ab_better_than_a"]+=1
        if k_ab<k_b: counts["ab_better_than_b"]+=1
        if not av or not bv: counts["at_least_one_single_invalid"]+=1
        if not av and not bv: counts["both_single_invalid"]+=1
        if rel(k_a)!="BETTER_V" or rel(k_b)!="BETTER_V": counts["at_least_one_single_not_better_V"]+=1
        if rel(k_a)!="BETTER_V" and rel(k_b)!="BETTER_V": counts["both_single_not_better_V"]+=1
        if r["outcome"]=="VALID_ADVANTAGE_PRESERVED":
            counts["success_pairs"]+=1
            if not av or not bv: counts["success_at_least_one_single_invalid"]+=1
            if not av and not bv: counts["success_both_single_invalid"]+=1
            if rel(k_a)!="BETTER_V" or rel(k_b)!="BETTER_V": counts["success_at_least_one_single_not_better_V"]+=1
            if rel(k_a)!="BETTER_V" and rel(k_b)!="BETTER_V": counts["success_both_single_not_better_V"]+=1
    require=lambda ok,msg: (_ for _ in ()).throw(RuntimeError(msg)) if not ok else None
    require(counts["pairs"]==int(parent_exec["counts"]["pair_records"]),"pair count drift")
    require(counts["success_pairs"]==int(parent_exec["counts"]["valid_advantage_preserved"]),"success count drift")
    report={"protocol":PROTOCOL,"identity":IDENTITY,"status":"MORPHOLOGY_COMPLETE","parent_execution_sha256":digest(PARENT/"execution.json"),"reference_execution_sha256":digest(REF/"execution.json"),"counts":dict(sorted(counts.items())),"per_context":{k:dict(sorted(v.items())) for k,v in sorted(cases.items())},"replay_performed":False,"scientific_promotion":False,"behavioral_probe":False}
    write_new(ROOT/"REPORT.json",report); write_new(ROOT/"STATUS.json",{"protocol":PROTOCOL,"identity":IDENTITY,"status":"MORPHOLOGY_COMPLETE","report_sha256":digest(ROOT/"REPORT.json")}); print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__": main()
