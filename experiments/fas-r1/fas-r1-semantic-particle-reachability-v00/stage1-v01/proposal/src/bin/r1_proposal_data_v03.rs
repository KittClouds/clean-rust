use r1_proposal_training::simulator_v03;
use std::env;
use std::path::Path;

const USAGE: &str = "usage: r1_proposal_data_v03 generate REQUESTS_JSONL FROZEN_WEIGHTS_JSON LABELS_JSONL TRACES_JSONL RECEIPT_JSON --mix incidence_masked_norm_4 --temperature T";

fn main() {
    let args = env::args().collect::<Vec<_>>();
    if args.len() != 11
        || args[1] != "generate"
        || args[7] != "--mix"
        || args[8] != "incidence_masked_norm_4"
        || args[9] != "--temperature"
    {
        eprintln!("{USAGE}");
        std::process::exit(2);
    }
    let temperature = match args[10].parse::<f64>() {
        Ok(value) if value.is_finite() && value > 0.0 => value,
        _ => {
            eprintln!("R1_V03_DATA_FAILED temperature must be finite and positive");
            std::process::exit(2);
        }
    };
    if let Err(error) = simulator_v03::generate(
        Path::new(&args[2]),
        Path::new(&args[3]),
        Path::new(&args[4]),
        Path::new(&args[5]),
        Path::new(&args[6]),
        &args[8],
        temperature,
    ) {
        eprintln!("R1_V03_DATA_FAILED {error}");
        std::process::exit(1);
    }
}
