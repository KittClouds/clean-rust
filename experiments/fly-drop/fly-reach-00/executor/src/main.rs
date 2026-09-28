mod graph;
mod reach_sim;
mod rng;
mod task;

use anyhow::{Context, Result, ensure};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use reach_sim::Sim;
use std::{collections::BTreeMap, fs::{self, File, OpenOptions}, io::{BufWriter, Read, Write}, path::{Path, PathBuf}, sync::Arc, time::Instant};
use task::{Pattern, Task};

const TAU: f32 = 16.0;
const ETA: f32 = 0.05;
const REFERENCE_LR: f64 = 0.05;
const ORACLE_LR: f64 = 0.5;
const ORACLE_STEPS: usize = 128;
const PRETRAIN_TRIALS: usize = 8192;
const THRESHOLD: f64 = 0.25;
const GLUT_SIGN: f32 = -1.0;
const SUBSTRATES: [&str; 9] = ["fly", "g001", "g002", "g003", "g004", "g005", "g006", "g007", "g008"];
const SIDES: [&str; 2] = ["L", "R"];
const BLOCKS: [u64; 12] = [52000, 52001, 52002, 52003, 52004, 52005, 52006, 52007, 52008, 52009, 52010, 52011];
const CHECKPOINTS: [usize; 6] = [0, 512, 1024, 2048, 4096, 8192];
const ARMS: [&str; 5] = ["native", "native_direction_reference_magnitude", "reference_direction_native_support", "reference_direction_full_support", "weight_oracle"];

#[derive(Deserialize)] struct TrainBlock { task_seed: u64, labels: Vec<bool>, schedule: Vec<Vec<usize>>, cue_count: usize }
#[derive(Deserialize)] struct TrainBank { blocks: BTreeMap<String, TrainBlock> }
#[derive(Deserialize)] struct EvalBank { response_draws_u64: Vec<Vec<u64>> }
#[derive(Clone, Copy)] struct Job { substrate: &'static str, side: &'static str, block: u64 }

#[derive(Serialize)] struct Outcome<'a> { substrate: &'a str, side: &'a str, block: u64, arm: &'a str, checkpoint: usize, loss_256: f64, loss_large: f64, competent: bool, finite: bool, state_digest: String }
#[derive(Serialize)] struct Diagnostics<'a> { substrate: &'a str, side: &'a str, block: u64, arm: &'a str, native_update_norm_mean: f64, reference_update_norm_mean: f64, native_reference_cosine_mean: f64, native_reference_norm_ratio_mean: f64, native_support_fraction_mean: f64, reference_mass_on_native_support_mean: f64, bound_clip_fraction: f64, cumulative_delivered_l2: f64, finite: bool }

fn hash_file(path: &Path) -> Result<String> { let mut f=File::open(path).with_context(||path.display().to_string())?; let mut h=Sha256::new(); let mut b=[0u8;65536]; loop { let n=f.read(&mut b)?; if n==0 {break;} h.update(&b[..n]); } Ok(format!("{:x}",h.finalize())) }
fn sigmoid(x: f64) -> f64 { 1.0/(1.0+(-x.clamp(-40.0,40.0)).exp()) }

fn verify_contract(study: &Path) -> Result<Value> {
    let p=study.join("manifests/REACH-CONTRACT.json"); let expected=fs::read_to_string(study.join("manifests/REACH-CONTRACT.sha256"))?.split_whitespace().next().context("contract sidecar")?.to_string(); ensure!(hash_file(&p)?==expected,"REACH contract checksum mismatch");
    let c:Value=serde_json::from_reader(File::open(p)?)?; ensure!(c["status"]=="SEALED_ENGINEERING_ONLY"); ensure!(c["no_lesions"]==true && c["no_biological_promotion"]==true);
    for e in c["input_hashes"].as_array().context("input hashes")? { let rel=e["path"].as_str().unwrap(); ensure!(hash_file(&study.join(rel))?==e["sha256"].as_str().unwrap(),"input hash mismatch: {rel}"); }
    Ok(c)
}

