use super::*;
use std::fs::OpenOptions;
use std::io::{self, Write};
use std::mem::{size_of, size_of_val};
use std::path::Path;
use std::time::Instant;

use bytemuck::cast_slice;
use memmap2::{Mmap, MmapOptions};
use zerocopy::{FromBytes, IntoBytes};

pub const AR02A_COMMITS: usize = 4_800;
pub const AR02A_COMMITS_PER_EVIDENCE: usize = 4;
pub const AR02A_VERIFIER_SIZE: usize = 16;
pub const AR02A_SEEDS: [u64; 3] = SEEDS;
pub const AR02A_METHODS: [Method; 6] = [
    Method::SameBatchRandom,
    Method::IndependentRandom,
    Method::ClassBalanced,
    Method::LatentStratified,
    Method::AdamW,
    Method::Sign,
];

const TRAIN_PER_CELL: usize = 8;
const VALIDATION_PER_CELL: usize = 4;
const CELL_COUNT: usize = 12;
const DATASET_MAGIC: [u8; 8] = *b"AR02GAUS";
const PROPOSAL_STREAM: u64 = 0x5052_4f50_4f53_414c;
const VERIFY_STREAM: u64 = 0x4152_3032_5645_5249;
const CELL_DATA_SEED: u64 = 0xA202_0920_6C65_6C6C;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Method {
    SameBatchRandom,
    IndependentRandom,
    ClassBalanced,
    LatentStratified,
    AdamW,
    Sign,
}

impl Method {
    pub const RUNTIME: [Self; 4] = [
        Self::SameBatchRandom,
        Self::IndependentRandom,
        Self::ClassBalanced,
        Self::LatentStratified,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::SameBatchRandom => "same_batch_random",
            Self::IndependentRandom => "independent_random",
            Self::ClassBalanced => "class_balanced",
            Self::LatentStratified => "latent_stratified",
            Self::AdamW => "adamw",
            Self::Sign => "sign",
        }
    }

    const fn is_runtime(self) -> bool {
        matches!(
            self,
            Self::SameBatchRandom
                | Self::IndependentRandom
                | Self::ClassBalanced
                | Self::LatentStratified
        )
    }
}

#[derive(Clone, Copy, Debug)]
pub struct GaussianCells {
    pub samples: [Sample; TOTAL_SAMPLES],
}

pub fn generate_gaussian_cells() -> GaussianCells {
    let mut samples = [Sample {
        x0: 0.0,
        x1: 0.0,
        target: 0,
    }; TOTAL_SAMPLES];
    let mut rng = Rng::new(CELL_DATA_SEED);

    for cell in 0..CELL_COUNT {
        let row = cell / 3;
        let column = cell % 3;
        let class = (row + column) % CLASSES;
        let center_x = -0.9 + column as f32 * 0.9;
        let center_y = -0.9 + row as f32 * 0.6;
        let angle = 0.23 + cell as f32 * 0.37;
        let (sin, cos) = angle.sin_cos();
        for (split, per_cell) in [(0, TRAIN_PER_CELL), (1, VALIDATION_PER_CELL)] {
            let base = if split == 0 {
                cell * TRAIN_PER_CELL
            } else {
                TRAIN_SAMPLES + cell * VALIDATION_PER_CELL
            };
            for offset in 0..per_cell {
                let (z0, z1) = normal_pair(&mut rng);
                let major = 0.225 * z0;
                let minor = 0.095 * z1;
                samples[base + offset] = Sample {
                    x0: center_x + major * cos - minor * sin,
                    x1: center_y + major * sin + minor * cos,
                    target: class as u32,
                };
            }
        }
    }
    GaussianCells { samples }
}

fn normal_pair(rng: &mut Rng) -> (f32, f32) {
    let first = uniform_open01(rng);
    let second = uniform_open01(rng);
    let radius = (-2.0 * first.ln()).sqrt();
    let angle = std::f32::consts::TAU * second;
    (radius * angle.cos(), radius * angle.sin())
}

fn uniform_open01(rng: &mut Rng) -> f32 {
    let mantissa = (rng.next() >> 40) as u32;
    (mantissa as f32 + 1.0) / 16_777_217.0
}

pub fn write_gaussian_dataset(path: impl AsRef<Path>) -> io::Result<()> {
    let dataset = generate_gaussian_cells();
    let header = DatasetHeader {
        magic: DATASET_MAGIC,
        sample_count: TOTAL_SAMPLES as u32,
        row_stride: size_of::<Sample>() as u32,
    };
    let mut bytes = Vec::with_capacity(size_of::<DatasetHeader>() + size_of_val(&dataset.samples));
    bytes.extend_from_slice(header.as_bytes());
    bytes.extend_from_slice(cast_slice(&dataset.samples));
    if let Some(parent) = path.as_ref().parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(path, bytes)
}

