use std::{
    fs::{self, File},
    path::{Path, PathBuf},
};

use hashbrown::HashMap;
use memmap2::MmapOptions;
use northstar_auction_contract::{AuctionResolution, CompletionStatus, NULL_TOKEN};
use northstar_mt5_corpus::{CorpusVerifier, MappedTsv, Row, parse_i16, parse_u64};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

const INTERFACE_SEAL_CONTRACT: &str = "MST_RG2_RESEARCH_INTERFACE_SEAL_V1";
const INTERFACE_VERSION: &str = "MST_RG2_RESEARCH_INTERFACE_V1_1";

#[derive(Debug, Error)]
pub enum InterfaceError {
    #[error("corpus verification failed: {0}")]
    Corpus(#[from] northstar_mt5_corpus::CorpusError),
    #[error("I/O failure at {path}: {source}")]
    Io {
        path: PathBuf,
        source: std::io::Error,
    },
    #[error("JSON failure at {path}: {source}")]
    Json {
        path: PathBuf,
        source: serde_json::Error,
    },
    #[error("Phase 10.5 interface contract failed: {0}")]
    Contract(String),
}

type Result<T> = std::result::Result<T, InterfaceError>;

#[derive(Clone, Copy, Debug, Default, Serialize)]
pub struct ViewCardinalities {
    pub attempt_view: u64,
    pub attempt_chain_view: u64,
    pub episode_timeline_view: u64,
    pub transit_view: u64,
    pub node_context_view: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TargetCount {
    pub target: String,
    pub eligible_count: u64,
    pub observed_count: u64,
    pub censored_count: u64,
}

#[derive(Debug, Serialize)]
pub struct InterfaceParityReport {
    pub contract: &'static str,
    pub status: &'static str,
    pub interface_version: &'static str,
    pub corpus_sha256: String,
    pub analysis_code_sha256: String,
    pub views: ViewCardinalities,
    pub targets: Vec<TargetCount>,
}

#[derive(Debug, Deserialize)]
struct InterfaceSeal {
    contract: String,
    status: String,
    corpus_sha256: String,
    interface_version: String,
    analysis_code_sha256: String,
    artifacts: HashMap<String, String>,
}

#[derive(Debug, Deserialize)]
struct RegistryCount {
    target: String,
    eligible_count: u64,
    observed_count: u64,
    censored_count: u64,
}

#[derive(Clone, Copy)]
struct Attempt {
    run: u32,
    episode: u64,
    is_retest: bool,
    has_contact: bool,
    has_break: bool,
    end: Option<u64>,
    resolution: AuctionResolution,
    completion: CompletionStatus,
}

#[derive(Clone, Copy)]
struct Episode {
    run: u32,
    id: u64,
    end: Option<u64>,
    resolution: AuctionResolution,
    completion: CompletionStatus,
}

#[derive(Clone, Copy)]
struct Transit {
    run: u32,
    episode: u64,
    start: Option<u64>,
    resolution: AuctionResolution,
}

pub struct ResearchInterfaceVerifier {
    workspace: PathBuf,
}

impl ResearchInterfaceVerifier {
    #[must_use]
    pub fn new(workspace: impl Into<PathBuf>) -> Self {
        Self {
            workspace: workspace.into(),
        }
    }

