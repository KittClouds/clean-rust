use crate::model::{
    ATLAS_SESSIONS, DerivedPartition, PARTITION_SALT, PartitionedSession,
    REPRESENTATION_GATE_SESSIONS, SessionMeta,
};
use hashbrown::{HashMap, HashSet};
use memchr::memchr;
use rayon::prelude::*;
use sha2::{Digest, Sha256};

pub fn parse_discovery_prefix(bytes: &[u8]) -> Result<Vec<SessionMeta>, String> {
    let header_end = memchr(b'\n', bytes).ok_or("PARTITION_MANIFEST_HEADER_MISSING")?;
    let header = trim_cr(&bytes[..header_end]);
    if header != b"session_id\tcivil_date\tpartition\tserver_offset_minutes\tconfirmation_status" {
        return Err("PARTITION_MANIFEST_HEADER_MISMATCH".into());
    }

    let mut sessions = Vec::with_capacity(ATLAS_SESSIONS + REPRESENTATION_GATE_SESSIONS);
    let mut cursor = header_end + 1;
    while cursor < bytes.len() {
        let remaining = &bytes[cursor..];
        let line_end = memchr(b'\n', remaining).unwrap_or(remaining.len());
        let line = trim_cr(&remaining[..line_end]);
        cursor += line_end + usize::from(line_end < remaining.len());
        if line.is_empty() {
            continue;
        }
        if !contains_bytes(line, b"\tDISCOVERY\t") {
            continue;
        }
        let text = std::str::from_utf8(line).map_err(|_| "PARTITION_MANIFEST_NOT_UTF8")?;
        let mut fields = text.split('\t');
        let session_id = fields.next().ok_or("SESSION_ID_MISSING")?;
        let civil_date = fields.next().ok_or("CIVIL_DATE_MISSING")?;
        let partition = fields.next().ok_or("PARTITION_MISSING")?;
        let offset = fields.next().ok_or("OFFSET_MISSING")?;
        let status = fields.next().ok_or("STATUS_MISSING")?;
        if fields.next().is_some() || partition != "DISCOVERY" || status != "NOT_APPLICABLE" {
            return Err("DISCOVERY_ROW_SCHEMA_MISMATCH".into());
        }
        if civil_date.len() != 10 || !civil_date.is_char_boundary(7) {
            return Err("CIVIL_DATE_INVALID".into());
        }
        sessions.push(SessionMeta {
            session_id: session_id.to_owned(),
            civil_date: civil_date.to_owned(),
            month: civil_date[..7].to_owned(),
            server_offset_minutes: offset.parse().map_err(|_| "OFFSET_INVALID")?,
        });
    }
    Ok(sessions)
}

pub fn partition_sessions(
    mut sessions: Vec<SessionMeta>,
) -> Result<Vec<PartitionedSession>, String> {
    let mut unique = HashSet::with_capacity(sessions.len());
    if sessions
        .iter()
        .any(|s| !unique.insert(s.session_id.clone()))
    {
        return Err("DUPLICATE_DISCOVERY_SESSION".into());
    }
    sessions.par_sort_unstable_by(|a, b| {
        partition_key(&a.session_id)
            .cmp(&partition_key(&b.session_id))
            .then_with(|| a.session_id.cmp(&b.session_id))
    });
    let assigned: Vec<_> = sessions
        .into_par_iter()
        .enumerate()
        .map(|(index, session)| PartitionedSession {
            rank_key: partition_key(&session.session_id),
            partition: if index < ATLAS_SESSIONS {
                DerivedPartition::AtlasDa
            } else {
                DerivedPartition::RepresentationDb
            },
            session,
        })
        .collect();
    validate_partition(&assigned)?;
    Ok(assigned)
}

pub fn validate_partition(rows: &[PartitionedSession]) -> Result<(), String> {
    let atlas = rows
        .iter()
        .filter(|r| r.partition == DerivedPartition::AtlasDa)
        .count();
    let gate = rows.len() - atlas;
    if atlas != ATLAS_SESSIONS || gate != REPRESENTATION_GATE_SESSIONS {
        return Err(format!("DERIVED_PARTITION_SIZE_MISMATCH:{atlas}:{gate}"));
    }
    let mut by_partition_month: HashMap<(DerivedPartition, &str), usize> = HashMap::new();
    let mut by_partition_offset: HashMap<(DerivedPartition, i16), usize> = HashMap::new();
    for row in rows {
        *by_partition_month
            .entry((row.partition, row.session.month.as_str()))
            .or_default() += 1;
        *by_partition_offset
            .entry((row.partition, row.session.server_offset_minutes))
            .or_default() += 1;
    }
    let months: HashSet<&str> = rows.iter().map(|r| r.session.month.as_str()).collect();
    for partition in [
        DerivedPartition::AtlasDa,
        DerivedPartition::RepresentationDb,
    ] {
        for month in &months {
            if !by_partition_month.contains_key(&(partition, *month)) {
                return Err(format!("MONTH_ABSENT_FROM_{}:{month}", partition.as_str()));
            }
        }
        for offset in [120_i16, 180_i16] {
            if !by_partition_offset.contains_key(&(partition, offset)) {
                return Err(format!(
                    "OFFSET_ABSENT_FROM_{}:{offset}",
                    partition.as_str()
                ));
            }
        }
    }
    Ok(())
}

pub fn partition_key(session_id: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(PARTITION_SALT.as_bytes());
    hasher.update(b"|");
    hasher.update(session_id.as_bytes());
    format!("{:x}", hasher.finalize())
}

fn trim_cr(bytes: &[u8]) -> &[u8] {
    bytes.strip_suffix(b"\r").unwrap_or(bytes)
}

fn contains_bytes(haystack: &[u8], needle: &[u8]) -> bool {
    if needle.is_empty() {
        return true;
    }
    let first = needle[0];
    let mut offset = 0;
    while let Some(found) = memchr(first, &haystack[offset..]) {
        let start = offset + found;
        if haystack[start..].starts_with(needle) {
            return true;
        }
        offset = start + 1;
    }
    false
}
