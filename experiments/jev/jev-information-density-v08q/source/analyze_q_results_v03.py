"""Frozen Q response-vector, paired-bootstrap, and same-seed gate analysis."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT=Path(__file__).resolve().parents[3]
Q=ROOT/"experiments/jev-information-density-v08q"
RUN=Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
OUTPUT=RUN/"evaluation"
PACKET=RUN/"q-full-execution-packet-v03.json"
PACKET_SEAL=RUN/"q-full-execution-packet-seal-v03.json"
SEEDS=(2540205348,2603246505,3565067208)
ARMS=("B-DUP","B-MATCHED","B-SHAM","B-SHAM-LOW")
STEPS=(40,80,100,120)
FAMILIES=("exposure_control","respiratory_monitoring","salinity_control","vibration_monitoring")
CONTRACT_SHA="b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc"
ADDENDUM_SHA="363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3"
ANALYZER_SHA="fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4"
BOOTSTRAP_SEED=3344893480
BOOTSTRAP_SEED_SHA="28065fc72b4d20e01eae364ce68a4ecc95b6ce04898099388492870da7308bca"
METRICS=("correct_direction","new_probability_delta","delta_mae","fact_new_map","strict_transition","anchor_old_map","anchor_gold_map_accuracy","sham_l1","sham_map_flip","matched_l1","matched_map_flip")
CELL_KEYS=[(s,"COMMON_INIT",0) for s in ()]


def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()

def read_json(path:Path)->Any:return json.loads(path.read_text(encoding="utf-8"))
def write_json(path:Path,value:Any)->None:
    if path.exists():raise FileExistsError(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp");tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with tmp.open("r+b") as f:f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def need(ok:bool,msg:str)->None:
    if not ok:raise RuntimeError(msg)
def load_module(path:Path,name:str)->Any:
    spec=importlib.util.spec_from_file_location(name,path);need(spec is not None and spec.loader is not None,f"cannot import {path}")
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

def expected_cells()->list[tuple[int,str,int]]:
    out=[]
    for seed in SEEDS:
        out.append((seed,"COMMON_INIT",0))
        for step in STEPS:out.extend((seed,arm,step) for arm in ARMS)
    return out

def read_cell(stream:Any,cell:tuple[int,str,int],metric:Any)->tuple[list[str],list[str],dict[str,dict[str,float]]]:
    seed,arm,step=cell;grouped:dict[str,dict[str,dict[str,Any]]]=defaultdict(dict);families={}
    for _ in range(8000):
        line=stream.readline()
        need(bool(line),f"Q prediction stream ended in {cell}")
        row=json.loads(line)
        need((int(row["seed"]),str(row["arm"]),int(row["global_step"]))==cell,f"Q prediction cell order mismatch at {cell}")
        nid=str(row["neighborhood_id"]);view=str(row["view"])
        need(view not in grouped[nid],f"duplicate Q view {nid}/{view}")
        grouped[nid][view]=row;families[nid]=str(row["family_id"]).split(":")[-1]
    need(len(grouped)==2000 and all(set(rows)=={"anchor","fact_flip","sham","matched_neutral"} for rows in grouped.values()),f"Q cell lacks 2000 complete four-view neighborhoods: {cell}")
    nids=sorted(grouped)
    vals={}
    for nid in nids:
        result=metric.neighborhood_metrics(grouped[nid])
        vals[nid]={k:float(result[k]) for k in METRICS}
        need(str(result["family_id"])==families[nid],f"Q metric family mismatch {nid}")
    return nids,[families[n] for n in nids],vals

def make_plan(nids:list[str],families:list[str])->tuple[np.ndarray,str,list[str],np.ndarray]:
    by={family:[] for family in FAMILIES}
    for i,(nid,fam) in enumerate(zip(nids,families,strict=True)):
        need(fam in by,f"uncontracted Q family {fam}");by[fam].append((nid,i))
    ordered=[]
    for fam in FAMILIES:
        block=sorted(by[fam]);need(len(block)==500,f"Q bootstrap family support mismatch {fam}");ordered.extend((nid,i,fam) for nid,i in block)
    ordered_ids=[x[0] for x in ordered];global_indices=np.asarray([x[1] for x in ordered],dtype=np.int32);labels=np.asarray([x[2] for x in ordered],dtype=object)
    rng=np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED));plan=np.empty((10_000,2_000),dtype=np.int32)
    offset=0
    for fam in FAMILIES:
        members=np.flatnonzero(labels==fam).astype(np.int32,copy=False)
        local=rng.integers(0,500,size=(10_000,500),dtype=np.int32)
        plan[:,offset:offset+500]=members[local];offset+=500
    digest=hashlib.sha256(np.asarray(plan,dtype="<i4").tobytes(order="C")).hexdigest()
    return plan,digest,ordered_ids,global_indices

def boot(values:np.ndarray,plan:np.ndarray)->dict[str,Any]:
    sample=values[plan].mean(axis=1)
    interval=[float(x) for x in np.quantile(sample,[0.025,0.975],method="linear")]
    return {"mean":float(values.mean()),"ci95":interval,"ci_excludes_zero":interval[0]>0.0 or interval[1]<0.0,"replicates":10_000}

def summarize(values:dict[str,dict[str,float]],families_by_id:dict[str,str],ids:list[str])->dict[str,Any]:
    out={"n":len(ids),"overall":{},"by_family":{}}
    for key in METRICS:
        out["overall"][key]=float(np.mean([values[n][key] for n in ids]))
    for fam in FAMILIES:
        rows=[values[n] for n in ids if families_by_id[n]==fam]
        need(len(rows)==500,f"Q metric family cell support mismatch {fam}")
        out["by_family"][fam]={k:float(np.mean([r[k] for r in rows])) for k in METRICS}
    cells={"A_old_AND_F_new":0,"A_old_AND_NOT_F_new":0,"NOT_A_old_AND_F_new":0,"NOT_A_old_AND_NOT_F_new":0}
    for nid in ids:
        a=bool(values[nid]["anchor_old_map"]);f=bool(values[nid]["fact_new_map"])
        cells[{(True,True):"A_old_AND_F_new",(True,False):"A_old_AND_NOT_F_new",(False,True):"NOT_A_old_AND_F_new",(False,False):"NOT_A_old_AND_NOT_F_new"}[(a,f)]]+=1
    out["four_cell_A_F_decomposition"]={k:{"count":v,"rate":v/len(ids)} for k,v in cells.items()}
    return out

def main()->int:
    stage="prediction_seal_preflight"
    try:
        contract=Q/"contracts/q-analysis-contract-v02.json";addendum=Q/"contracts/q-execution-addendum-v01.json"
        need(sha(contract)==CONTRACT_SHA and sha(addendum)==ADDENDUM_SHA,"Q analysis parent hash mismatch")
        packet=read_json(PACKET);packet_seal=read_json(PACKET_SEAL)
        need(packet.get("schema")=="jev-v08q-full-execution-packet-v03" and packet.get("authorization",{}).get("phase")=="Q_FULL_FROZEN_RUN_EVALUATION_AND_ANALYSIS" and packet.get("authorization",{}).get("explicit_user_authorization") is True and packet_seal.get("packet_sha256")==sha(PACKET),"Q full-execution authorization packet invalid")
        for binding in packet.get("implementation_bindings",[]):
            source=ROOT/binding["path"];need(source.is_file() and sha(source)==binding["sha256"],f"Q analysis implementation binding changed: {binding['path']}")
        need(sha(ROOT/"experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py")==ANALYZER_SHA,"Q frozen metric implementation hash mismatch")
        inference=read_json(OUTPUT/"inference-receipt-v01.json");tree=read_json(OUTPUT/"raw-prediction-hash-tree-v01.json")
        pred=OUTPUT/"raw-predictions-v01.jsonl"
        need(inference.get("status")=="Q_ALL_51_CELLS_INFERRED_AND_SEALED" and inference.get("prediction_sha256")==sha(pred) and tree.get("raw_predictions",{}).get("sha256")==sha(pred) and tree.get("prediction_rows")==408_000,"Q raw prediction seal invalid")
        need(tree.get("execution_packet_sha256")==sha(PACKET) and read_json(OUTPUT/"panel-opening-receipt-v01.json").get("execution_packet_sha256")==sha(PACKET),"Q prediction/packet binding mismatch")
        metric=load_module(ROOT/"experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py","q_frozen_neighborhood_metrics")
        summaries={};cells_meta=[];canonical_ids=None;canonical_families=None;cell_values={}
        metrics_path=OUTPUT/"neighborhood-metrics-v01.jsonl"
        with pred.open("r",encoding="utf-8") as source, metrics_path.open("x",encoding="utf-8",newline="\n") as dest:
            for cell in expected_cells():
                ids,fams,vals=read_cell(source,cell,metric)
                if canonical_ids is None:
                    need(set(fams)==set(FAMILIES),"Q first cell family set mismatch")
                    canonical_ids=ids;canonical_families=fams
                else:
                    need(ids==canonical_ids and fams==canonical_families,"Q paired cell event order/family identity mismatch")
                key=f"{cell[0]}/{cell[1]}/{cell[2]}";cell_values[cell]=vals
                family_map={nid:fam for nid,fam in zip(ids,fams,strict=True)}
                summaries[key]=summarize(vals,family_map,ids)
                for nid in ids:
                    dest.write(json.dumps({"seed":cell[0],"arm":cell[1],"step":cell[2],"neighborhood_id":nid,"family_id":family_map[nid],**vals[nid]},separators=(",",":"))+"\n")
                cells_meta.append({"seed":cell[0],"arm":cell[1],"step":cell[2],"neighborhoods":len(ids)})
            need(not source.readline(),"extra Q prediction rows after 51-cell matrix")
            dest.flush();os.fsync(dest.fileno())
        assert canonical_ids is not None and canonical_families is not None
        plan,plan_hash,ordered_ids,global_indices=make_plan(canonical_ids,canonical_families)
        plan_path=OUTPUT/"shared-bootstrap-resample-plan-v01.npy"
        with plan_path.open("xb") as f:np.save(f,plan,allow_pickle=False);f.flush();os.fsync(f.fileno())
        saved=np.load(plan_path,mmap_mode="r",allow_pickle=False)
        need(saved.shape==(10_000,2_000) and saved.dtype==np.int32 and hashlib.sha256(np.asarray(saved,dtype="<i4").tobytes(order="C")).hexdigest()==plan_hash,"Q bootstrap plan persistence mismatch")
        plan_ordered=np.asarray(saved,dtype=np.int32)
        contrasts={}
        step=120
        for seed in SEEDS:
            for left,right,names in (("B-SHAM-LOW","B-SHAM",METRICS),("B-SHAM-LOW","B-DUP",("sham_l1","sham_map_flip","matched_l1","matched_map_flip"))):
                lv=cell_values[(seed,left,step)];rv=cell_values[(seed,right,step)]
                for name in names:
                    diff=np.asarray([lv[n][name]-rv[n][name] for n in ordered_ids],dtype=np.float64)
                    contrasts[f"{seed}/{left}_minus_{right}/{name}"]=boot(diff,plan_ordered)
        labels_by_seed={}
        gate_module=load_module(Q/"source/q_analysis_rules_v02.py","q_frozen_seed_rules")
        for seed in SEEDS:
            def mean(arm:str,key:str)->float:return float(summaries[f"{seed}/{arm}/{step}"]["overall"][key])
            low_fam=summaries[f"{seed}/B-SHAM-LOW/{step}"]["by_family"]
            sham_fam=summaries[f"{seed}/B-SHAM/{step}"]["by_family"]
            gate_input={"delta_p_new_low_minus_sham":mean("B-SHAM-LOW","new_probability_delta")-mean("B-SHAM","new_probability_delta"),"sham_low_correct_direction":mean("B-SHAM-LOW","correct_direction"),"sham_correct_direction":mean("B-SHAM","correct_direction"),"a_old_low_minus_sham":mean("B-SHAM-LOW","anchor_old_map")-mean("B-SHAM","anchor_old_map"),"family_a_old_low_minus_sham":{f:low_fam[f]["anchor_old_map"]-sham_fam[f]["anchor_old_map"] for f in FAMILIES},"dup_sham_l1":mean("B-DUP","sham_l1"),"dup_matched_neutral_l1":mean("B-DUP","matched_l1"),"sham_low_sham_l1":mean("B-SHAM-LOW","sham_l1"),"sham_low_matched_neutral_l1":mean("B-SHAM-LOW","matched_l1"),"dup_sham_map_flip_rate":mean("B-DUP","sham_map_flip"),"dup_matched_neutral_map_flip_rate":mean("B-DUP","matched_map_flip"),"sham_low_sham_map_flip_rate":mean("B-SHAM-LOW","sham_map_flip"),"sham_low_matched_neutral_map_flip_rate":mean("B-SHAM-LOW","matched_map_flip"),"f_new_low_minus_sham":mean("B-SHAM-LOW","fact_new_map")-mean("B-SHAM","fact_new_map"),"strict_low_minus_sham":mean("B-SHAM-LOW","strict_transition")-mean("B-SHAM","strict_transition")}
            labels_by_seed[str(seed)]={"inputs":gate_input,"labels":gate_module.seed_gate_record(gate_input)}
        label_payload=gate_module.cohort_labels({seed:record["inputs"] for seed,record in labels_by_seed.items()})
        result={"status":"Q_FROZEN_RESPONSE_ANALYSIS_COMPLETE","identity":"JEV-V08Q-SINGLE-DOSE-GAIN","execution_packet_sha256":sha(PACKET),"execution_packet_seal_sha256":sha(PACKET_SEAL),"analysis_contract_sha256":CONTRACT_SHA,"execution_addendum_sha256":ADDENDUM_SHA,"raw_prediction_tree_sha256":sha(OUTPUT/"raw-prediction-hash-tree-v01.json"),"prediction_sha256":sha(pred),"metric_implementation_sha256":ANALYZER_SHA,"gate_rule_implementation_sha256":sha(Q/"source/q_analysis_rules_v02.py"),"cell_count":51,"prediction_rows":408_000,"neighborhood_metric_rows":102_000,"cells":cells_meta,"response_summaries":summaries,"step120_paired_contrasts_with_shared_bootstrap":contrasts,"shared_bootstrap":{"seed":BOOTSTRAP_SEED,"seed_derivation_sha256":BOOTSTRAP_SEED_SHA,"plan_sha256":plan_hash,"plan_file_sha256":sha(plan_path),"shape":list(plan.shape),"dtype":str(plan.dtype),"family_order":list(FAMILIES),"quantile_method":"linear","interval":"paired neighborhood 95% interval conditional on seed and fixed panel"},"same_seed_step120_gate_inputs_and_labels":labels_by_seed,"cohort_labels":label_payload,"pooled_seed_inference":False,"checkpoint_selection":False,"created_at_utc":datetime.now(timezone.utc).isoformat()}
        result_path=OUTPUT/"q-response-analysis-v01.json";write_json(result_path,result)
        report=OUTPUT/"q-response-analysis-v01.md"
        lines=["# JEV v0.8Q Single-Dose Gain Results","",f"Raw prediction root: `{sha(OUTPUT/'raw-prediction-hash-tree-v01.json')}`","", "## Step 120 by seed", "", "| Seed | Arm | Δp_new | Direction | F_new | Strict | Sham L1 | Matched L1 | A_old |", "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
        for seed in SEEDS:
            for arm in ARMS:
                s=summaries[f"{seed}/{arm}/120"]["overall"]
                lines.append(f"| {seed} | {arm} | {s['new_probability_delta']:.6f} | {s['correct_direction']:.4f} | {s['fact_new_map']:.4f} | {s['strict_transition']:.4f} | {s['sham_l1']:.4f} | {s['matched_l1']:.4f} | {s['anchor_old_map']:.4f} |")
        lines += ["", "## Frozen same-seed labels", "", "```json", json.dumps({"seeds":{k:v["labels"] for k,v in labels_by_seed.items()},"cohort":label_payload},indent=2), "```", "", "These are three observed paired trajectories on one fixed panel. Bootstrap intervals quantify neighborhood uncertainty conditional on each seed and this panel; they do not estimate optimizer-seed variation.",""]
        report.write_text("\n".join(lines),encoding="utf-8")
        with report.open("r+b") as f:f.flush();os.fsync(f.fileno())
        outputs=[metrics_path,plan_path,result_path,report]
        entries=[{"path":p.name,"bytes":p.stat().st_size,"sha256":sha(p)} for p in outputs]
        root=hashlib.sha256("".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in sorted(entries,key=lambda x:x["path"])).encode()).hexdigest()
        seal={"status":"Q_ANALYSIS_OUTPUTS_SEALED","identity":"JEV-V08Q-SINGLE-DOSE-GAIN","execution_packet_sha256":sha(PACKET),"execution_packet_seal_sha256":sha(PACKET_SEAL),"analysis_root_sha256":root,"output_count":len(entries),"outputs":entries,"prediction_hash_tree_sha256":sha(OUTPUT/"raw-prediction-hash-tree-v01.json"),"inference_receipt_sha256":sha(OUTPUT/"inference-receipt-v01.json"),"analysis_contract_sha256":CONTRACT_SHA,"execution_addendum_sha256":ADDENDUM_SHA,"metric_implementation_sha256":ANALYZER_SHA,"analysis_implementation_sha256":sha(Path(__file__).resolve()),"panel_open_count":1,"result_sealed_at_utc":datetime.now(timezone.utc).isoformat()}
        write_json(OUTPUT/"q-analysis-seal-v01.json",seal)
        print(json.dumps({"status":seal["status"],"analysis_root_sha256":root,"seal_sha256":sha(OUTPUT/"q-analysis-seal-v01.json"),"cohort_labels":label_payload},indent=2),flush=True)
        return 0
    except BaseException as exc:
        failure=OUTPUT/"analysis-failure-receipt-v01.json"
        if OUTPUT.exists() and not failure.exists():write_json(failure,{"status":"Q_ANALYSIS_FAILED_CLOSED_PARTIAL_OUTPUTS_PRESERVED","stage":stage,"exception_type":type(exc).__name__,"exception":str(exc),"automatic_retry":False,"failed_at_utc":datetime.now(timezone.utc).isoformat()})
        raise

if __name__=="__main__":raise SystemExit(main())
