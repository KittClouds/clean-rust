use crate::HyperbolicDiskError;

const EPS: f32 = 1.0e-6;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u32)]
pub enum MetricKind {
    Custom = 0,
    Poincare = 1,
    Lorentz = 2,
    SphereCosine = 3,
    SphereChordal = 4,
    SphereChordalSquared = 5,
    SphereGeodesic = 6,
    HybridInterior = 7,
    Euclidean = 8,
}

impl MetricKind {
    pub(crate) const fn from_raw(raw: u32) -> Option<Self> {
        match raw {
            0 => Some(Self::Custom),
            1 => Some(Self::Poincare),
            2 => Some(Self::Lorentz),
            3 => Some(Self::SphereCosine),
            4 => Some(Self::SphereChordal),
            5 => Some(Self::SphereChordalSquared),
            6 => Some(Self::SphereGeodesic),
            7 => Some(Self::HybridInterior),
            8 => Some(Self::Euclidean),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MetricIdentity {
    pub kind: MetricKind,
    pub parameter_bits: [u32; 4],
    pub implementation_hash: [u8; 32],
}

impl MetricIdentity {
    pub fn known(kind: MetricKind, parameter_bits: [u32; 4]) -> Self {
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"phoenix.ann.metric/v2\0");
        hasher.update(&(kind as u32).to_le_bytes());
        for value in parameter_bits {
            hasher.update(&value.to_le_bytes());
        }
        Self {
            kind,
            parameter_bits,
            implementation_hash: *hasher.finalize().as_bytes(),
        }
    }

    pub fn custom(type_name: &str) -> Self {
        let mut hasher = blake3::Hasher::new();
        hasher.update(b"phoenix.ann.metric.custom/v2\0");
        hasher.update(type_name.as_bytes());
        Self {
            kind: MetricKind::Custom,
            parameter_bits: [0; 4],
            implementation_hash: *hasher.finalize().as_bytes(),
        }
    }
}

pub trait MetricF32: Send + Sync + Clone + 'static {
    fn eval(&self, a: &[f32], b: &[f32]) -> f32;

    #[inline]
    fn rank_eval(&self, a: &[f32], b: &[f32]) -> f32 {
        self.eval(a, b)
    }

    fn project_to_ball(&self, vector: &mut [f32]);

    fn identity(&self) -> MetricIdentity {
        MetricIdentity::custom(std::any::type_name::<Self>())
    }
}

#[derive(Clone, Copy, Debug)]
pub struct PoincareMetric {
    pub curvature: f32,
}

impl MetricF32 for PoincareMetric {
    fn eval(&self, a: &[f32], b: &[f32]) -> f32 {
        let mut difference = 0.0;
        let mut left_norm = 0.0;
        let mut right_norm = 0.0;
        for (left, right) in a.iter().zip(b) {
            let delta = left - right;
            difference = delta.mul_add(delta, difference);
            left_norm = left.mul_add(*left, left_norm);
            right_norm = right.mul_add(*right, right_norm);
        }
        let curvature = self.curvature.abs().max(EPS);
        let denominator = (1.0 - curvature * left_norm) * (1.0 - curvature * right_norm);
        let argument = 1.0 + 2.0 * curvature * difference / denominator.max(EPS);
        argument.max(1.0).acosh() / curvature.sqrt()
    }

    fn project_to_ball(&self, vector: &mut [f32]) {
        let curvature = self.curvature.abs().max(EPS);
        let norm_squared = vector
            .iter()
            .fold(0.0, |sum, value| value.mul_add(*value, sum));
        let maximum = curvature.sqrt().recip() - EPS;
        if norm_squared >= maximum * maximum {
            let scale = maximum / norm_squared.sqrt().max(EPS);
            vector.iter_mut().for_each(|value| *value *= scale);
        }
    }

    fn identity(&self) -> MetricIdentity {
        MetricIdentity::known(MetricKind::Poincare, [self.curvature.to_bits(), 0, 0, 0])
    }
}

pub(crate) fn validate_vector(vector: &[f32]) -> Result<(), HyperbolicDiskError> {
    if vector.iter().all(|value| value.is_finite()) {
        Ok(())
    } else {
        Err(HyperbolicDiskError::NonFiniteVector)
    }
}
