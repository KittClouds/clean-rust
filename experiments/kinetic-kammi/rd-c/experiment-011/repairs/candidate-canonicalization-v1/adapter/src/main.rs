use memchr::memmem;
use memmap2::MmapOptions;
use rdc_candidate_canonicalizer::canonicalize_frame;
use serde_json::{Value, json};
use std::{
    env,
    fs::{self, File},
    process::ExitCode,
};

fn run() -> Result<(), String> {
    let args = env::args_os().skip(1).collect::<Vec<_>>();
    if args.len() != 3 || args[0] != "canonicalize" {
        return Err(
            "usage: rdc-candidate-canonicalizer canonicalize <input.json> <output.json>".into(),
        );
    }
    let input = File::open(&args[1]).map_err(|error| format!("open input: {error}"))?;
    let mapped =
        unsafe { MmapOptions::new().map(&input) }.map_err(|error| format!("map input: {error}"))?;
    if memmem::find(&mapped, b"action_options").is_none() {
        return Err("input does not contain action_options".into());
    }
    let frame: Value =
        serde_json::from_slice(&mapped).map_err(|error| format!("parse frame: {error}"))?;
    let (frame, receipt) = canonicalize_frame(frame)?;
    let output = json!({
        "adapter_id": "candidate-canonicalization-v1",
        "frame": frame,
        "receipt": receipt
    });
    let bytes =
        serde_json::to_vec_pretty(&output).map_err(|error| format!("serialize result: {error}"))?;
    fs::write(&args[2], bytes).map_err(|error| format!("write output: {error}"))?;
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}
