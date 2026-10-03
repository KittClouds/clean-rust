from pathlib import Path
import concurrent.futures
import hashlib
import importlib.util
import json
import math
import os
import sys
sys.dont_write_bytecode = True
REPO=Path.cwd()
ROOT=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-interaction-v1"
RERUN=REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-v1"
PROTOCOL="REQUAL1-SREPLACE-PAIRS-RERUN1-INTERACTION"
IDENTITY="q10-gc1-lr1-requal1-sreplace-pairs-rerun1-interaction-v1"
RERUN_SCRIPT=RERUN/"scripts/run_pairs.py"
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest().upper()
def require(ok,msg):
    if not ok: raise RuntimeError(msg)
def write_new(p,v):
    require(not p.exists(),f"sealed output exists: {p}")
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
def load_rerun():
    spec=importlib.util.spec_from_file_location("requal_pair_runner",RERUN_SCRIPT)
    module=importlib.util.module_from_spec(spec); require(spec.loader is not None,"runner loader missing"); spec.loader.exec_module(module); return module
def stats(values):
    vals=tuple(float(x) for x in values); absvals=tuple(abs(x) for x in vals)
    return {"l0_exact":sum(x!=0.0 for x in vals),"l1":math.fsum(absvals),"l2":math.sqrt(math.fsum(x*x for x in vals)),"linf":max(absvals,default=0.0),"length":len(vals)}
def interaction_stats(ab,a,b,s): return stats(tuple(x-y-z+w for x,y,z,w in zip(ab,a,b,s)))
def drive(rp,state,weights):
    return tuple(math.fsum(weights[i]-state.base_weights[i] for i in row) for row in state.rows)
def run_context(args):
    endpoint,set_index=args; rp=load_rerun(); pf,builder=rp.load_modules(); _,data=builder.fresh_lineage(rp.CLOSURE_REPO,pf); key=(endpoint,set_index); state=next(item for item in data["states"] if item.key==key)
    ref=json.loads((rp.REF_ROOT/"execution.json").read_text()); ref_result=next(x for x in ref["results"] if x["endpoint"]==endpoint and int(x["set_index"])==set_index); pf5=json.loads(rp.PF5_CONTRACT.read_text())
    s=rp.verify_s(pf,state,ref_result,pf5); vbits=rp.mapping_bits(pf,state,ref_result["best_valid"]["canonical_mapping"]); v=rp.replay(pf,state,vbits,pf5); require(v["final_geometry_pass"] and v["score"]==ref_result["best_valid"]["score"],f"V drift {key}")
    domain=json.loads(rp.PAIR_EXECUTION.read_text()); slug=rp.case_slug(key); pair_path=rp.PAIR_DOMAIN_ROOT/"shards"/(slug+".jsonl"); require(rp.digest(pair_path)==str(domain["shard_hashes"][slug]).upper(),f"domain drift {key}"); pair_rows=json.loads(pair_path.read_text())
    palette={}
    for line in rp.PALETTE.read_text().splitlines():
        item=json.loads(line)
        if str(item["identity"][0])==endpoint and int(item["identity"][1])==set_index: palette[int(item["identity"][2])]=item
    output=[]
    for pair in pair_rows:
        left,right=pair["a"],pair["b"]; require(int(left["group"])!=int(right["group"]),f"same group {key}")
        abits=rp.apply_candidate(pf,state,s["bits"],palette[int(left["group"])],str(left["to"])); bbits=rp.apply_candidate(pf,state,s["bits"],palette[int(right["group"])],str(right["to"])); abits=list(s["bits"])
        for candidate in (left,right): abits=list(rp.apply_candidate(pf,state,tuple(abits),palette[int(candidate["group"])],str(candidate["to"])))
        a=rp.replay(pf,state,abits if False else rp.apply_candidate(pf,state,s["bits"],palette[int(left["group"])],str(left["to"])),pf5); b=rp.replay(pf,state,rp.apply_candidate(pf,state,s["bits"],palette[int(right["group"])],str(right["to"])),pf5); ab=rp.replay(pf,state,tuple(abits),pf5)
        expected=(pair["singleton_weight_state_sha256"],pair["singleton_readout_sha256"]) if False else None
        require(a["weight_state_sha256"]==str(left["singleton_weight_state_sha256"]).upper() and a["readout_sha256"]==str(left["singleton_readout_sha256"]).upper(),f"A drift {key} {pair['pair_index']}")
        require(b["weight_state_sha256"]==str(right["singleton_weight_state_sha256"]).upper() and b["readout_sha256"]==str(right["singleton_readout_sha256"]).upper(),f"B drift {key} {pair['pair_index']}")
        prior=json.loads((RERUN/"shards"/(slug+".jsonl")).read_text()) if False else None
        sread=tuple(pf.from_bits(x) for x in s["readout"]); aread=tuple(pf.from_bits(x) for x in a["readout"]); bread=tuple(pf.from_bits(x) for x in b["readout"]); abread=tuple(pf.from_bits(x) for x in ab["readout"])
        sd=drive(rp,state,s["weights"]); ad=drive(rp,state,a["weights"]); bd=drive(rp,state,b["weights"]); abd=drive(rp,state,ab["weights"])
        ga,gb,gab,gs=a["geometry"],b["geometry"],ab["geometry"],s["geometry"]
        output.append({"pair_index":int(pair["pair_index"]),"case":[endpoint,set_index],"weight":interaction_stats(ab["weights"],a["weights"],b["weights"],s["weights"]),"readout":interaction_stats(abread,aread,bread,sread),"linear_drive":interaction_stats(abd,ad,bd,sd),"axis_interaction":gab["final_axis"]-ga["final_axis"]-gb["final_axis"]+gs["final_axis"],"norm_interaction":gab["final_norm"]-ga["final_norm"]-gb["final_norm"]+gs["final_norm"],"outcome":pair.get("outcome")})
    require(len(output)==len(pair_rows),f"cardinality drift {key}"); return key,output
