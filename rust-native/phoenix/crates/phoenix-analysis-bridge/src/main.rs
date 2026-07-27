mod analysis;
mod identity;
mod ner;
mod nli;

use anyhow::{bail, Context, Result};
use phoenix_analysis_contract::{
    open_message, write_analysis_artifact_new, PhoenixAnalysisRequestV1,
};
use std::env;
use std::path::{Path, PathBuf};

fn main() -> Result<()> {
    let mut arguments = env::args_os().skip(1);
    let command = arguments
        .next()
        .and_then(|value| value.into_string().ok())
        .context("missing command")?;
    if command != "analyze" {
        bail!("unknown command {command:?}; expected analyze");
    }
    let request_path = path(&mut arguments, "request artifact")?;
    let output_path = path(&mut arguments, "output artifact")?;
    if arguments.next().is_some() {
        bail!("unexpected extra argument");
    }
    let (_mapping, _hash, request) = open_message::<PhoenixAnalysisRequestV1>(&request_path)
        .context("open verified analysis request")?;
    request.validate().map_err(anyhow::Error::msg)?;
    let artifact = analysis::analyze(&request).context("run legacy native analysis")?;
    let artifact_hash =
        write_analysis_artifact_new(&output_path, &artifact).context("seal analysis artifact")?;
    println!(
        "PHOENIX_ANALYSIS_PUBLISHED path={} hash={} entities={} mentions={} nli={}",
        clean(&output_path),
        hex(&artifact_hash),
        artifact.ner.entities.len(),
        artifact.ner.mentions.len(),
        artifact.nli.nli_adjudications.len()
    );
    Ok(())
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
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}
