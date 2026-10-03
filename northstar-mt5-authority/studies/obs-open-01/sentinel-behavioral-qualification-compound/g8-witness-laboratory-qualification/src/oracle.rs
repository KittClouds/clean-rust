use crate::authority::UNIVERSAL_PROOF_SYSTEM_ID;
use crate::model::{FiniteMachine, UniversalProof};
use hashbrown::HashSet;
use std::collections::VecDeque;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OracleResult {
    Equivalent(UniversalProof),
    Distinguishable(Vec<usize>),
    Invalid,
}

fn valid(machine: &FiniteMachine) -> bool {
    !machine.outputs.is_empty()
        && machine.initial_state < machine.outputs.len()
        && machine.transitions.len() == machine.outputs.len()
        && machine.transitions.iter().all(|row| {
            row.len() == machine.alphabet_size
                && row.iter().all(|&next| next < machine.outputs.len())
        })
}

pub fn independent_product_oracle(left: &FiniteMachine, right: &FiniteMachine) -> OracleResult {
    if !valid(left) || !valid(right) || left.alphabet_size != right.alphabet_size {
        return OracleResult::Invalid;
    }
    let start = (left.initial_state, right.initial_state);
    let mut queue = VecDeque::from([(start, Vec::new())]);
    let mut seen = HashSet::new();
    seen.insert(start);
    let mut relation = Vec::new();
    while let Some(((l, r), word)) = queue.pop_front() {
        if left.outputs[l] != right.outputs[r] {
            return OracleResult::Distinguishable(word);
        }
        relation.push((l, r));
        for token in 0..left.alphabet_size {
            let next = (left.transitions[l][token], right.transitions[r][token]);
            if seen.insert(next) {
                let mut next_word = word.clone();
                next_word.push(token);
                queue.push_back((next, next_word));
            }
        }
    }
    relation.sort_unstable();
    OracleResult::Equivalent(UniversalProof {
        proof_system_id: UNIVERSAL_PROOF_SYSTEM_ID.into(),
        left: left.clone(),
        right: right.clone(),
        relation,
    })
}
