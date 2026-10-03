use std::fs::File;
use std::path::Path;

use hashbrown::HashSet;
use memchr::memchr_iter;
use memmap2::Mmap;
use serde::Deserialize;

#[derive(Default)]
pub struct Denylist {
    pub identities: HashSet<String>,
    pub input_hashes: HashSet<String>,
    pub source_rows: Vec<(String, u64)>,
}

#[derive(Deserialize)]
struct PriorQuartet<'a> {
    #[serde(borrow)]
    quartet_id: &'a str,
    #[serde(borrow)]
    variants: Vec<PriorEvent<'a>>,
}

#[derive(Deserialize)]
struct PriorEvent<'a> {
    #[serde(borrow)]
    event_id: &'a str,
    #[serde(borrow)]
    input_sha256: &'a str,
}

#[derive(Deserialize)]
struct PriorTokenRow<'a> {
    #[serde(borrow)]
    event_id: &'a str,
    #[serde(borrow)]
    input_sha256: &'a str,
}

pub fn build_denylist(s01_corpus: &Path, s09_token_rows: &Path) -> Result<Denylist, String> {
    let mut denied = Denylist::default();
    let s01_count = read_mapped_lines(s01_corpus, |line| {
        let row: PriorQuartet<'_> = serde_json::from_slice(line)
            .map_err(|error| format!("S01-2 identity metadata parse failed: {error}"))?;
        denied
            .identities
            .insert(identity_token("world", row.quartet_id));
        denied
            .identities
            .insert(identity_token("episode", row.quartet_id));
        denied
            .identities
            .insert(identity_token("quartet", row.quartet_id));
        for event in &row.variants {
            denied
                .identities
                .insert(identity_token("event", event.event_id));
            denied.input_hashes.insert(event.input_sha256.to_owned());
        }
        Ok(())
    })?;
    let s09_count = read_mapped_lines(s09_token_rows, |line| {
        let row: PriorTokenRow<'_> = serde_json::from_slice(line)
            .map_err(|error| format!("S09 token identity metadata parse failed: {error}"))?;
        denied
            .identities
            .insert(identity_token("event", row.event_id));
        if let Some((quartet, _)) = row.event_id.rsplit_once(':') {
            denied.identities.insert(identity_token("world", quartet));
            denied.identities.insert(identity_token("episode", quartet));
            denied.identities.insert(identity_token("quartet", quartet));
        }
        denied.input_hashes.insert(row.input_sha256.to_owned());
        Ok(())
    })?;
    if s01_count != 26_624 || s09_count != 106_496 {
        return Err(format!(
            "exact ancestry denylist source counts differ: S01 quartets={s01_count}, S09 rows={s09_count}"
        ));
    }
    denied
        .source_rows
        .push(("S01-2_QUARTETS".to_owned(), s01_count));
    denied
        .source_rows
        .push(("S09_TOKEN_ROWS".to_owned(), s09_count));
    // S10 reused the S09 population. The S10 sealed parent receipt is verified separately.
    denied
        .source_rows
        .push(("S10_INHERITED_S09_ROWS".to_owned(), s09_count));
    Ok(denied)
}

fn read_mapped_lines<F>(path: &Path, mut visit: F) -> Result<u64, String>
where
    F: FnMut(&[u8]) -> Result<(), String>,
{
    let file = File::open(path).map_err(|error| format!("open {}: {error}", path.display()))?;
    // SAFETY: the mapping is read-only, the file remains open for the mapping lifetime,
    // and this process never mutates the ancestry files.
    let map =
        unsafe { Mmap::map(&file) }.map_err(|error| format!("mmap {}: {error}", path.display()))?;
    let mut start = 0;
    let mut count = 0_u64;
    for end in memchr_iter(b'\n', &map) {
        if end > start {
            visit(&map[start..end])?;
            count += 1;
        }
        start = end + 1;
    }
    if start < map.len() {
        visit(&map[start..])?;
        count += 1;
    }
    Ok(count)
}

fn identity_token(kind: &str, raw_id: &str) -> String {
    let mut bytes = Vec::with_capacity(kind.len() + raw_id.len() + 1);
    bytes.extend_from_slice(kind.as_bytes());
    bytes.push(b'|');
    bytes.extend_from_slice(raw_id.as_bytes());
    crate::generate::sha256_hex(&bytes)
}
