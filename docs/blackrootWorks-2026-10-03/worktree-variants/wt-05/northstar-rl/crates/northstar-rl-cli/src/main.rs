use std::{env, path::PathBuf, process::ExitCode};

use northstar_rl_core::{
    Environment, MappedRunRawTape, ScriptedPolicy, benchmark, materialize_lab, qualify,
    run_scripted, seal_artifacts, write_json,
};

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("northstar-rl: {error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> northstar_rl_core::Result<()> {
    let arguments = env::args_os().skip(1).collect::<Vec<_>>();
    let command = arguments
        .first()
        .and_then(|value| value.to_str())
        .unwrap_or("help");
    let path = arguments.get(1).map(PathBuf::from);
    match command {
        "tape-inspect" => {
            let path = required(path, "RunRaw tape path")?;
            let tape = MappedRunRawTape::open(path)?;
            println!("{}", serde_json::to_string_pretty(tape.header())?);
        }
        "feature-compile" | "episode-build" => {
            let output = required(path, "output directory")?;
            let lab = materialize_lab(&output)?;
            println!(
                "{}",
                serde_json::to_string_pretty(&lab.config.environment_spec)?
            );
        }
        "env-verify" => {
            let output = required(path, "artifact directory")?;
            let config = output.join("environment_config.json");
            if !config.exists() {
                materialize_lab(&output)?;
            }
            for policy in [
                ScriptedPolicy::AlwaysFlat,
                ScriptedPolicy::AlwaysFullPositive,
                ScriptedPolicy::AlwaysFullNegative,
                ScriptedPolicy::AlternateExtremes,
                ScriptedPolicy::FixedActionSequence(vec![
                    0.0, 0.25, 0.5, 1.0, 0.0, -0.5, -1.0, 0.0, 0.5, 0.0, 0.0, 0.0,
                ]),
                ScriptedPolicy::SeededRandomActions,
            ] {
                let mut environment = Environment::open(&config)?;
                let receipt = run_scripted(&mut environment, None, 42, policy)?;
                println!("{}", serde_json::to_string(&receipt)?);
            }
        }
        "replay" => {
            let output = required(path, "artifact directory")?;
            let config = output.join("environment_config.json");
            if !config.exists() {
                materialize_lab(&output)?;
            }
            let mut environment = Environment::open(config)?;
            let receipt = run_scripted(
                &mut environment,
                None,
                42,
                ScriptedPolicy::AlternateExtremes,
            )?;
            write_json(output.join("replay_receipt.json"), &receipt)?;
            println!("{}", serde_json::to_string_pretty(&receipt)?);
        }
        "benchmark" => {
            let output = required(path, "artifact directory")?;
            let config = output.join("environment_config.json");
            if !config.exists() {
                materialize_lab(&output)?;
            }
            let report = benchmark(config)?;
            write_json(output.join("performance_report.json"), &report)?;
            println!("{}", serde_json::to_string_pretty(&report)?);
        }
        "qualify" => {
            let output = required(path, "artifact directory")?;
            let receipt = qualify(output)?;
            println!("environment_id={}", receipt.environment_id);
            println!("trajectory_root={}", receipt.trajectory_root);
            println!("surface_root={}", receipt.surface_root);
        }
        "seal" => {
            let output = required(path, "artifact directory")?;
            let manifest = seal_artifacts(output)?;
            println!("{}", manifest.root_identity);
        }
        "joint-qualify" => {
            let output = required(path, "joint artifact directory")?;
            let live_path = output.join("live_read_receipt.json");
            let live = live_path
                .exists()
                .then(|| {
                    northstar_rl_core::read_json::<northstar_rl_broker::LiveReadReceipt>(&live_path)
                })
                .transpose()?;
            let receipt = northstar_rl_broker::qualify_joint(&output, live)
                .map_err(|error| northstar_rl_core::Error::InvalidContract(error.to_string()))?;
            println!("fixture_root={}", receipt.fixture_root);
            println!("surface_root={}", receipt.surface_root);
        }
        "campaign-qualify" => {
            let output = required(path, "campaign artifact directory")?;
            let receipt = northstar_rl_campaign::qualify_campaign(&output)
                .map_err(|error| northstar_rl_core::Error::InvalidContract(error.to_string()))?;
            println!("campaign_id={}", receipt.campaign_id);
            println!("experiment_id={}", receipt.experiment_id);
            println!("surface_root={}", receipt.surface_root);
        }
        "broker" => broker(&arguments)?,
        "help" | "--help" | "-h" => print_help(),
        _ => {
            return Err(northstar_rl_core::Error::InvalidContract(format!(
                "unknown command {command}"
            )));
        }
    }
    Ok(())
}

