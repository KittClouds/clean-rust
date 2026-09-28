//! Read-only journal follower for processes other than the writer (the Ladybug projector,
//! auditors).
//!
//! It takes no lock, never writes or truncates, and never maps a file: frames are read with
//! positional reads from shared handles. A frame is delivered only when it is complete, its
//! checksum verifies, its `seq` is the next one and its `prev` is the previous event ID. An
//! incomplete tail is "not yet committed" (the writer may still be appending, or will cut it
//! on its next open), so the follower simply stops there and resumes on the next poll.

use std::fs::File;
use std::path::{Path, PathBuf};

use kammi_jcs::{raw_id, strict_json, typed_id_of_canonical, Domain, Sha256Id};

use crate::error::{corrupt, io, Result, StoreError};
use crate::frame::{self, Decoded, SEGMENT_HEADER_LEN};
use crate::journal::StoredEvent;

#[cfg(windows)]
fn read_at(file: &File, buf: &mut [u8], offset: u64) -> std::io::Result<usize> {
    std::os::windows::fs::FileExt::seek_read(file, buf, offset)
}

#[cfg(unix)]
fn read_at(file: &File, buf: &mut [u8], offset: u64) -> std::io::Result<usize> {
    std::os::unix::fs::FileExt::read_at(file, buf, offset)
}

fn read_full(file: &File, buf: &mut [u8], mut offset: u64) -> std::io::Result<usize> {
    let mut filled = 0;
    while filled < buf.len() {
        let n = read_at(file, &mut buf[filled..], offset)?;
        if n == 0 {
            break;
        }
        filled += n;
        offset += n as u64;
    }
    Ok(filled)
}

fn open_shared(path: &Path) -> std::io::Result<File> {
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        // FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE: never block the writer.
        options.share_mode(0x1 | 0x2 | 0x4);
    }
    options.open(path)
}

pub struct JournalFollower {
    dir: PathBuf,
    segment: Option<(u64, File)>,
    offset: u64,
    seq: u64,
    head: Sha256Id,
}

impl JournalFollower {
    /// Follows `<store>/journal/<name>` from genesis.
    pub fn new(store_root: &Path, name: &str) -> JournalFollower {
        JournalFollower::resume(store_root, name, 0, Sha256Id::ZERO)
    }

    /// Resumes after `seq` whose event ID is `head` (e.g. a projection's stored position).
    /// The next delivered frame must chain to `head`.
    pub fn resume(store_root: &Path, name: &str, seq: u64, head: Sha256Id) -> JournalFollower {
        JournalFollower {
            dir: store_root.join("journal").join(name),
            segment: None,
            offset: 0,
            seq,
            head,
        }
    }

    pub fn seq(&self) -> u64 {
        self.seq
    }

    pub fn head(&self) -> Sha256Id {
        self.head
    }

    /// Sorted (first_seq, path) of the segments present now.
    fn segments(&self) -> Result<Vec<(u64, PathBuf)>> {
        let mut out = Vec::new();
        let entries = match std::fs::read_dir(&self.dir) {
            Ok(entries) => entries,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(out),
            Err(e) => return Err(io(&self.dir)(e)),
        };
        for entry in entries {
            let path = entry.map_err(|e| io(&self.dir)(e))?.path();
            if path.extension().and_then(|e| e.to_str()) != Some("seg") {
                continue;
            }
            let file = open_shared(&path).map_err(|e| io(&path)(e))?;
            let mut header = [0u8; SEGMENT_HEADER_LEN as usize];
            if read_full(&file, &mut header, 0).map_err(|e| io(&path)(e))? < header.len() {
                continue; // a segment being created: its header is not durable yet
            }
            let first = frame::parse_segment_header(&header)
                .ok_or_else(|| corrupt("segment header", &path, 0, "bad magic"))?;
            out.push((first, path));
        }
        out.sort();
        Ok(out)
    }

