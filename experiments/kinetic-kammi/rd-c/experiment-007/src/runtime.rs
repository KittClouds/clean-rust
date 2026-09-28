use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    time::Instant,
};

use hashbrown::HashMap;
use rdc_runtime_contracts_v1::{
    CrashPoint, EndpointResponse, InspectionKind, InspectionReply, InspectionResult,
    PaidActionEndpoint, QueryJournal, RequestId, ResultBytes,
};

use crate::{
    authority::{self, AuthorityResult},
    domain::{HiddenEpisode, PublicEpisode, WorldBank, validate_source_reply},
    routing::{BudgetPlan, Lane, selected},
};

pub const RUN_SEED: u64 = 0xE007_2026_0927;

#[derive(Clone, Debug)]
pub struct EpisodeTrace {
    pub world_id: u32,
    pub stratum: &'static str,
    pub lane: Lane,
    pub budget: usize,
    pub episode_id: u32,
    pub domain_id: u32,
    pub active_action: u16,
    pub inspection_kind: Option<InspectionKind>,
    pub proposed_action: Option<u16>,
    pub correct_action: u16,
    pub task_completed: bool,
    pub wrong_to_right: bool,
    pub right_to_wrong: bool,
    pub unresolved: bool,
    pub avoided_wrong_commit: bool,
    pub illegal_commits: u32,
    pub rejected_proposals: u32,
    pub action_effects: u32,
    pub replay_identity_ok: bool,
    pub identity: [u8; 32],
    pub query_cost_units: u32,
    pub task_ns: u128,
    pub query_ns: u64,
    pub resolver_ns: u64,
}

#[derive(Clone, Debug, Default)]
pub struct GroupStats {
    pub world_id: u32,
    pub stratum: &'static str,
    pub lane: &'static str,
    pub budget: usize,
    pub planned_queries: usize,
    pub endpoint_attempts: usize,
    pub retries: usize,
    pub paid_queries: usize,
    pub paid_cost_units: u64,
    pub receipt_bytes: u64,
    pub receipt_identity: [u8; 32],
    pub query_ns: Vec<u64>,
    pub resolver_ns: Vec<u64>,
}

struct TraceMetrics {
    inspection: Option<InspectionResult>,
    authority: AuthorityResult,
    wrong_to_right: bool,
    right_to_wrong: bool,
    unresolved: bool,
    avoided_wrong_commit: bool,
    task_ns: u128,
    query_ns: u64,
    resolver_ns: u64,
}

