use obs_open_disc02e::AnyResult;
use obs_open_disc02e::authority::{AuthorityPaths, load};
use obs_open_disc02e::corpus::{CorpusCensus, reconstruct};
use obs_open_disc02e::output::{
    artifact_members, compare_artifacts, publish_compact_seal, seal, write_products,
    write_rebuild_receipt,
};
use obs_open_disc02e::stats::{FormalFamilyResult, analyze};
use obs_open_disc02p::{canonical_json_bytes, sha256_file};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

#[derive(Debug)]
struct Args {
    repo: PathBuf,
    raw: PathBuf,
    out_a: PathBuf,
    out_b: PathBuf,
    compact_seal: PathBuf,
    threads_a: usize,
    threads_b: usize,
}

#[derive(Debug, Clone, Serialize)]
struct RunSummary {
    census: CorpusCensus,
    formal_results: Vec<FormalFamilyResult>,
}

#[derive(Debug, Serialize)]
struct FinalSummary {
    schema: &'static str,
    status: &'static str,
    disc02e_root: String,
    execution_code_sha256: String,
    artifact_count: usize,
    physical_artifact_set_sha256: String,
    deterministic_mismatch_count: usize,
    discovery_sessions: usize,
    confirmation_sessions_read: usize,
    confirmation_observations_read: usize,
    census: CorpusCensus,
    formal_results: Vec<FormalFamilyResult>,
    promoted_candidate_count: usize,
    prospective_confirmation_contract_count: usize,
    bulk_payload: String,
    compact_seal: String,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("DISC02E_FAIL:{error}");
        std::process::exit(1);
    }
}

fn run() -> AnyResult<()> {
    let args = parse_args()?;
    let code_hash = execution_code_hash(&args.repo)?;
    let first = run_build(
        &args.repo,
        &args.raw,
        &args.out_a,
        args.threads_a,
        &code_hash,
    )?;
    let first_members = artifact_members(&args.out_a, &[])?;
    let second = run_build(
        &args.repo,
        &args.raw,
        &args.out_b,
        args.threads_b,
        &code_hash,
    )?;
    let second_members = artifact_members(&args.out_b, &[])?;
    let preseal_mismatches = compare_artifacts(&first_members, &second_members);
    if !preseal_mismatches.is_empty() {
        return Err(format!("PRESEAL_BYTE_MISMATCH:{preseal_mismatches:?}").into());
    }
    if canonical_json_bytes(&first)? != canonical_json_bytes(&second)? {
        return Err("RUN_SUMMARY_MISMATCH".into());
    }
    let preseal_hash_a = write_rebuild_receipt(&args.out_a, &first_members)?;
    let preseal_hash_b = write_rebuild_receipt(&args.out_b, &second_members)?;
    if preseal_hash_a != preseal_hash_b {
        return Err("PRESEAL_ARTIFACT_SET_HASH_MISMATCH".into());
    }
    let seal_a = seal(&args.out_a, &code_hash)?;
    let seal_b = seal(&args.out_b, &code_hash)?;
    if seal_a.root != seal_b.root {
        return Err(format!("DISC02E_ROOT_MISMATCH:{}:{}", seal_a.root, seal_b.root).into());
    }
    let final_a = artifact_members(&args.out_a, &[])?;
    let final_b = artifact_members(&args.out_b, &[])?;
    let final_mismatches = compare_artifacts(&final_a, &final_b);
    if !final_mismatches.is_empty() {
        return Err(format!("FINAL_BYTE_MISMATCH:{final_mismatches:?}").into());
    }
    publish_compact_seal(&args.out_a, &args.compact_seal)?;
    let promoted = first
        .formal_results
        .iter()
        .filter(|result| result.terminal_state == "PROMOTED_DISCOVERY_ONLY")
        .count();
    let summary = FinalSummary {
        schema: "OBS_OPEN_DISC02E_FINAL_SUMMARY_V1",
        status: "PASS",
        disc02e_root: seal_a.root,
        execution_code_sha256: code_hash,
        artifact_count: seal_a.artifact_count,
        physical_artifact_set_sha256: seal_a.artifact_set_hash,
        deterministic_mismatch_count: 0,
        discovery_sessions: first.census.sessions,
        confirmation_sessions_read: 0,
        confirmation_observations_read: 0,
        census: first.census,
        formal_results: first.formal_results,
        promoted_candidate_count: promoted,
        prospective_confirmation_contract_count: promoted,
        bulk_payload: args.out_a.to_string_lossy().into_owned(),
        compact_seal: args.compact_seal.to_string_lossy().into_owned(),
    };
    print!("{}", String::from_utf8(canonical_json_bytes(&summary)?)?);
    Ok(())
}

fn run_build(
    repo: &Path,
    raw: &Path,
    out: &Path,
    threads: usize,
    code_hash: &str,
) -> AnyResult<RunSummary> {
    let loaded = load(&AuthorityPaths::new(repo, raw))?;
    let parent = loaded.parent.clone();
    let access = loaded.access.clone();
    let corpus = reconstruct(loaded)?;
    if corpus.census.sessions != obs_open_disc02e::DISCOVERY_SESSIONS {
        return Err("DISCOVERY_CORPUS_ADMISSION_FAILURE".into());
    }
    let analysis = analyze(&corpus, threads)?;
    write_products(out, &parent, &access, &corpus, &analysis, code_hash)?;
    Ok(RunSummary {
        census: corpus.census.clone(),
        formal_results: analysis.results.clone(),
    })
}

fn parse_args() -> AnyResult<Args> {
    let mut repo = None;
    let mut raw = None;
    let mut out_a = None;
    let mut out_b = None;
    let mut compact_seal = None;
    let mut threads_a = 1usize;
    let mut threads_b = 4usize;
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        let value = args.next().ok_or_else(|| format!("MISSING_VALUE:{flag}"))?;
        match flag.as_str() {
            "--repo" => repo = Some(PathBuf::from(value)),
            "--raw" => raw = Some(PathBuf::from(value)),
            "--out-a" => out_a = Some(PathBuf::from(value)),
            "--out-b" => out_b = Some(PathBuf::from(value)),
            "--compact-seal" => compact_seal = Some(PathBuf::from(value)),
            "--threads-a" => threads_a = value.parse()?,
            "--threads-b" => threads_b = value.parse()?,
            _ => return Err(format!("UNKNOWN_ARGUMENT:{flag}").into()),
        }
    }
    Ok(Args {
        repo: repo.ok_or("--repo required")?,
        raw: raw.ok_or("--raw required")?,
        out_a: out_a.ok_or("--out-a required")?,
        out_b: out_b.ok_or("--out-b required")?,
        compact_seal: compact_seal.ok_or("--compact-seal required")?,
        threads_a,
        threads_b,
    })
}

fn execution_code_hash(repo: &Path) -> AnyResult<String> {
    let crate_root = repo.join("studies/obs-open-01/discovery-execution");
    let mut files = vec![crate_root.join("Cargo.toml"), crate_root.join("Cargo.lock")];
    for entry in std::fs::read_dir(crate_root.join("src"))? {
        let path = entry?.path();
        if path.extension().and_then(|value| value.to_str()) == Some("rs") {
            files.push(path);
        }
    }
    files.sort();
    let mut hash = Sha256::new();
    for path in files {
        let relative = path
            .strip_prefix(repo)?
            .to_string_lossy()
            .replace('\\', "/");
        hash.update(relative.as_bytes());
        hash.update([0]);
        hash.update(sha256_file(&path)?.as_bytes());
        hash.update([b'\n']);
    }
    Ok(format!("{:x}", hash.finalize()))
}