fn expected_score(weights:&[f32], sim:&Sim<'_>, pattern:&Pattern)->f64 { let mut score=0.0; for j in 0..sim.post.len() { let mut drive=0.0; for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j+1]] { drive+=f64::from(weights[ix]); } let p=sigmoid(2.0*(drive/f64::from(sim.denom[j])-f64::from(sim.bias[j]))); score+=f64::from(sim.action_sign[j])*(p-0.5); } score }

fn reference_delta_into(sim:&Sim<'_>, task:&Task, lr:f64, out:&mut [f32], grad:&mut [f64]) {
    grad.fill(0.0);
    for (pattern,&label) in task.patterns[..task.cues].iter().zip(&task.labels) {
        let score=expected_score(&sim.weights,sim,pattern); let y=if label {1.0}else{-1.0}; let coeff=-y*4.0*sigmoid(-y*4.0*score);
        for j in 0..sim.post.len() { let mut drive=0.0; for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j+1]] { drive+=f64::from(sim.weights[ix]); } let p=sigmoid(2.0*(drive/f64::from(sim.denom[j])-f64::from(sim.bias[j]))); let d=f64::from(sim.action_sign[j])*2.0*p*(1.0-p)/f64::from(sim.denom[j]); for &ix in &pattern.edges[pattern.offsets[j]..pattern.offsets[j+1]] { grad[ix]+=coeff*d/task.cues as f64; } }
    }
    for (o,&g) in out.iter_mut().zip(grad.iter()) { *o=(-lr*g) as f32; }
}

fn norm(v:&[f32])->f64 { v.iter().map(|x|f64::from(*x)*f64::from(*x)).sum::<f64>().sqrt() }
fn dot(a:&[f32],b:&[f32])->f64 { a.iter().zip(b).map(|(x,y)|f64::from(*x)*f64::from(*y)).sum() }
fn rescale(src:&[f32],target:f64,out:&mut [f32]) { let n=norm(src); if n==0.0 { out.fill(0.0); } else { let k=(target/n) as f32; for (o,&x) in out.iter_mut().zip(src) { *o=x*k; } } }
fn masked_rescale(src:&[f32],mask:&[f32],target:f64,out:&mut [f32]) { for ((o,&x),&m) in out.iter_mut().zip(src).zip(mask) { *o=if m.abs()>1e-12{x}else{0.0}; } let n=norm(out); if n==0.0 { out.fill(0.0); } else { let k=(target/n) as f32; for o in out { *o*=k; } } }

