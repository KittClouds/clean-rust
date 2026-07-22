use std::time::Instant;

use vector_wgpu_kernel::{
    DispatchPolicy, GpuVectorRuntime, RawVectorInput, normalize_rows, quantize_symmetric_i8,
};

fn main() {
    let rows = 20_000_u32;
    let dimensions = 256_u32;
    let raw = (0..rows * dimensions)
        .map(|index| ((index * 67 + 13) % 65_521) as f32 / 4_093.0 - 8.0)
        .collect::<Vec<_>>();
    let runtime = GpuVectorRuntime::request(DispatchPolicy::default()).expect("request GPU");
    let input = RawVectorInput {
        values: &raw,
        rows,
        dimensions,
    };
    runtime.normalize_quantize(input).expect("warm GPU");

    let mut cpu_values = raw.clone();
    let cpu_started = Instant::now();
    normalize_rows(&mut cpu_values, rows, dimensions).expect("CPU normalization");
    let cpu_quantized =
        quantize_symmetric_i8(&cpu_values, rows, dimensions).expect("CPU quantization");
    let cpu_ms = cpu_started.elapsed().as_secs_f64() * 1_000.0;

    let mut samples = Vec::with_capacity(5);
    let mut last = None;
    for _ in 0..5 {
        let started = Instant::now();
        last = Some(runtime.normalize_quantize(input).expect("GPU preprocess"));
        samples.push(started.elapsed().as_secs_f64() * 1_000.0);
    }
    samples.sort_by(f64::total_cmp);
    let gpu = last.unwrap();
    assert_eq!(gpu.normalized.len(), cpu_values.len());
    assert_eq!(gpu.quantized.values.len(), cpu_quantized.values.len());
    let maximum_normalized_drift = gpu
        .normalized
        .iter()
        .zip(&cpu_values)
        .map(|(actual, expected)| (actual - expected).abs())
        .fold(0.0_f32, f32::max);
    let maximum_quantized_drift = gpu
        .quantized
        .values
        .iter()
        .zip(&cpu_quantized.values)
        .map(|(actual, expected)| (i16::from(*actual) - i16::from(*expected)).abs())
        .max()
        .unwrap_or(0);
    assert!(maximum_normalized_drift <= 2.0e-6);
    assert!(maximum_quantized_drift <= 1);
    println!(
        "vector-preprocess rows={rows} dim={dimensions} cpu_ms={cpu_ms:.3} gpu_p50_ms={:.3} dispatch_us={} readback_us={} normalized_mib={:.2} quantized_mib={:.2} max_normalized_drift={maximum_normalized_drift:.9} max_quantized_drift={maximum_quantized_drift} adapter={}",
        samples[samples.len() / 2],
        gpu.receipt.dispatch_micros,
        gpu.receipt.readback_micros,
        gpu.receipt.shape.normalized_bytes as f64 / 1_048_576.0,
        gpu.receipt.shape.quantized_bytes as f64 / 1_048_576.0,
        runtime.adapter_receipt().name,
    );
}
