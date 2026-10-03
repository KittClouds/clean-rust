"""Two fixed training identities, paired initialization and batches, complete artifacts."""
from __future__ import annotations

import json
import math
import shutil
import time
from collections import Counter
from datetime import datetime, timezone

from p2_contract import (OUTPUT, PHASE1_OUTPUT, NVME, SUBSTRATE, ARMS, SOURCE,
                         PHASE0_LOCK_SHA, verify_prior, specification, freeze, verify_spec,
                         pad_candidates, state_hash, sha_file, write_json,
                         default_config, supervision_abi)
import numpy as np
import torch

from graft.dataset import PackedBank, assert_disjoint, training_normalizer
from graft.model import model_for_substrate, forward_batch
from graft.evaluate import predictions, runtime_envelopes
from p2_objective import objective
from p2_evaluate import state_statistics, pair_summary, exact_objective
from reporting import per_target, endpoint_metrics, complete_report


def cpu_tree(value):
    if torch.is_tensor(value):return value.detach().cpu().clone()
    if isinstance(value,dict):return {k:cpu_tree(v) for k,v in value.items()}
    if isinstance(value,list):return [cpu_tree(v) for v in value]
    return value


def audit_candidates(train,dev,prior):
    result={"populations":{},"Phase1_truncated_candidates":0,
            "Phase1_truncated_rows":0,"Phase1_cap":prior["candidate_convention"]["m_cap"]}
    for name,data in (("TRAIN",train),("DEV",dev)):
        counts=np.diff(data.arrays["offsets"])
        observed=np.flatnonzero(data.extras["action_available"])
        assert np.all(data.extras["action_target"][observed]<counts[observed])
        for left,right in data.extras["renderer_pairs"]:
            l,r=data.rows[int(left)],data.rows[int(right)]
            if l["candidate_actions"]!=r["candidate_actions"]:
                raise ValueError("pre-existing renderer pair has changed canonical candidate identities")
            la,lb=data.arrays["offsets"][left:left+2]
            ra,rb=data.arrays["offsets"][right:right+2]
            if not np.array_equal(data.arrays["actions"][la:lb],data.arrays["actions"][ra:rb]):
                raise ValueError("pre-existing renderer binding ordinals differ")
        result["populations"][name]={"rows":len(data),"max_candidates":int(counts.max()),
            "candidate_count_histogram":{str(k):v for k,v in sorted(Counter(map(int,counts)).items())},
            "total_candidates":int(counts.sum()),"eligible_ACT_endpoints":len(observed),
            "aligned_renderer_pairs":len(data.extras["renderer_pairs"]),
            "offsets_sha256":sha_file(data.folder/"offsets.npy")}
    cap=max(v["max_candidates"] for v in result["populations"].values())
    if cap!=prior["candidate_convention"]["m_cap"]:
        raise ValueError("Phase 1 cap audit requires explicit truncation accounting")
    result.update({"measured_maximum":cap,"retain_every_canonical_candidate":True,
                   "status":"EXHAUSTIVE_CANDIDATES_VERIFIED","protected_TEST_truth_opened":False})
    write_json(OUTPUT/"CANDIDATE-AUDIT.json",result)
    return cap


def save_checkpoint(path,model,opt,arm,epoch,loss,spec):
    temp=path.with_suffix(".tmp")
    torch.save({"state_dict":cpu_tree(model.state_dict()),"optimizer_state":cpu_tree(opt.state_dict()),
                "fabric_config":model.config,"arm":arm,"epoch":epoch,"DEV_selection_loss":loss,
                "phase2_spec_sha256":sha_file(OUTPUT/"PHASE2-SPEC.json"),
                "phase0_lock_sha256":PHASE0_LOCK_SHA,"supervision_abi":supervision_abi(),
                "representation_id":spec["representation_id"],
                "initial_state_sha256":spec["initial_state_sha256"],"frozen_backbone":True},temp)
    temp.replace(path)