pub struct GaussianMappedDataset {
    mmap: Mmap,
}

impl GaussianMappedDataset {
    pub fn open(path: impl AsRef<Path>) -> io::Result<Self> {
        let file = OpenOptions::new().read(true).open(path)?;
        // SAFETY: read-only mapping; the owner keeps the mapping alive.
        let mmap = unsafe { MmapOptions::new().map(&file)? };
        let header_bytes = size_of::<DatasetHeader>();
        let expected_len = header_bytes + TOTAL_SAMPLES * size_of::<Sample>();
        if mmap.len() != expected_len {
            return Err(invalid_data("AR-02A dataset length mismatch"));
        }
        let header = DatasetHeader::ref_from_bytes(&mmap[..header_bytes])
            .map_err(|_| invalid_data("invalid AR-02A dataset header"))?;
        if header.magic != DATASET_MAGIC
            || header.sample_count as usize != TOTAL_SAMPLES
            || header.row_stride as usize != size_of::<Sample>()
        {
            return Err(invalid_data("AR-02A dataset layout mismatch"));
        }
        Ok(Self { mmap })
    }

    #[inline]
    pub fn samples(&self) -> &[Sample] {
        let start = size_of::<DatasetHeader>();
        bytemuck::try_cast_slice(&self.mmap[start..]).expect("validated AR-02A mapping")
    }
}