fn oracle(sim0:&Sim<'_>,task:&Task)->Vec<f32> { let mut sim=sim0.clone(); let mut delta=vec![0.0;sim.weights.len()]; let mut grad=vec![0.0;sim.weights.len()]; for _ in 0..ORACLE_STEPS { reference_delta_into(&sim,task,ORACLE_LR,&mut delta,&mut grad); sim.apply_delta(&delta); } sim.weights }

fn run_job(graph:Arc<graph::Graph>,job:Job,train:&TrainBlock,eval:&EvalBank,large:&EvalBank)->Result<(Vec<String>,Vec<String>)> {
    ensure!(train.cue_count==4 && train.schedule.len()>=PRETRAIN_TRIALS); let task=Task::new(&graph,train.task_seed,train.labels.clone(),train.schedule.clone()); let initial=Sim::new(&graph,train.task_seed,TAU,ETA);
    let mut outcomes=Vec::new(); let mut diagnostics=Vec::new();
    for &arm in &ARMS {
        let mut sim=initial.clone(); let mut native_delta=vec![0.0;sim.weights.len()]; let mut reference_delta=vec![0.0;sim.weights.len()]; let mut custom_delta=vec![0.0;sim.weights.len()]; let mut grad=vec![0.0;sim.weights.len()]; let mut before=vec![0.0;sim.weights.len()];
        if arm=="weight_oracle" { let l0=sim.loss(&task,&eval.response_draws_u64); let ll0=sim.loss(&task,&large.response_draws_u64); outcomes.push(serde_json::to_string(&Outcome{substrate:job.substrate,side:job.side,block:job.block,arm,checkpoint:0,loss_256:l0,loss_large:ll0,competent:l0<=THRESHOLD,finite:sim.finite(),state_digest:sim.digest()})?+"\n"); sim.weights=oracle(&initial,&task); let l256=sim.loss(&task,&eval.response_draws_u64); let ll=sim.loss(&task,&large.response_draws_u64); outcomes.push(serde_json::to_string(&Outcome{substrate:job.substrate,side:job.side,block:job.block,arm,checkpoint:PRETRAIN_TRIALS,loss_256:l256,loss_large:ll,competent:l256<=THRESHOLD,finite:sim.finite(),state_digest:sim.digest()})?+"\n"); diagnostics.push(serde_json::to_string(&Diagnostics{substrate:job.substrate,side:job.side,block:job.block,arm,native_update_norm_mean:0.0,reference_update_norm_mean:0.0,native_reference_cosine_mean:0.0,native_reference_norm_ratio_mean:0.0,native_support_fraction_mean:0.0,reference_mass_on_native_support_mean:0.0,bound_clip_fraction:0.0,cumulative_delivered_l2:0.0,finite:sim.finite()})?+"\n"); continue; }
        let l0=sim.loss(&task,&eval.response_draws_u64); let ll0=sim.loss(&task,&large.response_draws_u64); outcomes.push(serde_json::to_string(&Outcome{substrate:job.substrate,side:job.side,block:job.block,arm,checkpoint:0,loss_256:l0,loss_large:ll0,competent:l0<=THRESHOLD,finite:sim.finite(),state_digest:sim.digest()})?+"\n");
        let mut sum_n=0.0; let mut sum_r=0.0; let mut sum_c=0.0; let mut sum_ratio=0.0; let mut sum_support=0.0; let mut sum_capture=0.0; let mut clip_count=0usize; let mut touched=0usize; let mut cumulative=0.0;
        for trial in 0..PRETRAIN_TRIALS {
            let (_correct,reward)=sim.begin_trial(&task,trial); sim.proposed_delta_into(reward,&mut native_delta); reference_delta_into(&sim,&task,REFERENCE_LR,&mut reference_delta,&mut grad);
            let rn=norm(&native_delta); let rr=norm(&reference_delta); let support=native_delta.iter().filter(|x|x.abs()>1e-12).count(); let capture=if reference_delta.iter().map(|x|f64::from(*x).abs()).sum::<f64>()==0.0 {0.0} else {reference_delta.iter().zip(&native_delta).filter(|(_,n)|n.abs()>1e-12).map(|(r,_)|f64::from(*r).abs()).sum::<f64>()/reference_delta.iter().map(|x|f64::from(*x).abs()).sum::<f64>()};
            sum_n+=rn; sum_r+=rr; sum_support+=support as f64/native_delta.len() as f64; sum_capture+=capture; if rn>0.0 && rr>0.0 { sum_c+=dot(&native_delta,&reference_delta)/(rn*rr); sum_ratio+=rn/rr; }
            let target=rr; match arm { "native"=>custom_delta.copy_from_slice(&native_delta), "native_direction_reference_magnitude"=>rescale(&native_delta,target,&mut custom_delta), "reference_direction_native_support"=>masked_rescale(&reference_delta,&native_delta,target,&mut custom_delta), "reference_direction_full_support"=>custom_delta.copy_from_slice(&reference_delta), _=>unreachable!() }
            before.copy_from_slice(&sim.weights); sim.apply_delta(&custom_delta); for i in 0..sim.weights.len() { let delivered=sim.weights[i]-before[i]; cumulative+=f64::from(delivered).powi(2); if custom_delta[i].abs()>1e-12 { touched+=1; if (f64::from(delivered)-f64::from(custom_delta[i])).abs()>1e-6 {clip_count+=1;} } }
            let checkpoint=trial+1; if CHECKPOINTS.contains(&checkpoint) { let l256=sim.loss(&task,&eval.response_draws_u64); let ll=sim.loss(&task,&large.response_draws_u64); outcomes.push(serde_json::to_string(&Outcome{substrate:job.substrate,side:job.side,block:job.block,arm,checkpoint,loss_256:l256,loss_large:ll,competent:l256<=THRESHOLD,finite:sim.finite(),state_digest:sim.digest()})?+"\n"); }
        }
        diagnostics.push(serde_json::to_string(&Diagnostics{substrate:job.substrate,side:job.side,block:job.block,arm,native_update_norm_mean:sum_n/PRETRAIN_TRIALS as f64,reference_update_norm_mean:sum_r/PRETRAIN_TRIALS as f64,native_reference_cosine_mean:sum_c/PRETRAIN_TRIALS as f64,native_reference_norm_ratio_mean:sum_ratio/PRETRAIN_TRIALS as f64,native_support_fraction_mean:sum_support/PRETRAIN_TRIALS as f64,reference_mass_on_native_support_mean:sum_capture/PRETRAIN_TRIALS as f64,bound_clip_fraction:if touched==0{0.0}else{clip_count as f64/touched as f64},cumulative_delivered_l2:cumulative.sqrt(),finite:sim.finite()})?+"\n");
    }
    Ok((outcomes,diagnostics))
}

fn main()->Result<()> {
    let args:Vec<String>=std::env::args().collect(); ensure!(args.len()==3,"usage: reach-executor STUDY_ROOT RUN_ROOT"); let study=fs::canonicalize(&args[1])?; let run=PathBuf::from(&args[2]); fs::create_dir_all(&run)?; let started=Instant::now(); eprintln!("reach_preflight_start"); let contract=verify_contract(&study)?; ensure!(contract["primary_task"]=="four_cue");
    let train:TrainBank=serde_json::from_reader(File::open(study.join("inputs/banks/training.json"))?)?; let eval:EvalBank=serde_json::from_reader(File::open(study.join("inputs/banks/competence.json"))?)?; let large:EvalBank=serde_json::from_reader(File::open(study.join("inputs/banks/evaluator-large.json"))?)?; ensure!(train.blocks.len()==12 && eval.response_draws_u64.len()==256 && large.response_draws_u64.len()==4096);
    let mut graphs:BTreeMap<(String,String),Arc<graph::Graph>>=BTreeMap::new(); for &s in &SUBSTRATES { for &side in &SIDES { graphs.insert((s.to_string(),side.to_string()),Arc::new(graph::load(&study,s,side,GLUT_SIGN)?)); } }
    let jobs:Vec<Job>=SUBSTRATES.iter().flat_map(|&s|SIDES.iter().flat_map(move |&side|BLOCKS.iter().map(move |&b|Job{substrate:s,side,block:b}))).collect(); ensure!(jobs.len()==216); eprintln!("reach_collection_start blocks={}",jobs.len());
    let results:Vec<Result<(Vec<String>,Vec<String>)>>=jobs.par_iter().map(|job|{let g=graphs.get(&(job.substrate.to_string(),job.side.to_string())).unwrap().clone(); run_job(g,*job,train.blocks.get(&job.block.to_string()).unwrap(),&eval,&large)}).collect();
    let mut ow=BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run.join("outcomes.jsonl"))?); let mut dw=BufWriter::new(OpenOptions::new().create_new(true).write(true).open(run.join("diagnostics.jsonl"))?); let mut oc=0; let mut dc=0; for result in results { let (a,b)=result?; for x in a {ow.write_all(x.as_bytes())?;oc+=1;} for x in b {dw.write_all(x.as_bytes())?;dc+=1;} } ow.flush()?;dw.flush()?;
    let receipt=serde_json::json!({"schema":"FLY-REACH-00-collection-receipt-v1","study_id":"FLY-REACH-00","status":"QUALIFICATION_COMPLETE","engineering_only":true,"completed_blocks":jobs.len(),"outcome_rows":oc,"diagnostic_rows":dc,"arms":ARMS,"checkpoints":CHECKPOINTS,"threshold":THRESHOLD,"wall_seconds":started.elapsed().as_secs_f64(),"contract_sha256":hash_file(&study.join("manifests/REACH-CONTRACT.json"))?}); let mut f=OpenOptions::new().create_new(true).write(true).open(run.join("collection-receipt.json"))?; serde_json::to_writer_pretty(&mut f,&receipt)?;f.write_all(b"\n")?;eprintln!("reach_collection_complete blocks={} outcomes={} diagnostics={}",jobs.len(),oc,dc);Ok(())
}

#[cfg(test)] mod tests { use super::*; #[test] fn frozen_reach_contract(){assert_eq!(ARMS.len(),5);assert_eq!(CHECKPOINTS,[0,512,1024,2048,4096,8192]);assert_eq!(THRESHOLD,0.25);} }
