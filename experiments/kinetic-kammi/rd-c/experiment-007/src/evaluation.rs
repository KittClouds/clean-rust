use rdc_runtime_contracts_v1::{ActionCode, InspectionReply, InspectionResult};

use crate::{
    domain::{HiddenEpisode, PublicEpisode, WorldBank},
    routing::{BUDGETS, BudgetPlan, Lane},
};

pub fn counterfactual_delta(
    public: PublicEpisode,
    reply: InspectionReply,
    correct_action: ActionCode,
) -> i8 {
    let before = (public.active == correct_action) as i8;
    let result = InspectionResult::classify(public.active, reply);
    let after = result
        .proposed_action
        .map_or(0, |action| (action == correct_action) as i8);
    after - before
}

/// The oracle is analysis-only and is called after ordinary route plans are frozen.
pub fn oracle_plans(bank: &WorldBank) -> Result<Vec<BudgetPlan>, Box<dyn std::error::Error>> {
    let by_id = bank
        .hidden
        .iter()
        .map(|hidden| (hidden.episode_id, hidden))
        .collect::<hashbrown::HashMap<_, _>>();
    let mut ranked = Vec::with_capacity(bank.public.len());
    for public in &bank.public {
        let hidden = by_id
            .get(&public.id)
            .ok_or("oracle label or source result missing")?;
        let delta = counterfactual_delta(*public, hidden.reply, hidden.correct_action);
        ranked.push((
            delta,
            public.query_cost_units,
            oracle_tie(bank.recipe.world_id, public.id),
            public.id,
        ));
    }
    ranked.sort_unstable_by(|left, right| {
        right
            .0
            .cmp(&left.0)
            .then_with(|| left.1.cmp(&right.1))
            .then_with(|| left.2.cmp(&right.2))
    });
    let ranked_ids = ranked.iter().map(|row| row.3).collect::<Vec<_>>();
    let mut plans = Vec::with_capacity(BUDGETS.len());
    for budget in BUDGETS {
        let mut selected_ids = ranked_ids[..budget].to_vec();
        selected_ids.sort_unstable();
        plans.push(BudgetPlan {
            world_id: bank.recipe.world_id,
            lane: Lane::Oracle,
            budget,
            selected_ids,
        });
    }
    Ok(plans)
}

pub fn hidden_for(hidden: &[HiddenEpisode], episode_id: u32) -> Option<&HiddenEpisode> {
    hidden.iter().find(|row| row.episode_id == episode_id)
}

fn oracle_tie(world_id: u32, episode_id: u32) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-E007-ORACLE-TIE-V1\0");
    hasher.update(&world_id.to_le_bytes());
    hasher.update(&episode_id.to_le_bytes());
    *hasher.finalize().as_bytes()
}
