use crate::{FrozenProposal, ProposalActionProbability, ProposalContext};
use r1_world::InferenceTask;
use serde::Deserialize;

use super::{BASE_FEATURES, STATIC_FEATURES};

#[derive(Clone, Debug, Deserialize)]
pub(super) struct ProposalWeights {
    schema: String,
    architecture: String,
    input_dim: usize,
    hidden_dim: usize,
    w1: Vec<Vec<f32>>,
    b1: Vec<f32>,
    w2: Vec<f32>,
    b2: f32,
    adapter_logit_bias: f32,
}

impl ProposalWeights {
    pub(super) fn validate(&self) -> Result<(), String> {
        if self.schema != "r1-proposal-weights-v02"
            || self.architecture != "tanh_mlp_base_f10_h16_plus_adapter_bias_v02"
            || self.input_dim != BASE_FEATURES
            || self.hidden_dim == 0
            || self.w1.len() != self.hidden_dim
            || self.b1.len() != self.hidden_dim
            || self.w2.len() != self.hidden_dim
            || self.w1.iter().any(|row| row.len() != self.input_dim)
        {
            return Err("v03 simulator requires proposal-v02 weights with the f10 schema".into());
        }
        if self
            .w1
            .iter()
            .flatten()
            .chain(&self.b1)
            .chain(&self.w2)
            .chain([&self.b2, &self.adapter_logit_bias])
            .any(|value| !value.is_finite())
        {
            return Err("proposal weights contain a non-finite value".into());
        }
        Ok(())
    }
}

pub(super) struct FixedProposal<'a> {
    pub(super) task_id: &'a str,
    pub(super) static_features: &'a [Vec<Vec<f32>>],
    pub(super) clause_probabilities: &'a [[f32; 6]],
    pub(super) weights: &'a ProposalWeights,
    pub(super) identity_digest: [u8; 32],
    pub(super) temperature: f64,
}

impl FrozenProposal for FixedProposal<'_> {
    fn snapshot_sha256(&self) -> [u8; 32] {
        self.identity_digest
    }

    fn action_distribution(
        &self,
        context: &ProposalContext<'_>,
        _remaining_budget: u32,
    ) -> Result<Vec<ProposalActionProbability>, String> {
        if context.inference.id != self.task_id {
            return Err("v03 proposal feature cache was bound to another task".into());
        }
        if self.clause_probabilities.len() != context.inference.clauses.len() {
            return Err("identity class probability count differs from public clauses".into());
        }

        let mut role_loads = vec![0u32; usize::from(context.inference.k)];
        for &role in context.assignment {
            *role_loads
                .get_mut(usize::from(role))
                .ok_or("assignment role is outside the public task")? += 1;
        }
        let n = context.assignment.len() as f32;
        let candidate_capacity = context.assignment.len() * usize::from(context.inference.k);
        let mut actions = Vec::with_capacity(candidate_capacity);
        let mut base_logits = Vec::with_capacity(candidate_capacity);
        let mut deltas = Vec::with_capacity(candidate_capacity);

        for entity in 0..context.inference.n {
            let old_role = context.assignment[usize::from(entity)];
            for new_role in 0..context.inference.k {
                if new_role == old_role {
                    continue;
                }
                let static_row = self
                    .static_features
                    .get(usize::from(entity))
                    .and_then(|roles| roles.get(usize::from(new_role)))
                    .ok_or("static candidate feature cache has the wrong shape")?;
                if static_row.len() != STATIC_FEATURES {
                    return Err("static candidate feature rows must have width eight".into());
                }
                let mut input = [0.0f32; BASE_FEATURES];
                input[..STATIC_FEATURES].copy_from_slice(static_row);
                input[STATIC_FEATURES] = role_loads[usize::from(old_role)] as f32 / n;
                input[STATIC_FEATURES + 1] = role_loads[usize::from(new_role)] as f32 / n;
                let edit_delta = incidence_masked_expected_delta(
                    context.inference,
                    self.clause_probabilities,
                    context.assignment,
                    usize::from(entity),
                    new_role,
                )?;
                actions.push((entity, new_role));
                base_logits.push(score(self.weights, &input));
                deltas.push(edit_delta);
            }
        }
        if actions.is_empty() || base_logits.iter().any(|value| !value.is_finite()) {
            return Err("v03 proposal has no legal actions or a non-finite base logit".into());
        }

        let logits = compose_norm4_logits(&base_logits, &deltas)?;
        // Runtime norm4 replaces proposal-v02's learned raw-delta bias; the
        // serialized adapter bias is validated but intentionally not applied.
        let probabilities = softmax_temperature(&logits, self.temperature)?;
        Ok(actions
            .into_iter()
            .zip(probabilities)
            .map(
                |((entity, new_role), probability)| ProposalActionProbability {
                    entity,
                    new_role,
                    probability,
                },
            )
            .collect())
    }

    fn advance_latent(
        &self,
        context: &ProposalContext<'_>,
        entity: u16,
        new_role: u8,
    ) -> Result<Vec<f32>, String> {
        let mut latent = context.latent_state.to_vec();
        if latent.is_empty() {
            return Ok(latent);
        }
        let index = usize::from(entity) % latent.len();
        let role_index = (usize::from(new_role) * 31 + index + 1) % latent.len();
        latent[index] = (0.875 * latent[index] + 0.125 * (f32::from(new_role) - 0.5)).tanh();
        latent[role_index] = (0.9 * latent[role_index] + 0.1 * (f32::from(entity) + 1.0)).tanh();
        Ok(latent)
    }
}
pub(super) fn incidence_masked_expected_delta(
    inference: &InferenceTask,
    probabilities_by_clause: &[[f32; 6]],
    assignment: &[u8],
    entity: usize,
    new_role: u8,
) -> Result<f32, String> {
    let mut total = 0.0f64;
    for clause in 0..inference.clauses.len() {
        let entities = &inference.entity_mentions[clause];
        if !entities.contains(&(entity as u16)) {
            continue;
        }
        let roles = &inference.role_mentions[clause];
        let supported = supported_kind_ids(entities.len(), roles.len())?;
        let probabilities = probabilities_by_clause
            .get(clause)
            .ok_or("identity probability row is missing")?;
        let mass = supported
            .iter()
            .map(|&kind| f64::from(probabilities[kind]))
            .sum::<f64>();
        if !mass.is_finite() || mass <= 0.0 {
            return Err(format!(
                "identity posterior has no supported mass at clause {clause}"
            ));
        }
        let mut conditioned = [0.0f64; 6];
        for &kind in supported {
            conditioned[kind] = f64::from(probabilities[kind]) / mass;
        }
        for &kind in supported {
            let after =
                satisfaction_after_edit(kind, entities, roles, assignment, entity, new_role);
            let before = satisfaction(kind, entities, roles, assignment);
            total += conditioned[kind] * (after - before);
        }
    }
    let result = total as f32;
    if result.is_finite() {
        Ok(result)
    } else {
        Err("masked expected action delta is non-finite after float32 conversion".into())
    }
}

