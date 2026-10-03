use std::f64::consts::TAU;

use hashbrown::HashMap;
use wide::f64x4;

use crate::{
    Digest, Error, FEATURE_REGISTRY_V1, FeatureCellState, FeatureColumn, FeatureDType,
    FeatureDeclaration, FeatureRegistry, FeatureTransform, Result, RunRawRow, SourceStatus,
    identity,
};

const FEATURE_IMPLEMENTATION_SOURCE: &[u8] = include_bytes!("feature.rs");

pub fn primitive_feature_registry(window: u32) -> Result<FeatureRegistry> {
    if window < 2 {
        return Err(Error::InvalidContract(
            "rolling window must be at least two".into(),
        ));
    }
    let transforms = [
        ("market.open.v1", "raw", FeatureTransform::RawOpen, "price"),
        ("market.high.v1", "raw", FeatureTransform::RawHigh, "price"),
        ("market.low.v1", "raw", FeatureTransform::RawLow, "price"),
        (
            "market.close.v1",
            "raw",
            FeatureTransform::RawClose,
            "price",
        ),
        (
            "market.log_return.v1",
            "return",
            FeatureTransform::LogReturn,
            "ratio",
        ),
        (
            "market.simple_return.v1",
            "return",
            FeatureTransform::SimpleReturn,
            "ratio",
        ),
        (
            "market.candle_range.v1",
            "candle",
            FeatureTransform::CandleRange,
            "price",
        ),
        (
            "market.candle_body.v1",
            "candle",
            FeatureTransform::CandleBody,
            "price",
        ),
        (
            "market.upper_wick.v1",
            "candle",
            FeatureTransform::UpperWick,
            "price",
        ),
        (
            "market.lower_wick.v1",
            "candle",
            FeatureTransform::LowerWick,
            "price",
        ),
        (
            "market.rolling_high.v1",
            "rolling",
            FeatureTransform::RollingHigh { window },
            "price",
        ),
        (
            "market.rolling_low.v1",
            "rolling",
            FeatureTransform::RollingLow { window },
            "price",
        ),
        (
            "market.rolling_range.v1",
            "rolling",
            FeatureTransform::RollingRange { window },
            "price",
        ),
        (
            "market.rolling_mean.v1",
            "rolling",
            FeatureTransform::RollingMean { window },
            "price",
        ),
        (
            "market.rolling_variance.v1",
            "rolling",
            FeatureTransform::RollingVariance { window },
            "price_squared",
        ),
        (
            "market.rolling_stddev.v1",
            "rolling",
            FeatureTransform::RollingStdDev { window },
            "price",
        ),
        (
            "market.realized_abs_movement.v1",
            "movement",
            FeatureTransform::RealizedAbsoluteMovement { window },
            "price",
        ),
        (
            "market.volume_change.v1",
            "volume",
            FeatureTransform::VolumeChange,
            "ratio",
        ),
        (
            "clock.time_of_day_sin.v1",
            "clock",
            FeatureTransform::TimeOfDaySin,
            "unitless",
        ),
        (
            "clock.time_of_day_cos.v1",
            "clock",
            FeatureTransform::TimeOfDayCos,
            "unitless",
        ),
        (
            "clock.session_progress.v1",
            "clock",
            FeatureTransform::SessionProgress,
            "ratio",
        ),
    ];
    let mut features = Vec::with_capacity(transforms.len());
    for (feature_id, family, transform, units) in transforms {
        let (lookback, warmup) = lookback_and_warmup(&transform);
        let parameters = match transform {
            FeatureTransform::RollingHigh { window }
            | FeatureTransform::RollingLow { window }
            | FeatureTransform::RollingRange { window }
            | FeatureTransform::RollingMean { window }
            | FeatureTransform::RollingVariance { window }
            | FeatureTransform::RollingStdDev { window }
            | FeatureTransform::RealizedAbsoluteMovement { window } => {
                vec![("window".into(), window.to_string())]
            }
            _ => Vec::new(),
        };
        let implementation_hash = Digest::hash_parts(
            b"northstar-feature-implementation-v1",
            [FEATURE_IMPLEMENTATION_SOURCE, feature_id.as_bytes()],
        );
        features.push(FeatureDeclaration {
            feature_id: feature_id.into(),
            feature_family: family.into(),
            version: 1,
            dtype: FeatureDType::Float64,
            shape: vec![1],
            source_dependencies: dependencies(&transform),
            lookback,
            warmup,
            event_time_semantics: "value is indexed by the completed source bar event_time".into(),
            knowledge_time_semantics: "maximum source knowledge_time in the declared lookback; observable only when t_known <= t".into(),
            missingness_semantics: "typed cell state; non-AVAILABLE values are not observations".into(),
            units: units.into(),
            transform,
            parameters,
            implementation_hash,
        });
    }
    let mut registry = FeatureRegistry {
        schema_version: FEATURE_REGISTRY_V1.into(),
        features,
        content_hash: Digest::ZERO,
    };
    registry.content_hash = identity(b"northstar-feature-registry-v1", &registry)?;
    Ok(registry)
}

