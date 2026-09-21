use anyhow::{Result, ensure};
use wide::{f32x8, f64x4};

pub const WIDTH: usize = 128;
pub const W1: usize = WIDTH * WIDTH;
pub const B1: usize = W1;
pub const W2: usize = B1 + WIDTH;
pub const B2: usize = W2 + WIDTH;
pub const PARAMS: usize = B2 + 1;

pub struct Model { pub p: Vec<f32>, m: Vec<f32>, v: Vec<f32> }

pub struct Cache {
    pre1: [f32; WIDTH],
    act1: [f32; WIDTH],
    act1_64: [f64; WIDTH],
    pre2: [f32; WIDTH],
    act2: [f32; WIDTH],
    dpre2_64: [f64; WIDTH],
    logit: f32,
}

impl Default for Cache {
    fn default() -> Self {
        Self { pre1: [0.0; WIDTH], act1: [0.0; WIDTH], act1_64: [0.0; WIDTH],
            pre2: [0.0; WIDTH], act2: [0.0; WIDTH], dpre2_64: [0.0; WIDTH], logit: 0.0 }
    }
}

impl Model {
    pub fn from_initial(bytes: &[u8]) -> Result<Self> {
        ensure!(bytes.len() == PARAMS * 4, "initial parameter file has wrong size");
        let initial: Vec<f32> = bytes.chunks_exact(4)
            .map(|chunk| f32::from_le_bytes(chunk.try_into().unwrap())).collect();
        ensure!(initial.iter().all(|x| x.is_finite()), "initial parameters contain nonfinite values");
        Ok(Self { p: initial, m: vec![0.0; PARAMS], v: vec![0.0; PARAMS] })
    }

    #[inline]
    pub fn forward(&self, x: &[f32], matrix: &[f64], cache: &mut Cache) {
        for out in 0..WIDTH {
            let row = &self.p[out * WIDTH..(out + 1) * WIDTH];
            let z = dot_f32x8(row, x) + self.p[B1 + out];
            cache.pre1[out] = z;
            cache.act1[out] = gelu(z);
            cache.act1_64[out] = cache.act1[out] as f64;
        }
        for out in 0..WIDTH {
            let row = &matrix[out * WIDTH..(out + 1) * WIDTH];
            let z = dot_f64x4(row, &cache.act1_64) as f32;
            cache.pre2[out] = z;
            cache.act2[out] = gelu(z);
        }
        cache.logit = dot_f32x8(&self.p[W2..W2 + WIDTH], &cache.act2) + self.p[B2];
    }

    #[inline]
    pub fn backward(&self, x: &[f32], label: u8, transpose: &[f64], cache: &mut Cache, grad: &mut [f32]) {
        let dlogit = sigmoid(cache.logit) - label as f32;
        grad[B2] += dlogit;
        add_scaled_f32x8(&mut grad[W2..W2 + WIDTH], &cache.act2, dlogit);
        for i in 0..WIDTH {
            let dact = dlogit * self.p[W2 + i];
            cache.dpre2_64[i] = (dact * gelu_grad(cache.pre2[i])) as f64;
        }
        let mut dpre1 = [0.0f32; WIDTH];
        for input in 0..WIDTH {
            let row = &transpose[input * WIDTH..(input + 1) * WIDTH];
            let dact = dot_f64x4(row, &cache.dpre2_64) as f32;
            dpre1[input] = dact * gelu_grad(cache.pre1[input]);
            grad[B1 + input] += dpre1[input];
        }
        for out in 0..WIDTH {
            let scale = f32x8::new([dpre1[out]; 8]);
            let start = out * WIDTH;
            for k in (0..WIDTH).step_by(8) {
                let prior = f32x8::new(grad[start + k..start + k + 8].try_into().unwrap());
                let xv = f32x8::new(x[k..k + 8].try_into().unwrap());
                (prior + xv * scale).to_array().iter().enumerate()
                    .for_each(|(lane, &value)| grad[start + k + lane] = value);
            }
        }
    }

    pub fn adamw_step(&mut self, grad: &mut [f32], step: u64) {
        const BETA1: f32 = 0.9;
        const BETA2: f32 = 0.999;
        const EPS: f32 = 1e-8;
        const LR: f32 = 1e-3;
        let c1 = 1.0 - BETA1.powf(step as f32);
        let c2 = 1.0 - BETA2.powf(step as f32);
        let inv_batch = 1.0 / 128.0;
        for i in 0..PARAMS {
            let g = grad[i] * inv_batch;
            self.m[i] = BETA1 * self.m[i] + (1.0 - BETA1) * g;
            self.v[i] = BETA2 * self.v[i] + (1.0 - BETA2) * g * g;
            let mhat = self.m[i] / c1;
            let vhat = self.v[i] / c2;
            self.p[i] -= LR * mhat / (vhat.sqrt() + EPS);
            grad[i] = 0.0;
        }
    }

    pub fn finite_state(&self) -> bool {
        self.p.iter().chain(self.m.iter()).chain(self.v.iter()).all(|x| x.is_finite())
    }
}

impl Cache { pub fn logit(&self) -> f32 { self.logit } }

#[inline]
fn dot_f32x8(a: &[f32], b: &[f32]) -> f32 {
    let mut sum = f32x8::ZERO;
    for i in (0..WIDTH).step_by(8) {
        sum += f32x8::new(a[i..i + 8].try_into().unwrap()) * f32x8::new(b[i..i + 8].try_into().unwrap());
    }
    sum.reduce_add()
}

#[inline]
fn add_scaled_f32x8(dst: &mut [f32], src: &[f32], scale: f32) {
    let factor = f32x8::new([scale; 8]);
    for i in (0..WIDTH).step_by(8) {
        let d = f32x8::new(dst[i..i + 8].try_into().unwrap());
        let s = f32x8::new(src[i..i + 8].try_into().unwrap());
        (d + s * factor).to_array().iter().enumerate().for_each(|(j, &value)| dst[i + j] = value);
    }
}

#[inline]
fn dot_f64x4(a: &[f64], b: &[f64]) -> f64 {
    let mut sum = f64x4::ZERO;
    for i in (0..WIDTH).step_by(4) {
        sum += f64x4::new(a[i..i + 4].try_into().unwrap()) * f64x4::new(b[i..i + 4].try_into().unwrap());
    }
    sum.reduce_add()
}

#[inline]
fn gelu(x: f32) -> f32 {
    let c = (2.0f32 / std::f32::consts::PI).sqrt();
    0.5 * x * (1.0 + (c * (x + 0.044715 * x * x * x)).tanh())
}

#[inline]
fn gelu_grad(x: f32) -> f32 {
    let c = (2.0f32 / std::f32::consts::PI).sqrt();
    let inner = c * (x + 0.044715 * x * x * x);
    let t = inner.tanh();
    0.5 * (1.0 + t) + 0.5 * x * (1.0 - t * t) * c * (1.0 + 3.0 * 0.044715 * x * x)
}

#[inline]
fn sigmoid(x: f32) -> f32 {
    if x >= 0.0 { 1.0 / (1.0 + (-x).exp()) }
    else { let e = x.exp(); e / (1.0 + e) }
}

pub fn binary_cross_entropy(logit: f32, label: u8) -> f64 {
    if !logit.is_finite() { return f64::NAN; }
    let z = logit as f64;
    let y = label as f64;
    z.max(0.0) - z * y + (-z.abs()).exp().ln_1p()
}
