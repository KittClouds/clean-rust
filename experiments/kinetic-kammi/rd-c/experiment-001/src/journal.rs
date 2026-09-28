use std::{
    fs::File,
    io::{self, BufWriter, Write},
    path::Path,
};

use memchr::memchr_iter;
use memmap2::MmapOptions;
use zerocopy::{FromBytes, Immutable, IntoBytes, KnownLayout, Unaligned};

use crate::{Action, DecisionCompiler, Evidence, Proposal, Receipt, Runtime, State};

const MAGIC: [u8; 4] = *b"RDC1";
const VERSION: [u8; 2] = [1, 0];

#[derive(FromBytes, IntoBytes, KnownLayout, Immutable, Unaligned)]
#[repr(C)]
struct JournalHeader {
    magic: [u8; 4],
    version: [u8; 2],
    reserved: [u8; 2],
    entry_count_le: [u8; 8],
}

impl JournalHeader {
    fn new(entry_count: usize) -> Self {
        Self {
            magic: MAGIC,
            version: VERSION,
            reserved: [0; 2],
            entry_count_le: (entry_count as u64).to_le_bytes(),
        }
    }
}

#[derive(Debug)]
pub enum JournalError {
    Io(io::Error),
    InvalidHeader,
    InvalidRow,
    SequenceMismatch { expected: u64, actual: u64 },
    ReplayMismatch { sequence: u64 },
    CountMismatch { expected: usize, actual: usize },
}

impl std::fmt::Display for JournalError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(f, "journal I/O error: {error}"),
            Self::InvalidHeader => f.write_str("invalid journal header"),
            Self::InvalidRow => f.write_str("invalid journal row"),
            Self::SequenceMismatch { expected, actual } => write!(
                f,
                "journal sequence mismatch: expected {expected}, got {actual}"
            ),
            Self::ReplayMismatch { sequence } => {
                write!(f, "receipt identity mismatch at sequence {sequence}")
            }
            Self::CountMismatch { expected, actual } => write!(
                f,
                "journal row count mismatch: expected {expected}, got {actual}"
            ),
        }
    }
}

impl std::error::Error for JournalError {}

impl From<io::Error> for JournalError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReplayReport {
    pub receipt_count: usize,
    pub rejected_count: usize,
    pub recovery_count: u8,
    pub completed: bool,
    pub final_hash: [u8; 32],
}

/// Writes a complete immutable journal. The caller should close the writer before replay.
pub fn write_journal(path: impl AsRef<Path>, receipts: &[Receipt]) -> Result<(), JournalError> {
    let file = File::create(path)?;
    let mut writer = BufWriter::with_capacity(16 * 1024, file);
    let header = JournalHeader::new(receipts.len());
    writer.write_all(header.as_bytes())?;
    for receipt in receipts {
        write!(
            writer,
            "{}\t{}\t{}\t{}\t",
            receipt.sequence,
            receipt.proposal.from as u8,
            receipt.proposal.requested_to as u8,
            receipt.proposal.action as u8,
        )?;
        match receipt.proposal.confidence {
            Some(value) => write!(writer, "{value}")?,
            None => writer.write_all(b"-")?,
        }
        writer.write_all(b"\t")?;
        match receipt.proposal.evidence {
            Some(evidence) => {
                write!(writer, "{}", evidence.code)?;
                writer.write_all(b"\t")?;
                write_hex(&mut writer, &evidence.digest)?;
            }
            None => writer.write_all(b"-\t-")?,
        }
        writer.write_all(b"\t")?;
        write_hex(&mut writer, &receipt.hash)?;
        writer.write_all(b"\n")?;
    }
    writer.flush()?;
    Ok(())
}

fn write_hex(writer: &mut impl Write, bytes: &[u8]) -> io::Result<()> {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for byte in bytes {
        writer.write_all(&[HEX[(byte >> 4) as usize], HEX[(byte & 0xf) as usize]])?;
    }
    Ok(())
}

struct ReplayRow {
    sequence: u64,
    proposal: Proposal,
    expected_hash: [u8; 32],
}

