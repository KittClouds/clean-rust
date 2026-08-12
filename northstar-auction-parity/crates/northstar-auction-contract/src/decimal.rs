use core::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
pub struct Decimal128 {
    coefficient: i128,
    scale: u8,
    negative_zero: bool,
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum DecimalError {
    #[error("decimal field is empty")]
    Empty,
    #[error("decimal field contains an invalid byte")]
    Invalid,
    #[error("decimal coefficient overflow")]
    Overflow,
    #[error("decimal scale exceeds 38 digits")]
    ScaleOverflow,
}

impl Decimal128 {
    #[must_use]
    pub const fn new(coefficient: i128, scale: u8) -> Self {
        Self {
            coefficient,
            scale,
            negative_zero: false,
        }
    }

    pub fn parse_bytes(input: &[u8]) -> Result<Self, DecimalError> {
        if input.is_empty() {
            return Err(DecimalError::Empty);
        }
        let (negative, digits) = match input[0] {
            b'-' => (true, &input[1..]),
            b'+' => (false, &input[1..]),
            _ => (false, input),
        };
        if digits.is_empty() {
            return Err(DecimalError::Invalid);
        }

        let mut coefficient = 0_i128;
        let mut scale = 0_u8;
        let mut decimal_seen = false;
        let mut digit_seen = false;
        for &byte in digits {
            match byte {
                b'0'..=b'9' => {
                    digit_seen = true;
                    coefficient = coefficient
                        .checked_mul(10)
                        .and_then(|value| value.checked_add(i128::from(byte - b'0')))
                        .ok_or(DecimalError::Overflow)?;
                    if decimal_seen {
                        scale = scale.checked_add(1).ok_or(DecimalError::ScaleOverflow)?;
                        if scale > 38 {
                            return Err(DecimalError::ScaleOverflow);
                        }
                    }
                }
                b'.' if !decimal_seen => decimal_seen = true,
                _ => return Err(DecimalError::Invalid),
            }
        }
        if !digit_seen {
            return Err(DecimalError::Invalid);
        }
        let negative_zero = negative && coefficient == 0;
        if negative {
            coefficient = coefficient.checked_neg().ok_or(DecimalError::Overflow)?;
        }
        Ok(Self {
            coefficient,
            scale,
            negative_zero,
        })
    }

    #[must_use]
    pub const fn coefficient(self) -> i128 {
        self.coefficient
    }

    #[must_use]
    pub const fn scale(self) -> u8 {
        self.scale
    }
}

impl FromStr for Decimal128 {
    type Err = DecimalError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::parse_bytes(value.as_bytes())
    }
}

impl fmt::Display for Decimal128 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let negative = self.coefficient < 0 || self.negative_zero;
        let magnitude = self.coefficient.unsigned_abs();
        if negative {
            formatter.write_str("-")?;
        }
        if self.scale == 0 {
            return write!(formatter, "{magnitude}");
        }
        let power = 10_u128.pow(u32::from(self.scale));
        let integer = magnitude / power;
        let fraction = magnitude % power;
        write!(
            formatter,
            "{integer}.{fraction:0width$}",
            width = usize::from(self.scale)
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preserves_source_scale_and_sign() {
        for value in ["0", "0.01", "-0.00000000", "24235.7300", "+17.80"] {
            let parsed: Decimal128 = value.parse().unwrap();
            let expected = value.trim_start_matches('+');
            assert_eq!(parsed.to_string(), expected);
        }
    }

    #[test]
    fn rejects_exponents_and_multiple_decimal_points() {
        assert_eq!(Decimal128::parse_bytes(b"1e3"), Err(DecimalError::Invalid));
        assert_eq!(
            Decimal128::parse_bytes(b"1.2.3"),
            Err(DecimalError::Invalid)
        );
    }
}