pub fn run_plan(
    bank: &WorldBank,
    plan: &BudgetPlan,
    receipt_root: &Path,
    run_seed: u64,
) -> Result<(Vec<EpisodeTrace>, GroupStats), Box<dyn std::error::Error>> {
    if plan.world_id != bank.recipe.world_id || bank.public.len() != bank.hidden.len() {
        return Err("E007 runtime received mismatched world bank and route plan".into());
    }
    let hidden = bank
        .hidden
        .iter()
        .map(|row| (row.episode_id, *row))
        .collect::<HashMap<_, _>>();
    let replies = hidden
        .iter()
        .map(|(id, row)| (*id, row.reply))
        .collect::<HashMap<_, _>>();
    let mut endpoint = FixtureEndpoint {
        replies,
        cache: HashMap::with_capacity(plan.budget),
        attempts: 0,
        charges: 0,
    };
    let receipt_path = receipt_path(receipt_root, plan);
    fs::create_dir_all(receipt_path.parent().ok_or("receipt path has no parent")?)?;
    let mut journal = if plan.budget > 0 {
        Some(QueryJournal::create(&receipt_path).map_err(std::io::Error::other)?)
    } else {
        None
    };
    let mut traces = Vec::with_capacity(bank.public.len());
    let mut group = GroupStats {
        world_id: bank.recipe.world_id,
        stratum: bank.recipe.stratum.label(),
        lane: plan.lane.label(),
        budget: plan.budget,
        planned_queries: plan.budget,
        ..GroupStats::default()
    };
    for public in &bank.public {
        let task_started = Instant::now();
        let truth = hidden
            .get(&public.id)
            .ok_or("runtime hidden label is missing")?;
        let selected_for_query = selected(plan, public);
        let (inspection, query_ns, resolver_ns) = if selected_for_query {
            let journal = journal.as_mut().ok_or("routed plan has no query journal")?;
            let request_id = RequestId::derive(
                b"RDC-E007-INSPECTION-V1",
                run_seed,
                bank.recipe.world_id,
                plan.lane.code(),
                plan.budget as u16,
                public.id,
            );
            let request = encode_request(*public);
            let query_started = Instant::now();
            let result_bytes = journal
                .execute(
                    &mut endpoint,
                    request_id,
                    public.query_cost_units,
                    &request,
                    CrashPoint::None,
                )
                .map_err(std::io::Error::other)?;
            let query_ns = query_started.elapsed().as_nanos().min(u64::MAX as u128) as u64;
            let reply = InspectionReply::decode(&result_bytes.into_array())?;
            let resolver_started = Instant::now();
            let inspection = InspectionResult::classify(public.active, reply);
            let resolver_ns = resolver_started.elapsed().as_nanos().min(u64::MAX as u128) as u64;
            group.query_ns.push(query_ns);
            group.resolver_ns.push(resolver_ns);
            (Some(inspection), query_ns, resolver_ns)
        } else {
            (None, 0, 0)
        };
        let authority = authority::execute(*public, inspection, truth.correct_action);
        let task_ns = task_started.elapsed().as_nanos();
        let selected_action = authority.selected_action;
        let wrong_to_right =
            public.active != truth.correct_action && selected_action == Some(truth.correct_action);
        let right_to_wrong = public.active == truth.correct_action
            && selected_action.is_some_and(|action| action != truth.correct_action);
        let unresolved = inspection.is_some_and(|result| {
            matches!(
                result.kind,
                InspectionKind::Unknown | InspectionKind::Failed
            )
        });
        let avoided_wrong_commit =
            unresolved && public.active != truth.correct_action && selected_action.is_none();
        traces.push(make_trace(
            bank,
            *public,
            truth,
            plan,
            TraceMetrics {
                inspection,
                authority,
                wrong_to_right,
                right_to_wrong,
                unresolved,
                avoided_wrong_commit,
                task_ns,
                query_ns,
                resolver_ns,
            },
        ));
    }
    if let Some(journal) = journal {
        let written_stats = journal.stats();
        drop(journal);
        let journal = QueryJournal::resume(&receipt_path).map_err(std::io::Error::other)?;
        let stats = journal.stats();
        if stats != written_stats {
            return Err(format!(
                "{} world {} journal stats changed across replay",
                plan.lane.label(),
                plan.world_id
            )
            .into());
        }
        for episode_id in &plan.selected_ids {
            let request_id = RequestId::derive(
                b"RDC-E007-INSPECTION-V1",
                run_seed,
                bank.recipe.world_id,
                plan.lane.code(),
                plan.budget as u16,
                *episode_id,
            );
            let expected_reply = endpoint
                .replies
                .get(episode_id)
                .ok_or("replay source reply is missing")?;
            let expected = ResultBytes::from_array(expected_reply.encode().map_err(str::to_owned)?);
            if journal.result(request_id) != Some(expected) {
                return Err(format!(
                    "{} world {} episode {} paid result differs after replay",
                    plan.lane.label(),
                    plan.world_id,
                    episode_id
                )
                .into());
            }
        }
        group.endpoint_attempts = endpoint.attempts;
        group.retries = stats.retries;
        group.paid_queries = endpoint.charges;
        group.paid_cost_units = stats.paid_cost_units;
        group.receipt_bytes = stats.bytes;
        group.receipt_identity = stats.identity;
        if stats.intents != plan.budget
            || stats.result_receipts != plan.budget
            || stats.endpoint_attempts != plan.budget
            || endpoint.attempts != plan.budget
            || endpoint.charges != plan.budget
        {
            return Err(format!(
                "{} world {} failed exact paid-query contract",
                plan.lane.label(),
                plan.world_id
            )
            .into());
        }
    }
    Ok((traces, group))
}