    pub fn verify(&self) -> Result<InterfaceParityReport> {
        let corpus = CorpusVerifier::new(
            self.workspace.join("furnace/corpus"),
            self.workspace.join("phase10/seal/corpus_seal.json"),
        )
        .verify()?;
        let interface_root = self.workspace.join("phase10_5");
        let output = interface_root.join("output");
        let seal_path = output.join("interface_seal.json");
        let seal: InterfaceSeal = read_json(&seal_path)?;
        if seal.contract != INTERFACE_SEAL_CONTRACT
            || seal.status != "PASS"
            || seal.interface_version != INTERFACE_VERSION
            || seal.corpus_sha256 != corpus.canonical_corpus_sha256
        {
            return Err(InterfaceError::Contract(
                "interface seal identity mismatch".into(),
            ));
        }
        for (relative, expected) in &seal.artifacts {
            let path = output.join(relative);
            if sha256_file(&path)? != *expected {
                return Err(InterfaceError::Contract(format!(
                    "sealed interface artifact mutated: {}",
                    path.display()
                )));
            }
        }
        let code_hash = interface_code_hash(&interface_root)?;
        if code_hash != seal.analysis_code_sha256 {
            return Err(InterfaceError::Contract(
                "analysis code hash mismatch".into(),
            ));
        }

        let mut attempts = Vec::with_capacity(corpus.datasets.attempts as usize);
        let mut episodes = Vec::with_capacity(corpus.datasets.episodes as usize);
        let mut transits = Vec::with_capacity(corpus.datasets.transits as usize);
        for (run_index, run) in corpus.runs.iter().enumerate() {
            let auction = self
                .workspace
                .join("furnace/corpus")
                .join(&run.run_key)
                .join("raw/auction");
            let run_index = u32::try_from(run_index)
                .map_err(|_| InterfaceError::Contract("too many runs".into()))?;
            attempts.extend(load_attempts(
                &dataset_path(&auction, "attempts")?,
                run_index,
            )?);
            episodes.extend(load_episodes(
                &dataset_path(&auction, "episodes")?,
                run_index,
            )?);
            transits.extend(load_transits(
                &dataset_path(&auction, "transits")?,
                run_index,
            )?);
        }
        let views = ViewCardinalities {
            attempt_view: attempts.len() as u64,
            attempt_chain_view: attempts.len() as u64,
            episode_timeline_view: corpus.datasets.events,
            transit_view: transits.len() as u64,
            node_context_view: corpus.datasets.context,
        };
        let targets = reconstruct_targets(&attempts, &episodes, &transits);
        let expected: Vec<RegistryCount> = read_json(&output.join("target_registry.json"))?;
        validate_target_registry(&targets, &expected)?;

        Ok(InterfaceParityReport {
            contract: "NORTHSTAR_PHASE10_5_PARITY_V1",
            status: "PASS",
            interface_version: INTERFACE_VERSION,
            corpus_sha256: corpus.canonical_corpus_sha256,
            analysis_code_sha256: code_hash,
            views,
            targets,
        })
    }
}

fn load_attempts(path: &Path, run: u32) -> Result<Vec<Attempt>> {
    let table = MappedTsv::open(path)?;
    let episode = table.column("episode_id")?;
    let is_retest = table.column("is_retest")?;
    let contact = table.column("contact")?;
    let break_time = table.column("break")?;
    let end = table.column("end")?;
    let resolution = table.column("resolution_code")?;
    let completion = table.column("completion_status_code")?;
    let mut output = Vec::new();
    for row in table.rows() {
        let row = row?;
        output.push(Attempt {
            run,
            episode: required_u64(row, episode, &table)?,
            is_retest: required_u64(row, is_retest, &table)? == 1,
            has_contact: !is_null(row, contact),
            has_break: !is_null(row, break_time),
            end: optional_u64(row, end),
            resolution: parse_resolution(row, resolution, &table)?,
            completion: parse_completion(row, completion, &table)?,
        });
    }
    Ok(output)
}

fn load_episodes(path: &Path, run: u32) -> Result<Vec<Episode>> {
    let table = MappedTsv::open(path)?;
    let id = table.column("episode_id")?;
    let end = table.column("end")?;
    let resolution = table.column("resolution_code")?;
    let completion = table.column("completion_status_code")?;
    let mut output = Vec::new();
    for row in table.rows() {
        let row = row?;
        output.push(Episode {
            run,
            id: required_u64(row, id, &table)?,
            end: optional_u64(row, end),
            resolution: parse_resolution(row, resolution, &table)?,
            completion: parse_completion(row, completion, &table)?,
        });
    }
    Ok(output)
}

fn load_transits(path: &Path, run: u32) -> Result<Vec<Transit>> {
    let table = MappedTsv::open(path)?;
    let episode = table.column("episode_id")?;
    let start = table.column("start")?;
    let resolution = table.column("resolution_code")?;
    let mut output = Vec::new();
    for row in table.rows() {
        let row = row?;
        output.push(Transit {
            run,
            episode: required_u64(row, episode, &table)?,
            start: optional_u64(row, start),
            resolution: parse_resolution(row, resolution, &table)?,
        });
    }
    Ok(output)
}

fn reconstruct_targets(
    attempts: &[Attempt],
    episodes: &[Episode],
    transits: &[Transit],
) -> Vec<TargetCount> {
    vec![
        count_attempt_target(
            "reclaim_given_break",
            attempts,
            |attempt| attempt.has_break,
            AuctionResolution::ReclaimAfterBreak,
        ),
        count_attempt_target(
            "initial_acceptance_given_initial_contact",
            attempts,
            |attempt| attempt.has_contact && !attempt.is_retest,
            AuctionResolution::AcceptThroughNode,
        ),
        count_attempt_target(
            "rejection_given_initial_contact",
            attempts,
            |attempt| attempt.has_contact && !attempt.is_retest,
            AuctionResolution::RejectToOrigin,
        ),
        count_attempt_target(
            "retest_hold_given_retest_contact",
            attempts,
            |attempt| attempt.has_contact && attempt.is_retest,
            AuctionResolution::AcceptAndHoldRetest,
        ),
        count_transit_target(attempts, episodes, transits),
    ]
}

fn count_attempt_target(
    target: &str,
    attempts: &[Attempt],
    eligible: impl Fn(&Attempt) -> bool,
    observed_resolution: AuctionResolution,
) -> TargetCount {
    let mut count = TargetCount {
        target: target.into(),
        eligible_count: 0,
        observed_count: 0,
        censored_count: 0,
    };
    for attempt in attempts.iter().filter(|attempt| eligible(attempt)) {
        count.eligible_count += 1;
        count.observed_count += u64::from(attempt.resolution == observed_resolution);
        count.censored_count += u64::from(is_behavior_censored(attempt));
    }
    count
}

fn count_transit_target(
    attempts: &[Attempt],
    episodes: &[Episode],
    transits: &[Transit],
) -> TargetCount {
    let mut first_acceptance = HashMap::<(u32, u64), u64>::new();
    for attempt in attempts.iter().filter(|attempt| {
        attempt.completion == CompletionStatus::Resolved
            && attempt.resolution == AuctionResolution::AcceptThroughNode
    }) {
        if let Some(end) = attempt.end {
            first_acceptance
                .entry((attempt.run, attempt.episode))
                .and_modify(|value| *value = (*value).min(end))
                .or_insert(end);
        }
    }
    let mut first_transit = HashMap::<(u32, u64), u64>::new();
    for transit in transits
        .iter()
        .filter(|transit| transit.resolution == AuctionResolution::TransitToNextNode)
    {
        if let Some(start) = transit.start {
            first_transit
                .entry((transit.run, transit.episode))
                .and_modify(|value| *value = (*value).min(start))
                .or_insert(start);
        }
    }
    let episode_map = episodes
        .iter()
        .map(|episode| ((episode.run, episode.id), *episode))
        .collect::<HashMap<_, _>>();
    let mut count = TargetCount {
        target: "transit_given_episode_acceptance".into(),
        eligible_count: first_acceptance.len() as u64,
        observed_count: 0,
        censored_count: 0,
    };
    for (&episode_key, &acceptance_end) in &first_acceptance {
        let observed = first_transit
            .get(&episode_key)
            .is_some_and(|start| *start >= acceptance_end);
        count.observed_count += u64::from(observed);
        let episode = episode_map[&episode_key];
        let censored = (episode.completion != CompletionStatus::Resolved
            || matches!(
                episode.resolution,
                AuctionResolution::NodeRetired
                    | AuctionResolution::Timeout
                    | AuctionResolution::None
            ))
            && !observed;
        let _terminal_time = episode.end;
        count.censored_count += u64::from(censored);
    }
    count
}

fn is_behavior_censored(attempt: &Attempt) -> bool {
    attempt.completion != CompletionStatus::Resolved
        || !matches!(
            attempt.resolution,
            AuctionResolution::RejectToOrigin
                | AuctionResolution::AcceptThroughNode
                | AuctionResolution::ReclaimAfterBreak
                | AuctionResolution::AcceptAndHoldRetest
                | AuctionResolution::AcceptAndFailRetest
        )
}

fn validate_target_registry(actual: &[TargetCount], expected: &[RegistryCount]) -> Result<()> {
    let expected = expected
        .iter()
        .map(|row| (row.target.as_str(), row))
        .collect::<HashMap<_, _>>();
    for row in actual {
        let Some(reference) = expected.get(row.target.as_str()) else {
            return Err(InterfaceError::Contract(format!(
                "target {} absent from registry",
                row.target
            )));
        };
        if row.eligible_count != reference.eligible_count
            || row.observed_count != reference.observed_count
            || row.censored_count != reference.censored_count
        {
            return Err(InterfaceError::Contract(format!(
                "target {} mismatch: Rust {}/{}/{}, Python {}/{}/{}",
                row.target,
                row.eligible_count,
                row.observed_count,
                row.censored_count,
                reference.eligible_count,
                reference.observed_count,
                reference.censored_count
            )));
        }
    }
    Ok(())
}

fn parse_resolution(row: Row<'_>, index: usize, table: &MappedTsv) -> Result<AuctionResolution> {
    parse_enum(row, index, table, "resolution")
}

fn parse_completion(row: Row<'_>, index: usize, table: &MappedTsv) -> Result<CompletionStatus> {
    parse_enum(row, index, table, "completion")
}

fn parse_enum<E>(row: Row<'_>, index: usize, table: &MappedTsv, kind: &str) -> Result<E>
where
    E: TryFrom<i16>,
{
    let code = parse_i16(row.field(index).unwrap_or_default()).ok_or_else(|| {
        InterfaceError::Contract(format!(
            "invalid {kind} code in {} row {}",
            table.path().display(),
            row.number()
        ))
    })?;
    E::try_from(code).map_err(|_| {
        InterfaceError::Contract(format!(
            "unknown {kind} code {code} in {}",
            table.path().display()
        ))
    })
}

fn required_u64(row: Row<'_>, index: usize, table: &MappedTsv) -> Result<u64> {
    parse_u64(row.field(index).unwrap_or_default()).ok_or_else(|| {
        InterfaceError::Contract(format!(
            "invalid u64 in {} row {}",
            table.path().display(),
            row.number()
        ))
    })
}

fn optional_u64(row: Row<'_>, index: usize) -> Option<u64> {
    let value = row.field(index)?;
    if value == NULL_TOKEN {
        None
    } else {
        parse_u64(value)
    }
}

fn is_null(row: Row<'_>, index: usize) -> bool {
    row.field(index)
        .is_none_or(|value| value == NULL_TOKEN || value.is_empty())
}

fn dataset_path(root: &Path, kind: &str) -> Result<PathBuf> {
    let suffix = format!("_{kind}.tsv");
    let mut paths = fs::read_dir(root)
        .map_err(|source| InterfaceError::Io {
            path: root.to_path_buf(),
            source,
        })?
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.ends_with(&suffix))
        })
        .collect::<Vec<_>>();
    if paths.len() != 1 {
        return Err(InterfaceError::Contract(format!(
            "expected one {kind} dataset at {}",
            root.display()
        )));
    }
    Ok(paths.pop().unwrap())
}