pub fn registry_id(registry: &FeatureRegistry) -> Result<Digest> {
    identity(b"northstar-feature-registry-identity-v1", registry)
}

pub fn compiler_identity() -> Digest {
    Digest::hash(
        b"northstar-feature-compiler-identity-v1",
        FEATURE_IMPLEMENTATION_SOURCE,
    )
}

pub fn compile_features(
    rows: &[RunRawRow],
    registry: &FeatureRegistry,
) -> Result<Vec<FeatureColumn>> {
    if rows.is_empty() {
        return Err(Error::InvalidContract(
            "cannot compile features over zero rows".into(),
        ));
    }
    let mut seen = HashMap::with_capacity(registry.features.len());
    let mut columns = Vec::with_capacity(registry.features.len());
    for declaration in &registry.features {
        if seen.insert(declaration.feature_id.as_str(), ()).is_some() {
            return Err(Error::InvalidContract(format!(
                "duplicate feature {}",
                declaration.feature_id
            )));
        }
        columns.push(compile_feature(rows, declaration));
    }
    Ok(columns)
}

fn compile_feature(rows: &[RunRawRow], declaration: &FeatureDeclaration) -> FeatureColumn {
    let mut values = vec![0.0; rows.len()];
    compute_values(rows, &declaration.transform, &mut values);
    let mut states = vec![FeatureCellState::Available as u8; rows.len()];
    let mut knowledge_times = vec![0_i64; rows.len()];
    let lookback = declaration.lookback as usize;
    let mut session_start = 0;
    for (index, (state, knowledge_time)) in states
        .iter_mut()
        .zip(knowledge_times.iter_mut())
        .enumerate()
    {
        if index == 0
            || rows[index].session_id != rows[index - 1].session_id
            || rows[index].instrument_id != rows[index - 1].instrument_id
        {
            session_start = index;
        }
        let local = index - session_start;
        let first = index.saturating_sub(lookback).max(session_start);
        *knowledge_time = rows[first..=index]
            .iter()
            .map(|row| row.knowledge_time)
            .max()
            .unwrap_or(rows[index].knowledge_time);
        *state = match rows[index].status() {
            SourceStatus::Gap => FeatureCellState::SourceGap,
            SourceStatus::Unavailable => FeatureCellState::Unavailable,
            SourceStatus::Censored => FeatureCellState::Censored,
            SourceStatus::Available if local < declaration.warmup as usize => {
                FeatureCellState::Warmup
            }
            SourceStatus::Available
                if rows[first..=index]
                    .iter()
                    .any(|row| row.status() != SourceStatus::Available) =>
            {
                FeatureCellState::SourceGap
            }
            SourceStatus::Available => FeatureCellState::Available,
        } as u8;
    }
    FeatureColumn {
        feature_id: declaration.feature_id.clone(),
        values,
        states,
        knowledge_times,
    }
}

