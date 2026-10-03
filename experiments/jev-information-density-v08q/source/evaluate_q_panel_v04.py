"""Single-opening evaluation of the sealed Q panel after the 12-run training seal."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
TRAIN = RUN / "training"
OUTPUT = RUN / "evaluation"
PACKET = RUN / "q-full-execution-packet-v04.json"
PACKET_SEAL = RUN / "q-full-execution-packet-seal-v04.json"
SEEDS = (2540205348, 2603246505, 3565067208)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")
STEPS = (40, 80, 100, 120)
VIEWS = ("anchor", "fact_flip", "matched_neutral", "sham")
PANEL_ROOT_SHA = "1b99d39ab6bfed8173a5410f6c8ae0df442aae03038e31bab46b779bd1e039a6"
TRAIN_CONTRACT_SHA = "5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae"
ANALYSIS_CONTRACT_SHA = "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc"
ADDENDUM_SHA = "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3"
PROBE_SHA = "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1"
METRIC_SHA = "fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4"


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()


def read_json(path: Path) -> Any: return json.loads(path.read_text(encoding="utf-8"))
def read_jsonl(path: Path) -> list[dict[str,Any]]:
    with path.open("r",encoding="utf-8") as f: return [json.loads(line) for line in f if line.strip()]


def write_json(path: Path, value: Any) -> None:
    if path.exists(): raise FileExistsError(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with tmp.open("r+b") as f: f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)


def need(ok: bool,msg: str)->None:
    if not ok: raise RuntimeError(msg)

def tensor_sha(value:torch.Tensor)->str:
    array=value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()

def state_sha(state:dict[str,torch.Tensor])->str:
    h=hashlib.sha256()
    for name,value in sorted(state.items()):
        array=value.detach().cpu().contiguous()
        h.update(name.encode());h.update(str(array.dtype).encode());h.update(json.dumps(list(array.shape)).encode())
        h.update(memoryview(array.numpy()).cast("B"))
    return h.hexdigest()


def load_module(path: Path,name: str)->Any:
    spec=importlib.util.spec_from_file_location(name,path)
    need(spec is not None and spec.loader is not None,f"cannot import {path}")
    module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module


def verify_training() -> tuple[dict[str,Any],dict[tuple[int,str,int],dict[str,Any]]]:
    seal_path=TRAIN/"training-seal-manifest.json"
    tree_path=TRAIN/"checkpoint-hash-tree.json"
    need(seal_path.is_file() and tree_path.is_file(),"Q training seal is absent")
    seal=read_json(seal_path); tree=read_json(tree_path)
    need(seal.get("status")=="Q_ALL_12_RUNS_COMPLETE_SEALED_UNEVALUATED" and seal.get("run_count")==12 and seal.get("trained_checkpoint_count")==48 and seal.get("initial_template_count")==3,"Q training seal state/count mismatch")
    need(seal.get("run_contract_sha256")==TRAIN_CONTRACT_SHA and seal.get("analysis_contract_sha256")==ANALYSIS_CONTRACT_SHA and seal.get("addendum_sha256")==ADDENDUM_SHA and seal.get("panel_phase_root_sha256")==PANEL_ROOT_SHA,"Q training parent binding mismatch")
    need(seal.get("execution_packet_sha256")==sha(PACKET) and seal.get("execution_packet_seal_sha256")==sha(PACKET_SEAL),"Q training execution packet binding mismatch")
    need(seal.get("checkpoint_tree_sha256")==sha(tree_path) and tree.get("trained_checkpoint_count")==48 and tree.get("initial_template_count")==3,"Q checkpoint tree hash/count mismatch")
    for entry in tree["entries"]:
        path=TRAIN/Path(entry["path"])
        need(path.is_file() and path.stat().st_size==entry["bytes"] and sha(path)==entry["sha256"],f"Q training artifact hash mismatch: {entry['path']}")
    lookup={}
    for seed in SEEDS:
        template=TRAIN/"initial-templates"/f"seed-{seed}.pt"
        pack=torch.load(template,map_location="cpu",weights_only=True)
        need(pack.get("seed")==seed and pack.get("state_sha256"),f"Q init template invalid: {seed}")
        for arm in ARMS:
            run=TRAIN/"runs"/f"seed-{seed}"/arm
            integrity=read_json(run/"run-integrity.json")
            need(integrity.get("status")=="Q_TRAINING_COMPLETE_UNEVALUATED" and integrity.get("optimizer_steps")==120 and integrity.get("checkpoint_count")==4,"Q run completeness mismatch")
            index=read_jsonl(run/"checkpoint-index.jsonl")
            need([r["step"] for r in index]==list(STEPS),f"Q checkpoint cadence mismatch {seed}/{arm}")
            for row in index:
                cp=run/row["path"]
                need(sha(cp)==row["sha256"],f"Q checkpoint index mismatch {seed}/{arm}/{row['step']}")
                lookup[(seed,arm,int(row["step"]))]={"path":cp,"sha256":row["sha256"],"head_sha256":row["head_sha256"]}
    need(len(lookup)==48,"Q checkpoint matrix incomplete")
    return seal,lookup


def verify_execution_packet()->dict[str,Any]:
    need(PACKET.is_file() and PACKET_SEAL.is_file(),"Q full-execution packet or seal is absent")
    packet=read_json(PACKET);packet_seal=read_json(PACKET_SEAL)
    need(packet.get("schema")=="jev-v08q-full-execution-packet-v04" and packet.get("authorization",{}).get("phase")=="Q_FULL_FROZEN_RUN_EVALUATION_AND_ANALYSIS" and packet.get("authorization",{}).get("explicit_user_authorization") is True,"Q execution authorization packet mismatch")
    need(packet.get("panel_root_sha256")==PANEL_ROOT_SHA and packet_seal.get("packet_sha256")==sha(PACKET) and packet_seal.get("packet_root_sha256")==packet.get("packet_root_sha256"),"Q execution packet seal identity mismatch")
    for row in packet.get("implementation_bindings",[]):
        path=ROOT/row["path"];need(path.is_file() and sha(path)==row["sha256"],f"Q frozen implementation changed: {row['path']}")
    return {"packet_sha256":sha(PACKET),"packet_seal_sha256":sha(PACKET_SEAL)}


def verify_panel_seal() -> dict[str,Any]:
    seal_path=PANEL/"seals/q-panel-phase-terminal-seal-v01.json"
    seal=read_json(seal_path)
    need(seal.get("root_sha256")==PANEL_ROOT_SHA and seal.get("entry_count")==len(seal.get("entries",[]))==30,"Q panel seal root/count mismatch")
    entries_root=hashlib.sha256("".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in sorted(seal["entries"],key=lambda x:x["path"])).encode()).hexdigest()
    need(entries_root==PANEL_ROOT_SHA,"Q panel entries root mismatch")
    for row in seal["entries"]:
        path=PANEL/row["path"]
        need(path.is_file() and path.stat().st_size==row["bytes"] and sha(path)==row["sha256"],f"Q panel sealed artifact mismatch: {row['path']}")
    need(seal.get("panel_verification_status")=="Q_INDEPENDENT_PANEL_VERIFICATION_PASS" and seal.get("radius_verification_status")=="Q_INDEPENDENT_RADIUS_AND_CANDIDATE_JOIN_VERIFICATION_PASS","Q independent panel/radius verification missing")
    return {"seal_path":str(seal_path),"seal_sha256":sha(seal_path),"panel_root_sha256":PANEL_ROOT_SHA,"entry_count":len(seal["entries"])}


def build_panel() -> tuple[list[dict[str,Any]],dict[str,dict[str,dict[str,Any]]],dict[str,dict[str,Any]],torch.Tensor,torch.Tensor,dict[str,int],dict[str,list[str]]]:
    scope=read_jsonl(PANEL/"panel/panel-feature-scope.jsonl")
    target_rows=read_jsonl(PANEL/"target-joins/q-exact-world-targets.jsonl")
    neighborhoods=read_jsonl(PANEL/"panel/panel-neighborhoods.jsonl")
    selections=read_jsonl(PANEL/"matching/matched-neutral-selection.jsonl")
    scope_manifest=read_jsonl(PANEL/"features/q-state-feature-manifest.jsonl")
    candidate_manifest=read_jsonl(PANEL/"features/q-candidate-feature-manifest.jsonl")
    scope_hashes={r["path"]:r["sha256"] for r in read_json(PANEL/"seals/q-panel-phase-terminal-seal-v01.json")["entries"]}
    need(sha(PANEL/"panel/panel-feature-scope.jsonl")==scope_hashes["panel/panel-feature-scope.jsonl"],"Q opened scope hash differs from seal")
    need(sha(PANEL/"target-joins/q-exact-world-targets.jsonl")==scope_hashes["target-joins/q-exact-world-targets.jsonl"],"Q opened exact-target hash differs from seal")
    need(len(scope)==len(target_rows)==len(scope_manifest)==22_000 and len(neighborhoods)==len(selections)==2_000,"Q opened panel cardinality mismatch")
    need(all(r["index"]==i and target_rows[i]["index"]==i and scope_manifest[i]["index"]==i for i,r in enumerate(scope)),"Q panel row order mismatch")
    feature_path=PANEL/"features/q-state-features.pt"; cand_path=PANEL/"features/q-candidate-features.pt"
    state_pack=torch.load(feature_path,map_location="cpu",weights_only=True); cand_pack=torch.load(cand_path,map_location="cpu",weights_only=True)
    states=state_pack["features"]; candidates=cand_pack["features"].to("cuda")
    need(tuple(states.shape)==(22_000,2048) and states.dtype==torch.float32 and states.is_contiguous(),"Q heldout state feature tensor invalid")
    need(tuple(candidates.shape)==(16,2048) and candidates.dtype==torch.float32 and candidates.is_contiguous(),"Q heldout candidate feature tensor invalid")
    feature_receipt=read_json(PANEL/"features/q-feature-extraction-receipt.json")
    need(feature_receipt.get("status")=="Q_FROZEN_PANEL_FEATURE_EXTRACTION_PASS" and feature_receipt.get("panel_root_sha256")==PANEL_ROOT_SHA,"Q feature receipt parent mismatch")
    need(state_pack.get("scope_sha256")==sha(PANEL/"panel/panel-feature-scope.jsonl") and tensor_sha(states)==feature_receipt["state_tensor"]["tensor_sha256"],"Q heldout feature cache scope/content identity mismatch")
    need(tensor_sha(candidates)==feature_receipt["candidate_tensor"]["tensor_sha256"],"Q candidate feature tensor identity mismatch")
    for i,row in enumerate(scope_manifest):
        need(row.get("index")==i and row.get("episode_id")==scope[i]["episode_id"] and row.get("input_sha256")==scope[i]["input_sha256"] and row.get("feature_sha256")==tensor_sha(states[i]),f"Q state feature row identity mismatch {i}")
    need(cand_pack.get("candidate_ids")==[r["candidate_semantic_id"] for r in candidate_manifest],"Q candidate feature semantic order mismatch")
    for i,row in enumerate(candidate_manifest):
        need(row.get("index")==i and row.get("feature_sha256")==tensor_sha(candidates[i]),f"Q candidate feature row identity mismatch {i}")
    target_by_index={int(r["index"]):r for r in target_rows}
    scope_by_nid:dict[str,dict[str,dict[str,Any]]]={}
    for i,row in enumerate(scope):
        need(row["episode_id"]==target_by_index[i]["episode_id"] and row["neighborhood_id"]==target_by_index[i]["neighborhood_id"] and row["role"]==target_by_index[i]["role"],"Q target join row identity mismatch")
        row=dict(row); row["target"]=[float(v) for v in target_by_index[i]["target"]]
        need(len(row["target"])==4 and abs(sum(row["target"])-1.0)<=1e-12,"Q exact target invalid")
        scope_by_nid.setdefault(str(row["neighborhood_id"]),{})[str(row["episode_id"])]=row
    selection_by_nid={str(r["neighborhood_id"]):r for r in selections}
    neighborhood_by_nid={str(r["neighborhood_id"]):r for r in neighborhoods}
    need(len(scope_by_nid)==len(selection_by_nid)==len(neighborhood_by_nid)==2_000,"Q panel identity set mismatch")
    candidate_index={str(r["candidate_semantic_id"]):int(r["index"]) for r in candidate_manifest}
    schema_order:dict[str,list[str]]={}; schema_by_slug={}
    for row in sorted(candidate_manifest,key=lambda x:(str(x["schema_family_id"]),int(x["candidate_order"]))):
        slug=str(row["schema_family_id"]).split(":")[-1]
        schema_order.setdefault(slug,[]).append(str(row["candidate_semantic_id"]))
        schema_by_slug[slug]=str(row["schema_family_id"])
    need(set(schema_order)=={"exposure_control","respiratory_monitoring","salinity_control","vibration_monitoring"} and all(len(v)==4 for v in schema_order.values()),"Q candidate schema order invalid")
    panel_rows=[]; neighborhood_meta={}
    for nid, raw in neighborhood_by_nid.items():
        roles=scope_by_nid[nid]; selected=selection_by_nid[nid]
        wanted_neutral=str(selected["matched_neutral_episode_id"])
        need(wanted_neutral in roles and str(roles[wanted_neutral]["role"])==str(selected["matched_neutral_role"]),f"Q selected neutral join mismatch {nid}")
        role_episode={str(row["role"]):str(row["episode_id"]) for row in roles.values()}
        need(all(role in role_episode for role in ("anchor","fact_flip","sham")),f"Q required event role absent {nid}")
        slug=str(raw["family_slug"]); schema=schema_by_slug[slug]
        panel_rows.append({"neighborhood_id":nid,"family_id":raw["family_id"],"template_id":roles[role_episode["anchor"]]["template_id"],"anchor_episode_id":role_episode["anchor"],"fact_episode_id":role_episode["fact_flip"],"sham_episode_id":role_episode["sham"],"matched_neutral_episode_id":wanted_neutral})
        neighborhood_meta[nid]={"schema_family_id":schema,"family_id":raw["family_id"],"family_slug":slug,"template_id":roles[role_episode["anchor"]]["template_id"]}
    return panel_rows,scope_by_nid,neighborhood_meta,states,candidates,candidate_index,schema_order


def main()->int:
    stage="training_seal_preflight"; started=time.perf_counter(); opened=False
    try:
        packet_binding=verify_execution_packet()
        training_seal,lookup=verify_training()
        panel_binding=verify_panel_seal()
        need(not OUTPUT.exists(),f"Q evaluation output already exists; refusing second opening: {OUTPUT}")
        OUTPUT.mkdir(parents=True,exist_ok=False)
        opening={"status":"Q_FRESH_PANEL_OPENED_ONCE_AFTER_ALL_TRAINING_STATES_SEALED","opening_count":1,"execution_packet_sha256":packet_binding["packet_sha256"],"execution_packet_seal_sha256":packet_binding["packet_seal_sha256"],"panel_root_sha256":PANEL_ROOT_SHA,"panel_seal_sha256":panel_binding["seal_sha256"],"training_seal_sha256":sha(TRAIN/"training-seal-manifest.json"),"checkpoint_tree_sha256":sha(TRAIN/"checkpoint-hash-tree.json"),"panel_parse_before_training_seal":False,"heldout_feedback_during_training":False,"opened_at_utc":datetime.now(timezone.utc).isoformat()}
        write_json(OUTPUT/"panel-opening-receipt-v01.json",opening); opened=True
        stage="single_panel_materialization"
        panel_rows,scope,meta,states,candidates,candidate_index,schema_order=build_panel()
        probe=load_module(ROOT/"experiments/jev-frozen-readout-v01/probe.py","q_eval_probe")
        metric=load_module(ROOT/"experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py","q_frozen_metric_evaluator")
        need(sha(ROOT/"experiments/jev-frozen-readout-v01/probe.py")==PROBE_SHA and sha(ROOT/"experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py")==METRIC_SHA,"Q frozen evaluator source mismatch")
        pred_path=OUTPUT/"raw-predictions-v01.jsonl"; cell_order=[]; checkpoint_records=[]
        with pred_path.open("x",encoding="utf-8",newline="\n") as stream:
            for seed in SEEDS:
                init=TRAIN/"initial-templates"/f"seed-{seed}.pt"
                init_pack=torch.load(init,map_location="cpu",weights_only=True)
                head=probe.CompatibilityHead(2048,"mlp",128).to("cuda"); head.load_state_dict(init_pack["state_dict"],strict=True)
                try:
                    rows,_=metric.metrics_for_run(seed,"COMMON_INIT",head,panel_rows,scope,meta,states,candidates,candidate_index,schema_order,"cuda")
                    need(len(rows)==8_000,f"Q initialization output cardinality mismatch {seed}")
                    for row in rows:
                        row.update({"global_step":0,"checkpoint_label":"COMMON_INIT","checkpoint_sha256":sha(init),"head_state_sha256":init_pack["state_sha256"]})
                        stream.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
                    cell_order.append({"seed":seed,"arm":"COMMON_INIT","step":0,"rows":len(rows),"checkpoint_sha256":sha(init)})
                finally:
                    del head; torch.cuda.empty_cache()
                for step in STEPS:
                    for arm in ARMS:
                        entry=lookup[(seed,arm,step)]
                        pack=torch.load(entry["path"],map_location="cpu",weights_only=False)
                        need(pack.get("seed")==seed and pack.get("arm")==arm and pack.get("global_step")==step and pack.get("schedule_sha256")==sha(RUN/"schedule/fixed-schedule.jsonl") and pack.get("initial_head_sha256")==init_pack["state_sha256"],f"Q checkpoint metadata mismatch {seed}/{arm}/{step}")
                        need(state_sha(pack["head_state"])==pack.get("head_sha256")==entry["head_sha256"],f"Q checkpoint head-state hash mismatch {seed}/{arm}/{step}")
                        head=probe.CompatibilityHead(2048,"mlp",128).to("cuda"); head.load_state_dict(pack["head_state"],strict=True)
                        need(pack.get("head_sha256")==entry["head_sha256"],f"Q checkpoint head state mismatch {seed}/{arm}/{step}")
                        try:
                            rows,_=metric.metrics_for_run(seed,arm,head,panel_rows,scope,meta,states,candidates,candidate_index,schema_order,"cuda")
                            need(len(rows)==8_000,f"Q prediction output cardinality mismatch {seed}/{arm}/{step}")
                            for row in rows:
                                row.update({"global_step":step,"checkpoint_label":f"step-{step:03}","checkpoint_sha256":entry["sha256"],"head_state_sha256":pack["head_sha256"]})
                                stream.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
                            cell_order.append({"seed":seed,"arm":arm,"step":step,"rows":len(rows),"checkpoint_sha256":entry["sha256"]})
                            if len(cell_order)%8==0: stream.flush(); os.fsync(stream.fileno())
                        finally:
                            del head; torch.cuda.empty_cache()
                        print(json.dumps({"event":"q_eval_cell_complete","seed":seed,"arm":arm,"step":step,"cells":len(cell_order),"expected_cells":51},separators=(",",":")),flush=True)
            stream.flush(); os.fsync(stream.fileno())
        need(len(cell_order)==51 and sum(r["rows"] for r in cell_order)==408_000 and all(r["rows"]==8_000 for r in cell_order),"Q evaluation matrix incomplete")
        prediction_sha=sha(pred_path)
        tree={"status":"Q_COMPLETE_408000_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS","identity":"JEV-V08Q-SINGLE-DOSE-GAIN","execution_packet_sha256":packet_binding["packet_sha256"],"prediction_rows":408_000,"cell_count":51,"rows_by_cell":cell_order,"raw_predictions":{"path":str(pred_path),"bytes":pred_path.stat().st_size,"sha256":prediction_sha},"training_seal_sha256":sha(TRAIN/"training-seal-manifest.json"),"checkpoint_tree_sha256":sha(TRAIN/"checkpoint-hash-tree.json"),"panel_opening_receipt_sha256":sha(OUTPUT/"panel-opening-receipt-v01.json"),"panel_root_sha256":PANEL_ROOT_SHA,"panel_open_count":1,"predictions_before_analysis":True,"checkpoint_selection":False,"training":False,"created_at_utc":datetime.now(timezone.utc).isoformat()}
        write_json(OUTPUT/"raw-prediction-hash-tree-v01.json",tree)
        write_json(OUTPUT/"inference-receipt-v01.json",{"status":"Q_ALL_51_CELLS_INFERRED_AND_SEALED","prediction_hash_tree_sha256":sha(OUTPUT/"raw-prediction-hash-tree-v01.json"),"prediction_sha256":prediction_sha,"prediction_rows":408_000,"cell_count":51,"panel_open_count":1,"predictions_before_analysis":True,"training":False})
        print(json.dumps({"status":tree["status"],"rows":408000,"sha256":prediction_sha,"elapsed_seconds":time.perf_counter()-started},indent=2),flush=True)
        return 0
    except BaseException as exc:
        failure=OUTPUT/"evaluation-failure-receipt-v01.json"
        if OUTPUT.exists() and not failure.exists(): write_json(failure,{"status":"Q_EVALUATION_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED","stage":stage,"exception_type":type(exc).__name__,"exception":str(exc),"panel_opened":opened,"automatic_retry":False,"failed_at_utc":datetime.now(timezone.utc).isoformat()})
        raise

if __name__=="__main__": raise SystemExit(main())