fn required(path: Option<PathBuf>, name: &str) -> northstar_rl_core::Result<PathBuf> {
    path.ok_or_else(|| northstar_rl_core::Error::InvalidContract(format!("missing {name}")))
}

fn print_help() {
    println!("northstar-rl tape-inspect <runraw.nrr1>");
    println!("northstar-rl feature-compile <output-dir>");
    println!("northstar-rl episode-build <output-dir>");
    println!("northstar-rl env-verify <artifact-dir>");
    println!("northstar-rl replay <artifact-dir>");
    println!("northstar-rl benchmark <artifact-dir>");
    println!("northstar-rl qualify <artifact-dir>");
    println!("northstar-rl seal <artifact-dir>");
    println!("northstar-rl joint-qualify <artifact-dir>");
    println!("northstar-rl campaign-qualify <artifact-dir>");
    println!("northstar-rl broker status tradelocker");
    println!("northstar-rl broker capture-live <artifact-dir>");
    println!("northstar-rl broker instruments tradelocker");
    println!("northstar-rl broker snapshot tradelocker");
    println!("northstar-rl broker compare <northstar-instrument-id>");
}

fn broker(arguments: &[std::ffi::OsString]) -> northstar_rl_core::Result<()> {
    let subcommand = arguments
        .get(1)
        .and_then(|value| value.to_str())
        .unwrap_or("help");
    match subcommand {
        "status" => {
            let diagnostic = northstar_rl_broker::credential_probe("LIVE");
            println!("{}", serde_json::to_string_pretty(&diagnostic)?);
        }
        "capture-live" => {
            let output = arguments.get(2).map(PathBuf::from).ok_or_else(|| {
                northstar_rl_core::Error::InvalidContract("missing artifact directory".into())
            })?;
            let receipt = northstar_rl_broker::capture_live_read_only()
                .map_err(|error| northstar_rl_core::Error::InvalidContract(error.to_string()))?;
            northstar_rl_core::write_json(output.join("live_read_receipt.json"), &receipt)?;
            northstar_rl_broker::seal_broker_capture(
                output.join("live_tradelocker_capture.nsb1"),
                &receipt.quote_tape,
            )
            .map_err(|error| northstar_rl_core::Error::InvalidContract(error.to_string()))?;
            println!("{}", serde_json::to_string_pretty(&receipt.diagnostic)?);
            println!("instrument_count={}", receipt.registry.instruments.len());
            println!("quote_count={}", receipt.quote_tape.rows.len());
            println!("position_count={}", receipt.positions.len());
            println!("receipt_id={}", receipt.receipt_id);
        }
        "instruments" => {
            let receipt = northstar_rl_broker::capture_live_read_only()
                .map_err(|error| northstar_rl_core::Error::InvalidContract(error.to_string()))?;
            println!("{}", serde_json::to_string_pretty(&receipt.registry)?);
        }
        "snapshot" => {
            let receipt = northstar_rl_broker::capture_live_read_only()
                .map_err(|error| northstar_rl_core::Error::InvalidContract(error.to_string()))?;
            println!(
                "{}",
                serde_json::to_string_pretty(&serde_json::json!({
                    "diagnostic": receipt.diagnostic, "account": receipt.account, "positions": receipt.positions
                }))?
            );
        }
        "compare" => {
            let id = arguments
                .get(2)
                .and_then(|value| value.to_str())
                .and_then(|value| value.parse::<u32>().ok())
                .ok_or_else(|| {
                    northstar_rl_core::Error::InvalidContract(
                        "missing northstar instrument ID".into(),
                    )
                })?;
            let fixture = northstar_rl_broker::joint_fixture()
                .map_err(|error| northstar_rl_core::Error::InvalidContract(error.to_string()))?;
            let comparisons = fixture
                .price_comparisons
                .into_iter()
                .filter(|row| row.northstar_instrument_id == id)
                .collect::<Vec<_>>();
            println!("source_class={}", fixture.source_class);
            println!("{}", serde_json::to_string_pretty(&comparisons)?);
        }
        _ => {
            return Err(northstar_rl_core::Error::InvalidContract(format!(
                "unknown broker command {subcommand}"
            )));
        }
    }
    Ok(())
}
