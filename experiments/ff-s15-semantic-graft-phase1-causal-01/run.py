"""Full causal Phase 1: frozen caches, unchanged model/loss, DEV selection, sealed receipt."""
from __future__ import annotations

import json
import math
import shutil
import time
from datetime import datetime, timezone

from contract import (SOURCE, OUTPUT, NVME, PHASE0, PHASE0_LOCK_SHA, SUBSTRATE,
                      default_config, freeze_spec, verify_spec, verify_frozen,
                      pad_candidates, sha_file, write_json, supervision_abi)
import numpy as np
import torch

from graft.baseline import prior_model
from graft.dataset import PackedBank, assert_disjoint, training_normalizer
from graft.model import model_for_substrate, forward_batch
from graft.objective import shared_objective
from graft.evaluate import runtime_envelopes
from reporting import exact_loss, complete_report, per_target


def cpu_tree(value):
    if torch.is_tensor(value):
        return value.detach().cpu()
    if isinstance(value,dict):
        return {k:cpu_tree(v) for k,v in value.items()}
    if isinstance(value,list):
        return [cpu_tree(v) for v in value]
    return value


def dump_checkpoint(path,model,opt,spec,epoch,dev_loss):
    temporary = path.with_suffix(".tmp")
    torch.save({"state_dict":cpu_tree(model.state_dict()),
                "optimizer_state":cpu_tree(opt.state_dict()),
                "fabric_config":model.config,"phase1_spec_sha256":sha_file(OUTPUT/"PHASE1-SPEC.json"),
                "phase0_lock_sha256":PHASE0_LOCK_SHA,"epoch":epoch,
                "DEV_selection_loss":dev_loss,"supervision_abi":supervision_abi(),
                "representation_id":spec["representation_id"],
                "frozen_backbone":True},temporary)
    temporary.replace(path)