fn compute_values(rows: &[RunRawRow], transform: &FeatureTransform, output: &mut [f64]) {
    match transform {
        FeatureTransform::RawOpen => copy_field(rows, output, |row| row.open),
        FeatureTransform::RawHigh => copy_field(rows, output, |row| row.high),
        FeatureTransform::RawLow => copy_field(rows, output, |row| row.low),
        FeatureTransform::RawClose => copy_field(rows, output, |row| row.close),
        FeatureTransform::CandleRange => simd_candle(rows, output, CandleKernel::Range),
        FeatureTransform::CandleBody => simd_candle(rows, output, CandleKernel::Body),
        FeatureTransform::UpperWick => simd_candle(rows, output, CandleKernel::UpperWick),
        FeatureTransform::LowerWick => simd_candle(rows, output, CandleKernel::LowerWick),
        FeatureTransform::LogReturn => previous_ratio(rows, output, |ratio| ratio.ln()),
        FeatureTransform::SimpleReturn => previous_ratio(rows, output, |ratio| ratio - 1.0),
        FeatureTransform::VolumeChange => previous_volume(rows, output),
        FeatureTransform::RollingHigh { window } => {
            rolling(rows, output, *window as usize, RollingKernel::High)
        }
        FeatureTransform::RollingLow { window } => {
            rolling(rows, output, *window as usize, RollingKernel::Low)
        }
        FeatureTransform::RollingRange { window } => {
            rolling(rows, output, *window as usize, RollingKernel::Range)
        }
        FeatureTransform::RollingMean { window } => {
            rolling(rows, output, *window as usize, RollingKernel::Mean)
        }
        FeatureTransform::RollingVariance { window } => {
            rolling(rows, output, *window as usize, RollingKernel::Variance)
        }
        FeatureTransform::RollingStdDev { window } => {
            rolling(rows, output, *window as usize, RollingKernel::StdDev)
        }
        FeatureTransform::RealizedAbsoluteMovement { window } => {
            realized_abs(rows, output, *window as usize)
        }
        FeatureTransform::TimeOfDaySin => time_of_day(rows, output, true),
        FeatureTransform::TimeOfDayCos => time_of_day(rows, output, false),
        FeatureTransform::SessionProgress => session_progress(rows, output),
    }
}

#[derive(Clone, Copy)]
enum CandleKernel {
    Range,
    Body,
    UpperWick,
    LowerWick,
}

fn simd_candle(rows: &[RunRawRow], output: &mut [f64], kernel: CandleKernel) {
    let chunks = rows.len() / 4;
    for chunk in 0..chunks {
        let base = chunk * 4;
        let open = f64x4::from(std::array::from_fn(|lane| rows[base + lane].open));
        let high = f64x4::from(std::array::from_fn(|lane| rows[base + lane].high));
        let low = f64x4::from(std::array::from_fn(|lane| rows[base + lane].low));
        let close = f64x4::from(std::array::from_fn(|lane| rows[base + lane].close));
        let value = match kernel {
            CandleKernel::Range => high - low,
            CandleKernel::Body => (close - open).abs(),
            CandleKernel::UpperWick => high - open.max(close),
            CandleKernel::LowerWick => open.min(close) - low,
        };
        output[base..base + 4].copy_from_slice(&value.to_array());
    }
    for index in chunks * 4..rows.len() {
        output[index] = match kernel {
            CandleKernel::Range => rows[index].high - rows[index].low,
            CandleKernel::Body => (rows[index].close - rows[index].open).abs(),
            CandleKernel::UpperWick => rows[index].high - rows[index].open.max(rows[index].close),
            CandleKernel::LowerWick => rows[index].open.min(rows[index].close) - rows[index].low,
        };
    }
}

fn copy_field(rows: &[RunRawRow], output: &mut [f64], field: impl Fn(&RunRawRow) -> f64) {
    for (value, row) in output.iter_mut().zip(rows) {
        *value = field(row);
    }
}

fn previous_ratio(rows: &[RunRawRow], output: &mut [f64], transform: impl Fn(f64) -> f64) {
    for index in 1..rows.len() {
        if same_series(rows, index) && rows[index - 1].close > 0.0 && rows[index].close > 0.0 {
            output[index] = transform(rows[index].close / rows[index - 1].close);
        }
    }
}

fn previous_volume(rows: &[RunRawRow], output: &mut [f64]) {
    for index in 1..rows.len() {
        if same_series(rows, index) && rows[index - 1].volume != 0.0 {
            output[index] = rows[index].volume / rows[index - 1].volume - 1.0;
        }
    }
}

#[derive(Clone, Copy)]
enum RollingKernel {
    High,
    Low,
    Range,
    Mean,
    Variance,
    StdDev,
}

