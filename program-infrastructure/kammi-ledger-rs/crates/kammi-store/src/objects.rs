//! Content-addressed objects: small objects in append-only packs, large ones loose.
//!
//! ```text
//! objects/packs/pack-00000001.pack   "KMPACK02" | pack_no u64 | records...
//!   record: len u32 LE | id [32] | bytes
//! objects/packs/index.log            "KMPIDX02" | reserved u64 | entries...   (derived)
//!   entry:  id [32] | location u64 LE | len u32 LE | reserved u32
//! objects/packs/packs.tbl            sorted id -> location table            (derived)
//! objects/sha256/ab/cdef...          loose objects, same path rule as v1
//! ```
//!
//! Identities are unchanged: every object is still named by the SHA-256 of its raw bytes.
//! `put_*` returns only after the bytes are durable, so an event committed afterwards can
//! never reference a missing object. Index files are rebuilt from the packs when damaged.

use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use hashbrown::HashSet;
use kammi_jcs::{raw_id, Sha256Hasher, Sha256Id};

use crate::durable::{self, read_exact_at};
use crate::error::{corrupt, io, Result, StoreError};
use crate::fault;
use crate::keyindex::{remove_if_exists, KeyIndex, SortedTable};

const PACK_MAGIC: [u8; 8] = *b"KMPACK02";
const PACK_HEADER_LEN: u64 = 16;
const LOG_MAGIC: [u8; 8] = *b"KMPIDX02";
const LOG_HEADER_LEN: u64 = 16;
const LOG_ENTRY_LEN: usize = 48;
const RECORD_HEADER_LEN: u64 = 36;
const OFFSET_BITS: u32 = 40;

#[derive(Debug, Clone)]
pub struct ObjectOptions {
    /// Objects smaller than this are packed; larger ones are stored loose.
    pub pack_threshold: usize,
    /// A pack is sealed once appending would take it past this size.
    pub max_pack_bytes: u64,
}

