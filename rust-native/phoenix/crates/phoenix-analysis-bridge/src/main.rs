mod analysis;
mod identity;
mod ner;
mod nli;

use anyhow::{bail, Context, Result};
use phoenix_analysis_contract::{
    open_message, write_analysis_artifact_new, write_producer_coordinator_new,
    write_structural_artifact_new, PhoenixAnalysisRequestV1,
};
use std::env;
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};

fn main() -> Result<()> {
    let mut arguments = env::args_os().skip(1);
    let command = arguments
        .next()
        .and_then(|value| value.into_string().ok())
        .context("missing command")?;
    if command == "serve" {
        let ner_root = path(&mut arguments, "Dynamic NER model root")?;
        let nli_root = path(&mut arguments, "NLI model root")?;
        if arguments.next().is_some() {
            bail!("unexpected extra argument");
        }
        return serve(&ner_root, &nli_root);
    }
    if command != "analyze" {
        bail!("unknown command {command:?}; expected analyze or serve");
    }
    let request_path = path(&mut arguments, "request artifact")?;
    let output_path = path(&mut arguments, "output artifact")?;
    let structural_path = arguments.next().map(PathBuf::from);
    let coordinator_path = arguments.next().map(PathBuf::from);
    if arguments.next().is_some() {
        bail!("unexpected extra argument");
    }
    let (_mapping, _hash, request) = open_request(&request_path)?;
    let output = analysis::analyze(&request).context("run native analysis")?;
    let hashes = publish(
        &output,
        &output_path,
        structural_path.as_deref(),
        coordinator_path.as_deref(),
    )?;
    print_publication(&output, &output_path, &hashes, None)?;
    Ok(())
}

fn serve(ner_root: &Path, nli_root: &Path) -> Result<()> {
    let runtime = analysis::LoadedAnalysisRuntime::load(ner_root, nli_root)
        .context("warm resident analysis models")?;
    control_line(&format!(
        "READY\t{}\t{}\t{}\t{}\t{}\t{}",
        std::process::id(),
        runtime.ner_load_micros,
        runtime.nli_load_micros,
        runtime.total_load_micros,
        u8::from(runtime.ner_cache_hit),
        u8::from(runtime.nli_cache_hit),
    ))?;
    let stdin = io::stdin();
    let mut line = String::with_capacity(1_024);
    loop {
        line.clear();
        if stdin.lock().read_line(&mut line)? == 0 {
            break;
        }
        let fields = line
            .trim_end_matches(['\r', '\n'])
            .split('\t')
            .collect::<Vec<_>>();
        match fields.as_slice() {
            ["SHUTDOWN"] => {
                control_line("BYE")?;
                break;
            }
            ["ANALYZE", request, output, structural, coordinator] => {
                let started = std::time::Instant::now();
                let result = (|| {
                    let request_path = PathBuf::from(request);
                    let output_path = PathBuf::from(output);
                    let structural_path = PathBuf::from(structural);
                    let coordinator_path = PathBuf::from(coordinator);
                    let (_mapping, _hash, request) = open_request(&request_path)?;
                    let output = runtime
                        .analyze(&request)
                        .context("run resident native analysis")?;
                    let hashes = publish(
                        &output,
                        &output_path,
                        Some(&structural_path),
                        Some(&coordinator_path),
                    )?;
                    print_publication(
                        &output,
                        &output_path,
                        &hashes,
                        Some(elapsed_micros(started)),
                    )
                })();
                match result {
                    Ok(()) => control_line("DONE")?,
                    Err(error) => {
                        let detail = format!("{error:#}").replace(['\r', '\n', '\t'], " ");
                        control_line(&format!("ERROR\t{detail}"))?;
                    }
                }
            }
            _ => control_line("ERROR\tmalformed control command")?,
        }
    }
    Ok(())
}

fn open_request(
    path: &Path,
) -> Result<(
    std::sync::Arc<memmap2::Mmap>,
    [u8; 32],
    PhoenixAnalysisRequestV1,
)> {
    let opened =
        open_message::<PhoenixAnalysisRequestV1>(path).context("open verified analysis request")?;
    opened.2.validate().map_err(anyhow::Error::msg)?;
    Ok(opened)
}

fn publish(
    output: &analysis::AnalysisOutput,
    output_path: &Path,
    structural_path: Option<&Path>,
    coordinator_path: Option<&Path>,
) -> Result<PublicationHashes> {
    let artifact_hash = write_analysis_artifact_new(output_path, &output.analysis)
        .context("seal analysis artifact")?;
    let structural_hash = structural_path
        .as_ref()
        .map(|path| write_structural_artifact_new(path, &output.structural))
        .transpose()
        .context("seal exact structural substrate")?;
    let coordinator_hash = coordinator_path
        .as_ref()
        .map(|path| write_producer_coordinator_new(path, &output.coordinator))
        .transpose()
        .context("seal semantic producer coordinator")?;
    Ok(PublicationHashes {
        artifact: artifact_hash,
        structural: structural_hash,
        coordinator: coordinator_hash,
    })
}

struct PublicationHashes {
    artifact: [u8; 32],
    structural: Option<[u8; 32]>,
    coordinator: Option<[u8; 32]>,
}

fn print_publication(
    output: &analysis::AnalysisOutput,
    output_path: &Path,
    hashes: &PublicationHashes,
    resident_total_micros: Option<u64>,
) -> Result<()> {
    let receipt = &output.analysis.ner.receipt;
    eprintln!(
        "PHOENIX_ANALYSIS_PUBLISHED path={} hash={} structural_hash={} coordinator_hash={} chunks={} entities={} mentions={} nli={} chunker_micros={} dynamic_ner_micros={} nli_load_micros={} nli_adjudication_micros={}",
        clean(output_path),
        hex(&hashes.artifact),
        hashes.structural.as_ref().map_or_else(|| "none".into(), |hash| hex(hash)),
        hashes.coordinator.as_ref().map_or_else(|| "none".into(), |hash| hex(hash)),
        output.structural.chunks.len(),
        output.analysis.ner.entities.len(),
        output.analysis.ner.mentions.len(),
        output.analysis.nli.nli_adjudications.len(),
        receipt.chunker_micros,
        receipt.dynamic_ner_micros,
        receipt.nli_load_micros,
        receipt.nli_adjudication_micros,
    );
    if let Some(micros) = resident_total_micros {
        eprintln!("PHOENIX_ANALYSIS_RESIDENT_RUN total_micros={micros}");
    }
    Ok(())
}

fn control_line(line: &str) -> Result<()> {
    let mut stdout = io::stdout().lock();
    stdout.write_all(b"PHOENIX_CONTROL\t")?;
    stdout.write_all(line.as_bytes())?;
    stdout.write_all(b"\n")?;
    stdout.flush()?;
    Ok(())
}

fn elapsed_micros(started: std::time::Instant) -> u64 {
    started.elapsed().as_micros().try_into().unwrap_or(u64::MAX)
}

fn path(arguments: &mut impl Iterator<Item = std::ffi::OsString>, name: &str) -> Result<PathBuf> {
    arguments
        .next()
        .map(PathBuf::from)
        .with_context(|| format!("missing {name}"))
}

fn clean(path: &Path) -> String {
    path.display().to_string().replace(['\r', '\n', '\t'], " ")
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        output.push(DIGITS[usize::from(byte >> 4)] as char);
        output.push(DIGITS[usize::from(byte & 0x0f)] as char);
    }
    output
}
