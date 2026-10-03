from pathlib import Path
import hashlib,json,sys,collections
sys.dont_write_bytecode=True
REPO=Path.cwd(); ROOT=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-coverage-v1"; PAIR=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-v1"; INTER=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-interaction-v1"; MORPH=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-morphology-v1"
PROTOCOL="REQUAL1-CSC1-COVERAGE"; IDENTITY="q10-gc1-lr1-requal1-csc1-coverage-v1"
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest().upper()
def write_new(p,v):
    if p.exists(): raise RuntimeError(f"sealed output exists {p}")
    p.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
def main():
    rows=[]
    for p in sorted((PAIR/"shards").glob("*.jsonl")): rows.extend(json.loads(p.read_text()))
    irows=[]
    for p in sorted((INTER/"shards").glob("*.jsonl")): irows.extend(json.loads(p.read_text()))
    require=lambda ok,msg: (_ for _ in ()).throw(RuntimeError(msg)) if not ok else None
    require(len(rows)==4999 and len(irows)==4999,"record count drift")
    scalar={"axis_signed":0,"norm_signed":0,"cue_linear_abs_only":0,"full_linear_drive_vector":0,"full_constraint_vector":0,"weight_state_vector":0,"readout_value_vector":0}
    for r in rows:
        for label in ("s","a","b","ab"):
            g=r[label]["geometry"]; scalar["axis_signed"]+=int("final_axis" in g and "target_axis" in g); scalar["norm_signed"]+=int("final_norm" in g and "target_norm" in g); scalar["cue_linear_abs_only"]+=int("cue_linear_absolute_error" in g)
            scalar["full_linear_drive_vector"]+=int("linear_drive_vector" in r[label]); scalar["weight_state_vector"]+=int("weights" in r[label]); scalar["readout_value_vector"]+=int("readout" in r[label])
        scalar["full_constraint_vector"]+=int("constraint_vector" in r)
    report={"protocol":PROTOCOL,"identity":IDENTITY,"status":"CSC1_BLOCKED_RECEIPT_COVERAGE","pair_records":len(rows),"pair_interaction_records":len(irows),"available": {"signed_axis_and_norm_scalars_per_state": scalar["axis_signed"]==len(rows)*4 and scalar["norm_signed"]==len(rows)*4,"cue_linear_error_magnitude_per_state":scalar["cue_linear_abs_only"]==len(rows)*4,"interaction_norm_summaries":True},"missing":{"signed_linear_drive_vectors":scalar["full_linear_drive_vector"]==0,"full_constraint_vectors":scalar["full_constraint_vector"]==0,"committed_weight_vectors":scalar["weight_state_vector"]==0,"readout_value_vectors":scalar["readout_value_vector"]==0},"counts":scalar,"interpretation":"Full CSC1 vector routing/alignment is not identifiable from current receipts. Scalar gate morphology is available; no signed linear-drive direction is available. Missing is not zero.","replay_performed":False,"scientific_promotion":False,"behavioral_probe":False,"parent_hashes":{"pair_execution":digest(PAIR/"execution.json"),"interaction_execution":digest(INTER/"execution.json"),"morphology_report":digest(MORPH/"REPORT.json")}}
    write_new(ROOT/"REPORT.json",report); write_new(ROOT/"STATUS.json",{"protocol":PROTOCOL,"identity":IDENTITY,"status":report["status"],"report_sha256":digest(ROOT/"REPORT.json")}); print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__": main()