def train_arm(arm,train,dev,spec,initial_state,reference_std,prior):
    root=OUTPUT/arm
    root.mkdir(exist_ok=False)
    ck=root/"checkpoints";ck.mkdir()
    torch.manual_seed(spec["seed"]);torch.cuda.manual_seed_all(spec["seed"])
    cfg=default_config();device="cuda:0"
    model=model_for_substrate(cfg,SUBSTRATE).to(device)
    model.load_state_dict(initial_state)
    initial_hash=state_hash(model)
    if initial_hash!=spec["initial_state_sha256"]:
        raise ValueError("arm initialization differs")
    tc=spec["training"]
    opt=torch.optim.AdamW(model.parameters(),lr=tc["lr"],weight_decay=tc["weight_decay"])
    scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(opt,T_max=tc["max_epochs"],eta_min=tc["minimum_lr"])
    rng=np.random.default_rng(spec["seed"])
    prng=np.random.default_rng(spec["seed"]+1)
    pairs=train.extras["renderer_pairs"]
    history=[];best=math.inf;best_epoch=0;steps=0
    start=time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    print(json.dumps({"status":"ARM_STARTED","arm":arm,"initial_state_sha256":initial_hash}),flush=True)
    for epoch in range(1,tc["max_epochs"]+1):
        epoch_start=time.perf_counter();model.train()
        order=rng.permutation(len(train))
        parts={};batches=0
        lr=opt.param_groups[0]["lr"]
        for position in range(0,len(order),tc["batch_size"]):
            b=pad_candidates(train.batch(order[position:position+tc["batch_size"]],device),spec["candidate_convention"]["m_cap"])
            chosen=pairs[prng.choice(len(pairs),min(len(pairs),tc["renderer_pairs_per_batch"]),replace=False)]
            l,r=(pad_candidates(train.batch(chosen[:,i],device)) for i in (0,1))
            renderer=(forward_batch(model,l),forward_batch(model,r),l,r)
            loss,detail=objective(arm,forward_batch(model,b),b,reference_std,renderer)
            if not torch.isfinite(loss):raise ValueError("nonfinite training loss")
            opt.zero_grad(set_to_none=True);loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),tc["gradient_clip"],error_if_nonfinite=True)
            opt.step();steps+=1;batches+=1
            for key,value in detail.items():
                if key!="active":parts[key]=parts.get(key,0.)+value
        scheduler.step()
        dev_loss=exact_objective(arm,model,dev,device,reference_std)
        rows=predictions(model,dev,device,128)
        target=per_target(rows);endpoint=endpoint_metrics(rows)
        diversity=state_statistics(model,dev,device)
        paired=pair_summary(model,dev,device)
        checkpoint=ck/f"epoch-{epoch:03d}.pt"
        save_checkpoint(checkpoint,model,opt,arm,epoch,dev_loss,spec)
        if dev_loss["total"]<best:best,best_epoch=dev_loss["total"],epoch
        record={"epoch":epoch,"lr":lr,"rows_seen":len(train),"optimizer_steps_total":steps,
                "training_mean_batch_components":{k:v/batches for k,v in parts.items()},
                "DEV_loss":dev_loss,"DEV_targets":target,"DEV_endpoint":endpoint,
                "DEV_state_diversity":diversity,"DEV_pair_JS":paired,
                "checkpoint_sha256":sha_file(checkpoint),"best_epoch_so_far":best_epoch,
                "seconds":time.perf_counter()-epoch_start}
        history.append(record);write_json(root/"training-history.json",history)
        print(json.dumps({"arm":arm,"epoch":epoch,"DEV_loss":dev_loss["total"],"best_epoch":best_epoch,
                          "action_accuracy":endpoint["accuracy"],"MOVE_accuracy":endpoint["by_target_action_type"].get("MOVE",{}).get("accuracy"),
                          "D_s":diversity["D_s"],"seconds":record["seconds"]}),flush=True)
        del rows
    artifact=root/"best-graft.pt"
    shutil.copyfile(ck/f"epoch-{best_epoch:03d}.pt",artifact)
    model.load_state_dict(torch.load(artifact,map_location=device,weights_only=True)["state_dict"])
    digest=sha_file(artifact)
    report,rows=complete_report(model,dev,device,prior)
    report["global_state_diversity"]=state_statistics(model,dev,device)
    report["TRAIN_global_state_diversity"]=state_statistics(model,train,device)
    report["renderer_JS"]=pair_summary(model,dev,device)
    report["own_objective_DEV"]=exact_objective(arm,model,dev,device,reference_std)
    report["global_state_diversity"]["coordinates_below_TRAIN_reference_half_floor"]=int(np.sum(
        np.asarray(report["global_state_diversity"]["per_coordinate_std"])<.5*reference_std.cpu().numpy()))
    write_json(root/"DEV-METRICS.json",report)
    with (root/"DEV-estimates.jsonl").open("x",encoding="utf-8") as stream:
        for row in runtime_envelopes(rows,digest,train.representation_id,supervision_abi()):
            stream.write(json.dumps(row,sort_keys=True,allow_nan=False)+"\n")
    clone=model_for_substrate(cfg,SUBSTRATE).to(device)
    clone.load_state_dict(torch.load(artifact,map_location=device,weights_only=True)["state_dict"])
    model.eval();clone.eval()
    b=pad_candidates(dev.batch(np.arange(8),device))
    with torch.no_grad():
        a,c=forward_batch(model,b),forward_batch(clone,b)
        if not all(torch.equal(a[k],c[k]) for k in a):raise ValueError("checkpoint replay differs")
    receipt={"status":"ARM_COMPLETE","arm":arm,"initial_state_sha256":initial_hash,"best_epoch":best_epoch,
             "epochs":len(history),"optimizer_steps":steps,"full_TRAIN_passes":len(history),
             "artifact_sha256":digest,"learned_state_sha256":state_hash(model),
             "DEV_selection_loss":best,"trainable_parameters":sum(p.numel() for p in model.parameters()),
             "seconds":time.perf_counter()-start,"peak_GPU_allocated_bytes":torch.cuda.max_memory_allocated(),
             "deterministic_checkpoint_replay":True,"backbone_optimizer_steps":0,
             "files":{str(p.relative_to(root)):sha_file(p) for p in sorted(root.rglob("*")) if p.is_file()}}
    write_json(root/"ARM-RECEIPT.json",receipt)
    del model,clone,opt
    torch.cuda.empty_cache()
    return receipt,report


