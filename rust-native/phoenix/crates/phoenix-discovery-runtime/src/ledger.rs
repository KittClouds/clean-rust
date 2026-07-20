use fs2::FileExt;
use phoenix_discovery_query::{
    BudgetExhaustion, DiscoveryPath, PreparedQueryReceipt, PreparedQueryResponse, SeedChannel,
};
use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

const CANDIDATE_SCHEMA: &str = "phoenix-discovery-candidate/v1";
const QUERY_RUN_SCHEMA: &str = "phoenix-discovery-query-run/v1";
const REVIEW_SCHEMA: &str = "phoenix-discovery-review-event/v1";
static TEMP_NONCE: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, thiserror::Error)]
enum LedgerError {
    #[error("discovery ledger I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("discovery ledger serialization failed: {0}")]
    Serde(#[from] serde_json::Error),
    #[error("discovery ledger contract failed: {0}")]
    Invalid(String),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CandidateReviewDecision {
    Reopened,
    Rejected,
    PromotionApproved,
    Superseded,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CandidateReviewEvent {
    pub schema_version: String,
    pub event_id: String,
    pub candidate_id: String,
    pub predecessor_event_id: Option<String>,
    pub decision: CandidateReviewDecision,
    pub reviewer_id: String,
    pub reviewed_at: i64,
    pub evidence_refs: Vec<String>,
    pub promotion_receipt_id: Option<String>,
    pub topology_writes: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryCandidateArtifact {
    pub schema_version: String,
    pub candidate_id: String,
    pub graph_generation: u64,
    pub discovery_digest: String,
    pub query_digest: String,
    pub seed_receipt_digest: String,
    pub score_policy_digest: String,
    pub canonical_path_digest: String,
    pub competing_path_digests: Vec<String>,
    pub exhaustion: BudgetExhaustion,
    pub path: DiscoveryPath,
    pub initial_review_status: String,
    pub topology_writes: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveryQueryRunArtifact {
    pub schema_version: String,
    pub run_id: String,
    pub query: String,
    pub query_digest: String,
    pub candidate_ids: Vec<String>,
    pub candidate_path_digests: Vec<String>,
    pub exhaustion: BudgetExhaustion,
    pub receipt: PreparedQueryReceipt,
    pub topology_writes: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LedgerPublication {
    pub run: DiscoveryQueryRunArtifact,
    pub candidates: Vec<DiscoveryCandidateArtifact>,
}

pub struct DiscoveryCandidateLedger {
    root: PathBuf,
}

struct ReviewHeadLock {
    file: std::fs::File,
}

impl ReviewHeadLock {
    fn acquire(root: &Path, candidate_id: &str) -> Result<Self, LedgerError> {
        let directory = root.join("reviews").join(candidate_id);
        fs::create_dir_all(&directory)?;
        let path = directory.join(".head.lock");
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&path)
            .map_err(LedgerError::Io)?;
        file.try_lock_exclusive().map_err(|error| {
            if error.kind() == std::io::ErrorKind::WouldBlock {
                LedgerError::Invalid("candidate review head is locked by another writer".to_owned())
            } else {
                LedgerError::Io(error)
            }
        })?;
        Ok(Self { file })
    }
}

impl Drop for ReviewHeadLock {
    fn drop(&mut self) {
        let _ = FileExt::unlock(&self.file);
    }
}

impl DiscoveryCandidateLedger {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, Box<dyn std::error::Error>> {
        let root = root.as_ref().to_path_buf();
        fs::create_dir_all(root.join("candidates"))?;
        fs::create_dir_all(root.join("runs"))?;
        fs::create_dir_all(root.join("reviews"))?;
        Ok(Self { root })
    }

    pub fn publish(
        &self,
        query: &str,
        response: &PreparedQueryResponse,
    ) -> Result<LedgerPublication, Box<dyn std::error::Error>> {
        validate_query_receipt(&response.receipt)?;
        if response.receipt.returned_paths as usize != response.paths.len() {
            return Err(Box::new(LedgerError::Invalid(
                "query receipt path count does not match its payload".to_owned(),
            )));
        }
        let query_digest = domain_hash(b"phoenix-discovery-query/v1\0", query.as_bytes());
        let path_digests = response
            .paths
            .iter()
            .map(canonical_path_digest)
            .collect::<Result<Vec<_>, _>>()?;
        let mut candidates = Vec::with_capacity(response.paths.len());
        for (index, path) in response.paths.iter().enumerate() {
            let mut competing = path_digests.clone();
            competing.remove(index);
            competing.sort_unstable();
            let candidate_id = candidate_identity(
                response.receipt.generation,
                &response.receipt.discovery_digest,
                &query_digest,
                &response.receipt.seed_receipt_digest,
                &response.receipt.score_policy_digest,
                &path_digests[index],
            );
            let candidate = DiscoveryCandidateArtifact {
                schema_version: CANDIDATE_SCHEMA.to_owned(),
                candidate_id: candidate_id.clone(),
                graph_generation: response.receipt.generation,
                discovery_digest: response.receipt.discovery_digest.clone(),
                query_digest: query_digest.clone(),
                seed_receipt_digest: response.receipt.seed_receipt_digest.clone(),
                score_policy_digest: response.receipt.score_policy_digest.clone(),
                canonical_path_digest: path_digests[index].clone(),
                competing_path_digests: competing,
                exhaustion: response.receipt.exhaustion,
                path: path.clone(),
                initial_review_status: "pending".to_owned(),
                topology_writes: 0,
            };
            publish_json(
                &self
                    .root
                    .join("candidates")
                    .join(&candidate_id)
                    .join("candidate.json"),
                &candidate,
            )?;
            candidates.push(candidate);
        }
        let candidate_ids = candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        let run_id = query_run_identity(&query_digest, &candidate_ids, &response.receipt)?;
        let run = DiscoveryQueryRunArtifact {
            schema_version: QUERY_RUN_SCHEMA.to_owned(),
            run_id: run_id.clone(),
            query: query.to_owned(),
            query_digest,
            candidate_ids,
            candidate_path_digests: path_digests,
            exhaustion: response.receipt.exhaustion,
            receipt: response.receipt.clone(),
            topology_writes: 0,
        };
        publish_json(&self.root.join("runs").join(&run_id).join("run.json"), &run)?;
        Ok(LedgerPublication { run, candidates })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn record_review(
        &self,
        candidate_id: &str,
        predecessor_event_id: Option<String>,
        decision: CandidateReviewDecision,
        reviewer_id: String,
        reviewed_at: i64,
        evidence_refs: Vec<String>,
        promotion_receipt_id: Option<String>,
    ) -> Result<CandidateReviewEvent, Box<dyn std::error::Error>> {
        if reviewer_id.trim().is_empty() || reviewed_at <= 0 {
            return Err(Box::new(LedgerError::Invalid(
                "review identity or timestamp is invalid".to_owned(),
            )));
        }
        let candidate_path = self
            .root
            .join("candidates")
            .join(candidate_id)
            .join("candidate.json");
        if !candidate_path.exists() {
            return Err(Box::new(LedgerError::Invalid(
                "review candidate does not exist".to_owned(),
            )));
        }
        let candidate: DiscoveryCandidateArtifact =
            serde_json::from_slice(&fs::read(&candidate_path)?)?;
        if candidate.candidate_id != candidate_id || candidate.topology_writes != 0 {
            return Err(Box::new(LedgerError::Invalid(
                "review candidate artifact failed its immutable identity contract".to_owned(),
            )));
        }
        let _head_lock = ReviewHeadLock::acquire(&self.root, candidate_id)?;
        let latest = self.latest_review(candidate_id)?;
        if latest.as_ref().map(|event| event.event_id.clone()) != predecessor_event_id {
            return Err(Box::new(LedgerError::Invalid(
                "review predecessor is not the current immutable head".to_owned(),
            )));
        }
        if decision == CandidateReviewDecision::PromotionApproved
            && promotion_receipt_id.as_deref().is_none_or(str::is_empty)
        {
            return Err(Box::new(LedgerError::Invalid(
                "promotion approval requires an external promotion receipt".to_owned(),
            )));
        }
        let mut event = CandidateReviewEvent {
            schema_version: REVIEW_SCHEMA.to_owned(),
            event_id: "pending".to_owned(),
            candidate_id: candidate_id.to_owned(),
            predecessor_event_id,
            decision,
            reviewer_id,
            reviewed_at,
            evidence_refs,
            promotion_receipt_id,
            topology_writes: 0,
        };
        event.event_id = review_identity(&event)?;
        publish_json(
            &self
                .root
                .join("reviews")
                .join(candidate_id)
                .join(format!("{}.json", event.event_id)),
            &event,
        )?;
        Ok(event)
    }

    pub fn latest_review(
        &self,
        candidate_id: &str,
    ) -> Result<Option<CandidateReviewEvent>, Box<dyn std::error::Error>> {
        let directory = self.root.join("reviews").join(candidate_id);
        if !directory.exists() {
            return Ok(None);
        }
        let mut events = Vec::new();
        for entry in fs::read_dir(directory)? {
            let path = entry?.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let event = serde_json::from_slice::<CandidateReviewEvent>(&fs::read(&path)?)?;
            let file_id = path.file_stem().and_then(|value| value.to_str());
            if event.schema_version != REVIEW_SCHEMA
                || event.candidate_id != candidate_id
                || event.topology_writes != 0
                || file_id != Some(event.event_id.as_str())
                || review_identity(&event)? != event.event_id
                || (event.decision == CandidateReviewDecision::PromotionApproved
                    && event
                        .promotion_receipt_id
                        .as_deref()
                        .is_none_or(str::is_empty))
            {
                return Err(Box::new(LedgerError::Invalid(
                    "review event failed its immutable identity contract".to_owned(),
                )));
            }
            events.push(event);
        }
        let mut predecessor = None;
        let mut latest = None;
        loop {
            let matches = events
                .iter()
                .filter(|event| event.predecessor_event_id == predecessor)
                .collect::<Vec<_>>();
            if matches.is_empty() {
                break;
            }
            if matches.len() != 1 {
                return Err(Box::new(LedgerError::Invalid(
                    "review event chain contains a fork".to_owned(),
                )));
            }
            let event = (*matches[0]).clone();
            predecessor = Some(event.event_id.clone());
            latest = Some(event);
        }
        if latest.is_none() != events.is_empty() {
            return Err(Box::new(LedgerError::Invalid(
                "review event chain is disconnected".to_owned(),
            )));
        }
        Ok(latest)
    }
}

fn validate_query_receipt(receipt: &PreparedQueryReceipt) -> Result<(), LedgerError> {
    let seed_bytes =
        serde_json::to_vec(&(&receipt.lexical_seed_receipt, &receipt.vector_seed_receipt))?;
    let seed_digest = blake3::hash(&seed_bytes).to_hex().to_string();
    let seed_receipts_valid = [
        (SeedChannel::Lexical, &receipt.lexical_seed_receipt),
        (SeedChannel::Vector, &receipt.vector_seed_receipt),
    ]
    .into_iter()
    .all(|(channel, seed)| {
        seed.channel == channel
            && seed.index_generation > 0
            && is_digest(&seed.index_digest)
            && seed.accepted as usize == seed.hits.len()
            && seed.examined >= seed.accepted
            && seed.source_discovery_digest == receipt.discovery_digest
            && !seed.encoder_id.trim().is_empty()
            && !seed.encoder_version.trim().is_empty()
            && seed
                .hits
                .iter()
                .all(|hit| (1..=1_000_000).contains(&hit.score_micros))
    });
    if receipt.generation == 0
        || !is_digest(&receipt.discovery_digest)
        || !is_digest(&receipt.seed_receipt_digest)
        || !is_digest(&receipt.score_policy_digest)
        || receipt.seed_receipt_digest != seed_digest
        || !seed_receipts_valid
        || receipt.lexical_candidates != receipt.lexical_seed_receipt.accepted
        || receipt.vector_candidates != receipt.vector_seed_receipt.accepted
        || receipt.resolved_seeds
            > receipt
                .lexical_candidates
                .saturating_add(receipt.vector_candidates)
        || receipt.total_examined_edges > receipt.limits.total_examined_edges
        || receipt.ppr_examined_edges > receipt.limits.ppr_examined_edges
        || receipt.ppr_visited_vertices > receipt.limits.ppr_visited_vertices
        || receipt.returned_paths > u32::from(receipt.limits.returned_paths)
        || receipt.admitted_candidate_edges != 0
        || receipt.topology_writes != 0
        || receipt.fallback_used
    {
        return Err(LedgerError::Invalid(
            "query receipt violates discovery candidate authority".to_owned(),
        ));
    }
    Ok(())
}

fn is_digest(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn canonical_path_digest(path: &DiscoveryPath) -> Result<String, LedgerError> {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-discovery-canonical-path/v1\0");
    for node in &path.node_identities {
        hasher.update(&node.hash.to_le_bytes());
        hasher.update(&node.collision.to_le_bytes());
    }
    for edge in &path.edges {
        hasher.update(&edge.identity.hash.to_le_bytes());
        hasher.update(&edge.identity.collision.to_le_bytes());
    }
    Ok(hasher.finalize().to_hex().to_string())
}

fn candidate_identity(
    generation: u64,
    discovery: &str,
    query: &str,
    seeds: &str,
    score_policy: &str,
    path: &str,
) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(b"phoenix-discovery-candidate-identity/v1\0");
    hasher.update(&generation.to_le_bytes());
    for value in [discovery, query, seeds, score_policy, path] {
        hasher.update(value.as_bytes());
        hasher.update(&[0]);
    }
    hasher.finalize().to_hex().to_string()
}

fn query_run_identity(
    query_digest: &str,
    candidates: &[String],
    receipt: &PreparedQueryReceipt,
) -> Result<String, LedgerError> {
    content_id(
        b"phoenix-discovery-query-run-identity/v1\0",
        &(query_digest, candidates, receipt),
    )
}

fn review_identity(event: &CandidateReviewEvent) -> Result<String, LedgerError> {
    let mut content = event.clone();
    content.event_id = "pending".to_owned();
    content_id(b"phoenix-discovery-review/v1\0", &content)
}

fn content_id<T: Serialize>(domain: &[u8], value: &T) -> Result<String, LedgerError> {
    let bytes = serde_json::to_vec(value)?;
    let mut hasher = blake3::Hasher::new();
    hasher.update(domain);
    hasher.update(&bytes);
    Ok(hasher.finalize().to_hex().to_string())
}

fn domain_hash(domain: &[u8], bytes: &[u8]) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(domain);
    hasher.update(bytes);
    hasher.finalize().to_hex().to_string()
}

fn publish_json<T: Serialize + serde::de::DeserializeOwned + PartialEq>(
    path: &Path,
    value: &T,
) -> Result<(), LedgerError> {
    let bytes = serde_json::to_vec(value)?;
    let parent = path
        .parent()
        .ok_or_else(|| LedgerError::Invalid("artifact path has no parent".to_owned()))?;
    fs::create_dir_all(parent)?;
    if path.exists() {
        return verify_existing(path, value);
    }
    let nonce = TEMP_NONCE.fetch_add(1, Ordering::Relaxed);
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| LedgerError::Invalid("artifact filename is invalid".to_owned()))?;
    let temporary = parent.join(format!(".{file_name}.{}.{}.tmp", std::process::id(), nonce));
    let write_result = (|| -> Result<(), LedgerError> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        drop(file);
        match fs::rename(&temporary, path) {
            Ok(()) => Ok(()),
            Err(_error) if path.exists() => verify_existing(path, value),
            Err(error) => Err(error.into()),
        }
    })();
    if write_result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    write_result
}

fn verify_existing<T: serde::de::DeserializeOwned + PartialEq>(
    path: &Path,
    value: &T,
) -> Result<(), LedgerError> {
    let existing: T = serde_json::from_slice(&fs::read(path)?)?;
    if &existing != value {
        return Err(LedgerError::Invalid(
            "content address resolves to different immutable bytes".to_owned(),
        ));
    }
    Ok(())
}
