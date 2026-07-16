use phoenix_candle_baseline_trainer::{run_optimization_envelope_v1, OptimizationEnvelopeRequest};
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args_os().skip(1).collect::<Vec<_>>();
    if arguments.len() == 2 && arguments[0] == "reseal" {
        let path = PathBuf::from(arguments.remove(1));
        let paths = phoenix_candle_baseline_trainer::reseal_optimization_envelope(&path)?;
        println!("envelope_id={}", paths.envelope_id);
        println!("manifest={}", paths.manifest.display());
        return Ok(());
    }
    if arguments.len() == 1 {
        let path = PathBuf::from(arguments.remove(0));
        let manifest = phoenix_candle_baseline_trainer::open_optimization_envelope(&path)?;
        println!("envelope_id={}", manifest.envelope_id);
        println!("manifest={}", path.display());
        return Ok(());
    }
    let mut arguments = arguments.into_iter();
    let source_manifest = PathBuf::from(arguments.next().ok_or("source manifest")?);
    let task_manifest = PathBuf::from(arguments.next().ok_or("task manifest")?);
    let output_root = PathBuf::from(arguments.next().ok_or("output root")?);
    if arguments.next().is_some() {
        return Err("usage: optimization-envelope-v1 SOURCE TASK OUTPUT".into());
    }
    let paths = run_optimization_envelope_v1(&OptimizationEnvelopeRequest {
        source_manifest,
        task_manifest,
        output_root,
    })?;
    println!("envelope_id={}", paths.envelope_id);
    println!("manifest={}", paths.manifest.display());
    Ok(())
}