fn rolling(rows: &[RunRawRow], output: &mut [f64], window: usize, kernel: RollingKernel) {
    let mut start = 0;
    for (index, value) in output.iter_mut().enumerate() {
        if index == 0 || !same_series(rows, index) {
            start = index;
        }
        let first = (index + 1).saturating_sub(window).max(start);
        let slice = &rows[first..=index];
        let high = slice
            .iter()
            .map(|row| row.high)
            .fold(f64::NEG_INFINITY, f64::max);
        let low = slice
            .iter()
            .map(|row| row.low)
            .fold(f64::INFINITY, f64::min);
        let mean = slice.iter().map(|row| row.close).sum::<f64>() / slice.len() as f64;
        let variance = slice
            .iter()
            .map(|row| (row.close - mean).powi(2))
            .sum::<f64>()
            / slice.len() as f64;
        *value = match kernel {
            RollingKernel::High => high,
            RollingKernel::Low => low,
            RollingKernel::Range => high - low,
            RollingKernel::Mean => mean,
            RollingKernel::Variance => variance,
            RollingKernel::StdDev => variance.sqrt(),
        };
    }
}

fn realized_abs(rows: &[RunRawRow], output: &mut [f64], window: usize) {
    let mut start = 0;
    for (index, value) in output.iter_mut().enumerate() {
        if index == 0 || !same_series(rows, index) {
            start = index;
        }
        let first = (index + 1).saturating_sub(window).max(start);
        *value = (first + 1..=index)
            .map(|at| (rows[at].close - rows[at - 1].close).abs())
            .sum();
    }
}

fn time_of_day(rows: &[RunRawRow], output: &mut [f64], sine: bool) {
    const DAY_NS: i64 = 86_400_000_000_000;
    for (value, row) in output.iter_mut().zip(rows) {
        let progress = row.event_time.rem_euclid(DAY_NS) as f64 / DAY_NS as f64;
        *value = if sine {
            (progress * TAU).sin()
        } else {
            (progress * TAU).cos()
        };
    }
}

fn session_progress(rows: &[RunRawRow], output: &mut [f64]) {
    let mut first = 0;
    while first < rows.len() {
        let mut end = first + 1;
        while end < rows.len()
            && rows[end].session_id == rows[first].session_id
            && rows[end].instrument_id == rows[first].instrument_id
        {
            end += 1;
        }
        let denominator = (end - first - 1).max(1) as f64;
        for (local, value) in output[first..end].iter_mut().enumerate() {
            *value = local as f64 / denominator;
        }
        first = end;
    }
}

fn same_series(rows: &[RunRawRow], index: usize) -> bool {
    rows[index].session_id == rows[index - 1].session_id
        && rows[index].instrument_id == rows[index - 1].instrument_id
}

fn lookback_and_warmup(transform: &FeatureTransform) -> (u32, u32) {
    match transform {
        FeatureTransform::LogReturn
        | FeatureTransform::SimpleReturn
        | FeatureTransform::VolumeChange => (1, 1),
        FeatureTransform::RollingHigh { window }
        | FeatureTransform::RollingLow { window }
        | FeatureTransform::RollingRange { window }
        | FeatureTransform::RollingMean { window }
        | FeatureTransform::RollingVariance { window }
        | FeatureTransform::RollingStdDev { window }
        | FeatureTransform::RealizedAbsoluteMovement { window } => (*window - 1, *window - 1),
        _ => (0, 0),
    }
}

fn dependencies(transform: &FeatureTransform) -> Vec<String> {
    match transform {
        FeatureTransform::RawOpen => vec!["open".into()],
        FeatureTransform::RawHigh => vec!["high".into()],
        FeatureTransform::RawLow => vec!["low".into()],
        FeatureTransform::RawClose => vec!["close".into()],
        FeatureTransform::LogReturn | FeatureTransform::SimpleReturn => vec!["close".into()],
        FeatureTransform::CandleRange
        | FeatureTransform::RollingHigh { .. }
        | FeatureTransform::RollingLow { .. }
        | FeatureTransform::RollingRange { .. } => vec!["high".into(), "low".into()],
        FeatureTransform::CandleBody
        | FeatureTransform::UpperWick
        | FeatureTransform::LowerWick => {
            vec!["open".into(), "high".into(), "low".into(), "close".into()]
        }
        FeatureTransform::RollingMean { .. }
        | FeatureTransform::RollingVariance { .. }
        | FeatureTransform::RollingStdDev { .. }
        | FeatureTransform::RealizedAbsoluteMovement { .. } => vec!["close".into()],
        FeatureTransform::VolumeChange => vec!["volume".into()],
        FeatureTransform::TimeOfDaySin | FeatureTransform::TimeOfDayCos => {
            vec!["event_time".into()]
        }
        FeatureTransform::SessionProgress => vec!["session_id".into(), "event_time".into()],
    }
}