    /// Positions on the segment holding `self.seq + 1`, scanning forward inside it if needed.
    fn locate(&mut self) -> Result<bool> {
        let want = self.seq + 1;
        let segments = self.segments()?;
        let Some((first, path)) = segments
            .iter()
            .rev()
            .find(|(first, _)| *first <= want)
            .cloned()
        else {
            return Ok(false);
        };
        let file = open_shared(&path).map_err(|e| io(&path)(e))?;
        self.segment = Some((first, file));
        self.offset = SEGMENT_HEADER_LEN;
        // Skip frames before `want` (resume inside a segment), verifying they chain to `head`.
        let mut seq = first;
        while seq < want {
            match self.frame_at()? {
                Some((len, event_id, _, _)) => {
                    self.offset += len;
                    if seq + 1 == want && event_id != self.head {
                        return Err(corrupt(
                            "journal chain",
                            &self.dir,
                            self.offset,
                            format!("follower resume head mismatch at seq {seq}"),
                        ));
                    }
                    seq += 1;
                }
                None => {
                    return Ok(false);
                }
            }
        }
        Ok(true)
    }

    /// Reads the complete frame at the cursor: (frame len, event id, event, payload).
    #[allow(clippy::type_complexity)]
    fn frame_at(&self) -> Result<Option<(u64, Sha256Id, Vec<u8>, Vec<u8>)>> {
        let (_, file) = self.segment.as_ref().expect("located");
        let mut len = [0u8; 4];
        if read_full(file, &mut len, self.offset).map_err(|e| io(&self.dir)(e))? < 4 {
            return Ok(None);
        }
        let body = u64::from(u32::from_le_bytes(len));
        if body == 0 {
            return Ok(None); // zero-filled preallocation or a torn length: not committed
        }
        let total = 4 + body + 32;
        if total > 5 + 16 * 1024 * 1024 + 64 * 1024 * 1024 + 36 {
            return Err(corrupt(
                "journal frame",
                &self.dir,
                self.offset,
                "frame length",
            ));
        }
        let mut buf = vec![0u8; total as usize];
        let got = read_full(file, &mut buf, self.offset).map_err(|e| io(&self.dir)(e))?;
        match frame::decode(&buf[..got]) {
            Decoded::Incomplete => Ok(None),
            Decoded::Invalid(what) => Err(corrupt("journal frame", &self.dir, self.offset, what)),
            Decoded::Frame(f) => {
                let event = buf[f.event.clone()].to_vec();
                let payload = buf[f.payload.clone()].to_vec();
                Ok(Some((
                    f.total_len as u64,
                    typed_id_of_canonical(Domain::Event, &event),
                    event,
                    payload,
                )))
            }
        }
    }

    /// The next committed event, or `None` when the follower has caught up.
    pub fn next_event(&mut self) -> Result<Option<StoredEvent>> {
        if self.segment.is_none() && !self.locate()? {
            return Ok(None);
        }
        let frame = match self.frame_at()? {
            Some(frame) => frame,
            None => {
                // Caught up in this segment; a newer segment starting at the next seq means
                // the writer rolled over.
                let next = self.seq + 1;
                if self.segments()?.iter().any(|(first, _)| *first == next) {
                    self.segment = None;
                    return self.next_event();
                }
                return Ok(None);
            }
        };
        let (len, event_id, event, payload) = frame;
        let envelope = strict_json(&event)?;
        let seq = envelope["seq"].as_u64().unwrap_or(0);
        if seq != self.seq + 1 || envelope["prev"].as_str() != Some(self.head.to_string().as_str())
        {
            return Err(StoreError::Chain {
                expected_seq: self.seq + 1,
                expected_prev: self.head,
            });
        }
        self.offset += len;
        self.seq = seq;
        self.head = event_id;
        Ok(Some(StoredEvent {
            seq,
            event_id,
            payload_id: raw_id(&payload),
            event,
            payload,
        }))
    }
}