impl Default for ObjectOptions {
    fn default() -> Self {
        ObjectOptions {
            pack_threshold: 256 * 1024,
            max_pack_bytes: 1024 * 1024 * 1024,
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ObjectReport {
    pub packed: u64,
    pub packed_bytes: u64,
    pub loose: u64,
    pub loose_bytes: u64,
    pub packs: usize,
}

fn location(pack: u32, offset: u64) -> u64 {
    (u64::from(pack) << OFFSET_BITS) | offset
}

fn split_location(loc: u64) -> (u32, u64) {
    ((loc >> OFFSET_BITS) as u32, loc & ((1 << OFFSET_BITS) - 1))
}

struct Pack {
    number: u32,
    path: PathBuf,
    file: File,
}

pub struct Objects {
    dir: PathBuf,
    opts: ObjectOptions,
    packs: Vec<Pack>,
    writer: File,
    active_len: u64,
    log: File,
    log_entries: u64,
    index: KeyIndex<32>,
    poisoned: bool,
    recovered: Vec<PathBuf>,
}

impl Objects {
    fn packs_dir(dir: &Path) -> PathBuf {
        dir.join("packs")
    }

    fn pack_path(dir: &Path, number: u32) -> PathBuf {
        Self::packs_dir(dir).join(format!("pack-{number:08}.pack"))
    }

    fn staging(&self) -> PathBuf {
        self.dir.join("staging")
    }

    pub fn loose_path(&self, id: &Sha256Id) -> PathBuf {
        let text = id.to_string();
        self.dir.join("sha256").join(&text[7..9]).join(&text[9..])
    }

    pub fn open(dir: &Path, opts: ObjectOptions) -> Result<Objects> {
        let packs_dir = Self::packs_dir(dir);
        durable::create_dir_all(&packs_dir)?;
        durable::create_dir_all(&dir.join("sha256"))?;
        let mut numbers: Vec<u32> = Vec::new();
        for entry in fs::read_dir(&packs_dir).map_err(io(&packs_dir))? {
            let name = entry
                .map_err(io(&packs_dir))?
                .file_name()
                .to_string_lossy()
                .into_owned();
            if let Some(n) = name
                .strip_prefix("pack-")
                .and_then(|n| n.strip_suffix(".pack"))
                .and_then(|n| n.parse().ok())
            {
                numbers.push(n);
            }
        }
        numbers.sort_unstable();
        if numbers
            .iter()
            .enumerate()
            .any(|(i, n)| *n as usize != i + 1)
        {
            return Err(corrupt(
                "object packs",
                &packs_dir,
                0,
                "pack numbers are not contiguous",
            ));
        }
        if numbers.is_empty() {
            create_pack(dir, 1)?;
            numbers.push(1);
        }
        let mut packs = Vec::new();
        for number in &numbers {
            let path = Self::pack_path(dir, *number);
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .open(&path)
                .map_err(io(&path))?;
            let mut header = [0u8; 16];
            let length = file.metadata().map_err(io(&path))?.len();
            if length < PACK_HEADER_LEN
                || read_exact_at(&file, &mut header, 0).is_err()
                || header[..8] != PACK_MAGIC
                || u64::from_le_bytes(header[8..].try_into().unwrap()) != u64::from(*number)
            {
                if *number == *numbers.last().unwrap() && length < PACK_HEADER_LEN {
                    // Crash while a new pack was being created: it holds nothing yet.
                    drop(file);
                    create_pack(dir, *number)?;
                    let file = OpenOptions::new()
                        .read(true)
                        .write(true)
                        .open(&path)
                        .map_err(io(&path))?;
                    packs.push(Pack {
                        number: *number,
                        path,
                        file,
                    });
                    continue;
                }
                return Err(corrupt("object pack", &path, 0, "bad pack header"));
            }
            packs.push(Pack {
                number: *number,
                path,
                file,
            });
        }

        let log_path = packs_dir.join("index.log");
        let table_path = packs_dir.join("packs.tbl");
        // Entries naming bytes beyond a pack's end describe records lost to a torn tail; they
        // are dropped and the log is rewritten so they cannot resurface.
        let mut stale = false;
        let mut entries = read_log(&log_path).map(|entries| {
            let total = entries.len();
            let kept: Vec<_> = entries
                .into_iter()
                .filter(|e| entry_in_bounds(e, &packs))
                .collect();
            stale = kept.len() != total;
            kept
        });
        // Every entry must describe a record that exists; otherwise rebuild from the packs.
        if let Some(list) = &entries {
            if !list.iter().all(|e| record_matches(&packs, e)) {
                entries = None;
            }
        }
        let rebuilt = entries.is_none();
        let mut entries = match entries {
            Some(entries) => entries,
            None => {
                let mut all = Vec::new();
                for (i, pack) in packs.iter().enumerate() {
                    let last = i + 1 == packs.len();
                    let (found, _) = scan_pack(pack, PACK_HEADER_LEN, last)?;
                    all.extend(found);
                }
                all
            }
        };
        // Recover records appended after the last logged one, and repair a torn pack tail.
        let active = packs.last().unwrap();
        let scan_from = entries
            .iter()
            .filter(|e| split_location(e.1).0 == active.number)
            .map(|e| split_location(e.1).1 + RECORD_HEADER_LEN + u64::from(e.2))
            .max()
            .unwrap_or(PACK_HEADER_LEN);
        let (found, torn) = scan_pack(active, scan_from, true)?;
        let recovered_count = found.len();
        entries.extend(found);
        let mut recovered = Vec::new();
        if let Some(offset) = torn {
            if let Some(saved) =
                durable::quarantine_tail(&active.file, &active.path, offset, &dir.join("recovery"))?
            {
                recovered.push(saved);
            }
        }
        if rebuilt || stale || recovered_count > 0 {
            let mut bytes = log_header().to_vec();
            for entry in &entries {
                bytes.extend_from_slice(&encode_entry(entry));
            }
            durable::publish(&dir.join("staging"), &log_path, &bytes)?;
            remove_if_exists(&table_path)?;
        }
        let log_entries = entries.len() as u64;
        let table = SortedTable::<32>::open(&table_path).filter(|t| t.covered() <= log_entries);
        if table.is_none() {
            remove_if_exists(&table_path)?;
        }
        let mut index = KeyIndex::with_table(table);
        for entry in entries.iter().skip(index.covered() as usize) {
            index.insert(entry.0, entry.1);
        }
        drop(entries);
        let active_path = packs.last().unwrap().path.clone();
        let writer = OpenOptions::new()
            .append(true)
            .open(&active_path)
            .map_err(io(&active_path))?;
        let active_len = writer.metadata().map_err(io(&active_path))?.len();
        let log = OpenOptions::new()
            .append(true)
            .open(&log_path)
            .map_err(io(&log_path))?;
        Ok(Objects {
            dir: dir.to_path_buf(),
            opts,
            packs,
            writer,
            active_len,
            log,
            log_entries,
            index,
            poisoned: false,
            recovered,
        })
    }

    pub fn recovered_tails(&self) -> &[PathBuf] {
        &self.recovered
    }

    pub fn pack_count(&self) -> usize {
        self.packs.len()
    }

    fn packed_location(&self, id: &Sha256Id) -> Option<(u32, u64)> {
        self.index.get(&id.0).map(split_location)
    }

    fn loose_len(&self, id: &Sha256Id) -> Option<u64> {
        match fs::symlink_metadata(self.loose_path(id)) {
            Ok(meta) if meta.is_file() => Some(meta.len()),
            _ => None,
        }
    }

    pub fn contains(&self, id: &Sha256Id) -> bool {
        self.packed_location(id).is_some() || self.loose_len(id).is_some()
    }

    /// Size of an object without reading it.
    pub fn len(&self, id: &Sha256Id) -> Result<Option<u64>> {
        if let Some((pack, offset)) = self.packed_location(id) {
            let mut header = [0u8; 4];
            let pack = &self.packs[pack as usize - 1];
            read_exact_at(&pack.file, &mut header, offset).map_err(io(&pack.path))?;
            return Ok(Some(u64::from(u32::from_le_bytes(header))));
        }
        Ok(self.loose_len(id))
    }

    /// Reads and verifies a whole object.
    pub fn get(&self, id: &Sha256Id) -> Result<Option<Vec<u8>>> {
        if let Some((pack_no, offset)) = self.packed_location(id) {
            let pack = &self.packs[pack_no as usize - 1];
            let mut header = [0u8; 36];
            read_exact_at(&pack.file, &mut header, offset).map_err(io(&pack.path))?;
            let length = u32::from_le_bytes(header[..4].try_into().unwrap()) as usize;
            let mut bytes = vec![0u8; length];
            read_exact_at(&pack.file, &mut bytes, offset + RECORD_HEADER_LEN)
                .map_err(io(&pack.path))?;
            if header[4..] != id.0 || raw_id(&bytes) != *id {
                return Err(StoreError::ObjectCorrupt(*id));
            }
            return Ok(Some(bytes));
        }
        let path = self.loose_path(id);
        if self.loose_len(id).is_none() {
            return Ok(None);
        }
        let bytes = fs::read(&path).map_err(io(&path))?;
        if raw_id(&bytes) != *id {
            return Err(StoreError::ObjectCorrupt(*id));
        }
        Ok(Some(bytes))
    }

    /// Verifies an object, then streams it to `out`. Large objects are never held in memory.
    pub fn copy_to(&self, id: &Sha256Id, out: &mut dyn Write) -> Result<u64> {
        if self.packed_location(id).is_some() {
            let bytes = self.get(id)?.ok_or(StoreError::ObjectMissing(*id))?;
            out.write_all(&bytes).map_err(io(&self.dir))?;
            return Ok(bytes.len() as u64);
        }
        let path = self.loose_path(id);
        if !self.verify_loose(id)? {
            return Err(if self.loose_len(id).is_some() {
                StoreError::ObjectCorrupt(*id)
            } else {
                StoreError::ObjectMissing(*id)
            });
        }
        let mut file = File::open(&path).map_err(io(&path))?;
        let mut hasher = Sha256Hasher::new();
        let mut buffer = vec![0u8; 1 << 20];
        let mut total = 0u64;
        loop {
            let read = file.read(&mut buffer).map_err(io(&path))?;
            if read == 0 {
                break;
            }
            hasher.update(&buffer[..read]);
            out.write_all(&buffer[..read]).map_err(io(&path))?;
            total += read as u64;
        }
        // Detects a change between the verification pass and the copy pass.
        if hasher.finish() != *id {
            return Err(StoreError::ObjectCorrupt(*id));
        }
        Ok(total)
    }

    fn verify_loose(&self, id: &Sha256Id) -> Result<bool> {
        let path = self.loose_path(id);
        if self.loose_len(id).is_none() {
            return Ok(false);
        }
        let mut file = File::open(&path).map_err(io(&path))?;
        let mut hasher = Sha256Hasher::new();
        let mut buffer = vec![0u8; 1 << 20];
        loop {
            let read = file.read(&mut buffer).map_err(io(&path))?;
            if read == 0 {
                break;
            }
            hasher.update(&buffer[..read]);
        }
        Ok(hasher.finish() == *id)
    }

    /// Stores one object durably and returns its identity.
    pub fn put(&mut self, bytes: &[u8]) -> Result<Sha256Id> {
        Ok(self.put_many(&[bytes])?[0])
    }

    /// Stores many objects with one flush for all packed ones. Existing objects are verified
    /// rather than rewritten, like `cas.py`.
    pub fn put_many(&mut self, items: &[&[u8]]) -> Result<Vec<Sha256Id>> {
        if self.poisoned {
            return Err(StoreError::Poisoned("objects".into()));
        }
        let mut ids = Vec::with_capacity(items.len());
        let mut pending: Vec<(Sha256Id, &[u8])> = Vec::new();
        let mut seen = HashSet::new();
        for bytes in items {
            let id = raw_id(bytes);
            ids.push(id);
            if !seen.insert(id) {
                continue;
            }
            if self.contains(&id) {
                if self.get(&id)?.is_none() {
                    return Err(StoreError::ObjectMissing(id));
                }
                continue;
            }
            if bytes.len() >= self.opts.pack_threshold {
                self.put_loose_bytes(&id, bytes)?;
            } else {
                pending.push((id, bytes));
            }
        }
        if !pending.is_empty() {
            let result = self.append_packed(&pending);
            if result.is_err() {
                self.poisoned = true;
            }
            result?;
        }
        Ok(ids)
    }

    fn append_packed(&mut self, pending: &[(Sha256Id, &[u8])]) -> Result<()> {
        let mut buffer = Vec::new();
        let mut entries: Vec<([u8; 32], u64, u32)> = Vec::new();
        for (id, bytes) in pending {
            let record_len = RECORD_HEADER_LEN + bytes.len() as u64;
            let end = self.active_len + buffer.len() as u64;
            if end > PACK_HEADER_LEN && end + record_len > self.opts.max_pack_bytes {
                self.flush_packed(&mut buffer, &mut entries)?;
                self.rollover()?;
            }
            let offset = self.active_len + buffer.len() as u64;
            buffer.extend_from_slice(&(bytes.len() as u32).to_le_bytes());
            buffer.extend_from_slice(&id.0);
            buffer.extend_from_slice(bytes);
            entries.push((
                id.0,
                location(self.packs.last().unwrap().number, offset),
                bytes.len() as u32,
            ));
        }
        self.flush_packed(&mut buffer, &mut entries)
    }

    fn flush_packed(
        &mut self,
        buffer: &mut Vec<u8>,
        entries: &mut Vec<([u8; 32], u64, u32)>,
    ) -> Result<()> {
        if entries.is_empty() {
            return Ok(());
        }
        let path = self.packs.last().unwrap().path.clone();
        fault::hit("cas.before_write");
        self.writer.write_all(buffer).map_err(io(&path))?;
        fault::hit("cas.after_write");
        self.writer.sync_data().map_err(io(&path))?;
        fault::hit("cas.after_fsync");
        let mut log_bytes = Vec::with_capacity(entries.len() * LOG_ENTRY_LEN);
        for entry in entries.iter() {
            log_bytes.extend_from_slice(&encode_entry(entry));
        }
        let log_path = Self::packs_dir(&self.dir).join("index.log");
        self.log.write_all(&log_bytes).map_err(io(&log_path))?;
        fault::hit("cas.after_index");
        for entry in entries.iter() {
            self.index.insert(entry.0, entry.1);
        }
        self.active_len += buffer.len() as u64;
        self.log_entries += entries.len() as u64;
        buffer.clear();
        entries.clear();
        Ok(())
    }

    fn rollover(&mut self) -> Result<()> {
        let number = self.packs.last().unwrap().number + 1;
        create_pack(&self.dir, number)?;
        let path = Self::pack_path(&self.dir, number);
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .map_err(io(&path))?;
        self.writer = OpenOptions::new()
            .append(true)
            .open(&path)
            .map_err(io(&path))?;
        self.active_len = PACK_HEADER_LEN;
        self.packs.push(Pack { number, path, file });
        Ok(())
    }

    fn put_loose_bytes(&mut self, id: &Sha256Id, bytes: &[u8]) -> Result<()> {
        let target = self.loose_path(id);
        let staging = self.staging();
        fault::hit("cas.before_write");
        durable::publish_with(
            &staging,
            &target,
            bytes,
            Some("cas.after_fsync"),
            Some("cas.after_rename"),
        )
    }

    /// Streams a (possibly huge) source into the store, hashing while copying. When
    /// `expected` is given the stream must hash to it. Small results are packed.
    pub fn put_stream(
        &mut self,
        source: &mut dyn Read,
        expected: Option<Sha256Id>,
    ) -> Result<Sha256Id> {
        let staging = self.staging();
        durable::create_dir_all(&staging)?;
        let temp = staging.join(format!(
            "stream-{}-{}",
            std::process::id(),
            self.log_entries
        ));
        let result = (|| {
            let mut out = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temp)
                .map_err(io(&temp))?;
            let mut hasher = Sha256Hasher::new();
            let mut buffer = vec![0u8; 1 << 20];
            let mut size = 0u64;
            fault::hit("cas.before_write");
            loop {
                let read = source.read(&mut buffer).map_err(io(&temp))?;
                if read == 0 {
                    break;
                }
                hasher.update(&buffer[..read]);
                out.write_all(&buffer[..read]).map_err(io(&temp))?;
                size += read as u64;
            }
            fault::hit("cas.after_write");
            durable::sync(&out, &temp)?;
            drop(out);
            fault::hit("cas.after_fsync");
            let id = hasher.finish();
            if expected.is_some_and(|e| e != id) {
                return Err(StoreError::ObjectCorrupt(expected.unwrap()));
            }
            if self.contains(&id) {
                if !self.verify_existing(&id)? {
                    return Err(StoreError::ObjectCorrupt(id));
                }
                return Ok(id);
            }
            if (size as usize) < self.opts.pack_threshold {
                let bytes = fs::read(&temp).map_err(io(&temp))?;
                self.put_many(&[&bytes])?;
            } else {
                let target = self.loose_path(&id);
                durable::create_dir_all(target.parent().unwrap())?;
                fs::rename(&temp, &target).map_err(io(&target))?;
                fault::hit("cas.after_rename");
                durable::sync_dir(target.parent().unwrap())?;
            }
            Ok(id)
        })();
        let _ = fs::remove_file(&temp);
        result
    }

    /// Re-hashes a stored object; `false` when it is missing or corrupt (`cas.verify`).
    pub fn verify(&self, id: &Sha256Id) -> Result<bool> {
        if self.packed_location(id).is_some() {
            return Ok(matches!(self.get(id), Ok(Some(_))));
        }
        self.verify_loose(id)
    }

    fn verify_existing(&self, id: &Sha256Id) -> Result<bool> {
        if self.packed_location(id).is_some() {
            return Ok(self.get(id).is_ok());
        }
        self.verify_loose(id)
    }

    /// Every stored identity: packed ones from the index, loose ones from the directory.
    pub fn ids(&self) -> Result<Vec<Sha256Id>> {
        let mut ids: HashSet<Sha256Id> = HashSet::new();
        for entry in read_log(&Self::packs_dir(&self.dir).join("index.log")).unwrap_or_default() {
            ids.insert(Sha256Id(entry.0));
        }
        let base = self.dir.join("sha256");
        for prefix in fs::read_dir(&base).map_err(io(&base))? {
            let prefix = prefix.map_err(io(&base))?;
            let prefix_name = prefix.file_name().to_string_lossy().into_owned();
            if prefix_name.len() != 2 {
                continue;
            }
            for entry in fs::read_dir(prefix.path()).map_err(io(prefix.path()))? {
                let entry = entry.map_err(io(prefix.path()))?;
                let text = format!(
                    "sha256:{prefix_name}{}",
                    entry.file_name().to_string_lossy()
                );
                if let Ok(id) = Sha256Id::parse(&text) {
                    ids.insert(id);
                }
            }
        }
        let mut ids: Vec<_> = ids.into_iter().collect();
        ids.sort_unstable();
        Ok(ids)
    }

    /// Rewrites the sorted table to cover every logged entry and empties the memory tail.
    pub fn compact_index(&mut self) -> Result<()> {
        let packs_dir = Self::packs_dir(&self.dir);
        let mut entries: Vec<([u8; 32], u64)> = read_log(&packs_dir.join("index.log"))
            .ok_or_else(|| corrupt("object index", &packs_dir, 0, "index.log unreadable"))?
            .into_iter()
            .map(|e| (e.0, e.1))
            .collect();
        drop(self.index.release_table());
        let table_path = packs_dir.join("packs.tbl");
        SortedTable::write(
            &self.staging(),
            &table_path,
            entries.len() as u64,
            &mut entries,
        )?;
        self.index = KeyIndex::with_table(SortedTable::open(&table_path));
        Ok(())
    }

    pub fn tail_entries(&self) -> usize {
        self.index.tail_len()
    }

    /// Re-reads every pack record and loose object and checks every digest, plus the index.
    pub fn verify_deep(&self) -> Result<ObjectReport> {
        let mut report = ObjectReport {
            packs: self.packs.len(),
            ..Default::default()
        };
        let mut from_packs = Vec::new();
        for (i, pack) in self.packs.iter().enumerate() {
            let (found, torn) = scan_pack(pack, PACK_HEADER_LEN, i + 1 == self.packs.len())?;
            if let Some(offset) = torn {
                return Err(corrupt(
                    "object pack",
                    &pack.path,
                    offset,
                    "unexpected torn tail",
                ));
            }
            for entry in &found {
                report.packed += 1;
                report.packed_bytes += u64::from(entry.2);
            }
            from_packs.extend(found);
        }
        let logged = read_log(&Self::packs_dir(&self.dir).join("index.log"))
            .ok_or_else(|| corrupt("object index", &self.dir, 0, "index.log unreadable"))?;
        if logged != from_packs {
            return Err(corrupt(
                "object index",
                &self.dir,
                0,
                "index.log differs from pack records",
            ));
        }
        for entry in &from_packs {
            match self.index.get(&entry.0) {
                Some(loc) if record_matches(&self.packs, &(entry.0, loc, entry.2)) => {}
                _ => {
                    return Err(corrupt(
                        "object index",
                        &self.dir,
                        0,
                        "lookup does not resolve to a record",
                    ))
                }
            }
        }
        if self
            .index
            .table
            .as_ref()
            .is_some_and(|t| !t.is_sorted_unique())
        {
            return Err(corrupt("object table", &self.dir, 0, "table not sorted"));
        }
        for id in self.ids()? {
            if self.packed_location(&id).is_some() {
                continue;
            }
            if !self.verify_loose(&id)? {
                return Err(StoreError::ObjectCorrupt(id));
            }
            report.loose += 1;
            report.loose_bytes += self.loose_len(&id).unwrap_or(0);
        }
        Ok(report)
    }
}

fn create_pack(dir: &Path, number: u32) -> Result<()> {
    let path = Objects::pack_path(dir, number);
    let mut file = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(&path)
        .map_err(io(&path))?;
    let mut header = [0u8; 16];
    header[..8].copy_from_slice(&PACK_MAGIC);
    header[8..].copy_from_slice(&u64::from(number).to_le_bytes());
    file.write_all(&header).map_err(io(&path))?;
    durable::sync(&file, &path)?;
    durable::sync_dir(&Objects::packs_dir(dir))?;
    Ok(())
}

fn log_header() -> [u8; 16] {
    let mut header = [0u8; 16];
    header[..8].copy_from_slice(&LOG_MAGIC);
    header
}

type Entry = ([u8; 32], u64, u32);

fn encode_entry(entry: &Entry) -> [u8; LOG_ENTRY_LEN] {
    let mut out = [0u8; LOG_ENTRY_LEN];
    out[..32].copy_from_slice(&entry.0);
    out[32..40].copy_from_slice(&entry.1.to_le_bytes());
    out[40..44].copy_from_slice(&entry.2.to_le_bytes());
    out
}

/// Reads index.log, ignoring a torn trailing entry. `None` for a missing or foreign file.
fn read_log(path: &Path) -> Option<Vec<Entry>> {
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return None,
        Err(_) => return None,
    };
    if bytes.len() < LOG_HEADER_LEN as usize || bytes[..8] != LOG_MAGIC {
        return None;
    }
    let body = &bytes[LOG_HEADER_LEN as usize..];
    if body.len() % LOG_ENTRY_LEN != 0 {
        return None;
    }
    Some(
        body.chunks_exact(LOG_ENTRY_LEN)
            .map(|c| {
                (
                    c[..32].try_into().unwrap(),
                    u64::from_le_bytes(c[32..40].try_into().unwrap()),
                    u32::from_le_bytes(c[40..44].try_into().unwrap()),
                )
            })
            .collect(),
    )
}

fn entry_in_bounds(entry: &Entry, packs: &[Pack]) -> bool {
    let (pack, offset) = split_location(entry.1);
    pack >= 1
        && (pack as usize) <= packs.len()
        && packs[pack as usize - 1]
            .file
            .metadata()
            .map(|m| offset + RECORD_HEADER_LEN + u64::from(entry.2) <= m.len())
            .unwrap_or(false)
}

fn record_matches(packs: &[Pack], entry: &Entry) -> bool {
    let (pack, offset) = split_location(entry.1);
    let Some(pack) = packs.get((pack as usize).wrapping_sub(1)) else {
        return false;
    };
    let mut header = [0u8; 36];
    read_exact_at(&pack.file, &mut header, offset).is_ok()
        && u32::from_le_bytes(header[..4].try_into().unwrap()) == entry.2
        && header[4..] == entry.0
}

/// Walks pack records from `from`, verifying each digest. On the active pack an incomplete
/// or zero-filled tail is reported as torn; anything else malformed is corruption.
fn scan_pack(pack: &Pack, from: u64, active: bool) -> Result<(Vec<Entry>, Option<u64>)> {
    let length = pack.file.metadata().map_err(io(&pack.path))?.len();
    let mut bytes = vec![0u8; length.saturating_sub(from) as usize];
    read_exact_at(&pack.file, &mut bytes, from).map_err(io(&pack.path))?;
    let mut entries = Vec::new();
    let mut position = 0usize;
    while position < bytes.len() {
        let offset = from + position as u64;
        let rest = &bytes[position..];
        let torn = |reason: &'static str| -> Result<(Vec<Entry>, Option<u64>)> {
            if active && (rest.len() < RECORD_HEADER_LEN as usize || rest.iter().all(|b| *b == 0)) {
                Ok((Vec::new(), Some(offset)))
            } else {
                Err(corrupt("object pack", &pack.path, offset, reason))
            }
        };
        if rest.len() < RECORD_HEADER_LEN as usize {
            let (_, t) = torn("incomplete record header")?;
            return Ok((entries, t));
        }
        let length = u32::from_le_bytes(rest[..4].try_into().unwrap()) as usize;
        let id: [u8; 32] = rest[4..36].try_into().unwrap();
        if rest.len() < RECORD_HEADER_LEN as usize + length {
            if active {
                return Ok((entries, Some(offset)));
            }
            return Err(corrupt(
                "object pack",
                &pack.path,
                offset,
                "incomplete record",
            ));
        }
        let body = &rest[36..36 + length];
        if raw_id(body).0 != id {
            let (_, t) = torn("record digest mismatch")?;
            return Ok((entries, t));
        }
        entries.push((id, location(pack.number, offset), length as u32));
        position += RECORD_HEADER_LEN as usize + length;
    }
    Ok((entries, None))
}
