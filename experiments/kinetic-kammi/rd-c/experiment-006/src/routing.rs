use std::{io::Write, path::Path};

use crate::{
    episodes::Episode,
    scoring::{FeatureValueModel, FrozenDomainTable, SmoothedValueModel},
};
use blake3::Hasher;
use hashbrown::{HashMap, HashSet};

pub const BUDGETS: [usize; 4] = [16, 32, 48, 64];

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum Lane {
    E005DomainTable,
    SmoothedEstimate,
    FeatureEstimate,
    MatchedRandom,
    NoInspection,
}

impl Lane {
    pub const ROUTERS: [Self; 4] = [
        Self::E005DomainTable,
        Self::SmoothedEstimate,
        Self::FeatureEstimate,
        Self::MatchedRandom,
    ];
    pub const ALL: [Self; 5] = [
        Self::E005DomainTable,
        Self::SmoothedEstimate,
        Self::FeatureEstimate,
        Self::MatchedRandom,
        Self::NoInspection,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::E005DomainTable => "e005_domain_table",
            Self::SmoothedEstimate => "smoothed_estimate",
            Self::FeatureEstimate => "feature_estimate",
            Self::MatchedRandom => "matched_random",
            Self::NoInspection => "no_inspection",
        }
    }

    pub fn index(self) -> u8 {
        match self {
            Self::E005DomainTable => 0,
            Self::SmoothedEstimate => 1,
            Self::FeatureEstimate => 2,
            Self::MatchedRandom => 3,
            Self::NoInspection => 4,
        }
    }
}

#[derive(Clone, Debug)]
pub struct BudgetPlan {
    pub lane: Lane,
    pub budget: usize,
    pub selected_ids: HashSet<u32>,
}

pub fn make_plans(
    episodes: &[Episode],
    budgets: &[usize],
    e005: &FrozenDomainTable,
    smoothed: &SmoothedValueModel,
    feature: &FeatureValueModel,
) -> Result<Vec<BudgetPlan>, Box<dyn std::error::Error>> {
    if budgets.iter().any(|budget| *budget > episodes.len()) {
        return Err("query budget exceeds held-out episode count".into());
    }
    let mut plans = Vec::with_capacity(Lane::ROUTERS.len() * budgets.len() + 1);
    plans.push(BudgetPlan {
        lane: Lane::NoInspection,
        budget: 0,
        selected_ids: HashSet::new(),
    });
    for lane in Lane::ROUTERS {
        let mut ranked = episodes
            .iter()
            .map(|episode| {
                let score = match lane {
                    Lane::E005DomainTable => e005.score(episode.domain),
                    Lane::SmoothedEstimate => smoothed.score(episode.domain),
                    Lane::FeatureEstimate => feature.score(episode.frame, episode.confidence),
                    Lane::MatchedRandom => 0.0,
                    Lane::NoInspection => unreachable!(),
                };
                (score, tie_break(episode.id, lane), episode.id)
            })
            .collect::<Vec<_>>();
        ranked.sort_unstable_by(|left, right| {
            right
                .0
                .total_cmp(&left.0)
                .then_with(|| left.1.cmp(&right.1))
        });
        for budget in budgets {
            plans.push(BudgetPlan {
                lane,
                budget: *budget,
                selected_ids: ranked.iter().take(*budget).map(|row| row.2).collect(),
            });
        }
    }
    validate_exact(&plans, episodes)?;
    Ok(plans)
}

pub fn validate_exact(
    plans: &[BudgetPlan],
    episodes: &[Episode],
) -> Result<(), Box<dyn std::error::Error>> {
    let ids = episodes
        .iter()
        .map(|episode| episode.id)
        .collect::<HashSet<_>>();
    for plan in plans {
        if plan.selected_ids.len() != plan.budget
            || plan.budget > episodes.len()
            || !plan.selected_ids.is_subset(&ids)
        {
            return Err(format!(
                "{} budget {} failed exact route validation",
                plan.lane.label(),
                plan.budget
            )
            .into());
        }
    }
    for lane in Lane::ROUTERS {
        let mut previous = HashSet::new();
        for budget in BUDGETS {
            if let Some(plan) = plans
                .iter()
                .find(|plan| plan.lane == lane && plan.budget == budget)
            {
                if !previous.is_subset(&plan.selected_ids) {
                    return Err(format!(
                        "{} route plans are not nested at budget {budget}",
                        lane.label()
                    )
                    .into());
                }
                previous.clone_from(&plan.selected_ids);
            }
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
    path: impl AsRef<Path>,
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
    let mut hasher = Hasher::new();
    hasher.update(b"RDC-E006-ROUTE-PLAN-V1\0");
    hasher.update(&episode_id.to_le_bytes());
    hasher.update(&[lane.index()]);
    *hasher.finalize().as_bytes()
}
