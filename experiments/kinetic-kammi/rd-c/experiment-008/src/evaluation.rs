use std::io::Write;

use hashbrown::HashMap;
use rdc_runtime_contracts_v1::{ActionCode, InspectionKind, InspectionReply, InspectionResult};

use crate::{
    domain::{Availability, HiddenEpisode, PublicEpisode, SourceOffer, WorldBank},
    routing::{BudgetPlan, Candidate, Lane},
};

#[derive(Clone, Copy, Debug, Default)]
pub struct OutcomeCounts {
    pub baseline_right: u32,
    pub baseline_wrong: u32,
    pub wrong_to_right: u32,
    pub right_to_wrong: u32,
    pub unresolved_baseline_right: u32,
    pub unresolved_baseline_wrong: u32,
    pub avoided_wrong: u32,
    pub query_confirmed: u32,
    pub query_contradicted: u32,
    pub query_unknown: u32,
    pub query_failed: u32,
}

impl OutcomeCounts {
    pub fn delta(self) -> i32 {
        self.wrong_to_right as i32
            - self.right_to_wrong as i32
            - self.unresolved_baseline_right as i32
    }
}

pub fn outcome_components(public: PublicEpisode, hidden: HiddenEpisode, source: usize) -> [f32; 4] {
    let baseline_right = public.active == hidden.correct_action;
    let result = InspectionResult::classify(public.active, hidden.replies[source]);
    let proposed = result.proposed_action;
    [
        (!baseline_right && proposed == Some(hidden.correct_action)) as u8 as f32,
        (baseline_right && proposed.is_some_and(|action| action != hidden.correct_action)) as u8
            as f32,
        (baseline_right && proposed.is_none()) as u8 as f32,
        (!baseline_right && proposed.is_none()) as u8 as f32,
    ]
}

pub fn counterfactual_delta(
    public: PublicEpisode,
    reply: InspectionReply,
    correct: ActionCode,
) -> i8 {
    let before = (public.active == correct) as i8;
    let result = InspectionResult::classify(public.active, reply);
    let after = result
        .proposed_action
        .map_or(0, |action| (action == correct) as i8);
    after - before
}

pub fn summarize_plan(
    bank: &WorldBank,
    plan: &BudgetPlan,
    queried: &[(u32, u8)],
) -> Result<OutcomeCounts, Box<dyn std::error::Error>> {
    let selected = queried
        .iter()
        .map(|(id, source)| (*id, *source as usize))
        .collect::<HashMap<_, _>>();
    let mut counts = OutcomeCounts::default();
    for (public, hidden) in bank.public.iter().zip(&bank.hidden) {
        let baseline_right = public.active == hidden.correct_action;
        if baseline_right {
            counts.baseline_right += 1;
        } else {
            counts.baseline_wrong += 1;
        }
        let Some(source) = selected.get(&public.id).copied() else {
            continue;
        };
        let reply = hidden.replies[source];
        let result = InspectionResult::classify(public.active, reply);
        match result.kind {
            InspectionKind::Confirmed => counts.query_confirmed += 1,
            InspectionKind::Contradicted => counts.query_contradicted += 1,
            InspectionKind::Unknown => counts.query_unknown += 1,
            InspectionKind::Failed => counts.query_failed += 1,
        }
        match result.proposed_action {
            Some(action) if !baseline_right && action == hidden.correct_action => {
                counts.wrong_to_right += 1
            }
            Some(action) if baseline_right && action != hidden.correct_action => {
                counts.right_to_wrong += 1
            }
            Some(_) => {}
            None if baseline_right => counts.unresolved_baseline_right += 1,
            None => counts.unresolved_baseline_wrong += 1,
        }
        if !baseline_right && result.proposed_action.is_none() {
            counts.avoided_wrong += 1;
        }
    }
    let _ = plan;
    Ok(counts)
}

#[derive(Clone, Debug)]
pub struct AuditGroup {
    pub cohort: String,
    pub feature: String,
    pub key: String,
    pub target: String,
    pub support: u32,
    pub largest_class: u32,
}

