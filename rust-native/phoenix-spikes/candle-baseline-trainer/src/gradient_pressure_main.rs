use phoenix_candle_baseline_trainer::{
    open_gradient_pressure_audit, run_gradient_pressure_audit_v1, GradientPressureAuditRequest,
};
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args_os().skip(1).collect::<Vec<_>>();
    if arguments.len() == 1 {
        let path = PathBuf::from(arguments.remove(0));
        let receipt = open_gradient_pressure_audit(&path)?;
        println!("audit_id={}", receipt.audit_id);
        println!("decision={:?}", receipt.decision);
        println!("receipt={}", path.display());
        return Ok(());
    }
    let mut arguments = arguments.into_iter();
    let source_manifest = PathBuf::from(arguments.next().ok_or("source manifest")?);
    let task_manifest = PathBuf::from(arguments.next().ok_or("task manifest")?);
    let checkpoint_manifest = PathBuf::from(arguments.next().ok_or("checkpoint manifest")?);
    let output_root = PathBuf::from(arguments.next().ok_or("output root")?);
    if arguments.next().is_some() {
        return Err("usage: gradient-pressure-audit-v1 SOURCE TASK CHECKPOINT OUTPUT".into());
    }
    let paths = run_gradient_pressure_audit_v1(&GradientPressureAuditRequest {
        source_manifest,
        task_manifest,
        checkpoint_manifest,
        output_root,
    })?;
    println!("audit_id={}", paths.audit_id);
    println!("receipt={}", paths.receipt.display());
    Ok(())
}
