use std::{
    fs,
    ops::AddAssign,
    path::{Path, PathBuf},
};

use hashbrown::{HashMap, HashSet};
use northstar_auction_contract::{
    AuctionResolution, CensorReason, CompletionStatus, DATASET_CONTRACT, DATASET_SCHEMA, EventType,
    NULL_TOKEN, RESEARCH_GENERATION, Region, StableLabel,
};
use serde::Serialize;

use crate::{
    CorpusError, MappedTsv, Result, Row, TerminalReceipt, parse_i16, parse_u16, parse_u64,
};

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct DatasetCounts {
    pub events: u64,
    pub attempts: u64,
    pub episodes: u64,
    pub context: u64,
    pub features: u64,
    pub transits: u64,
}

impl AddAssign for DatasetCounts {
    fn add_assign(&mut self, rhs: Self) {
        self.events += rhs.events;
        self.attempts += rhs.attempts;
        self.episodes += rhs.episodes;
        self.context += rhs.context;
        self.features += rhs.features;
        self.transits += rhs.transits;
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct RelationalReport {
    pub counts: DatasetCounts,
    pub attempts_resolved: u64,
    pub attempts_censored: u64,
    pub episodes_resolved: u64,
    pub episodes_censored: u64,
    pub transits_resolved: u64,
    pub transits_censored: u64,
}

struct LoadedIds {
    attempts: HashSet<u64>,
    attempt_episode: HashMap<u64, u64>,
}

pub fn validate_run_relations(
    run_dir: &Path,
    receipt: &TerminalReceipt,
) -> Result<RelationalReport> {
    let auction_dir = run_dir.join("raw/auction");
    let attempts_path = dataset_path(&auction_dir, "attempts")?;
    let episodes_path = dataset_path(&auction_dir, "episodes")?;
    let features_path = dataset_path(&auction_dir, "features")?;
    let context_path = dataset_path(&auction_dir, "context")?;
    let events_path = dataset_path(&auction_dir, "events")?;
    let transits_path = dataset_path(&auction_dir, "transits")?;

    let (ids, mut report) = load_attempts_and_episodes(&attempts_path, &episodes_path, receipt)?;
    validate_features(&features_path, receipt, &ids, &mut report)?;
    validate_context(&context_path, receipt, &ids, &mut report)?;
    validate_events(&events_path, receipt, &ids, &mut report)?;
    validate_transits(&transits_path, receipt, &ids, &mut report)?;
    validate_receipt_balances(receipt, report)?;
    Ok(report)
}

fn load_attempts_and_episodes(
    attempts_path: &Path,
    episodes_path: &Path,
    receipt: &TerminalReceipt,
) -> Result<(LoadedIds, RelationalReport)> {
    let attempts = MappedTsv::open(attempts_path)?;
    let attempt_id = attempts.column("attempt_id")?;
    let attempt_episode_id = attempts.column("episode_id")?;
    let completion_code = attempts.column("completion_status_code")?;
    let completion_label = attempts.column("completion_status")?;
    let censor_code = attempts.column("censor_reason_code")?;
    let censor_label = attempts.column("censor_reason")?;
    let resolution_code = attempts.column("resolution_code")?;
    let resolution_label = attempts.column("resolution")?;
    let mut attempt_ids = HashSet::new();
    let mut attempt_episode = HashMap::new();
    let mut actual_attempts_per_episode = HashMap::<u64, u64>::new();
    let mut report = RelationalReport::default();
    for row in attempts.rows() {
        let row = row?;
        validate_identity(row, &attempts, receipt)?;
        let id = required_u64(row, attempt_id, &attempts)?;
        let episode = required_u64(row, attempt_episode_id, &attempts)?;
        if !attempt_ids.insert(id) {
            return relational(receipt, format!("duplicate attempt_id {id}"));
        }
        attempt_episode.insert(id, episode);
        *actual_attempts_per_episode.entry(episode).or_default() += 1;
        let status =
            validate_enum::<CompletionStatus>(row, completion_code, completion_label, &attempts)?;
        let reason = validate_enum::<CensorReason>(row, censor_code, censor_label, &attempts)?;
        validate_enum::<AuctionResolution>(row, resolution_code, resolution_label, &attempts)?;
        validate_completion(receipt, status, reason, id, "attempt")?;
        match status {
            CompletionStatus::Resolved => report.attempts_resolved += 1,
            CompletionStatus::RightCensored => report.attempts_censored += 1,
            CompletionStatus::Active => {}
        }
        report.counts.attempts += 1;
    }

    let episodes = MappedTsv::open(episodes_path)?;
    let episode_id = episodes.column("episode_id")?;
    let attempts_count = episodes.column("attempts")?;
    let completion_code = episodes.column("completion_status_code")?;
    let completion_label = episodes.column("completion_status")?;
    let censor_code = episodes.column("censor_reason_code")?;
    let censor_label = episodes.column("censor_reason")?;
    let resolution_code = episodes.column("resolution_code")?;
    let resolution_label = episodes.column("resolution")?;
    let mut episode_ids = HashSet::new();
    let mut expected_attempts_per_episode = HashMap::new();
    for row in episodes.rows() {
        let row = row?;
        validate_identity(row, &episodes, receipt)?;
        let id = required_u64(row, episode_id, &episodes)?;
        if !episode_ids.insert(id) {
            return relational(receipt, format!("duplicate episode_id {id}"));
        }
        let expected = required_u64(row, attempts_count, &episodes)?;
        expected_attempts_per_episode.insert(id, expected);
        let status =
            validate_enum::<CompletionStatus>(row, completion_code, completion_label, &episodes)?;
        let reason = validate_enum::<CensorReason>(row, censor_code, censor_label, &episodes)?;
        validate_enum::<AuctionResolution>(row, resolution_code, resolution_label, &episodes)?;
        validate_completion(receipt, status, reason, id, "episode")?;
        match status {
            CompletionStatus::Resolved => report.episodes_resolved += 1,
            CompletionStatus::RightCensored => report.episodes_censored += 1,
            CompletionStatus::Active => {}
        }
        report.counts.episodes += 1;
    }
    for (&attempt, &episode) in &attempt_episode {
        if !episode_ids.contains(&episode) {
            return relational(
                receipt,
                format!("attempt {attempt} references missing episode {episode}"),
            );
        }
    }
    for (&episode, &expected) in &expected_attempts_per_episode {
        let actual = actual_attempts_per_episode
            .get(&episode)
            .copied()
            .unwrap_or(0);
        if actual != expected {
            return relational(
                receipt,
                format!("episode {episode} declares {expected} attempts, found {actual}"),
            );
        }
    }
    Ok((
        LoadedIds {
            attempts: attempt_ids,
            attempt_episode,
        },
        report,
    ))
}

fn validate_features(
    path: &Path,
    receipt: &TerminalReceipt,
    ids: &LoadedIds,
    report: &mut RelationalReport,
) -> Result<()> {
    let table = MappedTsv::open(path)?;
    let attempt_id = table.column("attempt_id")?;
    let region_code = table.column("price_region_code")?;
    let region_label = table.column("price_region")?;
    let cog_region_code = table.column("cog_region_code")?;
    let cog_region_label = table.column("cog_region")?;
    let mut seen = HashSet::new();
    for row in table.rows() {
        let row = row?;
        validate_identity(row, &table, receipt)?;
        let attempt = required_u64(row, attempt_id, &table)?;
        if !ids.attempts.contains(&attempt) {
            return relational(
                receipt,
                format!("feature references missing attempt {attempt}"),
            );
        }
        if !seen.insert(attempt) {
            return relational(
                receipt,
                format!("attempt {attempt} has duplicate feature row"),
            );
        }
        validate_enum::<Region>(row, region_code, region_label, &table)?;
        validate_enum::<Region>(row, cog_region_code, cog_region_label, &table)?;
        report.counts.features += 1;
    }
    if seen != ids.attempts {
        return relational(
            receipt,
            "feature rows are not exactly one per attempt".into(),
        );
    }
    Ok(())
}

fn validate_context(
    path: &Path,
    receipt: &TerminalReceipt,
    ids: &LoadedIds,
    report: &mut RelationalReport,
) -> Result<()> {
    let table = MappedTsv::open(path)?;
    let attempt_id = table.column("attempt_id")?;
    let episode_id = table.column("episode_id")?;
    let source_key = table.column("source_key")?;
    let mut seen_attempts = HashSet::new();
    let mut source_keys = HashSet::new();
    for row in table.rows() {
        let row = row?;
        validate_identity(row, &table, receipt)?;
        let attempt = required_u64(row, attempt_id, &table)?;
        let episode = required_u64(row, episode_id, &table)?;
        let source = required_u64(row, source_key, &table)?;
        if ids.attempt_episode.get(&attempt) != Some(&episode) {
            return relational(
                receipt,
                format!("context attempt {attempt} episode mismatch"),
            );
        }
        if !source_keys.insert((attempt, source)) {
            return relational(
                receipt,
                format!("duplicate context source {source} for attempt {attempt}"),
            );
        }
        seen_attempts.insert(attempt);
        report.counts.context += 1;
    }
    if seen_attempts != ids.attempts {
        return relational(
            receipt,
            "one or more attempts have no contributor context".into(),
        );
    }
    Ok(())
}

fn validate_events(
    path: &Path,
    receipt: &TerminalReceipt,
    ids: &LoadedIds,
    report: &mut RelationalReport,
) -> Result<()> {
    let table = MappedTsv::open(path)?;
    let event_id = table.column("event_id")?;
    let attempt_id = table.column("attempt_id")?;
    let episode_id = table.column("episode_id")?;
    let code = table.column("event_type_code")?;
    let label = table.column("event_type")?;
    let mut seen = HashSet::new();
    for row in table.rows() {
        let row = row?;
        validate_identity(row, &table, receipt)?;
        let event = required_u64(row, event_id, &table)?;
        let attempt = required_u64(row, attempt_id, &table)?;
        let episode = required_u64(row, episode_id, &table)?;
        if !seen.insert(event) {
            return relational(receipt, format!("duplicate event_id {event}"));
        }
        if ids.attempt_episode.get(&attempt) != Some(&episode) {
            return relational(
                receipt,
                format!("event {event} has invalid attempt/episode relation"),
            );
        }
        validate_enum::<EventType>(row, code, label, &table)?;
        report.counts.events += 1;
    }
    Ok(())
}

fn validate_transits(
    path: &Path,
    receipt: &TerminalReceipt,
    ids: &LoadedIds,
    report: &mut RelationalReport,
) -> Result<()> {
    let table = MappedTsv::open(path)?;
    let transit_id = table.column("transit_id")?;
    let attempt_id = table.column("attempt_id")?;
    let episode_id = table.column("episode_id")?;
    let source_node = table.column("source_node_id")?;
    let destination_node = table.column("destination_node_id")?;
    let completion_code = table.column("completion_status_code")?;
    let completion_label = table.column("completion_status")?;
    let censor_code = table.column("censor_reason_code")?;
    let censor_label = table.column("censor_reason")?;
    let resolution_code = table.column("resolution_code")?;
    let resolution_label = table.column("resolution")?;
    let mut seen = HashSet::new();
    for row in table.rows() {
        let row = row?;
        validate_identity(row, &table, receipt)?;
        let transit = required_u64(row, transit_id, &table)?;
        let attempt = required_u64(row, attempt_id, &table)?;
        let episode = required_u64(row, episode_id, &table)?;
        if !seen.insert(transit) {
            return relational(receipt, format!("duplicate transit_id {transit}"));
        }
        if ids.attempt_episode.get(&attempt) != Some(&episode) {
            return relational(
                receipt,
                format!("transit {transit} has invalid attempt/episode relation"),
            );
        }
        let source = required_u64(row, source_node, &table)?;
        let destination = required_u64(row, destination_node, &table)?;
        if source == 0 || destination == 0 || source == destination {
            return relational(receipt, format!("transit {transit} has invalid nodes"));
        }
        let status =
            validate_enum::<CompletionStatus>(row, completion_code, completion_label, &table)?;
        let reason = validate_enum::<CensorReason>(row, censor_code, censor_label, &table)?;
        validate_enum::<AuctionResolution>(row, resolution_code, resolution_label, &table)?;
        validate_completion(receipt, status, reason, transit, "transit")?;
        match status {
            CompletionStatus::Resolved => report.transits_resolved += 1,
            CompletionStatus::RightCensored => report.transits_censored += 1,
            CompletionStatus::Active => {}
        }
        report.counts.transits += 1;
    }
    Ok(())
}

fn validate_identity(row: Row<'_>, table: &MappedTsv, receipt: &TerminalReceipt) -> Result<()> {
    let schema = required_u16(row, table.column("dataset_schema")?, table)?;
    let generation = required_u16(row, table.column("research_generation")?, table)?;
    let contract = required(row, table.column("contract_id")?, table)?;
    let run_key = required(row, table.column("run_key")?, table)?;
    let invocation = required(row, table.column("invocation_id")?, table)?;
    if schema != DATASET_SCHEMA
        || generation != RESEARCH_GENERATION
        || contract != DATASET_CONTRACT.as_bytes()
        || run_key != receipt.run_key.as_bytes()
        || invocation != receipt.invocation_id.as_bytes()
    {
        return relational(
            receipt,
            format!(
                "row {} semantic identity mismatch in {}",
                row.number(),
                table.path().display()
            ),
        );
    }
    Ok(())
}

fn validate_enum<E>(
    row: Row<'_>,
    code_index: usize,
    label_index: usize,
    table: &MappedTsv,
) -> Result<E>
where
    E: TryFrom<i16> + StableLabel,
{
    let code = parse_i16(required(row, code_index, table)?).ok_or_else(|| CorpusError::Tsv {
        path: table.path().to_path_buf(),
        row: row.number(),
        detail: "invalid enum code".into(),
    })?;
    let value = E::try_from(code).map_err(|_| CorpusError::Tsv {
        path: table.path().to_path_buf(),
        row: row.number(),
        detail: format!("unknown enum code {code}"),
    })?;
    let label = required(row, label_index, table)?;
    if label != value.label().as_bytes() {
        return Err(CorpusError::Tsv {
            path: table.path().to_path_buf(),
            row: row.number(),
            detail: format!("enum code {code} label mismatch"),
        });
    }
    Ok(value)
}

fn validate_completion(
    receipt: &TerminalReceipt,
    status: CompletionStatus,
    reason: CensorReason,
    id: u64,
    kind: &str,
) -> Result<()> {
    let valid = match status {
        CompletionStatus::Resolved => reason == CensorReason::None,
        CompletionStatus::RightCensored => reason != CensorReason::None,
        CompletionStatus::Active => reason == CensorReason::None,
    };
    if valid {
        Ok(())
    } else {
        relational(
            receipt,
            format!("{kind} {id} has invalid completion/censor pair"),
        )
    }
}

fn validate_receipt_balances(receipt: &TerminalReceipt, report: RelationalReport) -> Result<()> {
    let expected = DatasetCounts {
        events: receipt_u64(receipt, &receipt.event_rows, "event_rows")?,
        attempts: receipt_u64(receipt, &receipt.attempt_rows, "attempt_rows")?,
        episodes: receipt_u64(receipt, &receipt.episode_rows, "episode_rows")?,
        context: receipt_u64(receipt, &receipt.context_rows, "context_rows")?,
        features: receipt_u64(receipt, &receipt.feature_rows, "feature_rows")?,
        transits: receipt_u64(receipt, &receipt.transit_rows, "transit_rows")?,
    };
    if report.counts != expected {
        return relational(
            receipt,
            format!(
                "dataset counts {:?} do not match receipt {:?}",
                report.counts, expected
            ),
        );
    }
    let event_emitted = receipt_u64(receipt, &receipt.events_emitted, "events_emitted")?;
    if event_emitted != report.counts.events {
        return relational(receipt, "events_emitted balance failed".into());
    }
    validate_balance(
        receipt,
        "attempt",
        report.counts.attempts,
        report.attempts_resolved,
        report.attempts_censored,
        &receipt.active_attempts,
    )?;
    validate_balance(
        receipt,
        "episode",
        report.counts.episodes,
        report.episodes_resolved,
        report.episodes_censored,
        &receipt.active_episodes,
    )?;
    validate_balance(
        receipt,
        "transit",
        report.counts.transits,
        report.transits_resolved,
        report.transits_censored,
        &receipt.active_transits,
    )?;
    Ok(())
}

fn validate_balance(
    receipt: &TerminalReceipt,
    kind: &str,
    started: u64,
    resolved: u64,
    censored: u64,
    active_text: &str,
) -> Result<()> {
    let active = receipt_u64(receipt, active_text, "active")?;
    if started != resolved + censored + active {
        return relational(
            receipt,
            format!("{kind} balance {started} != {resolved}+{censored}+{active}"),
        );
    }
    Ok(())
}

fn receipt_u64(receipt: &TerminalReceipt, value: &str, field: &str) -> Result<u64> {
    parse_u64(value.as_bytes()).ok_or_else(|| CorpusError::Relational {
        run_key: receipt.run_key.clone(),
        detail: format!("invalid receipt field {field}"),
    })
}

fn required<'a>(row: Row<'a>, index: usize, table: &MappedTsv) -> Result<&'a [u8]> {
    let value = row.field(index).ok_or_else(|| CorpusError::Tsv {
        path: table.path().to_path_buf(),
        row: row.number(),
        detail: format!("missing field index {index}"),
    })?;
    if value.is_empty() || value == NULL_TOKEN {
        return Err(CorpusError::Tsv {
            path: table.path().to_path_buf(),
            row: row.number(),
            detail: format!("required field {index} is null"),
        });
    }
    Ok(value)
}

