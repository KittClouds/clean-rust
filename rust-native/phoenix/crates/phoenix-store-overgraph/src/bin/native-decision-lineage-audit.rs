use std::{collections::BTreeMap, env, path::PathBuf};

use phoenix_store_native_core::PhoenixNativeDecisionStore;
use phoenix_store_overgraph::PhoenixOvergraphStore;
use serde_json::json;

#[derive(Default)]
struct Cohort {
    count: u64,
    first_observed_at: i64,
    last_observed_at: i64,
    first_decision_id: String,
    last_decision_id: String,
    samples: Vec<serde_json::Value>,
}

fn main() -> Result<(), String> {
    let store_path = env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("usage: native-decision-lineage-audit <store-path>")?;
    let store = PhoenixOvergraphStore::open(&store_path).map_err(|error| error.to_string())?;
    let decisions = store
        .load_native_decision_receipts()
        .map_err(|error| error.to_string())?;
    if env::args().nth(2).as_deref() == Some("selections") {
        let mut selections = decisions
            .iter()
            .map(|decision| {
                let action = decision
                    .candidates
                    .get(decision.chosen_candidate_ordinal as usize)
                    .and_then(|candidate| serde_json::to_value(&candidate.action).ok())
                    .ok_or("decision has no chosen action")?;
                let event_id = action
                    .pointer("/parameters/eventId")
                    .and_then(serde_json::Value::as_str)
                    .ok_or("chosen action has no event id")?;
                let episode_id = action
                    .pointer("/parameters/episodeId")
                    .and_then(serde_json::Value::as_str)
                    .ok_or("chosen action has no episode id")?;
                Ok(json!({
                    "eventId": event_id,
                    "selectedAction": {
                        "kind": "attach_to_episode",
                        "episodeId": episode_id,
                    },
                    "decidedAt": decision.observed_at,
                }))
            })
            .collect::<Result<Vec<_>, &str>>()?;
        selections.sort_unstable_by_key(|value| value["decidedAt"].as_i64().unwrap_or_default());
        println!("{}", serde_json::to_string(&selections).map_err(|error| error.to_string())?);
        return Ok(());
    }
    let mut cohorts = BTreeMap::<String, Cohort>::new();
    for decision in &decisions {
        let source = decision
            .lineage_ids
            .first()
            .map(ToString::to_string)
            .unwrap_or_else(|| "<missing>".to_owned());
        let chosen_action = decision
            .candidates
            .get(decision.chosen_candidate_ordinal as usize)
            .and_then(|candidate| serde_json::to_value(&candidate.action).ok())
            .unwrap_or_default();
        let event_id = chosen_action
            .pointer("/parameters/eventId")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("<missing>");
        let epoch = if decision.observed_at >= 1_784_150_000_000 {
            "replay"
        } else {
            "original"
        };
        let cohort = cohorts.entry(format!("{source}\n{epoch}")).or_default();
        if cohort.count == 0 || decision.observed_at < cohort.first_observed_at {
            cohort.first_observed_at = decision.observed_at;
            cohort.first_decision_id = decision.decision_id.to_string();
        }
        if cohort.count == 0 || decision.observed_at > cohort.last_observed_at {
            cohort.last_observed_at = decision.observed_at;
            cohort.last_decision_id = decision.decision_id.to_string();
        }
        cohort.count += 1;
        if cohort.samples.len() < 24 {
            cohort.samples.push(json!({
                "decisionId": decision.decision_id,
                "observedAt": decision.observed_at,
                "preStateSnapshotId": decision.pre_state_snapshot_id,
                "chosenAction": chosen_action,
                "eventId": event_id,
            }));
        }
    }
    let rows = cohorts
        .into_iter()
        .map(|(key, cohort)| {
            let (source_snapshot_id, epoch) = key.split_once('\n').unwrap_or((&key, "unknown"));
            json!({
                "sourceSnapshotId": source_snapshot_id,
                "epoch": epoch,
                "count": cohort.count,
                "firstObservedAt": cohort.first_observed_at,
                "lastObservedAt": cohort.last_observed_at,
                "firstDecisionId": cohort.first_decision_id,
                "lastDecisionId": cohort.last_decision_id,
                "samples": cohort.samples,
            })
        })
        .collect::<Vec<_>>();
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "schemaVersion": "phoenix-native-decision-lineage-audit/v1",
            "storePath": store_path,
            "decisionCount": decisions.len(),
            "cohorts": rows,
        }))
        .map_err(|error| error.to_string())?
    );
    Ok(())
}