/// Replays a closed immutable journal through the deterministic runtime.
///
/// # Safety
/// The caller must ensure that no other thread or process mutates the file while this
/// function maps and reads it. Mutating a mapped file can invalidate the memory view.
pub unsafe fn replay_mmap(
    path: impl AsRef<Path>,
    compiler: DecisionCompiler,
) -> Result<(Runtime, ReplayReport), JournalError> {
    let file = File::open(path)?;
    if file.metadata()?.len() == 0 {
        return Err(JournalError::InvalidHeader);
    }
    // SAFETY: upheld by this function's caller contract: the journal is closed and immutable.
    let map = unsafe { MmapOptions::new().map(&file)? };
    let (header, body) =
        JournalHeader::ref_from_prefix(&map).map_err(|_| JournalError::InvalidHeader)?;
    if header.magic != MAGIC || header.version != VERSION || header.reserved != [0; 2] {
        return Err(JournalError::InvalidHeader);
    }
    let expected_rows = u64::from_le_bytes(header.entry_count_le) as usize;
    let mut runtime = Runtime::with_capacity(compiler, expected_rows);
    let mut parsed_rows = 0usize;
    let mut row_start = 0usize;

    for end in memchr_iter(b'\n', body) {
        let row = parse_row(&body[row_start..end])?;
        if row.sequence != parsed_rows as u64 {
            return Err(JournalError::SequenceMismatch {
                expected: parsed_rows as u64,
                actual: row.sequence,
            });
        }
        let receipt = runtime.apply(row.proposal);
        if receipt.hash != row.expected_hash {
            return Err(JournalError::ReplayMismatch {
                sequence: row.sequence,
            });
        }
        parsed_rows += 1;
        row_start = end + 1;
    }
    if row_start != body.len() {
        return Err(JournalError::InvalidRow);
    }
    if parsed_rows != expected_rows {
        return Err(JournalError::CountMismatch {
            expected: expected_rows,
            actual: parsed_rows,
        });
    }

    let rejected_count = runtime
        .receipts()
        .iter()
        .filter(|receipt| !receipt.accepted())
        .count();
    let final_hash = runtime
        .receipts()
        .last()
        .map_or([0; 32], |receipt| receipt.hash);
    let report = ReplayReport {
        receipt_count: parsed_rows,
        rejected_count,
        recovery_count: runtime.recovery_count(),
        completed: runtime.state() == State::Done,
        final_hash,
    };
    Ok((runtime, report))
}

fn parse_row(row: &[u8]) -> Result<ReplayRow, JournalError> {
    let mut fields: [&[u8]; 8] = [&[]; 8];
    let mut start = 0usize;
    let mut count = 0usize;
    for delimiter in memchr_iter(b'\t', row) {
        if count >= 7 {
            return Err(JournalError::InvalidRow);
        }
        fields[count] = &row[start..delimiter];
        count += 1;
        start = delimiter + 1;
    }
    if count != 7 {
        return Err(JournalError::InvalidRow);
    }
    fields[7] = &row[start..];

    let sequence = parse_u64(fields[0])?;
    let from = State::try_from(parse_u8(fields[1])?).map_err(|_| JournalError::InvalidRow)?;
    let to = State::try_from(parse_u8(fields[2])?).map_err(|_| JournalError::InvalidRow)?;
    let action = Action::try_from(parse_u8(fields[3])?).map_err(|_| JournalError::InvalidRow)?;
    let confidence = optional_u16(fields[4])?;
    let (evidence_code, evidence_digest) = if fields[5] == b"-" {
        if fields[6] != b"-" {
            return Err(JournalError::InvalidRow);
        }
        (None, None)
    } else {
        let code = parse_u16(fields[5])?;
        let digest = parse_hex_16(fields[6])?;
        (Some(code), Some(digest))
    };
    let evidence = match (evidence_code, evidence_digest) {
        (Some(code), Some(digest)) => Some(Evidence { code, digest }),
        (None, None) => None,
        _ => return Err(JournalError::InvalidRow),
    };
    let expected_hash = parse_hex_32(fields[7])?;
    Ok(ReplayRow {
        sequence,
        proposal: Proposal {
            from,
            requested_to: to,
            action,
            confidence,
            evidence,
        },
        expected_hash,
    })
}

