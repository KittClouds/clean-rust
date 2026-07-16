use candle_core::{Device, Tensor};
use phoenix_candle_burn_spike::{
    artifact_root, benchmark_args, finish_report, prepare_input, FEATURE_DIM, HIDDEN_DIM,
};
use std::hint::black_box;
use std::time::Instant;

fn forward(input: &Tensor, weight_1: &Tensor, weight_2: &Tensor) -> candle_core::Result<Tensor> {
    input.matmul(weight_1)?.relu()?.matmul(weight_2)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (queries, warmups, iterations) = benchmark_args();
    let mut input = prepare_input(&artifact_root("shared-v1"), queries)?;
    let rows = input.rows.len();
    let device = Device::Cpu;

    let tensor_started = Instant::now();
    let features = Tensor::from_vec(
        std::mem::take(&mut input.features),
        (rows, FEATURE_DIM),
        &device,
    )?;
    let weight_1 = Tensor::from_vec(
        std::mem::take(&mut input.weight_1),
        (FEATURE_DIM, HIDDEN_DIM),
        &device,
    )?;
    let weight_2 = Tensor::from_vec(
        std::mem::take(&mut input.weight_2),
        (HIDDEN_DIM, 1),
        &device,
    )?;
    let tensor_create = tensor_started.elapsed();

    let warmup_started = Instant::now();
    for _ in 0..warmups {
        black_box(forward(&features, &weight_1, &weight_2)?);
    }
    let warmup = warmup_started.elapsed();

    let inference_started = Instant::now();
    let mut output = forward(&features, &weight_1, &weight_2)?;
    for _ in 1..iterations {
        output = forward(&features, &weight_1, &weight_2)?;
        black_box(&output);
    }
    let inference = inference_started.elapsed();

    let output_started = Instant::now();
    let scores = output.flatten_all()?.to_vec1::<f32>()?;
    let output_copy = output_started.elapsed();
    let report = finish_report(
        "candle",
        "0.11.0",
        "cpu",
        &input,
        scores,
        warmups,
        iterations,
        tensor_create,
        warmup,
        inference,
        output_copy,
    )?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
