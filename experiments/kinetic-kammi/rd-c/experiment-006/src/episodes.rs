use rdc_experiment_004::Choice;

use crate::domain::{PublicFeatures, PublicFrame};

pub const DEVELOPMENT_SEED: u64 = 0xE006_2026_0911;
pub const HELDOUT_SEED: u64 = 0xE006_2026_0924;
pub const EPISODES_PER_DOMAIN: usize = 32;
pub const DOMAIN_STRIDE: u32 = 521;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Scenario {
    ConfirmedCorrect,
    HelpfulContradiction,
    HarmfulContradiction,
    StaleEchoWrong,
    SelfConflict,
    Timeout,
    TransportFailure,
    MalformedEvidence,
}

impl Scenario {
    pub fn label(self) -> &'static str {
        match self {
            Self::ConfirmedCorrect => "confirmed_correct",
            Self::HelpfulContradiction => "helpful_contradiction",
            Self::HarmfulContradiction => "harmful_contradiction",
            Self::StaleEchoWrong => "stale_echo_wrong",
            Self::SelfConflict => "self_conflict",
            Self::Timeout => "timeout",
            Self::TransportFailure => "transport_failure",
            Self::MalformedEvidence => "malformed_evidence",
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Episode {
    pub id: u32,
    pub domain: u8,
    pub within: u16,
    pub scenario: Scenario,
    pub frame: PublicFrame,
    pub confidence: u16,
}

pub fn development_episodes() -> Vec<Episode> {
    generate(DEVELOPMENT_SEED, 8, false)
}

pub fn heldout_episodes() -> Vec<Episode> {
    generate(HELDOUT_SEED, 12, true)
}

fn generate(seed: u64, domains: usize, heldout: bool) -> Vec<Episode> {
    let mut episodes = Vec::with_capacity(domains * EPISODES_PER_DOMAIN);
    for domain in 0..domains {
        for within in 0..EPISODES_PER_DOMAIN {
            let id = (seed as u32)
                .wrapping_add(domain as u32 * DOMAIN_STRIDE)
                .wrapping_add(within as u32);
            let goal = ((within * 2 + domain) % 3) as u8;
            let truth_revision = hidden_revision(domain, within);
            let correct = contract_action(goal, truth_revision);
            let stale = contract_action(goal, truth_revision.saturating_sub(1));
            let scenario = scenario_for(domain, within, heldout);
            let (primary, audit, p_rev, a_rev, p_age, a_age, flags, confidence) =
                public_surface(scenario, correct, stale, truth_revision, within);
            episodes.push(Episode {
                id,
                domain: domain as u8,
                within: within as u16,
                scenario,
                frame: PublicFrame {
                    features: PublicFeatures {
                        episode_id: id,
                        inspection_domain: domain as u8,
                        goal,
                        primary_action: primary,
                        audit_action: audit,
                        primary_revision: p_rev,
                        audit_revision: a_rev,
                        primary_age: p_age,
                        audit_age: a_age,
                        flags,
                    },
                },
                confidence,
            });
        }
    }
    episodes
}

fn scenario_for(domain: usize, within: usize, heldout: bool) -> Scenario {
    match (heldout, domain, within) {
        (false, 0 | 4, _) => Scenario::ConfirmedCorrect,
        (false, 1, 0..24) | (false, 2, 0..16) | (false, 3, 0..30) => Scenario::HelpfulContradiction,
        (false, 1, _) | (false, 3, 30..) | (false, 5, 28..) | (false, 7, 24..) => Scenario::Timeout,
        (false, 2, 16..24) | (false, 5, 0..28) | (false, 7, 8..16) => {
            Scenario::HarmfulContradiction
        }
        (false, 2, 24..32) | (false, 7, 16..24) | (false, 6, 16..24) => Scenario::SelfConflict,
        (false, 6, 0..8) => Scenario::StaleEchoWrong,
        (false, 6, 8..16) | (false, 7, 0..8) => Scenario::HelpfulContradiction,
        (false, 6, 24..) => Scenario::TransportFailure,
        (false, _, _) => Scenario::MalformedEvidence,
        (true, 0 | 4, _) => Scenario::ConfirmedCorrect,
        (true, 1, 0..12)
        | (true, 2, 0..8)
        | (true, 3, 0..8)
        | (true, 5, 0..8)
        | (true, 7, 0..8)
        | (true, 8, 0..24) => Scenario::HelpfulContradiction,
        (true, 1, 12..20)
        | (true, 2, 8..16)
        | (true, 3, 8..16)
        | (true, 5, 8..16)
        | (true, 7, 8..16)
        | (true, 9, 0..24)
        | (true, 11, 16..24) => Scenario::HarmfulContradiction,
        (true, 2, 16..24) | (true, 3, 16..24) | (true, 7, 16..24) | (true, 10, _) => {
            Scenario::SelfConflict
        }
        (true, 1, 20..)
        | (true, 2, 24..)
        | (true, 3, 24..)
        | (true, 5, 16..24)
        | (true, 9, 28..32) => Scenario::Timeout,
        (true, 5, 24..)
        | (true, 7, 24..)
        | (true, 8, 24..)
        | (true, 9, 24..28)
        | (true, 11, 24..) => Scenario::TransportFailure,
        (true, 6, _) | (true, 11, 0..8) => Scenario::StaleEchoWrong,
        (true, 11, 8..16) => Scenario::HelpfulContradiction,
        _ => Scenario::MalformedEvidence,
    }
}

fn public_surface(
    scenario: Scenario,
    correct: Choice,
    stale: Choice,
    truth_revision: u8,
    within: usize,
) -> (Choice, Choice, u8, u8, u8, u8, u8, u16) {
    match scenario {
        Scenario::ConfirmedCorrect => (
            correct,
            correct,
            truth_revision,
            truth_revision,
            0,
            0,
            0,
            930,
        ),
        Scenario::HelpfulContradiction | Scenario::StaleEchoWrong => (
            stale,
            stale,
            truth_revision.saturating_sub(1),
            truth_revision.saturating_sub(1),
            0,
            0,
            0,
            960,
        ),
        Scenario::HarmfulContradiction => (
            correct,
            correct,
            truth_revision,
            truth_revision,
            0,
            0,
            0,
            940,
        ),
        Scenario::SelfConflict => (
            stale,
            correct,
            truth_revision.saturating_sub(1),
            truth_revision,
            1,
            0,
            0b101,
            820,
        ),
        Scenario::Timeout | Scenario::TransportFailure | Scenario::MalformedEvidence => {
            let flip = within.is_multiple_of(2);
            (
                if flip { stale } else { correct },
                if flip { correct } else { stale },
                truth_revision.saturating_sub(flip as u8),
                truth_revision,
                u8::from(flip),
                0,
                0b001,
                790,
            )
        }
    }
}

pub fn hidden_revision(domain: usize, within: usize) -> u8 {
    40 + ((within + 2 * domain) % 3) as u8
}

pub fn contract_action(goal: u8, revision: u8) -> Choice {
    const CONTRACT: [[Choice; 3]; 3] = [
        [
            Choice::UsePrimary,
            Choice::VerifyRecord,
            Choice::RefreshSnapshot,
        ],
        [
            Choice::VerifyRecord,
            Choice::RefreshSnapshot,
            Choice::UsePrimary,
        ],
        [
            Choice::RefreshSnapshot,
            Choice::UsePrimary,
            Choice::VerifyRecord,
        ],
    ];
    CONTRACT[goal as usize % 3][revision as usize % 3]
}

pub fn rotated(action: Choice, by: usize) -> Choice {
    Choice::ALL[(action as usize + by) % Choice::ALL.len()]
}
