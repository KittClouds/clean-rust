use serde::{Deserialize, Serialize};

use super::error::{LorentzResult, LorentzTreeError};

pub(crate) const DEFAULT_EPS: f32 = 1e-6;
const MIN_TIME: f32 = 1.0;

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HyperboloidPoint {
    /// Coordinates are `[t, x, y, z, w]`.
    pub coords: [f32; 5],
}

impl HyperboloidPoint {
    #[inline]
    pub fn origin() -> Self {
        Self {
            coords: [1.0, 0.0, 0.0, 0.0, 0.0],
        }
    }

    #[inline]
    pub fn from_spatial(spatial: [f32; 4]) -> LorentzResult<Self> {
        let norm_sq = spatial.iter().try_fold(0.0f32, |acc, value| {
            if value.is_finite() {
                Ok(value.mul_add(*value, acc))
            } else {
                Err(LorentzTreeError::InvalidHyperboloidPoint {
                    lorentz_norm: f32::NAN,
                    time: f32::NAN,
                })
            }
        })?;
        let time = (1.0 + norm_sq).sqrt();
        Self::new_checked([time, spatial[0], spatial[1], spatial[2], spatial[3]])
    }

    pub fn from_tangent(tangent: [f32; 4], radius_scale: f32) -> LorentzResult<Self> {
        validate_positive("radius_scale", radius_scale)?;
        let tangent_norm = euclidean_norm4(tangent);
        if !tangent_norm.is_finite() || tangent_norm <= DEFAULT_EPS {
            return Ok(Self::origin());
        }
        let radius = tangent_norm * radius_scale;
        let sinh_r = radius.sinh();
        let cosh_r = radius.cosh();
        if !sinh_r.is_finite() || !cosh_r.is_finite() {
            return Err(LorentzTreeError::InvalidHyperboloidPoint {
                lorentz_norm: f32::NAN,
                time: cosh_r,
            });
        }
        let inv = tangent_norm.recip();
        Self::new_checked([
            cosh_r,
            sinh_r * tangent[0] * inv,
            sinh_r * tangent[1] * inv,
            sinh_r * tangent[2] * inv,
            sinh_r * tangent[3] * inv,
        ])
    }

    pub fn from_slice_spatial(spatial: &[f32], radius_scale: f32) -> LorentzResult<Self> {
        if spatial.is_empty() {
            return Err(LorentzTreeError::EmptyVector);
        }
        if spatial.len() != 4 {
            return Err(LorentzTreeError::DimensionMismatch {
                expected: 4,
                got: spatial.len(),
            });
        }
        Self::from_tangent(
            [spatial[0], spatial[1], spatial[2], spatial[3]],
            radius_scale,
        )
    }

    pub fn new_checked(coords: [f32; 5]) -> LorentzResult<Self> {
        if !coords.iter().all(|value| value.is_finite()) {
            return Err(LorentzTreeError::InvalidHyperboloidPoint {
                lorentz_norm: f32::NAN,
                time: coords[0],
            });
        }
        let point = Self { coords };
        point.validate()?;
        Ok(point)
    }

    pub fn validate(self) -> LorentzResult<()> {
        let norm = lorentz_dot(self, self);
        let time = self.coords[0];
        if time < MIN_TIME || (norm + 1.0).abs() > 1e-3 {
            return Err(LorentzTreeError::InvalidHyperboloidPoint {
                lorentz_norm: norm,
                time,
            });
        }
        Ok(())
    }

    #[inline]
    pub fn time(self) -> f32 {
        self.coords[0]
    }

    #[inline]
    pub fn spatial(self) -> [f32; 4] {
        [
            self.coords[1],
            self.coords[2],
            self.coords[3],
            self.coords[4],
        ]
    }
}

#[inline]
pub fn lorentz_dot(a: HyperboloidPoint, b: HyperboloidPoint) -> f32 {
    (-a.coords[0] * b.coords[0])
        + a.coords[1].mul_add(b.coords[1], 0.0)
        + a.coords[2] * b.coords[2]
        + a.coords[3] * b.coords[3]
        + a.coords[4] * b.coords[4]
}

#[inline]
pub fn hyperbolic_distance(a: HyperboloidPoint, b: HyperboloidPoint) -> LorentzResult<f32> {
    a.validate()?;
    b.validate()?;
    Ok((-lorentz_dot(a, b)).max(1.0).acosh())
}

#[inline]
pub fn hyperbolic_similarity01(
    a: HyperboloidPoint,
    b: HyperboloidPoint,
    distance_scale: f32,
) -> LorentzResult<f32> {
    validate_positive("distance_scale", distance_scale)?;
    let distance = hyperbolic_distance(a, b)?;
    Ok((-distance / distance_scale).exp().clamp(0.0, 1.0))
}

#[inline]
pub(crate) fn euclidean_norm4(v: [f32; 4]) -> f32 {
    v.iter()
        .fold(0.0f32, |acc, value| value.mul_add(*value, acc))
        .sqrt()
}

#[inline]
pub(crate) fn validate_non_negative(field: &'static str, value: f32) -> LorentzResult<()> {
    if !value.is_finite() || value < 0.0 {
        return Err(LorentzTreeError::InvalidConfigField { field, value });
    }
    Ok(())
}

#[inline]
pub(crate) fn validate_positive(field: &'static str, value: f32) -> LorentzResult<()> {
    if !value.is_finite() || value <= DEFAULT_EPS {
        return Err(LorentzTreeError::InvalidConfigField { field, value });
    }
    Ok(())
}
