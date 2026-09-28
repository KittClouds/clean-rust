use std::io::Write;

use hashbrown::{HashMap, HashSet};
use rdc_experiment_004::{
    BudgetPlan as E004BudgetPlan, Episode as E004Episode, EpisodeClass as E004EpisodeClass,
    Policy as E004Policy, plan_budgets as e004_plan_budgets,
};

use crate::{
    episodes::Episode, evaluation::EvalLabel, inspection::SourceStateStore,
    scoring::DevelopmentValueModel,
};

pub const BUDGETS: [usize; 4] = [16, 32, 48, 64];

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum Lane {
    E004Combined,
    DevelopmentVoI,
    MatchedRandom,
    OfflineOracle,
}

impl Lane {
    pub const PUBLIC: [Self; 3] = [
        Self::E004Combined,
        Self::DevelopmentVoI,
        Self::MatchedRandom,
    ];
    pub const ALL: [Self; 4] = [
        Self::E004Combined,
        Self::DevelopmentVoI,
        Self::MatchedRandom,
        Self::OfflineOracle,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::E004Combined => "e004_combined",
            Self::DevelopmentVoI => "development_voi",
            Self::MatchedRandom => "matched_random",
            Self::OfflineOracle => "offline_oracle",
        }
    }

    pub fn index(self) -> u8 {
        match self {
            Self::E004Combined => 0,
            Self::DevelopmentVoI => 1,
            Self::MatchedRandom => 2,
            Self::OfflineOracle => 3,
        }
    }
}

#[derive(Clone, Debug)]
pub struct BudgetPlan {
    pub lane: Lane,
    pub budget: usize,
    pub selected_ids: HashSet<u32>,
}

pub fn make_public_plans(
    episodes: &[Episode],
    budgets: &[usize],
    model: &DevelopmentValueModel,
) -> Result<Vec<BudgetPlan>, Box<dyn std::error::Error>> {
    if budgets.iter().any(|budget| *budget > episodes.len()) {
        return Err("routing budget exceeds episode count".into());
    }
    let legacy_episodes = episodes
        .iter()
        .map(|episode| E004Episode {
            id: episode.id,
            class: E004EpisodeClass::FreshAgreement,
            features: episode.frame.features,
            confidence: episode.confidence,
        })
        .collect::<Vec<_>>();
    let legacy_plans = e004_plan_budgets(&legacy_episodes, budgets);
    let mut plans = Vec::with_capacity(Lane::PUBLIC.len() * budgets.len());

    for budget in budgets {
        let legacy: &E004BudgetPlan = legacy_plans
            .iter()
            .find(|plan| plan.policy == E004Policy::Combined && plan.budget == *budget)
            .ok_or("E004 combined plan missing")?;
        plans.push(BudgetPlan {
            lane: Lane::E004Combined,
            budget: *budget,
            selected_ids: legacy.selected_ids.clone(),
        });
    }

    for lane in [Lane::DevelopmentVoI, Lane::MatchedRandom] {
        let mut ranked = episodes
            .iter()
            .map(|episode| {
                let score = if lane == Lane::DevelopmentVoI {
                    model.score(episode.frame.inspection_domain)
                } else {
                    0
                };
                (score, tie_break(episode.id, lane), episode.id)
            })
            .collect::<Vec<_>>();
        ranked.sort_unstable_by(|left, right| {
            right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1))
        });
        for budget in budgets {
            plans.push(BudgetPlan {
                lane,
                budget: *budget,
                selected_ids: ranked.iter().take(*budget).map(|item| item.2).collect(),
            });
        }
    }
    validate_exact(&plans, episodes.len())?;
    Ok(plans)
}

/// Builds the non-deployable offline ceiling after labels are frozen.
pub fn make_oracle_plans(
    episodes: &[Episode],
    budgets: &[usize],
    labels: &[EvalLabel],
    source_state: &SourceStateStore,
) -> Result<Vec<BudgetPlan>, Box<dyn std::error::Error>> {
    if episodes.len() != labels.len() {
        return Err("oracle episode and label counts differ".into());
    }
    let label_by_id = labels
        .iter()
        .map(|label| (label.episode_id, label.correct_action))
        .collect::<HashMap<_, _>>();
    let mut ranked = episodes
        .iter()
        .map(|episode| {
            let correct = label_by_id
                .get(&episode.id)
                .copied()
                .unwrap_or(episode.frame.features.primary_action);
            let active = episode.frame.features.primary_action;
            let inspected = source_state
                .get(episode.id)
                .and_then(|state| rdc_experiment_004::Choice::from_code(state.recommendation))
                .unwrap_or(active);
            let delta = (inspected == correct) as i32 - (active == correct) as i32;
            (
                delta,
                tie_break(episode.id, Lane::OfflineOracle),
                episode.id,
            )
        })
        .collect::<Vec<_>>();
    ranked.sort_unstable_by(|left, right| right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1)));
    let plans = budgets
        .iter()
        .map(|budget| BudgetPlan {
            lane: Lane::OfflineOracle,
            budget: *budget,
            selected_ids: ranked.iter().take(*budget).map(|item| item.2).collect(),
        })
        .collect::<Vec<_>>();
    validate_exact(&plans, episodes.len())?;
    Ok(plans)
}

pub fn validate_exact(
    plans: &[BudgetPlan],
    episode_count: usize,
) -> Result<(), Box<dyn std::error::Error>> {
    for plan in plans {
        if plan.budget > episode_count || plan.selected_ids.len() != plan.budget {
            return Err(
                format!("{} budget {} is not exact", plan.lane.label(), plan.budget).into(),
            );
        }
    }
    Ok(())
}

pub fn plan_map(plans: &[BudgetPlan]) -> HashMap<(Lane, usize), HashSet<u32>> {
    plans
        .iter()
        .map(|plan| ((plan.lane, plan.budget), plan.selected_ids.clone()))
        .collect()
}

pub fn write_plans(
    path: impl AsRef<std::path::Path>,
    plans: &[BudgetPlan],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = std::io::BufWriter::new(std::fs::File::create(path)?);
    writeln!(writer, "lane,budget,episode_id,query")?;
    for plan in plans {
        let mut ids = plan.selected_ids.iter().copied().collect::<Vec<_>>();
        ids.sort_unstable();
        for id in ids {
            writeln!(writer, "{},{},{id},true", plan.lane.label(), plan.budget)?;
        }
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn tie_break(episode_id: u32, lane: Lane) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"RDC-E005-ROUTE-PLAN-V1\0");
    hasher.update(&episode_id.to_le_bytes());
    hasher.update(&[lane.index()]);
    *hasher.finalize().as_bytes()
}
