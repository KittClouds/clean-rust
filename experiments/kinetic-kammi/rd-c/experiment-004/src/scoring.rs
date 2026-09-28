use hashbrown::HashSet;

use crate::{episodes::Episode, routing::Policy};

#[derive(Clone, Debug)]
pub struct BudgetPlan {
    pub policy: Policy,
    pub budget: usize,
    pub selected_ids: HashSet<u32>,
}

/// Plan resolver calls using only observation features; no evaluation labels are accepted here.
pub fn plan_budgets(episodes: &[Episode], budgets: &[usize]) -> Vec<BudgetPlan> {
    let mut plans = Vec::with_capacity(Policy::ALL.len() * budgets.len());
    for policy in Policy::ALL {
        let mut ranked = episodes
            .iter()
            .map(|episode| {
                let f = episode.features;
                let b_source = if f.flags & 4 != 0 { 2 } else { 1 };
                let b_action = if b_source == 2 {
                    f.audit_action
                } else {
                    f.primary_action
                };
                let disagreement = u8::from(f.primary_action != b_action);
                let witness =
                    u8::from(disagreement == 0 && f.primary_action == b_action && b_source == 1)
                        * u8::from(
                            f.primary_age > 0
                                || f.flags & 1 != 0
                                || f.primary_action
                                    != crate::episodes::contract_action(f.goal, f.primary_revision),
                        );
                let confidence_need = 1000u16.saturating_sub(episode.confidence);
                let score = match policy {
                    Policy::Disagreement => [disagreement, 0, 0],
                    Policy::Confidence => [0, 0, (confidence_need / 100) as u8],
                    Policy::Combined => [witness, disagreement, (confidence_need / 100) as u8],
                    Policy::RandomMatched => [0, 0, 0],
                };
                (score, tie_break(episode.id, policy), episode.id)
            })
            .collect::<Vec<_>>();
        ranked.sort_unstable_by(|left, right| {
            right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1))
        });
        for budget in budgets {
            assert!(
                *budget <= episodes.len(),
                "resolver budget exceeds episode bank"
            );
            plans.push(BudgetPlan {
                policy,
                budget: *budget,
                selected_ids: ranked.iter().take(*budget).map(|row| row.2).collect(),
            });
        }
    }
    plans
}

pub fn budget_is_exact(plan: &BudgetPlan) -> bool {
    plan.selected_ids.len() == plan.budget
}

fn tie_break(episode_id: u32, policy: Policy) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-E004-ROUTE-PLAN-V1\0");
    hasher.update(&episode_id.to_le_bytes());
    hasher.update(&[policy.index()]);
    *hasher.finalize().as_bytes()
}
