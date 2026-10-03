use crate::model::*;
use hashbrown::HashMap;
use obs_open_03a::AtlasSession;
use serde_json::json;

pub fn raw_snapshot(session: &AtlasSession, k: usize) -> Result<RawSnapshot, String> {
    let range = session.ranges.get(k - 1).ok_or("RANGE_MISSING")?;
    let bar = session.bars.get(k - 1).ok_or("FREEZE_BAR_MISSING")?;
    if range.k as usize != k || bar.close_time != range.freeze_commit_time {
        return Err("FREEZE_BAR_ALIGNMENT_DRIFT".into());
    }
    if !(range.width.is_finite() && range.width > 0.0) {
        return Err("NOT_EVALUABLE_DEGENERATE_RANGE".into());
    }
    Ok(RawSnapshot {
        width: range.width,
        open_minus_mid: bar.open - range.midpoint,
        high_minus_mid: bar.high - range.midpoint,
        low_minus_mid: bar.low - range.midpoint,
        close_minus_mid: bar.close - range.midpoint,
    })
}

pub fn normalize(raw: RawSnapshot) -> Result<ZSnapshot, String> {
    if !(raw.width.is_finite() && raw.width > 0.0) {
        return Err("NOT_EVALUABLE_DEGENERATE_RANGE".into());
    }
    let scale = 2.0 / raw.width;
    Ok(ZSnapshot {
        z_open: raw.open_minus_mid * scale,
        z_high: raw.high_minus_mid * scale,
        z_low: raw.low_minus_mid * scale,
        z_close: raw.close_minus_mid * scale,
    })
}

pub fn audit(sessions: &[AtlasSession]) -> Result<AlgebraAudit, String> {
    let mut raw_groups: HashMap<[u64; 5], usize> = HashMap::with_capacity(RANGE_COUNT * 2);
    let mut z_groups: HashMap<[u64; 4], usize> = HashMap::with_capacity(RANGE_COUNT * 2);
    let mut objects = 0;
    for session in sessions {
        for k in 1..=RANGE_PER_SESSION {
            let raw = raw_snapshot(session, k)?;
            let z = normalize(raw)?;
            *raw_groups.entry(raw_key(raw)?).or_insert(0) += 1;
            *z_groups.entry(z_key(z)?).or_insert(0) += 1;
            objects += 1;
        }
    }
    if objects != RANGE_COUNT {
        return Err(format!("RANGE_OBJECT_COUNT_DRIFT:{objects}"));
    }
    let raw_census = census(
        "RANGE_RAW_SNAPSHOT_V1",
        objects,
        raw_groups.values().copied(),
    );
    let z_census = census("RANGE_Z_SNAPSHOT_V1", objects, z_groups.values().copied());
    let a = RawSnapshot {
        width: 10.0,
        open_minus_mid: -2.0,
        high_minus_mid: 5.0,
        low_minus_mid: -5.0,
        close_minus_mid: 1.0,
    };
    let b = RawSnapshot {
        width: 20.0,
        open_minus_mid: -4.0,
        high_minus_mid: 10.0,
        low_minus_mid: -10.0,
        close_minus_mid: 2.0,
    };
    let za = normalize(a)?;
    let zb = normalize(b)?;
    if za != zb || a == b {
        return Err("SYNTHETIC_QUOTIENT_COLLISION_FAILED".into());
    }
    Ok(AlgebraAudit {
        primary_classification: "LOSSY_QUOTIENT".into(),
        context_classification: "NON_EQUIVALENT_GIVEN_RANGE_DESIGN_CONTEXT_V1".into(),
        conditional_classification: "CONDITIONALLY_INVERTIBLE_GIVEN_WIDTH".into(),
        removed_degrees_of_freedom: vec!["frozen range width / positive price scale".into()],
        preserved_degrees_of_freedom: vec![
            "freeze-bar OHLC position relative to midpoint and half-width".into(),
        ],
        raw_to_z: "DETERMINISTIC_FOR_POSITIVE_WIDTH".into(),
        z_to_raw_given_context: "NOT_RECONSTRUCTIBLE; k and offset regime do not contain width"
            .into(),
        synthetic_collision: json!({"raw_a":a,"raw_b":b,"z_a":za,"z_b":zb,"same_z":true,"same_raw":false}),
        raw_collision_census: raw_census,
        z_collision_census: z_census,
    })
}

fn census(name: &str, objects: usize, sizes: impl Iterator<Item = usize>) -> CollisionCensus {
    let mut unique = 0;
    let mut groups = 0;
    let mut relations = 0u64;
    let mut largest = 0;
    for n in sizes {
        unique += 1;
        largest = largest.max(n);
        if n > 1 {
            groups += 1;
            relations += (n as u64) * (n as u64 - 1) / 2;
        }
    }
    CollisionCensus {
        representation: name.into(),
        objects,
        unique_tuples: unique,
        collision_groups: groups,
        collision_relations: relations,
        largest_group: largest,
        canonicalization: "finite IEEE-754 bits; negative zero canonicalized to positive zero"
            .into(),
    }
}

fn raw_key(x: RawSnapshot) -> Result<[u64; 5], String> {
    Ok([
        bits(x.width)?,
        bits(x.open_minus_mid)?,
        bits(x.high_minus_mid)?,
        bits(x.low_minus_mid)?,
        bits(x.close_minus_mid)?,
    ])
}
fn z_key(x: ZSnapshot) -> Result<[u64; 4], String> {
    Ok([
        bits(x.z_open)?,
        bits(x.z_high)?,
        bits(x.z_low)?,
        bits(x.z_close)?,
    ])
}
fn bits(x: f64) -> Result<u64, String> {
    if !x.is_finite() {
        return Err("NONFINITE_REPRESENTATION_FIELD".into());
    }
    Ok(if x == 0.0 { 0 } else { x.to_bits() })
}