fn required_u64(row: Row<'_>, index: usize, table: &MappedTsv) -> Result<u64> {
    parse_u64(required(row, index, table)?).ok_or_else(|| CorpusError::Tsv {
        path: table.path().to_path_buf(),
        row: row.number(),
        detail: format!("field {index} is not u64"),
    })
}

fn required_u16(row: Row<'_>, index: usize, table: &MappedTsv) -> Result<u16> {
    parse_u16(required(row, index, table)?).ok_or_else(|| CorpusError::Tsv {
        path: table.path().to_path_buf(),
        row: row.number(),
        detail: format!("field {index} is not u16"),
    })
}

fn dataset_path(auction_dir: &Path, kind: &str) -> Result<PathBuf> {
    let suffix = format!("_{kind}.tsv");
    let mut matches = fs::read_dir(auction_dir)
        .map_err(|error| crate::error::io(auction_dir, error))?
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.ends_with(&suffix))
        })
        .collect::<Vec<_>>();
    if matches.len() != 1 {
        return Err(CorpusError::Contract(format!(
            "expected one {kind} dataset in {}, found {}",
            auction_dir.display(),
            matches.len()
        )));
    }
    Ok(matches.pop().unwrap())
}

fn relational<T>(receipt: &TerminalReceipt, detail: String) -> Result<T> {
    Err(CorpusError::Relational {
        run_key: receipt.run_key.clone(),
        detail,
    })
}
