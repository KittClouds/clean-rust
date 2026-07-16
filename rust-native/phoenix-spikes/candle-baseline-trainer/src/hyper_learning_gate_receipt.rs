use crate::{CandleTrainerError, HyperLearningGatesReceipt};
use compact_str::{format_compact, CompactString};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

const RECEIPT_ID_PLACEHOLDER: &str =
    "b3-0000000000000000000000000000000000000000000000000000000000000000";

pub fn open_hyper_learning_gates(
    path: impl AsRef<Path>,
) -> Result<HyperLearningGatesReceipt, CandleTrainerError> {
    let bytes = std::fs::read(path.as_ref())?;
    let receipt: HyperLearningGatesReceipt = serde_json::from_slice(&bytes)?;
    if receipt.receipt_id != file_identity(&bytes, receipt.receipt_id.as_str())? {
        return Err(CandleTrainerError::Contract(
            "learning gate receipt identity",
        ));
    }
    Ok(receipt)
}

pub(crate) fn seal_learning_gate_receipt(
    mut receipt: HyperLearningGatesReceipt,
    root: &Path,
) -> Result<(HyperLearningGatesReceipt, PathBuf), CandleTrainerError> {
    receipt.receipt_id = RECEIPT_ID_PLACEHOLDER.into();
    receipt.receipt_id = format_compact!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec_pretty(&receipt)?).to_hex()
    );
    let path = root.join(format!("{}.learning-gates.json", receipt.receipt_id));
    write_new(&path, &serde_json::to_vec_pretty(&receipt)?)?;
    Ok((receipt, path))
}

fn file_identity(bytes: &[u8], receipt_id: &str) -> Result<CompactString, CandleTrainerError> {
    if receipt_id.len() != RECEIPT_ID_PLACEHOLDER.len() {
        return Err(CandleTrainerError::Contract("learning gate receipt id"));
    }
    let needle = format!("\"{receipt_id}\"");
    let replacement = format!("\"{RECEIPT_ID_PLACEHOLDER}\"");
    let offset = bytes
        .windows(needle.len())
        .position(|window| window == needle.as_bytes())
        .ok_or(CandleTrainerError::Contract("learning gate receipt id"))?;
    let mut authority = bytes.to_vec();
    authority[offset..offset + replacement.len()].copy_from_slice(replacement.as_bytes());
    Ok(format_compact!("b3-{}", blake3::hash(&authority).to_hex()))
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<(), CandleTrainerError> {
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
