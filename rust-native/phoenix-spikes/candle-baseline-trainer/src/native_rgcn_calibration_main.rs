use phoenix_candle_baseline_trainer::{
    run_native_rgcn_calibration, CandleRgcnConfig, NativeRgcnCalibrationRequest,
};
use std::env;
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = env::args_os().skip(1);
    let store_path = arguments
        .next()
        .map(PathBuf::from)
        .ok_or("usage: native-rgcn-calibration-760 <store-path> <output-root> [seed]")?;
    let output_root = arguments
        .next()
        .map(PathBuf::from)
        .ok_or("usage: native-rgcn-calibration-760 <store-path> <output-root> [seed]")?;
    let seed = arguments
        .next()
        .map(|value| value.to_string_lossy().parse::<u64>())
        .transpose()?
        .unwrap_or(0x7605_eed5_1ce5_2026);
    if arguments.next().is_some() {
        return Err("unexpected native R-GCN calibration argument".into());
    }
    let report = run_native_rgcn_calibration(&NativeRgcnCalibrationRequest {
        store_path,
        output_root,
        expected_receipts: 760,
        seed,
        config: CandleRgcnConfig::default(),
    })?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
