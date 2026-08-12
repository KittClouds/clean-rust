//! Read-only verifier and zero-copy reader for sealed MT5 auction corpora.

mod error;
mod relational;
mod seal;
mod tsv;

pub use error::{CorpusError, Result};
pub use relational::{DatasetCounts, RelationalReport, validate_run_relations};
pub use seal::{CorpusReport, CorpusSeal, CorpusVerifier, RunReport, RunSeal, TerminalReceipt};
pub use tsv::{MappedTsv, Row, parse_i16, parse_i64, parse_u16, parse_u64};
