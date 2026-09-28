use std::{fs, path::PathBuf};

use rdc_experiment_008::{
    domain, evaluation, manifest,
    model::FrozenModels,
    report,
    routing::{self, BudgetPlan, Lane},
    runtime,
};
use serde_json::json;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let contracts_root = project_root.join("../rdc-runtime-contracts-v1");
    let (run_id, run_dir, run_nonce) = manifest::new_run_dir(&project_root)?;
    let e007_provenance = manifest::copy_e007_provenance(&run_dir)?;
    let dev_dir = run_dir.join("inputs/development");
    let heldout_dir = run_dir.join("inputs/heldout");
    let planning_dir = run_dir.join("planning");
    let receipt_dir = run_dir.join("query-receipts");
    fs::create_dir_all(&dev_dir)?;
    fs::create_dir_all(&heldout_dir)?;
    fs::create_dir_all(&planning_dir)?;
    fs::create_dir_all(&receipt_dir)?;

    // Development truth is allowed to fit the frozen offer-value model.
    let development = domain::development_banks();
    domain::write_world_recipes(dev_dir.join("world-recipes.json"), &development)?;
    domain::write_public(dev_dir.join("public.csv"), &development)?;
    domain::write_offers(dev_dir.join("source-offers.csv"), &development, false)?;
    domain::write_offers(dev_dir.join("current-offers.csv"), &development, true)?;
    domain::write_labels(dev_dir.join("task-truth.csv"), &development)?;
    domain::write_source_fixture(dev_dir.join("inspection-replies.csv"), &development)?;
    let models = FrozenModels::fit(&development)?;
    models.write_csv(dev_dir.join("frozen-models.csv"))?;

    // The ordinary held-out route interface receives only public episodes and offers.
    let heldout = domain::heldout_banks();
    domain::write_world_recipes(heldout_dir.join("world-recipes.json"), &heldout)?;
    domain::write_public(heldout_dir.join("public.csv"), &heldout)?;
    domain::write_offers(heldout_dir.join("source-offers.csv"), &heldout, false)?;
    domain::write_offers(heldout_dir.join("current-offers.csv"), &heldout, true)?;

    let mut ordinary_plans = Vec::<BudgetPlan>::with_capacity(heldout.len() * 80);
    for bank in &heldout {
        let mut plans = routing::make_plans(
            bank.recipe.world_id,
            &bank.public,
            &bank.offers,
            bank.recipe.offer_request_cost_units,
            &models,
        );
        let fitted = plans
            .iter()
            .filter(|plan| {
                matches!(
                    plan.lane,
                    Lane::SimpleOffer | Lane::FittedOffer | Lane::ShuffledOffers
                )
            })
            .cloned()
            .collect::<Vec<_>>();
        for reference in fitted {
            let preview =
                routing::preview_route(&bank.public, &bank.current_offers, &reference, &models);
            plans.push(routing::make_matched_random_plan(
                bank.recipe.world_id,
                &bank.offers,
                &bank.current_offers,
                &reference,
                &preview.paid_queries,
                preview.offer_requests,
            ));
        }
        routing::validate_plans(&plans)?;
        ordinary_plans.extend(plans);
    }
    let ordinary_plan_path = planning_dir.join("frozen-router-plans.csv");
    routing::write_plans(&ordinary_plan_path, &ordinary_plans)?;
    let pre_outcome_hashes = [
        (
            "heldout/world-recipes.json",
            manifest::hash_file(&heldout_dir.join("world-recipes.json"))?,
        ),
        (
            "heldout/public.csv",
            manifest::hash_file(&heldout_dir.join("public.csv"))?,
        ),
        (
            "heldout/source-offers.csv",
            manifest::hash_file(&heldout_dir.join("source-offers.csv"))?,
        ),
        (
            "heldout/current-offers.csv",
            manifest::hash_file(&heldout_dir.join("current-offers.csv"))?,
        ),
        (
            "planning/frozen-router-plans.csv",
            manifest::hash_file(&ordinary_plan_path)?,
        ),
    ];
    fs::write(
        planning_dir.join("heldout-plan-seal.json"),
        serde_json::to_vec_pretty(&json!({
            "run_id": run_id,
            "ordinary_route_plans_frozen": true,
            "oracle_not_included": true,
            "labels_or_replies_used": false,
            "hashes": pre_outcome_hashes.iter().map(|(path, hash)| (*path, hash)).collect::<std::collections::BTreeMap<_,_>>(),
            "ordinary_plan_count": ordinary_plans.len(),
        }))?,
    )?;

    // Held-out outcome fixtures are committed only after the ordinary routes are sealed.
    domain::write_labels(heldout_dir.join("task-truth.csv"), &heldout)?;
    domain::write_source_fixture(heldout_dir.join("inspection-replies.csv"), &heldout)?;
    let outcome_hashes = json!({
        "task_truth_blake3": manifest::hash_file(&heldout_dir.join("task-truth.csv"))?,
        "inspection_replies_blake3": manifest::hash_file(&heldout_dir.join("inspection-replies.csv"))?,
        "written_after_router_plan_seal": true,
    });
    fs::write(
        planning_dir.join("heldout-outcome-seal.json"),
        serde_json::to_vec_pretty(&outcome_hashes)?,
    )?;

    let (audit_rows, audit_observations) = evaluation::input_audit(&heldout, "heldout-input-audit");
    let deterministic_groups = audit_rows
        .iter()
        .filter(|row| row.support >= 8 && row.support == row.largest_class)
        .count();
    evaluation::write_input_audit(run_dir.join("input-audit.csv"), &audit_rows)?;
    // Preserve the audit finding and frozen held-out bank; never alter labels or
    // offers to make a finite-sample collision disappear.

    // The evaluation-only oracle is built after the ordinary route plan file is frozen.
    let mut oracle_plans =
        Vec::with_capacity(heldout.len() * routing::LAMBDAS.len() * routing::BUDGETS.len());
    for bank in &heldout {
        oracle_plans.extend(evaluation::oracle_plans(bank, &routing::LAMBDAS));
    }
    let oracle_path = planning_dir.join("evaluation-oracle-plans.csv");
    routing::write_plans(&oracle_path, &oracle_plans)?;

    let total_plans = ordinary_plans.len() + oracle_plans.len();
    let mut traces = Vec::with_capacity(total_plans * 48);
    let mut groups = Vec::with_capacity(total_plans);
    for (plan_index, plan) in ordinary_plans.iter().chain(&oracle_plans).enumerate() {
        let bank = heldout
            .iter()
            .find(|bank| bank.recipe.world_id == plan.world_id)
            .ok_or("plan world not found")?;
        let (mut plan_traces, group, _calls) =
            runtime::run_plan(bank, plan, &receipt_dir, run_nonce, &models)?;
        traces.append(&mut plan_traces);
        groups.push(group);
        if (plan_index + 1) % 64 == 0 {
            eprintln!(
                "E008 run progress: {}/{} world-plan lanes",
                plan_index + 1,
                total_plans
            );
        }
    }
    for index in 0..groups.len() {
        let reference_lane = match groups[index].lane.as_str() {
            "matched_random_offer_simple" => Lane::SimpleOffer,
            "matched_random_offer_fitted" => Lane::FittedOffer,
            "matched_random_shuffled_offers" => Lane::ShuffledOffers,
            _ => continue,
        };
        let Some(reference_paid) = groups
            .iter()
            .find(|group| {
                group.world_id == groups[index].world_id
                    && group.lane == reference_lane.label()
                    && group.budget == groups[index].budget
                    && group.lambda == groups[index].lambda
                    && group.offer_mode == groups[index].offer_mode
            })
            .map(|reference| reference.paid_queries)
        else {
            continue;
        };
        groups[index].random_call_residual =
            groups[index].paid_queries as i32 - reference_paid as i32;
    }
    runtime::write_traces(run_dir.join("run-trace.csv"), &traces)?;
    runtime::write_group_stats(run_dir.join("group-stats.csv"), &groups)?;
    let crash_dir = run_dir.join("crash-recovery");
    let crashes = runtime::crash_recovery(&crash_dir)?;
    report::write_outputs(
        &run_dir,
        &heldout,
        &traces,
        &groups,
        &crashes,
        audit_observations,
        deterministic_groups,
    )?;
    manifest::seal(
        &project_root,
        &contracts_root,
        &run_dir,
        &run_id,
        run_nonce,
        &e007_provenance,
        deterministic_groups,
    )?;
    verify_artifact_seal(&run_dir)?;
    let final_e007_manifest = manifest::hash_file(&PathBuf::from(
        r"C:\rd-c\experiment-007\artifacts\runs\e007-1790316330677261600\manifest.json",
    ))?;
    if e007_provenance["run_manifest_blake3"].as_str() != Some(final_e007_manifest.as_str()) {
        return Err("sealed E007 manifest changed during E008".into());
    }
    println!(
        "E008 completed: {} held-out worlds, {} plans, {} selected-query traces, {} injected crash boundaries.",
        heldout.len(),
        groups.len(),
        traces.len(),
        crashes.len()
    );
    println!("Report: {}", run_dir.join("benchmark-report.md").display());
    println!("Manifest: {}", run_dir.join("manifest.json").display());
    Ok(())
}

fn verify_artifact_seal(run_dir: &std::path::Path) -> Result<(), Box<dyn std::error::Error>> {
    let manifest: serde_json::Value =
        serde_json::from_slice(&fs::read(run_dir.join("manifest.json"))?)?;
    let artifacts = manifest["artifacts_blake3"]
        .as_object()
        .ok_or("artifact hash table missing")?;
    for (relative, expected) in artifacts {
        let actual = manifest::hash_file(&run_dir.join(relative))?;
        if expected.as_str() != Some(actual.as_str()) {
            return Err(format!("artifact hash mismatch: {relative}").into());
        }
    }
    Ok(())
}
