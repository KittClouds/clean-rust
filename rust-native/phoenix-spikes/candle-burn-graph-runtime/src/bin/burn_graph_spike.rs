use burn::backend::Flex;
use burn::tensor::activation;
use burn::tensor::{Tensor, TensorData};
use phoenix_candle_burn_spike::{
    artifact_root, benchmark_args, finish_report, prepare_input, FEATURE_DIM, HIDDEN_DIM,
};
use std::hint::black_box;
use std::time::Instant;

type Cpu = Flex;

fn forward(
    input: &Tensor<Cpu, 2>,
    weight_1: &Tensor<Cpu, 2>,
    weight_2: &Tensor<Cpu, 2>,
) -> Tensor<Cpu, 2> {
    activation::relu(input.clone().matmul(weight_1.clone())).matmul(weight_2.clone())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (queries, warmups, iterations) = benchmark_args();
    let mut input = prepare_input(&artifact_root("shared-v1"), queries)?;
    let rows = input.rows.len();
    let device = Default::default();

    let tensor_started = Instant::now();
    let features = Tensor::<Cpu, 2>::from_data(
        TensorData::new(std::mem::take(&mut input.features), [rows, FEATURE_DIM]),
        &device,
    );
    let weight_1 = Tensor::<Cpu, 2>::from_data(
        TensorData::new(
            std::mem::take(&mut input.weight_1),
            [FEATURE_DIM, HIDDEN_DIM],
        ),
        &device,
    );
    let weight_2 = Tensor::<Cpu, 2>::from_data(
        TensorData::new(std::mem::take(&mut input.weight_2), [HIDDEN_DIM, 1]),
        &device,
    );
    let tensor_create = tensor_started.elapsed();

    let warmup_started = Instant::now();
    for _ in 0..warmups {
        black_box(forward(&features, &weight_1, &weight_2));
    }
    let warmup = warmup_started.elapsed();

    let inference_started = Instant::now();
    let mut output = forward(&features, &weight_1, &weight_2);
    for _ in 1..iterations {
        output = forward(&features, &weight_1, &weight_2);
        black_box(&output);
    }
    let inference = inference_started.elapsed();

    let output_started = Instant::now();
    let scores = output.into_data().to_vec::<f32>()?;
    let output_copy = output_started.elapsed();
    let report = finish_report(
        "burn",
        "0.21.0",
        "flex-cpu",
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