pub fn input_audit(banks: &[WorldBank], cohort: &str) -> (Vec<AuditGroup>, usize) {
    let mut groups = HashMap::<(String, String, String, String), [u32; 4]>::with_capacity(2048);
    let mut labels = 0usize;
    for bank in banks {
        let world_cohort = format!("{cohort}-world-{}", bank.recipe.world_id);
        for (public, hidden, bundle) in bank
            .public
            .iter()
            .zip(&bank.hidden)
            .zip(&bank.offers)
            .map(|((p, h), o)| (p, h, o))
        {
            for source in 0..3 {
                let offer = bundle.offers[source];
                let reply = hidden.replies[source];
                let offer_fields = offer_field_values(offer);
                let action_label = hidden.correct_action.0.min(3) as usize;
                let result = InspectionResult::classify(public.active, reply);
                let outcome_label = match result.kind {
                    InspectionKind::Confirmed => 0,
                    InspectionKind::Contradicted => 1,
                    InspectionKind::Unknown => 2,
                    InspectionKind::Failed => 3,
                };
                for (i, value) in offer_fields.iter().enumerate() {
                    add_group(
                        &mut groups,
                        &world_cohort,
                        &format!("field_{i}"),
                        value,
                        "correct_action",
                        action_label,
                    );
                    add_group(
                        &mut groups,
                        &world_cohort,
                        &format!("field_{i}"),
                        value,
                        "inspection_outcome",
                        outcome_label,
                    );
                    labels += 2;
                    for (j, right_value) in offer_fields.iter().enumerate().skip(i + 1) {
                        let pair = format!("{}+{}", i, j);
                        let key = format!("{value}|{right_value}");
                        add_group(
                            &mut groups,
                            &world_cohort,
                            &pair,
                            &key,
                            "correct_action",
                            action_label,
                        );
                        add_group(
                            &mut groups,
                            &world_cohort,
                            &pair,
                            &key,
                            "inspection_outcome",
                            outcome_label,
                        );
                        labels += 2;
                    }
                }
                let full_signature = offer_fields.join("|");
                add_group(
                    &mut groups,
                    &world_cohort,
                    "all_fields",
                    &full_signature,
                    "correct_action",
                    action_label,
                );
                add_group(
                    &mut groups,
                    &world_cohort,
                    "all_fields",
                    &full_signature,
                    "inspection_outcome",
                    outcome_label,
                );
                labels += 2;
            }
        }
    }
    let mut rows = groups
        .into_iter()
        .map(|((cohort, feature, key, target), counts)| {
            let support = counts.iter().sum::<u32>();
            AuditGroup {
                cohort,
                feature,
                key,
                target,
                support,
                largest_class: *counts.iter().max().unwrap_or(&0),
            }
        })
        .collect::<Vec<_>>();
    rows.sort_unstable_by(|a, b| {
        a.cohort
            .cmp(&b.cohort)
            .then(a.feature.cmp(&b.feature))
            .then(a.key.cmp(&b.key))
            .then(a.target.cmp(&b.target))
    });
    (rows, labels)
}

fn add_group(
    map: &mut HashMap<(String, String, String, String), [u32; 4]>,
    cohort: &str,
    feature: &str,
    key: &str,
    target: &str,
    label: usize,
) {
    let counts = map
        .entry((
            cohort.to_owned(),
            feature.to_owned(),
            key.to_owned(),
            target.to_owned(),
        ))
        .or_default();
    counts[label] += 1;
}

fn offer_field_values(offer: SourceOffer) -> [String; 10] {
    [
        offer.schema_version.to_string(),
        offer.version.to_string(),
        offer.source_id.to_string(),
        (offer.availability as u8).to_string(),
        offer.source_local_age_bucket.to_string(),
        offer.provenance_family.to_string(),
        (offer.independence_from_active_source as u8).to_string(),
        offer.historical_reliability_bucket.to_string(),
        offer.quoted_query_price.to_string(),
        offer.offer_expiry.to_string(),
    ]
}

pub fn write_input_audit(
    path: impl AsRef<std::path::Path>,
    rows: &[AuditGroup],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = std::io::BufWriter::with_capacity(32 * 1024, std::fs::File::create(path)?);
    writeln!(
        writer,
        "cohort,feature,key,target,support,largest_class,purity,deterministic_at_support_8"
    )?;
    for row in rows {
        let purity = row.largest_class as f64 / row.support.max(1) as f64;
        writeln!(
            writer,
            "{},{},{},{},{},{},{:.6},{}",
            row.cohort,
            row.feature,
            row.key,
            row.target,
            row.support,
            row.largest_class,
            purity,
            row.support >= 8 && row.largest_class == row.support
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

pub fn oracle_plans(bank: &WorldBank, lambdas: &[f32]) -> Vec<BudgetPlan> {
    let mut plans = Vec::with_capacity(lambdas.len() * crate::routing::BUDGETS.len());
    for &lambda in lambdas {
        let mut candidates = Vec::with_capacity(bank.public.len() * 3);
        for (public, hidden) in bank.public.iter().zip(&bank.hidden) {
            for source in 0..3 {
                let offer = bank
                    .offers
                    .iter()
                    .find(|bundle| bundle.episode_id == public.id)
                    .unwrap()
                    .offers[source];
                if offer.availability == Availability::Unavailable {
                    continue;
                }
                let delta =
                    counterfactual_delta(*public, hidden.replies[source], hidden.correct_action)
                        as f32;
                let value = delta - lambda * offer.quoted_query_price as f32;
                if value > 0.0 {
                    candidates.push(Candidate {
                        episode_id: public.id,
                        source_id: source as u8,
                        offer,
                        signal_offer: offer,
                        signal_episode_id: public.id,
                        estimate: estimate_for_delta(delta),
                        predicted_delta: delta,
                        predicted_value: value,
                        offer_only: false,
                    });
                }
            }
        }
        candidates.sort_unstable_by(candidate_order);
        for budget in crate::routing::BUDGETS {
            plans.push(BudgetPlan {
                world_id: bank.recipe.world_id,
                lane: Lane::Oracle,
                budget,
                lambda,
                offer_mode: crate::routing::OfferMode::PushedCache,
                offer_request_cost: 0,
                call_target: None,
                offer_charge_target: None,
                query_price_targets: Vec::new(),
                candidates: candidates.clone(),
            });
        }
    }
    plans
}

fn estimate_for_delta(delta: f32) -> crate::model::ValueEstimate {
    crate::model::ValueEstimate {
        wrong_to_right: delta.max(0.0),
        right_to_wrong: (-delta).max(0.0),
        ..Default::default()
    }
}

fn candidate_order(a: &Candidate, b: &Candidate) -> std::cmp::Ordering {
    b.predicted_value
        .total_cmp(&a.predicted_value)
        .then(a.offer.quoted_query_price.cmp(&b.offer.quoted_query_price))
        .then(a.episode_id.cmp(&b.episode_id))
        .then(a.source_id.cmp(&b.source_id))
}
