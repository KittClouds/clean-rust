use std::{fs, path::PathBuf};

use rdc_experiment_007::{
    domain::{self, WorldBank},
    evaluation::oracle_plans,
    manifest,
    model::FrozenModels,
    report,
    routing::{self, BudgetPlan},
    runtime,
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let contracts_root = project_root.join("../rdc-runtime-contracts-v1");
    let (run_id, run_dir) = manifest::new_run_dir(&project_root)?;
    let e006_provenance = manifest::copy_e006_provenance(&run_dir)?;
    let dev_dir = run_dir.join("inputs/development");
    let heldout_dir = run_dir.join("inputs/heldout");
    let planning_dir = run_dir.join("planning");
    let query_dir = run_dir.join("query-receipts");
    fs::create_dir_all(&dev_dir)?;
    fs::create_dir_all(&heldout_dir)?;
    fs::create_dir_all(&planning_dir)?;
    fs::create_dir_all(&query_dir)?;

    // Fit and freeze all estimators before the held-out banks are constructed.
    let development = domain::development_banks();
    domain::write_world_recipes(dev_dir.join("world-recipes.json"), &development)?;
    domain::write_public(dev_dir.join("public.csv"), &development)?;
    domain::write_source_fixture(dev_dir.join("source-state.csv"), &development)?;
    domain::write_labels(dev_dir.join("labels.csv"), &development)?;
    let models = FrozenModels::fit(&development)?;
    models.write_csv(dev_dir.join("frozen-models.csv"))?;

    // Holdout routes accept only the public slice. Labels and source replies stay separate.
    let heldout = domain::heldout_banks();
    domain::write_world_recipes(heldout_dir.join("world-recipes.json"), &heldout)?;
    domain::write_public(heldout_dir.join("public.csv"), &heldout)?;
    let mut ordinary_plans = Vec::<BudgetPlan>::with_capacity(208);
    for bank in &heldout {
        ordinary_plans.extend(routing::make_plans(
            bank.recipe.world_id,
            &bank.public,
            &models,
        )?);
    }
    routing::write_plans(
        planning_dir.join("frozen-router-plans.csv"),
        &ordinary_plans,
    )?;

    // Only after every ordinary route plan is durably written are held-out outcomes sealed.
    domain::write_source_fixture(heldout_dir.join("source-state.csv"), &heldout)?;
    domain::write_labels(heldout_dir.join("labels.csv"), &heldout)?;
    let mut oracle_plans_all = Vec::<BudgetPlan>::with_capacity(48);
    for bank in &heldout {
        oracle_plans_all.extend(oracle_plans(bank)?);
    }
    routing::write_plans(
        planning_dir.join("evaluation-oracle-plans.csv"),
        &oracle_plans_all,
    )?;

    let mut traces = Vec::with_capacity(
        heldout.len() * 16 * domain::HELDOUT_DOMAINS * domain::EPISODES_PER_DOMAIN,
    );
    let mut groups = Vec::with_capacity(heldout.len() * 16);
    for bank in &heldout {
        for plan in ordinary_plans
            .iter()
            .filter(|plan| plan.world_id == bank.recipe.world_id)
        {
            let (mut rows, group) = runtime::run_plan(bank, plan, &query_dir, runtime::RUN_SEED)?;
            traces.append(&mut rows);
            groups.push(group);
        }
        for plan in oracle_plans_all
            .iter()
            .filter(|plan| plan.world_id == bank.recipe.world_id)
        {
            let (mut rows, group) = runtime::run_plan(bank, plan, &query_dir, runtime::RUN_SEED)?;
            traces.append(&mut rows);
            groups.push(group);
        }
    }
    runtime::write_traces(run_dir.join("run-trace.csv"), &traces)?;
    runtime::write_group_stats(run_dir.join("group-stats.csv"), &groups)?;
    let crashes = runtime::crash_recovery(&run_dir.join("crash-recovery"))?;
    report::write_outputs(&run_dir, &heldout, &traces, &groups, &crashes)?;
    fs::copy(
        run_dir.join("benchmark-report.md"),
        project_root.join("artifacts/benchmark-report.md"),
    )?;
    manifest::seal(
        &project_root,
        &contracts_root,
        &run_dir,
        &run_id,
        &e006_provenance,
    )?;
    println!(
        "E007 completed {} held-out worlds, {} episode traces, and {} crash injections.",
        heldout.len(),
        traces.len(),
        crashes.len()
    );
    println!("Report: {}", run_dir.join("benchmark-report.md").display());
    Ok(())
}

#[allow(dead_code)]
fn _bank_type_boundary(_: &[WorldBank]) {}
