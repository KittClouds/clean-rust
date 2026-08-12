use std::{env, ffi::OsStr, fs, path::PathBuf, process::ExitCode, time::Instant};

use northstar_auction_replay::{ResearchInterfaceVerifier, verify_golden_grammar};
use northstar_mt5_corpus::CorpusVerifier;
use northstar_parity_fixtures::verify_fixtures;
use serde::Serialize;

#[derive(Serialize)]
struct CorpusParityReceipt<'a> {
    contract: &'static str,
    status: &'static str,
    source: &'static str,
    report: &'a northstar_mt5_corpus::CorpusReport,
}

#[derive(Serialize)]
struct GoldenParityReceipt {
    contract: &'static str,
    status: &'static str,
    fixtures: northstar_parity_fixtures::FixtureReport,
    grammar: northstar_auction_replay::GoldenGrammarReport,
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("PARITY_FAIL {error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args_os();
    let binary = args.next().unwrap_or_default();
    let command = args.next().ok_or_else(|| usage(&binary))?;
    let pairs = parse_pairs(args)?;
    match command.to_str() {
        Some("verify") => verify_corpus(&pairs),
        Some("verify-interface") => verify_interface(&pairs),
        Some("verify-golden") => verify_golden(&pairs),
        _ => Err(usage(&binary)),
    }
}

fn verify_corpus(pairs: &[(String, PathBuf)]) -> Result<(), String> {
    let corpus = required(pairs, "--corpus")?;
    let seal = required(pairs, "--seal")?;
    let started = Instant::now();
    let report = CorpusVerifier::new(corpus, seal)
        .verify()
        .map_err(|error| error.to_string())?;
    if let Some(path) = optional(pairs, "--receipt") {
        let receipt = CorpusParityReceipt {
            contract: "NORTHSTAR_MT5_CORPUS_PARITY_V1",
            status: "PASS",
            source: "sealed_mt5_rg2",
            report: &report,
        };
        write_json(path, &receipt)?;
        println!("receipt={}", path.display());
    }
    println!("PARITY_PASS");
    println!("canonical_corpus_sha256={}", report.canonical_corpus_sha256);
    println!("runs={}", report.run_count);
    println!("sealed_files={}", report.sealed_file_count);
    println!("sealed_bytes={}", report.sealed_bytes);
    println!("events={}", report.datasets.events);
    println!("attempts={}", report.datasets.attempts);
    println!("episodes={}", report.datasets.episodes);
    println!("context={}", report.datasets.context);
    println!("features={}", report.datasets.features);
    println!("transits={}", report.datasets.transits);
    println!("elapsed_ms={}", started.elapsed().as_millis());
    for run in &report.runs {
        println!(
            "run={} instrument={} events={} attempts={} episodes={} transits={}",
            run.run_key,
            run.canonical_instrument,
            run.relational.counts.events,
            run.relational.counts.attempts,
            run.relational.counts.episodes,
            run.relational.counts.transits,
        );
    }
    Ok(())
}

fn verify_interface(pairs: &[(String, PathBuf)]) -> Result<(), String> {
    let workspace = required(pairs, "--workspace")?;
    let started = Instant::now();
    let report = ResearchInterfaceVerifier::new(workspace)
        .verify()
        .map_err(|error| error.to_string())?;
    if let Some(path) = optional(pairs, "--receipt") {
        write_json(path, &report)?;
        println!("receipt={}", path.display());
    }
    println!("INTERFACE_PARITY_PASS");
    println!("corpus_sha256={}", report.corpus_sha256);
    println!("analysis_code_sha256={}", report.analysis_code_sha256);
    println!("attempt_view={}", report.views.attempt_view);
    println!("attempt_chain_view={}", report.views.attempt_chain_view);
    println!(
        "episode_timeline_view={}",
        report.views.episode_timeline_view
    );
    println!("transit_view={}", report.views.transit_view);
    println!("node_context_view={}", report.views.node_context_view);
    for target in &report.targets {
        println!(
            "target={} eligible={} observed={} censored={}",
            target.target, target.eligible_count, target.observed_count, target.censored_count
        );
    }
    println!("elapsed_ms={}", started.elapsed().as_millis());
    Ok(())
}

fn verify_golden(pairs: &[(String, PathBuf)]) -> Result<(), String> {
    let fixtures = verify_fixtures().map_err(str::to_owned)?;
    let grammar = verify_golden_grammar()?;
    let report = GoldenParityReceipt {
        contract: "NORTHSTAR_MQL5_GOLDEN_PARITY_V1",
        status: "PASS",
        fixtures,
        grammar,
    };
    if let Some(path) = optional(pairs, "--receipt") {
        write_json(path, &report)?;
        println!("receipt={}", path.display());
    }
    println!("GOLDEN_PARITY_PASS");
    println!("scenarios={}", report.fixtures.scenarios);
    println!(
        "directional_certificates={}",
        report.fixtures.directional_certificates
    );
    println!("semantic_assertions={}", report.grammar.semantic_assertions);
    println!("boundary_assertions={}", report.grammar.boundary_assertions);
    Ok(())
}

fn parse_pairs(
    args: impl Iterator<Item = std::ffi::OsString>,
) -> Result<Vec<(String, PathBuf)>, String> {
    let mut args = args;
    let mut pairs = Vec::new();
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {}", flag.to_string_lossy()))?;
        let flag = flag
            .into_string()
            .map_err(|flag| format!("argument is not Unicode: {}", flag.to_string_lossy()))?;
        if !matches!(
            flag.as_str(),
            "--corpus" | "--seal" | "--workspace" | "--receipt"
        ) {
            return Err(format!("unknown argument {flag}"));
        }
        pairs.push((flag, value.into()));
    }
    Ok(pairs)
}

fn required(pairs: &[(String, PathBuf)], key: &str) -> Result<PathBuf, String> {
    optional(pairs, key)
        .cloned()
        .ok_or_else(|| format!("{key} is required"))
}

fn optional<'a>(pairs: &'a [(String, PathBuf)], key: &str) -> Option<&'a PathBuf> {
    pairs
        .iter()
        .find_map(|(name, value)| (name == key).then_some(value))
}

fn write_json(path: &PathBuf, value: &impl Serialize) -> Result<(), String> {
    let bytes = serde_json::to_vec_pretty(value).map_err(|error| error.to_string())?;
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::write(path, bytes).map_err(|error| error.to_string())
}

fn usage(binary: &OsStr) -> String {
    format!(
        "usage:\n  {} verify --corpus <runs> --seal <corpus_seal.json> [--receipt <json>]\n  {} verify-interface --workspace <eas> [--receipt <json>]\n  {} verify-golden [--receipt <json>]",
        binary.to_string_lossy(),
        binary.to_string_lossy(),
        binary.to_string_lossy()
    )
}
