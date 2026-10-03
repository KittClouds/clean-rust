use crate::model::NeutralToken;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct RankKey {
    pub shell: u128,
    pub token_length: usize,
    pub max_abs_coordinate: u64,
    pub sum_abs_coordinates: u128,
    pub finite_code: Vec<u128>,
}

fn abs_u64(value: i64) -> u64 {
    value.unsigned_abs()
}

fn signed_code(value: i64) -> u128 {
    if value >= 0 {
        (value as u128) * 2
    } else {
        (value.unsigned_abs() as u128) * 2 - 1
    }
}

pub fn rank_key(word: &[NeutralToken]) -> RankKey {
    let mut max_abs = 0_u64;
    let mut sum_abs = 0_u128;
    let mut finite_code = Vec::with_capacity(word.len().saturating_mul(5));
    for token in word {
        for value in [
            token.open_delta_ticks,
            token.high_delta_ticks,
            token.low_delta_ticks,
            token.close_delta_ticks,
        ] {
            let magnitude = abs_u64(value);
            max_abs = max_abs.max(magnitude);
            sum_abs = sum_abs.saturating_add(magnitude as u128);
            finite_code.push(signed_code(value));
        }
        finite_code.push(token.coverage_class as u128);
    }
    let shell = (word.len() as u128).max(max_abs as u128);
    RankKey {
        shell,
        token_length: word.len(),
        max_abs_coordinate: max_abs,
        sum_abs_coordinates: sum_abs,
        finite_code,
    }
}

pub fn finite_shell(max_shell: u8) -> Vec<Vec<NeutralToken>> {
    let mut all = Vec::new();
    all.push(Vec::new());
    for length in 1..=max_shell as usize {
        let mut token_alphabet = Vec::new();
        let bound = max_shell as i64;
        for open in -bound..=bound {
            for high in -bound..=bound {
                for low in -bound..=bound {
                    for close in -bound..=bound {
                        for coverage in 0..=1 {
                            let token = NeutralToken {
                                open_delta_ticks: open,
                                high_delta_ticks: high,
                                low_delta_ticks: low,
                                close_delta_ticks: close,
                                coverage_class: coverage,
                            };
                            if token.is_source_valid() {
                                token_alphabet.push(token);
                            }
                        }
                    }
                }
            }
        }
        token_alphabet.sort_unstable();
        enumerate_words(
            &token_alphabet,
            length,
            &mut Vec::with_capacity(length),
            &mut all,
        );
    }
    all.retain(|word| rank_key(word).shell <= max_shell as u128);
    all.sort_unstable_by_key(|word| rank_key(word));
    all.dedup();
    all
}

fn enumerate_words(
    alphabet: &[NeutralToken],
    remaining: usize,
    prefix: &mut Vec<NeutralToken>,
    output: &mut Vec<Vec<NeutralToken>>,
) {
    if remaining == 0 {
        output.push(prefix.clone());
        return;
    }
    for token in alphabet {
        prefix.push(token.clone());
        enumerate_words(alphabet, remaining - 1, prefix, output);
        prefix.pop();
    }
}