def main():
    require(os.environ.get("PYTHONDONTWRITEBYTECODE")=="1","environment hygiene missing"); require(sys.dont_write_bytecode,"bytecode enabled"); require(not (ROOT/"scripts"/"__pycache__").exists(),"preflight cache exists")
    all_rows={}
    keys=(("seed9731-L-tau16.json",2),("seed9731-L-tau4.json",3),("seed9731-R-tau16.json",1),("seed9731-R-tau16.json",3),("seed9731-R-tau4.json",0),("seed9731-R-tau4.json",1),("seed9731-R-tau4.json",2),("seed9731-R-tau4.json",3))
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(run_context,key) for key in keys]
            for future in futures:
                key,rows=future.result(); slug=f"{key[0].removesuffix('.json')}__set{key[1]}"; all_rows[slug]=rows; write_new(ROOT/"shards"/(slug+".jsonl"),rows); print(json.dumps({"context":[key[0],key[1]],"records":len(rows),"status":"INTERACTION_REPLAY_COMPLETE"},sort_keys=True),flush=True)
        ordered=[r for key in keys for r in all_rows[f"{key[0].removesuffix('.json')}__set{key[1]}"]]; require(len(ordered)==4999,f"total count {len(ordered)}")
        execution={"protocol":PROTOCOL,"identity":IDENTITY,"status":"INTERACTION_REPLAY_COMPLETE","engineering_only":True,"scientific_promotion":False,"behavioral_probe":False,"historical_lr1_results_used_as_evidence":False,"execution_hygiene":{"python_flag_B":bool(sys.dont_write_bytecode),"PYTHONDONTWRITEBYTECODE":os.environ.get("PYTHONDONTWRITEBYTECODE"),"preflight_no_pycache":True,"unexpected_path_policy":"FAIL_PROMOTION","write_allowlist":["shards/*.jsonl","execution.json","STATUS.json"]},"parent_rerun_execution_sha256":digest(RERUN/"execution.json"),"parent_morphology_report_sha256":digest(REPO/"experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-morphology-v1/REPORT.json"),"counts":{"contexts":8,"pair_records":len(ordered),"weight_nonzero":sum(r["weight"]["l0_exact"]>0 for r in ordered),"readout_nonzero":sum(r["readout"]["l0_exact"]>0 for r in ordered),"linear_drive_nonzero":sum(r["linear_drive"]["l0_exact"]>0 for r in ordered),"axis_nonzero":sum(r["axis_interaction"]!=0.0 for r in ordered),"norm_nonzero":sum(r["norm_interaction"]!=0.0 for r in ordered)},"shard_hashes":{slug:digest(ROOT/"shards"/(slug+".jsonl")) for slug in sorted(all_rows)}}
        write_new(ROOT/"execution.json",execution); write_new(ROOT/"STATUS.json",{"protocol":PROTOCOL,"identity":IDENTITY,"status":execution["status"],"execution_sha256":digest(ROOT/"execution.json")}); print(json.dumps(execution,indent=2,sort_keys=True)); return 0
    except Exception as exc:
        write_new(ROOT/"execution.json",{"protocol":PROTOCOL,"identity":IDENTITY,"status":"BLOCKED_INTERACTION_REPLAY","engineering_only":True,"scientific_promotion":False,"completed_shards":sorted(all_rows),"error_type":type(exc).__name__,"error":str(exc)}); return 2
if __name__=="__main__": raise SystemExit(main())
