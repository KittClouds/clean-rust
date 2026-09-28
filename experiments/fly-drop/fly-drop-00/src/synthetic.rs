use crate::graph::{BuildManifest, SplitMix, WIDTH};
use anyhow::{Context, Result};
use bytemuck::cast_slice;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::Path;

const TEACHER_SEEDS: [u64; 4] = [6101, 6102, 6103, 6104];
const TRAIN_COUNT: usize = 8192;
const HELDOUT_COUNT: usize = 4096;
const LATENT: usize = 32;

#[derive(Serialize)]
pub struct TeacherReceipt {
    pub seed: u64,
    pub latent_width: usize,
    pub input_width: usize,
    pub train_examples: usize,
    pub heldout_examples: usize,
    pub train_class_counts: [u64; 2],
    pub heldout_class_counts: [u64; 2],
    pub files: Vec<FileReceipt>,
}

#[derive(Serialize)]
pub struct FileReceipt {
    pub file: String,
    pub bytes: u64,
    pub sha256: String,
}

pub fn build_teacher_worlds(artifacts: &Path, manifest: &mut BuildManifest) -> Result<()> {
    for seed in TEACHER_SEEDS {
        let dir = artifacts.join("teachers").join(format!("teacher-{seed}"));
        fs::create_dir_all(&dir)?;
        let mut teacher_rng = SplitMix::new(seed ^ 0x7465_6163_6865_722d);
        let scale_w = 1.0 / (WIDTH as f64).sqrt();
        let scale_v = 1.0 / (LATENT as f64).sqrt();
        let w: Vec<f32> = (0..LATENT * WIDTH).map(|_| (teacher_rng.normal() * scale_w) as f32).collect();
        let v: Vec<f32> = (0..LATENT).map(|_| (teacher_rng.normal() * scale_v) as f32).collect();
        let mut params = Vec::with_capacity((w.len() + v.len()) * 4);
        params.extend_from_slice(cast_slice(&w));
        params.extend_from_slice(cast_slice(&v));
        fs::write(dir.join("teacher-parameters.f32le"), &params)?;

        let (train_x, train_y, train_counts) = make_dataset(seed, false, TRAIN_COUNT, &w, &v);
        let (heldout_x, heldout_y, heldout_counts) = make_dataset(seed, true, HELDOUT_COUNT, &w, &v);
        fs::write(dir.join("train-x.f32le"), cast_slice(&train_x))?;
        fs::write(dir.join("train-y.u8"), &train_y)?;
        fs::write(dir.join("heldout-x.f32le"), cast_slice(&heldout_x))?;
        fs::write(dir.join("heldout-y.u8"), &heldout_y)?;

        let files = [
            "teacher-parameters.f32le", "train-x.f32le", "train-y.u8", "heldout-x.f32le", "heldout-y.u8",
        ].iter().map(|name| file_receipt(&dir, name)).collect::<Result<Vec<_>>>()?;
        manifest.teacher_worlds.push(TeacherReceipt {
            seed,
            latent_width: LATENT,
            input_width: WIDTH,
            train_examples: TRAIN_COUNT,
            heldout_examples: HELDOUT_COUNT,
            train_class_counts: train_counts,
            heldout_class_counts: heldout_counts,
            files,
        });
        println!("teacher world {seed}: train {:?}; heldout {:?}", train_counts, heldout_counts);
    }
    Ok(())
}

fn make_dataset(seed: u64, heldout: bool, count: usize, w: &[f32], v: &[f32]) -> (Vec<f32>, Vec<u8>, [u64; 2]) {
    let domain = if heldout { 0x6865_6c64_6f75_742d } else { 0x7472_6169_6e2d_7631 };
    let mut rng = SplitMix::new(seed ^ domain);
    let mut x_all = Vec::with_capacity(count * WIDTH);
    let mut labels = Vec::with_capacity(count);
    let mut counts = [0u64; 2];
    for _ in 0..count {
        let start = x_all.len();
        x_all.extend((0..WIDTH).map(|_| rng.normal() as f32));
        let x = &x_all[start..start + WIDTH];
        let mut score = 0.0f64;
        for k in 0..LATENT {
            let row = &w[k * WIDTH..(k + 1) * WIDTH];
            let activation = row.iter().zip(x).map(|(&a, &b)| a as f64 * b as f64).sum::<f64>().tanh();
            score += v[k] as f64 * activation;
        }
        let label = u8::from(score > 0.0);
        counts[label as usize] += 1;
        labels.push(label);
    }
    (x_all, labels, counts)
}

fn file_receipt(dir: &Path, name: &str) -> Result<FileReceipt> {
    let path = dir.join(name);
    let bytes = fs::read(&path).with_context(|| format!("read {}", path.display()))?;
    Ok(FileReceipt {
        file: path.to_string_lossy().replace('\\', "/"),
        bytes: bytes.len() as u64,
        sha256: hex(&Sha256::digest(&bytes)),
    })
}

fn hex(bytes: &[u8]) -> String { bytes.iter().map(|b| format!("{b:02x}")).collect() }
