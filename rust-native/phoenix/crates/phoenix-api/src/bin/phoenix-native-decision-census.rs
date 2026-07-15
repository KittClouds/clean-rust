use std::path::PathBuf;

use phoenix_api::{native_decision_census, native_reward_observation_census};
use phoenix_store_overgraph::PhoenixOvergraphStore;
use serde_json::json;

fn main() -> Result<(), String> {
    let store_path = parse_store_path(std::env::args().skip(1))?;
    let store = PhoenixOvergraphStore::open(&store_path).map_err(display_error)?;
    let decisions = native_decision_census(&store).map_err(display_error)?;
    let rewards = native_reward_observation_census(&store).map_err(display_error)?;
    let report = json!({
        "schemaVersion": "phoenix-native-decision-census-report/v1",
        "storePath": store_path.display().to_string(),
        "readOnly": true,
        "decisions": decisions,
        "rewards": rewards,
    });
    store.close_fast().map_err(display_error)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&report)
            .map_err(|error| format!("serialize census: {error}"))?
    );
    Ok(())
}

fn parse_store_path(args: impl Iterator<Item = String>) -> Result<PathBuf, String> {
    let mut store_path = None;
    let mut args = args.peekable();
    while let Some(argument) = args.next() {
        match argument.as_str() {
            "--store-path" => store_path = args.next().map(PathBuf::from),
            other => return Err(format!("unknown argument: {other}")),
        }
    }
    let store_path = store_path.ok_or("--store-path is required")?;
    if !store_path.is_dir() {
        return Err(format!(
            "store path does not exist: {}",
            store_path.display()
        ));
    }
    Ok(store_path)
}

fn display_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}
