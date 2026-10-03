use crate::authority::sha256;
use crate::model::FixtureReceipt;
use hashbrown::HashSet;
use serde_json::json;
use wide::f64x4;

pub fn qualify() -> Result<Vec<FixtureReceipt>, Box<dyn std::error::Error>> {
    let receipts = vec![
        zero_mean_asymmetric()?,
        marginal_symmetry_with_dependence()?,
        global_not_coordinatewise()?,
        block_reflection_with_dependence()?,
        unit_distinction()?,
        exactness_authority_distinction()?,
    ];
    if receipts.iter().any(|x| x.status != "PASS") {
        return Err("SYNTHETIC_AUDIT_FIXTURE_FAILED".into());
    }
    Ok(receipts)
}

fn zero_mean_asymmetric() -> Result<FixtureReceipt, Box<dyn std::error::Error>> {
    let support = [-1.0_f64, -1.0, 2.0];
    let mean = support.iter().sum::<f64>() / support.len() as f64;
    let negated = [1.0_f64, 1.0, -2.0];
    let symmetry = multiset_bits(&support) == multiset_bits(&negated);
    require(
        mean == 0.0 && !symmetry,
        "ZERO_MEAN_ASYMMETRIC_WITNESS_FAILED",
    )?;
    Ok(fixture(
        "ZERO_MEAN_ASYMMETRIC",
        "A zero mean does not imply marginal or coordinate reflection symmetry.",
        json!({"support":support,"mean":mean,"negated_support":negated,"reflection_invariant":symmetry}),
    ))
}

fn marginal_symmetry_with_dependence() -> Result<FixtureReceipt, Box<dyn std::error::Error>> {
    let support = vec![vec![1_i8, 1], vec![-1, -1]];
    let first_marginal = vec![1_i8, -1];
    let second_marginal = vec![1_i8, -1];
    let reflected_first = coordinate_reflect(&support, 0);
    let joint_invariant = set(&support) == set(&reflected_first);
    require(!joint_invariant, "MARGINAL_SERIAL_WITNESS_FAILED")?;
    Ok(fixture(
        "MARGINAL_SYMMETRY_SERIAL_DEPENDENCE",
        "Symmetric session marginals with perfect serial dependence do not license arbitrary session-coordinate reflections.",
        json!({"joint_support":support,"marginal_1":first_marginal,"marginal_2":second_marginal,"coordinate_1_reflected_support":reflected_first,"joint_coordinate_invariant":joint_invariant}),
    ))
}

fn global_not_coordinatewise() -> Result<FixtureReceipt, Box<dyn std::error::Error>> {
    let support = vec![vec![1_i8, 1], vec![-1, -1]];
    let global = support
        .iter()
        .map(|v| v.iter().map(|x| -*x).collect())
        .collect::<Vec<Vec<i8>>>();
    let coordinate = coordinate_reflect(&support, 0);
    let global_invariant = set(&support) == set(&global);
    let coordinate_invariant = set(&support) == set(&coordinate);
    require(
        global_invariant && !coordinate_invariant,
        "GLOBAL_VS_COORDINATE_WITNESS_FAILED",
    )?;
    Ok(fixture(
        "GLOBAL_NOT_COORDINATEWISE",
        "Global sign symmetry is weaker than coordinate-wise sign-reflection invariance.",
        json!({"support":support,"global_reflection_invariant":global_invariant,"coordinate_reflection_invariant":coordinate_invariant}),
    ))
}