fn parse_u8(bytes: &[u8]) -> Result<u8, JournalError> {
    parse_u64(bytes)?
        .try_into()
        .map_err(|_| JournalError::InvalidRow)
}

fn parse_u16(bytes: &[u8]) -> Result<u16, JournalError> {
    parse_u64(bytes)?
        .try_into()
        .map_err(|_| JournalError::InvalidRow)
}

fn parse_u64(bytes: &[u8]) -> Result<u64, JournalError> {
    if bytes.is_empty() || !bytes.iter().all(u8::is_ascii_digit) {
        return Err(JournalError::InvalidRow);
    }
    std::str::from_utf8(bytes)
        .map_err(|_| JournalError::InvalidRow)?
        .parse()
        .map_err(|_| JournalError::InvalidRow)
}

fn optional_u16(bytes: &[u8]) -> Result<Option<u16>, JournalError> {
    if bytes == b"-" {
        Ok(None)
    } else {
        parse_u16(bytes).map(Some)
    }
}

fn parse_hex_16(bytes: &[u8]) -> Result<[u8; 16], JournalError> {
    let mut output = [0; 16];
    parse_hex(bytes, &mut output)?;
    Ok(output)
}

fn parse_hex_32(bytes: &[u8]) -> Result<[u8; 32], JournalError> {
    let mut output = [0; 32];
    parse_hex(bytes, &mut output)?;
    Ok(output)
}

fn parse_hex(bytes: &[u8], output: &mut [u8]) -> Result<(), JournalError> {
    if bytes.len() != output.len() * 2 {
        return Err(JournalError::InvalidRow);
    }
    for (index, target) in output.iter_mut().enumerate() {
        let high = hex_value(bytes[index * 2]).ok_or(JournalError::InvalidRow)?;
        let low = hex_value(bytes[index * 2 + 1]).ok_or(JournalError::InvalidRow)?;
        *target = (high << 4) | low;
    }
    Ok(())
}

fn hex_value(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{Observation, Signal, WorkflowObserver, standard_schema};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_path() -> std::path::PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("rdc-exp001-{stamp}.journal"))
    }

    #[test]
    fn mapped_journal_replays_and_detects_mutation() {
        let mut runtime = Runtime::new(DecisionCompiler::compile(&standard_schema()).unwrap());
        let mut observer = WorkflowObserver;
        let evidence = Evidence {
            code: 3,
            digest: [8; 16],
        };
        for signal in [
            Signal::Start,
            Signal::Observed,
            Signal::Approve,
            Signal::ActionSucceeded,
            Signal::Verified,
        ] {
            let mut observation = Observation::new(signal);
            if signal != Signal::Start {
                observation = observation.with_evidence(evidence);
            }
            if signal == Signal::Approve {
                observation = observation.with_confidence(900);
            }
            runtime.step(&observation, &mut observer);
        }
        let path = temp_path();
        write_journal(&path, runtime.receipts()).unwrap();
        drop(runtime);

        // SAFETY: the test owns the unique temp file and no writer is open.
        let (replayed, report) = unsafe {
            replay_mmap(
                &path,
                DecisionCompiler::compile(&standard_schema()).unwrap(),
            )
            .unwrap()
        };
        assert!(report.completed);
        assert_eq!(report.receipt_count, 5);
        assert_eq!(report.final_hash, replayed.receipts().last().unwrap().hash);

        let mut corrupted = std::fs::read(&path).unwrap();
        let last_hex = corrupted.iter().rposition(u8::is_ascii_hexdigit).unwrap();
        corrupted[last_hex] = if corrupted[last_hex] == b'0' {
            b'1'
        } else {
            b'0'
        };
        std::fs::write(&path, corrupted).unwrap();
        // SAFETY: the prior mapping has been dropped and no writer is open during replay.
        let result = unsafe {
            replay_mmap(
                &path,
                DecisionCompiler::compile(&standard_schema()).unwrap(),
            )
        };
        assert!(matches!(result, Err(JournalError::ReplayMismatch { .. })));
        std::fs::remove_file(path).unwrap();
    }
}
