#![allow(dead_code, unused_imports)] // Frozen compatibility modules retained for tests.
mod allocation;
#[cfg(test)] mod baseline;
mod graph; mod observer; mod plasticity; mod rng; mod simulation; mod task;
mod capture; mod rotation;
pub use allocation::allocations;
use anyhow::{Result,ensure};
use serde::{Serialize,Deserialize};
use serde_json::{json,Value};
use simulation::{Simulator,Dh07Condition};
use std::{path::Path,fs::{File,OpenOptions},io::{BufReader,BufWriter,Write}};

#[derive(Serialize,Deserialize)]
struct States {
    seed:u64, side:String, tau:f32, condition:String,
    snapshots:Vec<capture::Snapshot>,
}
fn write(path:&Path,value:&impl Serialize)->Result<()> {
    let mut w=BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?);
    serde_json::to_writer(&mut w,value)?; w.write_all(b"\n")?;w.flush()?;Ok(())
}
fn get_parent(path:&Path,seed:u64)->Result<Value> {
    use std::io::BufRead;
    for line in BufReader::new(File::open(path)?).lines() {
        let value:Value=serde_json::from_str(&line?)?;
        if value["seed"]==seed {return Ok(value);}
    }
    anyhow::bail!("parent seed missing")
}
fn compare(parent:&Value,result:&Value,condition:&str)->Result<()> {
    let old=parent["results"].as_array().unwrap().iter().find(|r|r["arm"]=="E" && r["condition"]==condition).unwrap();
    for field in ["trajectory","acquisition_state_sha256","paired_final_old_probe","paired_final_reversal_probe","weight_geometry"] {
        ensure!(old["result"][field]==result[field],"parent mismatch {condition} {field}: archived={} replay={}",old["result"][field],result[field]);
    }
    for field in ["curve","accuracy","acquisition","reversal","probe_acquisition","probe_reversal","changed_weights","stimulus_events"] {
        ensure!(old["result"]["outcome"][field]==result["outcome"][field],"parent outcome mismatch {field}");
    }
    Ok(())
}
fn collect(anatomy:&Path,out:&Path,phase:&str)->Result<()> {
    let audit=phase=="audit";
    let range=match phase {"dev"=>9000..9004,"holdout"=>9004..9006,"audit"=>6000..6032,_=>anyhow::bail!("unknown phase")};
    std::fs::create_dir_all(out)?;
    for side in ["R","L"] {for tau in [4.,16.] {
        let graph=graph::Graph::load(anatomy,side,-1.)?;
        for seed in range.clone() {
            let (route,_)=graph.route.rewired(seed^0x887733);
            let task=task::Task::new(&graph,seed^858_980_352,16,12,512);
            let parent=if audit {Some(get_parent(&anatomy.parent().unwrap().parent().unwrap().join(format!("{side}-tau{tau}.jsonl")),seed)?)}else{None};
            let conditions=if audit {vec![(Dh07Condition::Neither,"neither"),(Dh07Condition::ParallelOnly,"parallel_only"),(Dh07Condition::TruePerpendicular,"perpendicular_only"),(Dh07Condition::BothTrue,"both")]}else{vec![(Dh07Condition::TruePerpendicular,"perpendicular_only"),(Dh07Condition::BothTrue,"both")]};
            for (condition,name) in conditions {
                let mut sim=Simulator::new(&graph,&graph.route,seed,tau,0.05,"E");
                sim.capture=Some(capture::Capture::new(sim.weights.len()));
                let run=sim.run_dh07(&task,condition,&route,true,0)?;
                ensure!(run.result.outcome.hot_allocations==0,"capture allocated in hot loop");
                let result=serde_json::to_value(&run.result)?;
                if let Some(p)=&parent {compare(p,&result,name)?;}
                let mut reference=Simulator::new(&graph,&graph.route,seed,tau,0.05,"E");
                let unobserved=reference.run_dh07(&task,condition,&route,true,0)?;
                ensure!(sim.weights==reference.weights && run.result.outcome.curve==unobserved.result.outcome.curve);
                let capture=sim.capture.take().unwrap();
                let stem=format!("{seed}-{side}-{tau}-{name}");
                write(&out.join(format!("{stem}-events.json")),&json!({"seed":seed,"side":side,"tau":tau,"condition":name,"events":capture.events,"parent_behavior_parity":audit,"capture_weight_parity":true,"hot_allocations":run.result.outcome.hot_allocations}))?;
                if !audit {
                    write(&out.join(format!("{stem}-states.json")),&States{seed,side:side.into(),tau,condition:name.into(),snapshots:capture.slots})?;
                }
            }
            println!("{phase}: seed {seed} {side} tau {tau} complete");
        }
    }} Ok(())
}
fn construct(input:&Path,out:&Path)->Result<()> {
    std::fs::create_dir_all(out)?;
    let mut paths=std::fs::read_dir(input)?.map(|p|p.unwrap().path()).filter(|p|p.to_string_lossy().ends_with("-states.json")).collect::<Vec<_>>();paths.sort();
    for path in paths {
        let states:States=serde_json::from_reader(BufReader::new(File::open(&path)?))?;
        let mut rotor=rotation::Rotation::new(states.snapshots[0].base.len());
        let mut rows=Vec::new();let mut committed=Vec::new();
        for (slot,snapshot) in states.snapshots.iter().enumerate() {
            ensure!(snapshot.trial>0);
            let key=rotation::event_key(states.seed,states.tau,states.side.as_bytes()[0],snapshot.trial);
            let audit=rotor.construct(snapshot,key);
            ensure!(audit.hot_allocations==0 && audit.outside_support_changes==0);
            rows.push(json!({"slot":slot,"key":key,"audit":audit}));
            committed.push(rotor.committed.clone());
        }
        let stem=path.file_stem().unwrap().to_str().unwrap().replace("-states","");
        write(&out.join(format!("{stem}-geometry.json")),&json!({"seed":states.seed,"side":states.side,"tau":states.tau,"condition":states.condition,"states_sha256":sha(&path)?,"rows":rows}))?;
        write(&out.join(format!("{stem}-committed.json")),&committed)?;
        println!("constructed {stem}");
    } Ok(())
}
fn sha(path:&Path)->Result<String> {
    use sha2::{Digest,Sha256}; use std::io::Read;
    let mut f=File::open(path)?;let mut hasher=Sha256::new();let mut buf=[0u8;65536];
    loop {let n=f.read(&mut buf)?;if n==0 {break;}hasher.update(&buf[..n]);}
    Ok(format!("{:x}",hasher.finalize()))
}
fn main()->Result<()> {
    let args=std::env::args().collect::<Vec<_>>();
    ensure!(args.len()>=4,"collect ANATOMY OUTPUT dev|holdout|audit OR construct STATES OUTPUT");
    match args[1].as_str() {
        "collect"=>{ensure!(args.len()==5);collect(Path::new(&args[2]),Path::new(&args[3]),&args[4])},
        "construct"=>construct(Path::new(&args[2]),Path::new(&args[3])),
        _=>anyhow::bail!("No measured experiment command exists"),
    }
}