fn invalid_data(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

#[derive(Clone, Copy, Debug, Default)]
pub struct CurvePoint {
    pub commit: usize,
    pub train_loss: f32,
    pub validation_loss: f32,
    pub train_accuracy: f32,
    pub validation_accuracy: f32,
}

#[derive(Clone, Debug)]
pub struct RunResult {
    pub method: Method,
    pub seed: u64,
    pub final_train_loss: f32,
    pub final_validation_loss: f32,
    pub final_train_accuracy: f32,
    pub final_validation_accuracy: f32,
    pub optimizer_steps: usize,
    pub committed_programs: u64,
    pub committed_primitives: u64,
    pub proposal_evaluations: u64,
    pub compound_evaluations: u64,
    pub pair_events: u64,
    pub full_train_audit_commits: u64,
    pub full_train_positive_commits: u64,
    pub full_train_utility_sum: f64,
    pub identical_proposal_verifier_rounds: u64,
    pub coverage: Coverage,
    pub elapsed_seconds: f64,
    pub curve: Vec<CurvePoint>,
}

pub fn run_method(samples: &[Sample], method: Method, seed: u64) -> RunResult {
    run_method_for_commits(samples, method, seed, AR02A_COMMITS)
}

fn run_method_for_commits(
    samples: &[Sample],
    method: Method,
    seed: u64,
    commits: usize,
) -> RunResult {
    assert_eq!(samples.len(), TOTAL_SAMPLES);
    assert!(commits > 0 && commits.is_multiple_of(AR02A_COMMITS_PER_EVIDENCE));
    if method.is_runtime() {
        run_runtime(samples, method, seed, commits)
    } else {
        run_reference(samples, method, seed, commits)
    }
}

fn run_runtime(samples: &[Sample], method: Method, seed: u64, commits: usize) -> RunResult {
    let started = Instant::now();
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let mut model = Model::initial();
    let mut coverage = [[false; PARAMS]; PARAMS];
    let mut telemetry = Telemetry::default();
    let mut curve = Vec::with_capacity(commits / 50 + 1);
    let mut full_train_audit_commits = 0;
    let mut full_train_positive_commits = 0;
    let mut full_train_utility_sum = 0.0_f64;
    let mut identical_proposal_verifier_rounds = 0;

    for evidence_round in 0..commits / AR02A_COMMITS_PER_EVIDENCE {
        let proposal_ids = batch_indices(seed, evidence_round, PROPOSAL_STREAM);
        let proposal = indexed_samples(train, &proposal_ids);
        let verifier = verifier_batch(train, method, seed, evidence_round, &proposal);
        if verifier == proposal {
            identical_proposal_verifier_rounds += 1;
        }
        let verify_batches = [&verifier[..]];

        for inner_commit in 0..AR02A_COMMITS_PER_EVIDENCE {
            let global_commit = evidence_round * AR02A_COMMITS_PER_EVIDENCE + inner_commit;
            let (groups, group_count) = partition(global_commit % PARAMS);
            mark_coverage(&mut coverage, &groups, group_count);
            let mut selection = Selection::default();
            for &group in &groups[..group_count] {
                let (candidate, candidate_telemetry) = best_runtime_program(
                    &model,
                    &proposal,
                    &verify_batches,
                    Arm::G2Balanced64,
                    group,
                );
                selection.telemetry.absorb(candidate_telemetry);
                if let Some(candidate) = candidate
                    && selection
                        .program
                        .is_none_or(|current| candidate.utility > current.utility)
                {
                    selection.program = Some(candidate);
                    selection.group = group;
                }
            }
            selection.telemetry.pair_events = (group_count - 1) as u64;
            telemetry.absorb(selection.telemetry);

            if let Some(program) = selection.program {
                let before = model.loss(train);
                commit(&mut model, program);
                let reference_utility = before - model.loss(train);
                full_train_audit_commits += 1;
                full_train_positive_commits += u64::from(reference_utility > 0.0);
                full_train_utility_sum += f64::from(reference_utility);
                telemetry.committed_programs += 1;
                telemetry.committed_primitives += program.len as u64;
            }
            if (global_commit + 1).is_multiple_of(50) || global_commit + 1 == commits {
                curve.push(curve_point(&model, train, validation, global_commit + 1));
            }
        }
    }
    finish_run(
        method,
        seed,
        &model,
        train,
        validation,
        commits,
        telemetry,
        coverage_summary(&coverage, commits),
        full_train_audit_commits,
        full_train_positive_commits,
        full_train_utility_sum,
        identical_proposal_verifier_rounds,
        curve,
        started.elapsed().as_secs_f64(),
    )
}

fn verifier_batch(
    train: &[Sample],
    method: Method,
    seed: u64,
    round: usize,
    proposal: &[Sample; BATCH_SIZE],
) -> [Sample; AR02A_VERIFIER_SIZE] {
    let mut result = [train[0]; AR02A_VERIFIER_SIZE];
    match method {
        Method::SameBatchRandom => result.copy_from_slice(proposal),
        Method::IndependentRandom => {
            let mut rng = Rng::new(seed ^ VERIFY_STREAM ^ (round as u64).wrapping_mul(0x9e37_79b9));
            for sample in &mut result {
                *sample = train[(rng.next() as usize) % TRAIN_SAMPLES];
            }
        }
        Method::ClassBalanced => fill_class_balanced(&mut result, train, seed, round),
        Method::LatentStratified => fill_latent_stratified(&mut result, train, seed, round),
        Method::AdamW | Method::Sign => unreachable!("reference methods do not verify pairs"),
    }
    result
}

fn fill_class_balanced(
    output: &mut [Sample; AR02A_VERIFIER_SIZE],
    train: &[Sample],
    seed: u64,
    round: usize,
) {
    let mut rng = Rng::new(seed ^ 0x434c_4153_5342_414c ^ (round as u64).wrapping_mul(0x9e37_79b9));
    let mut class_indices = [[0_usize; TRAIN_SAMPLES / CLASSES]; CLASSES];
    let mut class_lengths = [0_usize; CLASSES];
    for (index, sample) in train.iter().enumerate() {
        let class = sample.target as usize;
        class_indices[class][class_lengths[class]] = index;
        class_lengths[class] += 1;
    }
    assert!(
        class_lengths
            .iter()
            .all(|&length| length == TRAIN_SAMPLES / CLASSES)
    );
    let quotas = [5_usize, 5, 6];
    let mut cursor = 0;
    for (class, quota) in quotas.into_iter().enumerate() {
        for _ in 0..quota {
            let within_class = (rng.next() as usize) % class_lengths[class];
            let index = class_indices[class][within_class];
            output[cursor] = train[index];
            cursor += 1;
        }
    }
}

fn fill_latent_stratified(
    output: &mut [Sample; AR02A_VERIFIER_SIZE],
    train: &[Sample],
    seed: u64,
    round: usize,
) {
    let mut rng = Rng::new(seed ^ 0x4c41_5445_4e54_5354 ^ (round as u64).wrapping_mul(0x9e37_79b9));
    let mut cursor = 0;
    for cell in 0..CELL_COUNT {
        let sample_index = cell * TRAIN_PER_CELL + (rng.next() as usize % TRAIN_PER_CELL);
        output[cursor] = train[sample_index];
        cursor += 1;
    }
    // Add one further draw from classes 0 and 1, and two from class 2.
    // Cell IDs [0, 1, 2, 4] have those labels under class=(row+column)%3.
    for cell in [0_usize, 1, 2, 4] {
        let sample_index = cell * TRAIN_PER_CELL + (rng.next() as usize % TRAIN_PER_CELL);
        output[cursor] = train[sample_index];
        cursor += 1;
    }
}

fn run_reference(samples: &[Sample], method: Method, seed: u64, commits: usize) -> RunResult {
    let started = Instant::now();
    let train = &samples[..TRAIN_SAMPLES];
    let validation = &samples[TRAIN_SAMPLES..];
    let mut model = Model::initial();
    let mut optimizer = AdamW::new();
    let mut curve = Vec::with_capacity(commits / 50 + 1);
    for step in 0..commits {
        let indices = batch_indices(seed, step, PROPOSAL_STREAM);
        let batch = indexed_samples(train, &indices);
        let (_, gradient) = model.gradient(&batch);
        match method {
            Method::AdamW => optimizer.step(&mut model, &gradient),
            Method::Sign => update_sign(&mut model, &gradient),
            _ => unreachable!("runtime methods use pairwise interposition"),
        }
        if (step + 1).is_multiple_of(50) || step + 1 == commits {
            curve.push(curve_point(&model, train, validation, step + 1));
        }
    }
    finish_run(
        method,
        seed,
        &model,
        train,
        validation,
        commits,
        Telemetry::default(),
        Coverage::default(),
        0,
        0,
        0.0,
        0,
        curve,
        started.elapsed().as_secs_f64(),
    )
}

#[allow(clippy::too_many_arguments)]
fn finish_run(
    method: Method,
    seed: u64,
    model: &Model,
    train: &[Sample],
    validation: &[Sample],
    optimizer_steps: usize,
    telemetry: Telemetry,
    coverage: Coverage,
    full_train_audit_commits: u64,
    full_train_positive_commits: u64,
    full_train_utility_sum: f64,
    identical_proposal_verifier_rounds: u64,
    curve: Vec<CurvePoint>,
    elapsed_seconds: f64,
) -> RunResult {
    RunResult {
        method,
        seed,
        final_train_loss: model.loss(train),
        final_validation_loss: model.loss(validation),
        final_train_accuracy: model.accuracy(train),
        final_validation_accuracy: model.accuracy(validation),
        optimizer_steps,
        committed_programs: telemetry.committed_programs,
        committed_primitives: telemetry.committed_primitives,
        proposal_evaluations: telemetry.proposal_evaluations,
        compound_evaluations: telemetry.compound_evaluations,
        pair_events: telemetry.pair_events,
        full_train_audit_commits,
        full_train_positive_commits,
        full_train_utility_sum,
        identical_proposal_verifier_rounds,
        coverage,
        elapsed_seconds,
        curve,
    }
}

fn curve_point(
    model: &Model,
    train: &[Sample],
    validation: &[Sample],
    commit: usize,
) -> CurvePoint {
    CurvePoint {
        commit,
        train_loss: model.loss(train),
        validation_loss: model.loss(validation),
        train_accuracy: model.accuracy(train),
        validation_accuracy: model.accuracy(validation),
    }
}

pub fn run_ar02a(samples: &[Sample], output_dir: impl AsRef<Path>) -> io::Result<Vec<RunResult>> {
    let mut results = Vec::with_capacity(AR02A_METHODS.len() * AR02A_SEEDS.len());
    for method in AR02A_METHODS {
        for seed in AR02A_SEEDS {
            let result = run_method(samples, method, seed);
            eprintln!(
                "AR-02A {:<22} seed {:016x}: val loss {:.6}, accuracy {:.1}%, commits {}, {:.2}s",
                method.as_str(),
                seed,
                result.final_validation_loss,
                result.final_validation_accuracy * 100.0,
                result.committed_programs,
                result.elapsed_seconds,
            );
            results.push(result);
        }
    }
    write_results(output_dir, &results)?;
    Ok(results)
}

pub fn write_results(output_dir: impl AsRef<Path>, results: &[RunResult]) -> io::Result<()> {
    std::fs::create_dir_all(output_dir.as_ref())?;
    write_runs_csv(output_dir.as_ref().join("ar-02a-runs.csv"), results)?;
    write_curve_csv(output_dir.as_ref().join("ar-02a-curve.csv"), results)?;
    write_report_json(output_dir.as_ref().join("ar-02a-report.json"), results)
}

fn write_runs_csv(path: impl AsRef<Path>, results: &[RunResult]) -> io::Result<()> {
    let mut file = std::fs::File::create(path)?;
    writeln!(
        file,
        "method,seed,train_loss,validation_loss,train_accuracy,validation_accuracy,optimizer_steps,committed_programs,committed_primitives,proposal_evaluations,compound_evaluations,pair_events,full_train_audit_commits,full_train_positive_commits,full_train_utility_sum,identical_proposal_verifier_rounds,pairs_seen,pairs_possible,elapsed_seconds"
    )?;
    for result in results {
        writeln!(
            file,
            "{},{:016x},{:.9},{:.9},{:.6},{:.6},{},{},{},{},{},{},{},{},{:.12},{},{},{},{:.6}",
            result.method.as_str(),
            result.seed,
            result.final_train_loss,
            result.final_validation_loss,
            result.final_train_accuracy,
            result.final_validation_accuracy,
            result.optimizer_steps,
            result.committed_programs,
            result.committed_primitives,
            result.proposal_evaluations,
            result.compound_evaluations,
            result.pair_events,
            result.full_train_audit_commits,
            result.full_train_positive_commits,
            result.full_train_utility_sum,
            result.identical_proposal_verifier_rounds,
            result.coverage.ever_pairs,
            result.coverage.possible_pairs,
            result.elapsed_seconds,
        )?;
    }
    file.flush()
}

fn write_curve_csv(path: impl AsRef<Path>, results: &[RunResult]) -> io::Result<()> {
    let mut file = std::fs::File::create(path)?;
    writeln!(
        file,
        "method,seed,commit,train_loss,validation_loss,train_accuracy,validation_accuracy"
    )?;
    for result in results {
        for point in &result.curve {
            writeln!(
                file,
                "{},{:016x},{},{:.9},{:.9},{:.6},{:.6}",
                result.method.as_str(),
                result.seed,
                point.commit,
                point.train_loss,
                point.validation_loss,
                point.train_accuracy,
                point.validation_accuracy,
            )?;
        }
    }
    file.flush()
}

fn write_report_json(path: impl AsRef<Path>, results: &[RunResult]) -> io::Result<()> {
    let mut file = std::fs::File::create(path)?;
    writeln!(file, "{{")?;
    writeln!(
        file,
        "  \"protocol\": \"AR-02A anisotropic Gaussian cells; engineering-only, toy-scale\","
    )?;
    writeln!(
        file,
        "  \"dataset\": {{\"train\": 96, \"validation\": 48, \"classes\": 3, \"latent_cells\": 12, \"dataset_seed\": \"{CELL_DATA_SEED:016x}\"}},"
    )?;
    writeln!(
        file,
        "  \"runtime\": {{\"mlp\": \"2-8-8-3 ReLU\", \"commits\": {AR02A_COMMITS}, \"commits_per_evidence\": {AR02A_COMMITS_PER_EVIDENCE}, \"verifier_size\": {AR02A_VERIFIER_SIZE}, \"beam\": 2, \"action_values\": [0.0, -0.02, 0.02, -0.01, 0.01, -0.005, 0.005]}},"
    )?;
    writeln!(
        file,
        "  \"seeds\": [\"{:016x}\", \"{:016x}\", \"{:016x}\"],",
        AR02A_SEEDS[0], AR02A_SEEDS[1], AR02A_SEEDS[2]
    )?;
    writeln!(file, "  \"methods\": [")?;
    for (index, method) in AR02A_METHODS.iter().enumerate() {
        let matching: Vec<_> = results.iter().filter(|run| run.method == *method).collect();
        let count = matching.len().max(1) as f64;
        let mean_validation_loss = matching
            .iter()
            .map(|run| f64::from(run.final_validation_loss))
            .sum::<f64>()
            / count;
        let mean_validation_accuracy = matching
            .iter()
            .map(|run| f64::from(run.final_validation_accuracy))
            .sum::<f64>()
            / count;
        let mean_train_loss = matching
            .iter()
            .map(|run| f64::from(run.final_train_loss))
            .sum::<f64>()
            / count;
        let mean_wall = matching.iter().map(|run| run.elapsed_seconds).sum::<f64>() / count;
        let suffix = if index + 1 == AR02A_METHODS.len() {
            ""
        } else {
            ","
        };
        writeln!(
            file,
            "    {{\"name\": \"{}\", \"n\": {}, \"mean_train_loss\": {:.9}, \"mean_validation_loss\": {:.9}, \"mean_validation_accuracy\": {:.6}, \"mean_wall_seconds\": {:.6}}}{}",
            method.as_str(),
            matching.len(),
            mean_train_loss,
            mean_validation_loss,
            mean_validation_accuracy,
            mean_wall,
            suffix
        )?;
    }
    writeln!(file, "  ],")?;
    writeln!(
        file,
        "  \"integrity\": {{\"all_verifiers_size_16\": {}, \"same_batch_rounds_per_runtime_run\": {}, \"validation_used_for_selection\": false, \"same_proposal_batches_across_runtime_methods\": true, \"same_initialization_across_methods_per_seed\": true}},",
        AR02A_METHODS[..4]
            .iter()
            .all(|_| AR02A_VERIFIER_SIZE == BATCH_SIZE),
        AR02A_COMMITS / AR02A_COMMITS_PER_EVIDENCE
    )?;
    writeln!(
        file,
        "  \"artifacts\": [\"gaussian-cells.bin\", \"ar-02a-runs.csv\", \"ar-02a-curve.csv\"]"
    )?;
    writeln!(file, "}}")?;
    file.flush()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_cells_are_balanced_and_reproducible() {
        let first = generate_gaussian_cells();
        let second = generate_gaussian_cells();
        assert_eq!(first.samples.len(), TOTAL_SAMPLES);
        assert_eq!(first.samples, second.samples);
        for class in 0..CLASSES {
            assert_eq!(
                first.samples[..TRAIN_SAMPLES]
                    .iter()
                    .filter(|s| s.target as usize == class)
                    .count(),
                32
            );
            assert_eq!(
                first.samples[TRAIN_SAMPLES..]
                    .iter()
                    .filter(|s| s.target as usize == class)
                    .count(),
                16
            );
        }
        assert!(
            first
                .samples
                .iter()
                .all(|sample| sample.x0.is_finite() && sample.x1.is_finite())
        );
    }

    #[test]
    fn verifiers_have_equal_cardinality_and_frozen_composition() {
        let dataset = generate_gaussian_cells();
        let train = &dataset.samples[..TRAIN_SAMPLES];
        let proposal_ids = batch_indices(AR02A_SEEDS[0], 0, PROPOSAL_STREAM);
        let proposal = indexed_samples(train, &proposal_ids);
        let independent = verifier_batch(
            train,
            Method::IndependentRandom,
            AR02A_SEEDS[0],
            0,
            &proposal,
        );
        let balanced = verifier_batch(train, Method::ClassBalanced, AR02A_SEEDS[0], 0, &proposal);
        let stratified = verifier_batch(
            train,
            Method::LatentStratified,
            AR02A_SEEDS[0],
            0,
            &proposal,
        );
        assert_eq!(independent.len(), AR02A_VERIFIER_SIZE);
        assert_eq!(balanced.len(), AR02A_VERIFIER_SIZE);
        assert_eq!(stratified.len(), AR02A_VERIFIER_SIZE);
        assert_eq!(class_counts(&balanced), [5, 5, 6]);
        assert_eq!(class_counts(&stratified), [5, 5, 6]);
    }

    #[test]
    fn gaussian_dataset_zero_copy_mapping_round_trips() {
        let path = std::env::temp_dir().join(format!("ar02a-smoke-{}.bin", std::process::id()));
        write_gaussian_dataset(&path).expect("write dataset");
        let mapped = GaussianMappedDataset::open(&path).expect("map dataset");
        assert_eq!(mapped.samples(), generate_gaussian_cells().samples);
        std::fs::remove_file(path).expect("remove temporary dataset");
    }

    #[test]
    fn short_k2_run_uses_frozen_commit_cadence_and_reference_audit() {
        let dataset = generate_gaussian_cells();
        let result = run_method_for_commits(
            &dataset.samples,
            Method::LatentStratified,
            AR02A_SEEDS[0],
            4,
        );
        assert_eq!(result.optimizer_steps, 4);
        assert!(result.identical_proposal_verifier_rounds <= 1);
        assert_eq!(
            result.proposal_evaluations,
            (PARAMS * 7 * AR02A_COMMITS_PER_EVIDENCE) as u64
        );
        assert!(result.compound_evaluations > 0);
        assert!(result.coverage.ever_pairs > 0);
    }

    fn class_counts(samples: &[Sample]) -> [usize; CLASSES] {
        let mut counts = [0; CLASSES];
        for sample in samples {
            counts[sample.target as usize] += 1;
        }
        counts
    }
}
