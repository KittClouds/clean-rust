"""Clean-process Q seal, matrix, bootstrap, and same-seed label verification."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT=Path(__file__).resolve().parents[3]
Q=ROOT/"experiments/jev-information-density-v08q"
RUN=Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
PANEL=Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
TRAIN=RUN/"training"; EVAL=RUN/"evaluation"
SEEDS=(2540205348,2603246505,3565067208)
ARMS=("B-DUP","B-MATCHED","B-SHAM","B-SHAM-LOW")
STEPS=(40,80,100,120)
FAMILIES=("exposure_control","respiratory_monitoring","salinity_control","vibration_monitoring")
METRICS=("correct_direction","new_probability_delta","delta_mae","fact_new_map","strict_transition","anchor_old_map","anchor_gold_map_accuracy","sham_l1","sham_map_flip","matched_l1","matched_map_flip")
PANEL_ROOT="1b99d39ab6bfed8173a5410f6c8ae0df442aae03038e31bab46b779bd1e039a6"
RUN_CONTRACT="5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae"
ANALYSIS_CONTRACT="b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc"
ADDENDUM="363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3"
PACKET=RUN/"q-full-execution-packet-v05.json"
PACKET_SEAL=RUN/"q-full-execution-packet-seal-v05.json"
RECEIPT=RUN/"independent-verification-v01.json"

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()
def read_json(p:Path)->Any:return json.loads(p.read_text(encoding="utf-8"))
def read_jsonl(p:Path)->list[dict[str,Any]]:
    with p.open("r",encoding="utf-8") as f:return [json.loads(x) for x in f if x.strip()]
def need(ok:bool,msg:str)->None:
    if not ok:raise RuntimeError(msg)
def load_module(path:Path,name:str)->Any:
    spec=importlib.util.spec_from_file_location(name,path);need(spec is not None and spec.loader is not None,f"cannot import {path}")
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def write_json(path:Path,value:Any)->None:
    if path.exists():raise FileExistsError(path)
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
def expected_cells()->list[tuple[int,str,int]]:
    x=[]
    for seed in SEEDS:
        x.append((seed,"COMMON_INIT",0))
        for step in STEPS:x.extend((seed,arm,step) for arm in ARMS)
    return x
def close(a:float,b:float)->bool:return abs(float(a)-float(b))<=1e-12

def verify_prediction_matrix()->dict[str,Any]:
    tree=read_json(EVAL/"raw-prediction-hash-tree-v01.json");pred=EVAL/"raw-predictions-v01.jsonl"
    need(sha(pred)==tree["raw_predictions"]["sha256"] and tree["prediction_rows"]==408_000 and tree["cell_count"]==51,"Q raw prediction root/count mismatch")
    opening=read_json(EVAL/"panel-opening-receipt-v01.json")
    need(opening.get("opening_count")==1 and opening.get("panel_root_sha256")==PANEL_ROOT and opening.get("training_seal_sha256")==sha(TRAIN/"training-seal-manifest.json") and opening.get("execution_packet_sha256")==sha(PACKET),"Q panel opening receipt mismatch")
    counts={};current=None;per_cell=0;views=set();nids=set();total=0
    with pred.open("r",encoding="utf-8") as f:
        for line in f:
            if not line.strip():continue
            row=json.loads(line);cell=(int(row["seed"]),str(row["arm"]),int(row["global_step"]))
            if current is None:current=cell
            if cell!=current:
                need(per_cell==8000 and len(nids)==2000 and all(v=={"anchor","fact_flip","sham","matched_neutral"} for v in views.values()),f"Q prediction cell malformed: {current}")
                counts[f"{current[0]}/{current[1]}/{current[2]}"]=per_cell
                current=cell;per_cell=0;views={};nids=set()
            nid=str(row["neighborhood_id"]);views.setdefault(nid,set()).add(str(row["view"]))
            nids.add(nid);per_cell+=1;total+=1
        if current is not None:
            need(per_cell==8000 and len(nids)==2000 and all(v=={"anchor","fact_flip","sham","matched_neutral"} for v in views.values()),f"Q final prediction cell malformed: {current}")
            counts[f"{current[0]}/{current[1]}/{current[2]}"]=per_cell
    expected=[f"{s}/{a}/{step}" for s,a,step in expected_cells()]
    need(list(counts)==expected and total==408_000,"Q prediction cell order or total mismatch")
    need(tree.get("execution_packet_sha256")==sha(PACKET),"Q prediction tree execution packet mismatch")
    return {"prediction_sha256":sha(pred),"prediction_rows":total,"cell_count":len(counts),"panel_open_count":1}

def verify_training_tree()->dict[str,Any]:
    seal=read_json(TRAIN/"training-seal-manifest.json");tree_path=TRAIN/"checkpoint-hash-tree.json";tree=read_json(tree_path)
    need(seal["status"]=="Q_ALL_12_RUNS_COMPLETE_SEALED_UNEVALUATED" and seal["run_contract_sha256"]==RUN_CONTRACT and seal["analysis_contract_sha256"]==ANALYSIS_CONTRACT and seal["addendum_sha256"]==ADDENDUM and seal["panel_phase_root_sha256"]==PANEL_ROOT and seal["execution_packet_sha256"]==sha(PACKET) and seal["execution_packet_seal_sha256"]==sha(PACKET_SEAL),"Q training seal identity mismatch")
    need(seal["checkpoint_tree_sha256"]==sha(tree_path) and tree["trained_checkpoint_count"]==48 and tree["initial_template_count"]==3,"Q training tree root/count mismatch")
    for row in tree["entries"]:
        p=TRAIN/Path(row["path"])
        need(p.is_file() and p.stat().st_size==row["bytes"] and sha(p)==row["sha256"],f"Q training entry changed: {row['path']}")
    templates=list((TRAIN/"initial-templates").glob("*.pt"));cps=list((TRAIN/"runs").glob("seed-*/*/step-*.pt"))
    need(len(templates)==3 and len(cps)==48,"Q physical model-state cardinality mismatch")
    return {"training_seal_sha256":sha(TRAIN/"training-seal-manifest.json"),"checkpoint_tree_sha256":sha(tree_path),"initial_templates":len(templates),"trained_checkpoints":len(cps)}

def verify_analysis()->dict[str,Any]:
    seal=read_json(EVAL/"q-analysis-seal-v01.json");result=read_json(EVAL/"q-response-analysis-v01.json")
    need(seal["status"]=="Q_ANALYSIS_OUTPUTS_SEALED" and seal.get("analysis_contract_sha256")==ANALYSIS_CONTRACT,"Q analysis seal status/contract mismatch")
    need(seal.get("execution_packet_sha256")==sha(PACKET) and seal.get("execution_packet_seal_sha256")==sha(PACKET_SEAL) and result.get("execution_packet_sha256")==sha(PACKET),"Q analysis execution packet mismatch")
    entries=seal["outputs"];root=hashlib.sha256("".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in sorted(entries,key=lambda x:x["path"])).encode()).hexdigest()
    need(root==seal["analysis_root_sha256"],"Q analysis output root mismatch")
    for row in entries:
        p=EVAL/row["path"];need(p.is_file() and p.stat().st_size==row["bytes"] and sha(p)==row["sha256"],f"Q analysis output hash mismatch: {row['path']}")
    need(sha(Q/"contracts/q-analysis-contract-v02.json")==ANALYSIS_CONTRACT and sha(Q/"contracts/q-execution-addendum-v01.json")==ADDENDUM,"Q analysis parent changed")
    metric_module=load_module(ROOT/"experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py","q_independent_neighborhood_metrics")
    metrics=read_jsonl(EVAL/"neighborhood-metrics-v01.jsonl")
    need(len(metrics)==102_000,"Q neighborhood metric count mismatch")
    saved_metrics={(int(r["seed"]),str(r["arm"]),int(r["step"]),str(r["neighborhood_id"])):r for r in metrics}
    need(len(saved_metrics)==102_000,"Q duplicate neighborhood metric identity")
    prediction_path=EVAL/"raw-predictions-v01.jsonl"
    with prediction_path.open("r",encoding="utf-8") as source:
        for cell in expected_cells():
            cell_rows:dict[str,dict[str,dict[str,Any]]]={}
            for _ in range(8_000):
                line=source.readline();need(bool(line),f"Q raw prediction ended in {cell}")
                row=json.loads(line);need((int(row["seed"]),str(row["arm"]),int(row["global_step"]))==cell,f"Q raw prediction order changed during metric replay: {cell}")
                views=cell_rows.setdefault(str(row["neighborhood_id"]),{});view=str(row["view"])
                need(view not in views,f"Q duplicate view during metric replay {cell}/{view}");views[view]=row
            need(len(cell_rows)==2_000 and all(set(v)=={"anchor","fact_flip","sham","matched_neutral"} for v in cell_rows.values()),f"Q raw prediction neighborhood incomplete {cell}")
            for nid,views in cell_rows.items():
                recomputed=metric_module.neighborhood_metrics(views)
                saved=saved_metrics[(cell[0],cell[1],cell[2],nid)]
                for name in METRICS:
                    need(close(recomputed[name],saved[name]),f"Q raw-to-metric independent replay mismatch {cell}/{nid}/{name}")
        need(not source.readline(),"Q raw prediction tail after independent metric replay")
    grouped:dict[tuple[int,str,int],dict[str,dict[str,Any]]]={}
    for row in metrics:
        cell=(int(row["seed"]),str(row["arm"]),int(row["step"]))
        grouped.setdefault(cell,{})[str(row["neighborhood_id"])]=row
    need(set(grouped)==set(expected_cells()),"Q metric cells mismatch")
    for cell,rows in grouped.items():need(len(rows)==2000,"Q metric neighborhood count mismatch")
    plan=np.load(EVAL/"shared-bootstrap-resample-plan-v01.npy",mmap_mode="r",allow_pickle=False)
    need(plan.shape==(10_000,2_000) and plan.dtype==np.int32,"Q shared bootstrap plan shape/dtype mismatch")
    plan_hash=hashlib.sha256(np.asarray(plan,dtype="<i4").tobytes(order="C")).hexdigest()
    need(plan_hash==result["shared_bootstrap"]["plan_sha256"],"Q shared bootstrap plan value hash mismatch")
    analysis_cells={}
    for cell,rows in grouped.items():
        fams={nid:str(r["family_id"]).split(":")[-1] for nid,r in rows.items()};ids=sorted(rows)
        overall={k:float(np.mean([float(rows[n][k]) for n in ids])) for k in METRICS}
        by={}
        for fam in FAMILIES:
            block=[rows[n] for n in ids if fams[n]==fam];need(len(block)==500,f"Q metric family support mismatch {fam}")
            by[fam]={k:float(np.mean([float(r[k]) for r in block])) for k in METRICS}
        key=f"{cell[0]}/{cell[1]}/{cell[2]}"; saved=result["response_summaries"][key]
        for k,v in overall.items():need(close(v,saved["overall"][k]),f"Q independent aggregate mismatch {key}/{k}")
        for fam in FAMILIES:
            for k,v in by[fam].items():need(close(v,saved["by_family"][fam][k]),f"Q independent family aggregate mismatch {key}/{fam}/{k}")
        analysis_cells[key]=rows
    rules=load_module(Q/"source/q_analysis_rules_v02.py","q_independent_gate_rules")
    for seed in SEEDS:
        sm=result["response_summaries"]
        def m(arm:str,key:str)->float:return float(sm[f"{seed}/{arm}/120"]["overall"][key])
        low=sm[f"{seed}/B-SHAM-LOW/120"]["by_family"];sham=sm[f"{seed}/B-SHAM/120"]["by_family"]
        inp={"delta_p_new_low_minus_sham":m("B-SHAM-LOW","new_probability_delta")-m("B-SHAM","new_probability_delta"),"sham_low_correct_direction":m("B-SHAM-LOW","correct_direction"),"sham_correct_direction":m("B-SHAM","correct_direction"),"a_old_low_minus_sham":m("B-SHAM-LOW","anchor_old_map")-m("B-SHAM","anchor_old_map"),"family_a_old_low_minus_sham":{f:low[f]["anchor_old_map"]-sham[f]["anchor_old_map"] for f in FAMILIES},"dup_sham_l1":m("B-DUP","sham_l1"),"dup_matched_neutral_l1":m("B-DUP","matched_l1"),"sham_low_sham_l1":m("B-SHAM-LOW","sham_l1"),"sham_low_matched_neutral_l1":m("B-SHAM-LOW","matched_l1"),"dup_sham_map_flip_rate":m("B-DUP","sham_map_flip"),"dup_matched_neutral_map_flip_rate":m("B-DUP","matched_map_flip"),"sham_low_sham_map_flip_rate":m("B-SHAM-LOW","sham_map_flip"),"sham_low_matched_neutral_map_flip_rate":m("B-SHAM-LOW","matched_map_flip"),"f_new_low_minus_sham":m("B-SHAM-LOW","fact_new_map")-m("B-SHAM","fact_new_map"),"strict_low_minus_sham":m("B-SHAM-LOW","strict_transition")-m("B-SHAM","strict_transition")}
        saved=result["same_seed_step120_gate_inputs_and_labels"][str(seed)]["inputs"]
        need(saved==inp,f"Q gate input mismatch {seed}")
        need(rules.seed_gate_record(inp)==result["same_seed_step120_gate_inputs_and_labels"][str(seed)]["labels"],f"Q same-seed gate label mismatch {seed}")
    cohort=rules.cohort_labels({seed:result["same_seed_step120_gate_inputs_and_labels"][seed]["inputs"] for seed in (str(s) for s in SEEDS)})
    need(cohort==result["cohort_labels"],"Q cohort gate labels mismatch")
    # Recompute every contracted step-120 paired interval from the single saved plan.
    ordered_ids=[]
    first=grouped[(SEEDS[0],"B-DUP",120)]
    for family in FAMILIES:ordered_ids.extend(sorted(n for n,r in first.items() if str(r["family_id"]).split(":")[-1]==family))
    plan_array=np.asarray(plan)
    for key,row in result["step120_paired_contrasts_with_shared_bootstrap"].items():
        seed_s,comparison,name=key.split("/",2);left,right=comparison.split("_minus_",1);seed=int(seed_s)
        lv=grouped[(seed,left,120)];rv=grouped[(seed,right,120)]
        values=np.asarray([float(lv[n][name])-float(rv[n][name]) for n in ordered_ids],dtype=np.float64)
        sample=values[plan_array].mean(axis=1);interval=[float(x) for x in np.quantile(sample,[.025,.975],method="linear")]
        need(close(values.mean(),row["mean"]) and all(close(a,b) for a,b in zip(interval,row["ci95"],strict=True)),f"Q paired interval mismatch {key}")
    return {"analysis_root_sha256":root,"analysis_seal_sha256":sha(EVAL/"q-analysis-seal-v01.json"),"metric_rows":len(metrics),"raw_predictions_recomputed_into_metrics":True,"bootstrap_plan_sha256":plan_hash,"family_cells_recomputed":len(grouped)*4,"same_seed_labels_recomputed":True,"paired_intervals_recomputed":len(result["step120_paired_contrasts_with_shared_bootstrap"])}

def main()->int:
    need(not RECEIPT.exists(),"Q independent verification receipt already exists")
    packet=read_json(PACKET)
    need(packet.get("schema")=="jev-v08q-full-execution-packet-v05" and packet.get("authorization",{}).get("phase")=="Q_FULL_FROZEN_RUN_EVALUATION_AND_ANALYSIS" and packet.get("authorization",{}).get("explicit_user_authorization") is True,"Q full execution packet authorization mismatch")
    packet_seal=read_json(PACKET_SEAL)
    root=hashlib.sha256("".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in sorted(packet["implementation_bindings"],key=lambda x:x["path"])).encode()).hexdigest()
    need(root==packet["packet_root_sha256"]==packet_seal["packet_root_sha256"] and packet_seal["packet_sha256"]==sha(PACKET),"Q full execution packet seal/root mismatch")
    for item in packet["implementation_bindings"]:
        path=ROOT/item["path"];need(path.is_file() and sha(path)==item["sha256"],f"Q implementation changed after packet seal: {item['path']}")
    training=verify_training_tree();prediction=verify_prediction_matrix();analysis=verify_analysis()
    receipt={"status":"Q_FULL_EXECUTION_INDEPENDENT_VERIFICATION_PASS","execution_packet_sha256":sha(PACKET),"training":training,"prediction_matrix":prediction,"analysis":analysis,"panel_open_count":1,"training_panel_feedback":False,"extra_runs":False,"extra_checkpoints":False,"extra_doses":False}
    write_json(RECEIPT,receipt);print(json.dumps(receipt,indent=2));return 0

if __name__=="__main__":raise SystemExit(main())