pub(super) fn supported_kind_ids(
    entity_count: usize,
    role_count: usize,
) -> Result<&'static [usize], String> {
    const DIFFERENT_SAME: &[usize] = &[0, 5];
    const EXACT_FIXED_FORBIDDEN: &[usize] = &[1, 2, 3];
    const EXACTLY_ONE: &[usize] = &[1];
    const IMPLIES: &[usize] = &[4];
    match (entity_count, role_count) {
        (2, 0) => Ok(DIFFERENT_SAME),
        (1, 1) => Ok(EXACT_FIXED_FORBIDDEN),
        (n, 1) if n >= 2 => Ok(EXACTLY_ONE),
        (1, 2) => Ok(IMPLIES),
        shape => Err(format!(
            "public incidence shape {shape:?} grounds no supported clause kinds"
        )),
    }
}

fn satisfaction(kind: usize, entities: &[u16], roles: &[u8], assignment: &[u8]) -> f64 {
    match kind {
        0 => {
            f64::from(assignment[usize::from(entities[0])] != assignment[usize::from(entities[1])])
        }
        1 => f64::from(
            entities
                .iter()
                .filter(|&&entity| assignment[usize::from(entity)] == roles[0])
                .count()
                == 1,
        ),
        2 => f64::from(assignment[usize::from(entities[0])] == roles[0]),
        3 => f64::from(assignment[usize::from(entities[0])] != roles[0]),
        4 if entities.len() == 1 && roles.len() == 2 => {
            if roles[0] != roles[1] {
                1.0
            } else {
                f64::from(assignment[usize::from(entities[0])] != roles[0])
            }
        }
        4 if entities.len() == 2 && roles.len() == 2 => {
            let first = assignment[usize::from(entities[0])];
            let second = assignment[usize::from(entities[1])];
            let direct = first != roles[0] || second != roles[1];
            let swapped = first != roles[1] || second != roles[0];
            f64::from(direct) * 0.5 + f64::from(swapped) * 0.5
        }
        5 => {
            f64::from(assignment[usize::from(entities[0])] == assignment[usize::from(entities[1])])
        }
        _ => unreachable!("supported kind/incidence pair was validated"),
    }
}

