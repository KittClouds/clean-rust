use std::{io::Write, path::Path};

use blake3::Hasher;

use crate::{domain::PublicEpisode, model::FrozenModels};

pub const BUDGETS: [usize; 3] = [16, 32, 64];

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum Lane {
    DomainTable,
    SmoothedTable,
    FeatureRouter,
    MatchedRandom,
    NoInspection,
    Oracle,
}

impl Lane {
    pub const ROUTERS: [Self; 4] = [
        Self::DomainTable,
        Self::SmoothedTable,
        Self::FeatureRouter,
        Self::MatchedRandom,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::DomainTable => "domain_table",
            Self::SmoothedTable => "smoothed_table",
            Self::FeatureRouter => "feature_router",
            Self::MatchedRandom => "matched_random",
            Self::NoInspection => "no_inspection",
            Self::Oracle => "evaluation_oracle",
        }
    }

    pub fn code(self) -> u8 {
        match self {
            Self::DomainTable => 0,
            Self::SmoothedTable => 1,
            Self::FeatureRouter => 2,
            Self::MatchedRandom => 3,
            Self::NoInspection => 4,
            Self::Oracle => 5,
        }
    }
}

#[derive(Clone, Debug)]
pub struct BudgetPlan {
    pub world_id: u32,
    pub lane: Lane,
    pub budget: usize,
    pub selected_ids: Vec<u32>,
}

pub fn make_plans(
    world_id: u32,
    public: &[PublicEpisode],
    models: &FrozenModels,
) -> Result<Vec<BudgetPlan>, Box<dyn std::error::Error>> {
    if BUDGETS.iter().any(|budget| *budget > public.len()) {
        return Err("query budget exceeds world episode count".into());
    }
    let mut plans = Vec::with_capacity(Lane::ROUTERS.len() * BUDGETS.len() + 1);
    plans.push(BudgetPlan {
        world_id,
        lane: Lane::NoInspection,
        budget: 0,
        selected_ids: Vec::new(),
    });
    for lane in Lane::ROUTERS {
        let mut ranked = public
            .iter()
            .map(|episode| {
                let score = match lane {
                    Lane::DomainTable => models.score_domain_table(*episode),
                    Lane::SmoothedTable => models.score_smoothed_table(*episode),
                    Lane::FeatureRouter => {
                        models.score_feature_router(&episode.features(), episode.query_cost_units)
                    }
                    Lane::MatchedRandom => 0.0,
                    Lane::NoInspection | Lane::Oracle => unreachable!(),
                };
                (score, tie_break(world_id, episode.id, lane), episode.id)
            })
            .collect::<Vec<_>>();
        ranked.sort_unstable_by(|left, right| {
            right
                .0
                .total_cmp(&left.0)
                .then_with(|| left.1.cmp(&right.1))
        });
        let ranked_ids = ranked.iter().map(|row| row.2).collect::<Vec<_>>();
        for budget in BUDGETS {
            let mut selected_ids = ranked_ids[..budget].to_vec();
            selected_ids.sort_unstable();
            plans.push(BudgetPlan {
                world_id,
                lane,
                budget,
                selected_ids,
            });
        }
    }
    validate_plans(&plans, world_id, public)?;
    Ok(plans)
}

pub fn validate_plans(
    plans: &[BudgetPlan],
    world_id: u32,
    public: &[PublicEpisode],
) -> Result<(), Box<dyn std::error::Error>> {
    let episode_ids = public
        .iter()
        .map(|episode| episode.id)
        .collect::<std::collections::HashSet<_>>();
    for plan in plans {
        if plan.world_id != world_id
            || plan.selected_ids.len() != plan.budget
            || plan.budget > public.len()
            || plan.selected_ids.iter().any(|id| !episode_ids.contains(id))
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
        let at_16 = plans
            .iter()
            .find(|plan| plan.lane == lane && plan.budget == 16)
            .ok_or("missing 16-call plan")?;
        let at_32 = plans
            .iter()
            .find(|plan| plan.lane == lane && plan.budget == 32)
            .ok_or("missing 32-call plan")?;
        let at_64 = plans
            .iter()
            .find(|plan| plan.lane == lane && plan.budget == 64)
            .ok_or("missing 64-call plan")?;
        if !subset(&at_16.selected_ids, &at_32.selected_ids)
            || !subset(&at_32.selected_ids, &at_64.selected_ids)
        {
            return Err(format!("{} plans are not nested by budget", lane.label()).into());
        }
    }
    Ok(())
}

pub fn write_plans(
    path: impl AsRef<Path>,
    plans: &[BudgetPlan],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = std::io::BufWriter::with_capacity(32 * 1024, std::fs::File::create(path)?);
    writeln!(writer, "world_id,lane,budget,episode_id,query")?;
    for plan in plans {
        for id in &plan.selected_ids {
            writeln!(
                writer,
                "{},{},{},{id},true",
                plan.world_id,
                plan.lane.label(),
                plan.budget
            )?;
        }
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn subset(smaller: &[u32], larger: &[u32]) -> bool {
    smaller
        .iter()
        .all(|value| larger.binary_search(value).is_ok())
}

fn tie_break(world_id: u32, episode_id: u32, lane: Lane) -> [u8; 32] {
    let mut hasher = Hasher::new();
    hasher.update(b"RDC-E007-ROUTE-TIE-V1\0");
    hasher.update(&world_id.to_le_bytes());
    hasher.update(&episode_id.to_le_bytes());
    hasher.update(&[lane.code()]);
    *hasher.finalize().as_bytes()
}

pub fn selected(plan: &BudgetPlan, episode: &PublicEpisode) -> bool {
    plan.selected_ids.binary_search(&episode.id).is_ok()
}