fn interface_code_hash(root: &Path) -> Result<String> {
    let mut files = fs::read_dir(root)
        .map_err(|source| InterfaceError::Io {
            path: root.to_path_buf(),
            source,
        })?
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .filter(|path| {
            path.extension().is_some_and(|extension| extension == "py")
                && !path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| name.starts_with("test_"))
        })
        .collect::<Vec<_>>();
    files.sort_unstable_by(|left, right| left.file_name().cmp(&right.file_name()));
    let mut hasher = Sha256::new();
    for path in files {
        hasher.update(path.file_name().unwrap().to_string_lossy().as_bytes());
        let bytes = fs::read(&path).map_err(|source| InterfaceError::Io {
            path: path.clone(),
            source,
        })?;
        hasher.update(bytes);
    }
    Ok(hex_digest(hasher.finalize()))
}

fn sha256_file(path: &Path) -> Result<String> {
    let file = File::open(path).map_err(|source| InterfaceError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    let length = file
        .metadata()
        .map_err(|source| InterfaceError::Io {
            path: path.to_path_buf(),
            source,
        })?
        .len();
    if length == 0 {
        return Ok(hex_digest(Sha256::digest([])));
    }
    // SAFETY: read-only mapping of a sealed interface artifact.
    let mmap = unsafe { MmapOptions::new().map(&file) }.map_err(|source| InterfaceError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    Ok(hex_digest(Sha256::digest(&mmap)))
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T> {
    let bytes = fs::read(path).map_err(|source| InterfaceError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    let bytes = bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&bytes);
    serde_json::from_slice(bytes).map_err(|source| InterfaceError::Json {
        path: path.to_path_buf(),
        source,
    })
}

fn hex_digest(bytes: impl AsRef<[u8]>) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let bytes = bytes.as_ref();
    let mut output = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        output.push(HEX[usize::from(byte >> 4)] as char);
        output.push(HEX[usize::from(byte & 15)] as char);
    }
    output
}