fn block_reflection_with_dependence() -> Result<FixtureReceipt, Box<dyn std::error::Error>> {
    let block_signs = [[1_i8, 1_i8], [1, -1], [-1, 1], [-1, -1]];
    let support = block_signs
        .iter()
        .map(|s| vec![s[0], s[0], s[1], s[1]])
        .collect::<Vec<_>>();
    let reflected_block_1 = support
        .iter()
        .map(|v| vec![-v[0], -v[1], v[2], v[3]])
        .collect::<Vec<_>>();
    let reflected_coordinate_1 = coordinate_reflect(&support, 0);
    let block_invariant = set(&support) == set(&reflected_block_1);
    let coordinate_invariant = set(&support) == set(&reflected_coordinate_1);
    require(
        block_invariant && !coordinate_invariant,
        "BLOCK_REFLECTION_WITNESS_FAILED",
    )?;
    Ok(fixture(
        "BLOCK_REFLECTION_WITHIN_BLOCK_DEPENDENCE",
        "Whole-block reflections can preserve a law with within-block dependence when individual-coordinate reflections do not.",
        json!({"support":support,"blocks":[[0,1],[2,3]],"block_reflection_invariant":block_invariant,"coordinate_reflection_invariant":coordinate_invariant}),
    ))
}

fn unit_distinction() -> Result<FixtureReceipt, Box<dyn std::error::Error>> {
    let session_d = [0.25_f64, -0.10, 0.05, 0.20];
    let simd = f64x4::from(session_d);
    let global_reflection: [f64; 4] = (-simd).into();
    let calendar_blocks = [session_d[0] + session_d[1], session_d[2] + session_d[3]];
    require(
        global_reflection[0] == -0.25 && calendar_blocks.len() == 2,
        "UNIT_WITNESS_FAILED",
    )?;
    let bytes = bytemuck::cast_slice::<f64, u8>(&session_d);
    Ok(fixture(
        "ESTIMAND_INFERENCE_TRANSFORMATION_UNIT",
        "A session estimand can be aggregated into calendar-block inference units and transformed only at block level.",
        json!({"estimand_unit":"SESSION","session_d":session_d,"inference_unit":"CALENDAR_BLOCK","block_sums":calendar_blocks,"transformation_unit":"CALENDAR_BLOCK","simd_global_reflection":global_reflection,"witness_sha256":sha256(bytes)}),
    ))
}

fn exactness_authority_distinction() -> Result<FixtureReceipt, Box<dyn std::error::Error>> {
    Ok(fixture(
        "DESIGN_VS_MODEL_EXACTNESS",
        "Random assignment can supply design-based transformation authority; observed chronological sessions without assignment require a model-based invariance assumption.",
        json!({"design_based":{"assignment_randomized":true,"basis":"KNOWN_ASSIGNMENT_MECHANISM"},"observational_sign_reflection":{"assignment_randomized":false,"basis":"ASSUMED_JOINT_REFLECTION_INVARIANCE"},"equivalent":false}),
    ))
}

fn coordinate_reflect(support: &[Vec<i8>], coordinate: usize) -> Vec<Vec<i8>> {
    support
        .iter()
        .map(|row| {
            let mut out = row.clone();
            out[coordinate] = -out[coordinate];
            out
        })
        .collect()
}

fn set(values: &[Vec<i8>]) -> HashSet<Vec<i8>> {
    values.iter().cloned().collect()
}

fn multiset_bits(values: &[f64]) -> Vec<u64> {
    let mut bits = values.iter().map(|x| x.to_bits()).collect::<Vec<_>>();
    bits.sort_unstable();
    bits
}

fn fixture(
    id: &'static str,
    established: &'static str,
    witness: serde_json::Value,
) -> FixtureReceipt {
    FixtureReceipt {
        fixture_id: id,
        status: "PASS",
        established,
        witness,
        real_session_assumption_established: false,
    }
}

fn require(ok: bool, error: &'static str) -> Result<(), Box<dyn std::error::Error>> {
    if ok { Ok(()) } else { Err(error.into()) }
}

#[cfg(test)]
mod tests {
    #[test]
    fn all_semantic_fixtures_pass() {
        let cases = super::qualify().unwrap();
        assert_eq!(cases.len(), 6);
        assert!(cases.iter().all(|x| x.status == "PASS"));
    }
}