def main():
    spec = freeze_spec()
    start = time.perf_counter()
    torch.set_num_threads(4)
    torch.manual_seed(spec["seed"])
    torch.cuda.manual_seed_all(spec["seed"])
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(False)
    if not torch.cuda.is_available():
        raise RuntimeError("declared CUDA device unavailable")
    device = spec["device"]
    cfg = default_config()
    train = PackedBank(NVME/"data"/"TRAIN",SUBSTRATE,cfg)
    dev = PackedBank(NVME/"data"/"DEV",SUBSTRATE,cfg)
    assert_disjoint(train,dev)
    if len(train)!=20000 or len(dev)!=2000:
        raise ValueError("canonical split population changed")
    if train.representation_id!=dev.representation_id:
        raise ValueError("representation identity mismatch")
    for data in (train,dev):
        if int(np.diff(data.arrays["offsets"]).max())>28:
            raise ValueError("m_cap overflow; cannot silently prune")
    model = model_for_substrate(cfg,SUBSTRATE).to(device)
    mean,std = training_normalizer(train)
    model.input_mean.copy_(mean.to(device));model.input_std.copy_(std.to(device))
    spec["representation_id"] = train.representation_id
    prior = prior_model(train)
    prior["candidate_majority"] = [float(train.arrays["candidate_y"][:,i].mean()) for i in range(7)]
    endpoints = train.extras["action_target"][train.extras["action_available"]]
    prior["endpoint_index_mode"] = int(np.bincount(endpoints,minlength=28).argmax())
    write_json(OUTPUT/"TRAIN-trivial-baselines.json",prior)
    from graft.evaluate import predictions
    initial_rows = predictions(model,dev,device,128)
    initial_targets = per_target(initial_rows)
    initial_loss = exact_loss(model,dev,device)
    from reporting import conditioning, renderer_diagnostic, endpoint_metrics
    initial = {"targets":initial_targets,"loss":initial_loss,"endpoint":endpoint_metrics(initial_rows),
               "candidate_conditioning":conditioning(model,dev,device),
               "renderer":renderer_diagnostic(model,dev,device),
               "scope":"Untrained full DEV forward only; no 6k smoke evidence"}
    write_json(OUTPUT/"UNTRAINED-DEV.json",initial)
    del initial_rows
    tc = spec["training"]
    opt = torch.optim.AdamW(model.parameters(),lr=tc["lr"],weight_decay=tc["weight_decay"])
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt,T_max=tc["max_epochs"],eta_min=tc["minimum_lr"])
    rng = np.random.default_rng(spec["seed"])
    pair_rng = np.random.default_rng(spec["seed"]+1)
    pairs = train.extras["renderer_pairs"]
    history=[]
    best, best_epoch, stale = math.inf,0,0
    steps=0
    checkpoints=OUTPUT/"checkpoints"
    checkpoints.mkdir(exist_ok=False)
    print(json.dumps({"status":"TRAINING_STARTED","substrate":SUBSTRATE,"TRAIN":len(train),
                      "DEV":len(dev),"parameters":sum(p.numel() for p in model.parameters()),
                      "m_cap":28,"max_epochs":tc["max_epochs"],"initial_DEV_loss":initial_loss}),flush=True)
    for epoch in range(1,tc["max_epochs"]+1):
        epoch_start=time.perf_counter()
        model.train()
        order=rng.permutation(len(train))
        losses={k:0.0 for k in ("S","E","A","CF","R")}
        batches=0
        grad_norms=[]
        learning_rate=opt.param_groups[0]["lr"]
        for position in range(0,len(order),tc["batch_size"]):
            indices=order[position:position+tc["batch_size"]]
            b=pad_candidates(train.batch(indices,device))
            chosen=pairs[pair_rng.choice(len(pairs),min(len(pairs),tc["renderer_pairs_per_batch"]),replace=False)]
            left,right=(pad_candidates(train.batch(chosen[:,i],device)) for i in (0,1))
            renderer=(forward_batch(model,left),forward_batch(model,right),left["candidate_mask"],right["candidate_mask"])
            loss,detail=shared_objective(forward_batch(model,b),b,cfg,renderer=renderer)
            if not torch.isfinite(loss):
                raise ValueError("nonfinite objective; preserve attempt")
            opt.zero_grad(set_to_none=True)
            loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),tc["gradient_clip"],error_if_nonfinite=True)
            opt.step()
            steps+=1;batches+=1
            grad_norms.append(float(norm))
            for k in losses:
                losses[k]+=detail[k]
        scheduler.step()
        dev_loss=exact_loss(model,dev,device,tc["batch_size"])
        from reporting import endpoint_metrics
        epoch_rows=predictions(model,dev,device,tc["batch_size"])
        targets=per_target(epoch_rows)
        endpoint=endpoint_metrics(epoch_rows)
        record={"epoch":epoch,"lr":learning_rate,"rows_seen":len(order),"optimizer_steps_total":steps,
                "mean_batch_training_components":{k:v/batches for k,v in losses.items()},
                "mean_unclipped_gradient_norm":float(np.mean(grad_norms)),"DEV_loss":dev_loss,
                "DEV_targets":targets,"DEV_endpoint":endpoint,
                "elapsed_seconds":time.perf_counter()-epoch_start}
        history.append(record)
        checkpoint=checkpoints/f"epoch-{epoch:03d}.pt"
        dump_checkpoint(checkpoint,model,opt,spec,epoch,dev_loss)
        record["checkpoint_sha256"]=sha_file(checkpoint)
        if dev_loss["total"]<best:
            best,best_epoch,stale=dev_loss["total"],epoch,0
        else:
            stale+=1
        record["best_epoch_so_far"]=best_epoch
        write_json(OUTPUT/"training-history.json",history)
        print(json.dumps({"epoch":epoch,"DEV_loss":dev_loss["total"],"best_epoch":best_epoch,
                          "DEV_action_accuracy":endpoint["accuracy"],
                          "elapsed_seconds":record["elapsed_seconds"]}),flush=True)
        del epoch_rows
        if stale>=tc["early_stopping_patience"]:
            break
    best_path=checkpoints/f"epoch-{best_epoch:03d}.pt"
    artifact=OUTPUT/"best-graft.pt"
    shutil.copyfile(best_path,artifact)
    saved=torch.load(artifact,map_location=device,weights_only=True)
    model.load_state_dict(saved["state_dict"])
    artifact_hash=sha_file(artifact)
    torch.cuda.synchronize()
    train_seconds=time.perf_counter()-start
    report,rows=complete_report(model,dev,device,prior,initial)
    report["best_DEV_exact_loss"]=exact_loss(model,dev,device)
    write_json(OUTPUT/"DEV-METRICS.json",report)
    with (OUTPUT/"DEV-estimates.jsonl").open("x",encoding="utf-8") as stream:
        for envelope in runtime_envelopes(rows,artifact_hash,train.representation_id,supervision_abi()):
            stream.write(json.dumps(envelope,sort_keys=True,allow_nan=False)+"\n")
    # A second artifact load must reproduce deterministic inference exactly.
    clone=model_for_substrate(cfg,SUBSTRATE).to(device)
    clone.load_state_dict(torch.load(artifact,map_location=device,weights_only=True)["state_dict"])
    model.eval();clone.eval()
    b=pad_candidates(dev.batch(np.arange(8),device))
    with torch.no_grad():
        before,after=forward_batch(model,b),forward_batch(clone,b)
        if not all(torch.equal(before[k],after[k]) for k in before):
            raise ValueError("trained checkpoint inference replay mismatch")
    verify_spec(spec)
    files={str(p.relative_to(OUTPUT)):sha_file(p) for p in sorted(OUTPUT.rglob("*"))
           if p.is_file() and p.name not in ("PHASE1-RECEIPT.json","ENGINEERING-REPORT.md")}
    from interpretation import write_interpretation
    write_interpretation(report,history,best_epoch,artifact_hash)
    files["ENGINEERING-REPORT.md"]=sha_file(OUTPUT/"ENGINEERING-REPORT.md")
    receipt={"status":"PHASE1_COMPLETE","schema":"frozen-fabrique.semantic-graft-phase1-receipt/v1",
             "completed_at_utc":datetime.now(timezone.utc).isoformat(),
             "substrate":SUBSTRATE,"representation_id":train.representation_id,
             "phase0_lock_sha256":PHASE0_LOCK_SHA,"phase0_architecture_sha256":spec["architecture_sha256"],
             "model_class":type(model).__name__,"latent_dimensions":{"s":cfg["semantic_dim"],"e":cfg["epistemic_dim"]},
             "trainable_parameters":sum(p.numel() for p in model.parameters()),"candidate_convention":spec["candidate_convention"],
             "TRAIN_rows":len(train),"DEV_rows":len(dev),"training_config":tc,
             "target_availability":supervision_abi(),"best_epoch":best_epoch,"epochs_completed":len(history),
             "optimizer_steps":steps,"backbone_optimizer_steps":0,"full_TRAIN_passes":len(history),
             "best_checkpoint_sha256":artifact_hash,"DEV_selection_loss":best,
             "elapsed_training_and_selection_seconds":train_seconds,
             "total_elapsed_seconds":time.perf_counter()-start,
             "peak_GPU_allocated_bytes":torch.cuda.max_memory_allocated(),
             "device_name":torch.cuda.get_device_name(0),"torch_version":torch.__version__,
             "files":files,"checkpoint_replay_exact":True,
             "exit_gate":{"FULL_TRAIN_RUN_COMPLETE":True,"BEST_CHECKPOINT_FROZEN":True,
                          "ALL_SOURCEABLE_TARGETS_SCORED":True,"CANDIDATE_CONDITIONING_CHECK_COMPLETE":True,
                          "PHASE0_TARGET_SEMANTICS_UNCHANGED":True,"PHASE0_ARCHITECTURE_UNCHANGED":True,
                          "PROTECTED_TEST_TRUTH_OPENED":False,"BANK_V2_USED":False,"PHASE1_RECEIPT_COMPLETE":True},
             "scope":"Causal engineering phase only; no cross-lane winner, protected TEST, BANK-v2, VCS or System1.5 integration",
             "anomalies":["Candidate cap corrected from 24 to user-authorized 28 before training",
                          "Candidate-supported and related epistemic targets unavailable; CF inactive",
                          "Missing-annotation count restricted to 0/1",
                          "No S7/S8/S9 coverage; renderer diagnostics not held-renderer qualification"]}
    write_json(OUTPUT/"PHASE1-RECEIPT.json",receipt)
    print(json.dumps({"status":receipt["status"],"best_epoch":best_epoch,"artifact_sha256":artifact_hash,
                      "receipt":str(OUTPUT/"PHASE1-RECEIPT.json"),"elapsed_seconds":receipt["total_elapsed_seconds"]}),flush=True)


if __name__=="__main__":
    main()