fn satisfaction_after_edit(
    kind: usize,
    entities: &[u16],
    roles: &[u8],
    assignment: &[u8],
    edited_entity: usize,
    new_role: u8,
) -> f64 {
    let role = |entity: u16| {
        if usize::from(entity) == edited_entity {
            new_role
        } else {
            assignment[usize::from(entity)]
        }
    };
    match kind {
        0 => f64::from(role(entities[0]) != role(entities[1])),
        1 => f64::from(entities.iter().filter(|&&e| role(e) == roles[0]).count() == 1),
        2 => f64::from(role(entities[0]) == roles[0]),
        3 => f64::from(role(entities[0]) != roles[0]),
        4 if entities.len() == 1 && roles.len() == 2 => {
            f64::from(roles[0] != roles[1] || role(entities[0]) != roles[0])
        }
        4 if entities.len() == 2 && roles.len() == 2 => {
            let first = role(entities[0]);
            let second = role(entities[1]);
            let direct = first != roles[0] || second != roles[1];
            let swapped = first != roles[1] || second != roles[0];
            f64::from(direct) * 0.5 + f64::from(swapped) * 0.5
        }
        5 => f64::from(role(entities[0]) == role(entities[1])),
        _ => unreachable!("supported kind/incidence pair was validated"),
    }
}

pub(super) fn mean_std(values: &[f32]) -> (f32, f32) {
    if values.is_empty() {
        return (0.0, 0.0);
    }
    let mean = values.iter().map(|value| f64::from(*value)).sum::<f64>() / values.len() as f64;
    let variance = values
        .iter()
        .map(|value| {
            let difference = f64::from(*value) - mean;
            difference * difference
        })
        .sum::<f64>()
        / values.len() as f64;
    (mean as f32, variance.sqrt() as f32)
}

pub(super) fn compose_norm4_logits(
    base_logits: &[f32],
    masked_deltas: &[f32],
) -> Result<Vec<f32>, String> {
    if base_logits.is_empty()
        || base_logits.len() != masked_deltas.len()
        || base_logits
            .iter()
            .chain(masked_deltas)
            .any(|value| !value.is_finite())
    {
        return Err("norm4 needs equal-length nonempty finite logits and deltas".into());
    }
    let (delta_mean, delta_sd) = mean_std(masked_deltas);
    let (_, base_sd) = mean_std(base_logits);
    Ok(base_logits
        .iter()
        .zip(masked_deltas)
        .map(|(&base, &delta)| {
            // Keep the runtime f32 sequence: subtract, divide, multiply by
            // base spread, then by the fixed norm4 ratio.
            let adjustment = if delta_sd <= 1e-8 || base_sd <= 1e-8 {
                0.0
            } else {
                ((delta - delta_mean) / delta_sd) * base_sd * 4.0f32
            };
            base + adjustment
        })
        .collect())
}

pub(super) fn softmax_temperature(logits: &[f32], temperature: f64) -> Result<Vec<f64>, String> {
    if logits.is_empty() || logits.iter().any(|value| !value.is_finite()) {
        return Err("proposal logits must be nonempty and finite".into());
    }
    if !temperature.is_finite() || temperature <= 0.0 {
        return Err("temperature must be finite and positive".into());
    }
    let maximum = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let weights = if temperature == 1.0 {
        logits
            .iter()
            .map(|value| f64::from((*value - maximum).exp()))
            .collect::<Vec<_>>()
    } else {
        let max64 = f64::from(maximum);
        logits
            .iter()
            .map(|value| ((f64::from(*value) - max64) / temperature).exp())
            .collect::<Vec<_>>()
    };
    let total = weights.iter().sum::<f64>();
    if !total.is_finite() || total <= 0.0 {
        return Err("temperature softmax is not normalizable".into());
    }
    Ok(weights.into_iter().map(|weight| weight / total).collect())
}
fn score(weights: &ProposalWeights, features: &[f32]) -> f32 {
    let mut output = weights.b2;
    for (index, (row, bias)) in weights.w1.iter().zip(&weights.b1).enumerate() {
        let hidden = row
            .iter()
            .zip(features)
            .fold(*bias, |sum, (weight, feature)| sum + weight * feature)
            .tanh();
        output += weights.w2[index] * hidden;
    }
    output
}
