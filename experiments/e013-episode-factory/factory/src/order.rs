use sha2::{Digest, Sha256};

/// Deterministic shuffle whose ranking uses only the private seed and opaque candidate IDs.
pub fn candidate_order(seed: u64, candidate_ids: &[String]) -> Vec<String> {
    let mut ranked: Vec<([u8; 32], &str)> = candidate_ids
        .iter()
        .map(|candidate_id| {
            let mut digest = Sha256::new();
            digest.update(b"E013 candidate order v1\0");
            digest.update(seed.to_be_bytes());
            digest.update([0]);
            digest.update(candidate_id.as_bytes());
            (digest.finalize().into(), candidate_id.as_str())
        })
        .collect();
    ranked.sort_unstable_by(|left, right| left.0.cmp(&right.0).then_with(|| left.1.cmp(right.1)));
    ranked
        .into_iter()
        .map(|(_, candidate_id)| candidate_id.to_owned())
        .collect()
}