def main():
    if (OUTPUT/"PHASE2-SPEC.json").exists():raise ValueError("completed/frozen identity already exists")
    started=time.perf_counter()
    lock,prior_receipt,prior_spec=verify_prior()
    torch.set_num_threads(4)
    torch.manual_seed(prior_spec["seed"]);torch.cuda.manual_seed_all(prior_spec["seed"])
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    torch.backends.cuda.enable_flash_sdp(False);torch.backends.cuda.enable_mem_efficient_sdp(False)
    if not torch.cuda.is_available():raise RuntimeError("CUDA unavailable")
    cfg=default_config();device="cuda:0"
    train=PackedBank(NVME/"data"/"TRAIN",SUBSTRATE,cfg)
    dev=PackedBank(NVME/"data"/"DEV",SUBSTRATE,cfg)
    assert_disjoint(train,dev)
    if len(train)!=20000 or len(dev)!=2000:raise ValueError("canonical population changed")
    if train.representation_id!=dev.representation_id:raise ValueError("representation identity differs")
    cap=audit_candidates(train,dev,prior_receipt)
    model=model_for_substrate(cfg,SUBSTRATE).to(device)
    mean,std=training_normalizer(train)
    model.input_mean.copy_(mean.to(device));model.input_std.copy_(std.to(device))
    initial_hash=state_hash(model)
    reference=state_statistics(model,train,device)
    reference_std=torch.tensor(reference["per_coordinate_std"],dtype=torch.float32,device=device)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    np.save(OUTPUT/"TRAIN-untrained-sigma.npy",reference_std.cpu().numpy(),allow_pickle=False)
    initial_state=cpu_tree(model.state_dict())
    torch.save({"state_dict":initial_state,"fabric_config":model.config,"state_sha256":initial_hash,
                "representation_id":train.representation_id},OUTPUT/"PHASE0-INITIALIZATION.pt")
    write_json(OUTPUT/"VARIANCE-REFERENCE.json",{
        **reference,"source":"Untrained Phase 0 seed model with TRAIN-only normalizer",
        "initial_state_sha256":initial_hash,"sigma_artifact_sha256":sha_file(OUTPUT/"TRAIN-untrained-sigma.npy"),
        "DEV_used":False,"coefficient":.05,"floor_multiplier":.5})
    spec=specification(cap,train.representation_id)
    spec["initial_state_sha256"]=initial_hash
    spec["reference_sigma_sha256"]=sha_file(OUTPUT/"TRAIN-untrained-sigma.npy")
    spec["initialization_artifact_sha256"]=sha_file(OUTPUT/"PHASE0-INITIALIZATION.pt")
    freeze(spec)
    print(json.dumps({"status":"PHASE2_FROZEN","m_cap":cap,"TRAIN_reference_D_s":reference["D_s"],
                      "spec_sha256":sha_file(OUTPUT/"PHASE2-SPEC.json")}),flush=True)
    del model;torch.cuda.empty_cache()
    prior=json.loads((PHASE1_OUTPUT/"TRAIN-trivial-baselines.json").read_text())
    results={}
    for arm in ARMS:results[arm]=train_arm(arm,train,dev,spec,initial_state,reference_std,prior)
    verify_spec(spec)
    from compare import make_comparison
    comparison=make_comparison(results,prior_receipt)
    write_json(OUTPUT/"COMPARISON.json",comparison)
    files={str(p.relative_to(OUTPUT)):sha_file(p) for p in sorted(OUTPUT.rglob("*")) if p.is_file()}
    receipt={"status":"PHASE2_COMPLETE","schema":"frozen-fabrique.semantic-graft-phase2-receipt/v1",
             "completed_at_utc":datetime.now(timezone.utc).isoformat(),"substrate":SUBSTRATE,
             "phase0_lock_sha256":PHASE0_LOCK_SHA,"phase1_receipt_sha256":sha_file(PHASE1_OUTPUT/"PHASE1-RECEIPT.json"),
             "phase2_spec_sha256":sha_file(OUTPUT/"PHASE2-SPEC.json"),"initial_state_sha256":initial_hash,
             "architecture_sha256":spec["architecture_sha256"],"representation_id":train.representation_id,
             "latent_dimensions":{"s":64,"e":64},"candidate_convention":spec["candidate_convention"],
             "TRAIN":20000,"DEV":2000,"sourceable_target_ABI":supervision_abi(),
             "arms":{arm:result[0] for arm,result in results.items()},"files":files,
             "total_seconds":time.perf_counter()-started,"torch_version":str(torch.__version__),
             "device":torch.cuda.get_device_name(0),"no_covariance_penalty":True,
             "exit_gate":{"BOTH_TRAIN_RUNS_COMPLETE":True,"CHECKPOINTS_FROZEN":True,
                          "SOURCEABLE_TARGETS_AND_ACTION_SCORED":True,"STATE_DIVERSITY_CHECK_COMPLETE":True,
                          "S_E_A_RENDERER_DISAGREEMENT_SEPARATE":True,"PHASE0_ARCHITECTURE_UNCHANGED":True,
                          "TARGETS_AND_AVAILABILITY_UNCHANGED":True,"PROTECTED_TEST_TRUTH_OPENED":False,
                          "BANK_V2_USED":False,"PHASE2_RECEIPT_COMPLETE":True},
             "scope":"Causal objective intervention only; no external qualification, new architecture or cross-lane winner"}
    write_json(OUTPUT/"PHASE2-RECEIPT.json",receipt)
    print(json.dumps({"status":"PHASE2_COMPLETE","receipt":str(OUTPUT/"PHASE2-RECEIPT.json"),
                      "elapsed_seconds":receipt["total_seconds"]}),flush=True)


if __name__=="__main__":main()