pub fn write_traces(
    path: impl AsRef<Path>,
    traces: &[EpisodeTrace],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = std::io::BufWriter::with_capacity(64 * 1024, fs::File::create(path)?);
    writeln!(
        writer,
        "world_id,stratum,lane,budget,episode_id,domain_id,active_action,inspection_kind,proposed_action,correct_action,completed,wrong_to_right,right_to_wrong,unresolved,avoided_wrong_commit,illegal_commits,rejected_proposals,action_effects,replay_identity_ok,identity,query_cost_units,task_ns,query_ns,resolver_ns"
    )?;
    for row in traces {
        writeln!(
            writer,
            "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
            row.world_id,
            row.stratum,
            row.lane.label(),
            row.budget,
            row.episode_id,
            row.domain_id,
            row.active_action,
            row.inspection_kind.map_or("none", InspectionKind::label),
            row.proposed_action
                .map_or_else(|| "none".to_owned(), |action| action.to_string()),
            row.correct_action,
            row.task_completed,
            row.wrong_to_right,
            row.right_to_wrong,
            row.unresolved,
            row.avoided_wrong_commit,
            row.illegal_commits,
            row.rejected_proposals,
            row.action_effects,
            row.replay_identity_ok,
            hex(&row.identity),
            row.query_cost_units,
            row.task_ns,
            row.query_ns,
            row.resolver_ns
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

pub fn write_group_stats(
    path: impl AsRef<Path>,
    groups: &[GroupStats],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = std::io::BufWriter::with_capacity(16 * 1024, fs::File::create(path)?);
    writeln!(
        writer,
        "world_id,stratum,lane,budget,planned_queries,endpoint_attempts,retries,paid_queries,paid_cost_units,receipt_bytes,receipt_identity,p50_query_ns,p95_query_ns,p50_resolver_ns,p95_resolver_ns"
    )?;
    for group in groups {
        writeln!(
            writer,
            "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
            group.world_id,
            group.stratum,
            group.lane,
            group.budget,
            group.planned_queries,
            group.endpoint_attempts,
            group.retries,
            group.paid_queries,
            group.paid_cost_units,
            group.receipt_bytes,
            hex(&group.receipt_identity),
            percentile(&group.query_ns, 0.50),
            percentile(&group.query_ns, 0.95),
            percentile(&group.resolver_ns, 0.50),
            percentile(&group.resolver_ns, 0.95)
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

#[derive(Clone, Debug)]
pub struct CrashResult {
    pub point: &'static str,
    pub attempts: usize,
    pub retries: usize,
    pub charges: usize,
    pub result_receipts: usize,
    pub duplicate_effects: usize,
    pub replay_ok: bool,
}

#[derive(Default)]
struct CrashEndpoint {
    cache: HashMap<RequestId, ResultBytes>,
    attempts: usize,
    charges: usize,
    effects: usize,
}

impl PaidActionEndpoint for CrashEndpoint {
    fn invoke(
        &mut self,
        id: RequestId,
        _cost: u32,
        request: &[u8],
    ) -> Result<EndpointResponse, String> {
        self.attempts += 1;
        if let Some(result) = self.cache.get(&id).copied() {
            return Ok(EndpointResponse {
                result,
                charged_for_request: true,
            });
        }
        self.charges += 1;
        self.effects += 1;
        let mut bytes = [0; 64];
        let digest = blake3::hash(request);
        bytes[..32].copy_from_slice(digest.as_bytes());
        bytes[32..].copy_from_slice(digest.as_bytes());
        let result = ResultBytes::from_array(bytes);
        self.cache.insert(id, result);
        Ok(EndpointResponse {
            result,
            charged_for_request: true,
        })
    }
}

pub fn crash_recovery(root: &Path) -> Result<Vec<CrashResult>, Box<dyn std::error::Error>> {
    let mut output = Vec::with_capacity(3);
    for (index, point) in [
        CrashPoint::AfterIntent,
        CrashPoint::AfterEndpointResponse,
        CrashPoint::AfterOutcomeReceipt,
    ]
    .into_iter()
    .enumerate()
    {
        let folder = root.join(format!("crash-{}", crash_label(point)));
        fs::create_dir_all(&folder)?;
        let receipt = folder.join("paid-actions.rdj");
        let id = RequestId::derive(b"RDC-E007-CRASH", RUN_SEED, 900 + index as u32, 1, 1, 7);
        let request = b"synthetic paid inspection request";
        let mut endpoint = CrashEndpoint::default();
        let mut journal = QueryJournal::create(&receipt).map_err(std::io::Error::other)?;
        let injected = journal
            .execute(&mut endpoint, id, 3, request, point)
            .is_err();
        drop(journal);
        let mut journal = QueryJournal::resume(&receipt).map_err(std::io::Error::other)?;
        let recovered = journal.execute(&mut endpoint, id, 3, request, CrashPoint::None)?;
        let recovered_stats = journal.stats();
        let recovered_result = journal.result(id);
        drop(journal);
        let journal = QueryJournal::resume(&receipt).map_err(std::io::Error::other)?;
        let stats = journal.stats();
        let replay_ok = recovered_result == Some(recovered)
            && journal.result(id) == Some(recovered)
            && stats == recovered_stats
            && stats.result_receipts == 1;
        let row = CrashResult {
            point: crash_label(point),
            attempts: endpoint.attempts,
            retries: stats.retries,
            charges: endpoint.charges,
            result_receipts: stats.result_receipts,
            duplicate_effects: endpoint.effects.saturating_sub(1),
            replay_ok: injected && replay_ok && endpoint.charges == 1,
        };
        output.push(row);
    }
    Ok(output)
}

pub fn write_crash_results(
    path: impl AsRef<Path>,
    rows: &[CrashResult],
) -> Result<(), Box<dyn std::error::Error>> {
    let mut writer = std::io::BufWriter::new(fs::File::create(path)?);
    writeln!(
        writer,
        "crash_boundary,endpoint_attempts,retries,paid_charges,result_receipts,duplicate_effects,replay_ok"
    )?;
    for row in rows {
        writeln!(
            writer,
            "{},{},{},{},{},{},{}",
            row.point,
            row.attempts,
            row.retries,
            row.charges,
            row.result_receipts,
            row.duplicate_effects,
            row.replay_ok
        )?;
    }
    writer.flush()?;
    writer.get_ref().sync_all()?;
    Ok(())
}

fn make_trace(
    bank: &WorldBank,
    public: PublicEpisode,
    truth: &HiddenEpisode,
    plan: &BudgetPlan,
    metrics: TraceMetrics,
) -> EpisodeTrace {
    EpisodeTrace {
        world_id: bank.recipe.world_id,
        stratum: bank.recipe.stratum.label(),
        lane: plan.lane,
        budget: plan.budget,
        episode_id: public.id,
        domain_id: public.domain_id,
        active_action: public.active.0,
        inspection_kind: metrics.inspection.map(|result| result.kind),
        proposed_action: metrics.authority.selected_action.map(|action| action.0),
        correct_action: truth.correct_action.0,
        task_completed: metrics.authority.task_completed,
        wrong_to_right: metrics.wrong_to_right,
        right_to_wrong: metrics.right_to_wrong,
        unresolved: metrics.unresolved,
        avoided_wrong_commit: metrics.avoided_wrong_commit,
        illegal_commits: metrics.authority.illegal_commits,
        rejected_proposals: metrics.authority.rejected_proposals,
        action_effects: metrics.authority.task_action_effects,
        replay_identity_ok: metrics.authority.replay_identity_ok,
        identity: metrics.authority.identity,
        query_cost_units: if plan.budget > 0 && selected(plan, &public) {
            public.query_cost_units
        } else {
            0
        },
        task_ns: metrics.task_ns,
        query_ns: metrics.query_ns,
        resolver_ns: metrics.resolver_ns,
    }
}

struct FixtureEndpoint {
    replies: HashMap<u32, InspectionReply>,
    cache: HashMap<RequestId, ResultBytes>,
    attempts: usize,
    charges: usize,
}

impl PaidActionEndpoint for FixtureEndpoint {
    fn invoke(
        &mut self,
        id: RequestId,
        _cost: u32,
        request: &[u8],
    ) -> Result<EndpointResponse, String> {
        self.attempts += 1;
        if let Some(result) = self.cache.get(&id).copied() {
            return Ok(EndpointResponse {
                result,
                charged_for_request: true,
            });
        }
        let episode_id = u32::from_le_bytes(
            request
                .get(..4)
                .ok_or("request omits episode ID")?
                .try_into()
                .unwrap(),
        );
        let reply = self
            .replies
            .get(&episode_id)
            .ok_or("source fixture omits routed episode")?;
        if !validate_source_reply(episode_id, *reply) {
            return Err("source fixture digest does not match its reply".into());
        }
        let result = ResultBytes::from_array(reply.encode().map_err(str::to_owned)?);
        self.cache.insert(id, result);
        self.charges += 1;
        Ok(EndpointResponse {
            result,
            charged_for_request: true,
        })
    }
}

fn encode_request(public: PublicEpisode) -> [u8; 14] {
    let mut request = [0; 14];
    request[..4].copy_from_slice(&public.id.to_le_bytes());
    request[4..6].copy_from_slice(&public.active.0.to_le_bytes());
    request[6..10].copy_from_slice(&public.domain_id.to_le_bytes());
    request[10..14].copy_from_slice(&public.query_cost_units.to_le_bytes());
    request
}

fn receipt_path(root: &Path, plan: &BudgetPlan) -> PathBuf {
    root.join(format!("world-{:03}", plan.world_id))
        .join(format!(
            "{}-budget-{:03}.rdj",
            plan.lane.label(),
            plan.budget
        ))
}

fn crash_label(point: CrashPoint) -> &'static str {
    match point {
        CrashPoint::AfterIntent => "after-durable-intent-before-call",
        CrashPoint::AfterEndpointResponse => "after-paid-response-before-outcome-receipt",
        CrashPoint::AfterOutcomeReceipt => "after-durable-outcome-receipt",
        CrashPoint::None => "none",
    }
}

fn percentile(values: &[u64], quantile: f32) -> u64 {
    if values.is_empty() {
        return 0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let index = ((sorted.len() - 1) as f32 * quantile).ceil() as usize;
    sorted[index.min(sorted.len() - 1)]
}

fn hex(bytes: &[u8; 32]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
