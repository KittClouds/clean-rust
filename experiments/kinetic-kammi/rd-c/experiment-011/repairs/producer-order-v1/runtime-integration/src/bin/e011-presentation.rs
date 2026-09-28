use std::{env, fs};

use rdc_e011_runtime_integration::{
    PresentedOption, hex_digest, parse_hex_digest, prepare_presentation,
};
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    task_digest_hex: String,
    options: Vec<PresentedOption>,
}

#[derive(Serialize)]
struct Output {
    schema_id: &'static str,
    task_digest_hex: String,
    request_id_hex: String,
    receipt_hex: String,
    receipt_digest_hex: String,
    ordered_options: Vec<PresentedOption>,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("e011-presentation: {error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args_os().skip(1);
    let input_path = args.next().ok_or("missing input JSON path")?;
    let output_path = args.next().ok_or("missing output JSON path")?;
    if args.next().is_some() {
        return Err("expected exactly two paths".into());
    }
    let input: Input = serde_json::from_slice(&fs::read(input_path)?)?;
    let task_digest = parse_hex_digest(&input.task_digest_hex)?;
    let prepared = prepare_presentation(task_digest, input.options)?;
    let output = Output {
        schema_id: "rdc-candidate-presentation.v1",
        task_digest_hex: hex_digest(&task_digest),
        request_id_hex: hex_digest(&prepared.request_id),
        receipt_hex: encode_hex(&prepared.receipt),
        receipt_digest_hex: hex_digest(&prepared.receipt_digest),
        ordered_options: prepared.ordered_options,
    };
    fs::write(output_path, serde_json::to_vec_pretty(&output)?)?;
    Ok(())
}

fn encode_hex(bytes: &[u8]) -> String {
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}
