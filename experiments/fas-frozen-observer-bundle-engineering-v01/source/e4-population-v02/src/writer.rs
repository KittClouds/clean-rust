use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::population::{PopulationPermit, PopulationPlan};
use crate::schema::{FileReceipt, PopulationReceipt};

const INPUT_LINE_LIMIT: usize = 1_024;
const LABEL_LINE_LIMIT: usize = 1_024;
const MANIFEST_LINE_LIMIT: usize = 512;
const WRITE_BUFFER_BYTES: usize = 1 << 20;

pub const POPULATION_INPUTS_ARTIFACT_ID: &str = "E4_POPULATION_INPUTS_V01";
pub const POPULATION_ROW_MANIFEST_ARTIFACT_ID: &str = "E4_POPULATION_ROW_MANIFEST_V01";
pub const PRIMARY_LABELS_ARTIFACT_ID: &str = "E4_PRIMARY_TERMINAL_LABELS_V01";
pub const TEMPLATE_ESCROW_LABELS_ARTIFACT_ID: &str = "E4_TEMPLATE_JOINT_ESCROW_LABELS_V01";
pub const POPULATION_RECEIPT_ARTIFACT_ID: &str = "E4_POPULATION_GENERATION_RECEIPT_V01";

#[derive(Clone, Debug)]
pub struct WrittenPopulation {
    pub output_root: PathBuf,
    pub receipt: PopulationReceipt,
}

pub fn write_population(
    plan: &PopulationPlan,
    permit: &PopulationPermit,
) -> Result<WrittenPopulation, String> {
    let output_root = permit.output_root().to_owned();
    if output_root.exists() {
        return Err(format!(
            "authorized output root already exists; preserving it and refusing in-place writes: {}",
            output_root.display()
        ));
    }
    let parent = output_root
        .parent()
        .ok_or("authorized output root has no parent directory")?;
    fs::create_dir_all(parent).map_err(|error| format!("create output parent: {error}"))?;
    let stage_root = stage_path(&output_root)?;
    fs::create_dir(&stage_root).map_err(|error| {
        format!(
            "create unique population staging root {}: {error}",
            stage_root.display()
        )
    })?;

    let result = write_staged(plan, permit, &stage_root);
    match result {
        Ok(receipt) => {
            fs::rename(&stage_root, &output_root).map_err(|error| {
                format!(
                    "atomic population-root rename failed; stage preserved at {}: {error}",
                    stage_root.display()
                )
            })?;
            Ok(WrittenPopulation {
                output_root,
                receipt,
            })
        }
        Err(error) => Err(format!(
            "population generation stopped; partial attempt preserved at {}: {error}",
            stage_root.display()
        )),
    }
}

fn stage_path(output_root: &Path) -> Result<PathBuf, String> {
    let name = output_root
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or("authorized output root has no UTF-8 leaf name")?;
    Ok(output_root.with_file_name(format!(".{name}.population-stage-v01")))
}

fn write_staged(
    plan: &PopulationPlan,
    permit: &PopulationPermit,
    stage_root: &Path,
) -> Result<PopulationReceipt, String> {
    let population_dir = stage_root.join("population");
    let labels_dir = stage_root.join("labels");
    let receipts_dir = stage_root.join("receipts");
    fs::create_dir(&population_dir)
        .map_err(|error| format!("create population directory: {error}"))?;
    fs::create_dir(&labels_dir).map_err(|error| format!("create labels directory: {error}"))?;
    fs::create_dir(&receipts_dir).map_err(|error| format!("create receipts directory: {error}"))?;

    let input_path = population_dir.join("panel-inputs-v01.jsonl");
    let manifest_path = population_dir.join("row-manifest-v01.jsonl");
    let primary_labels_path = labels_dir.join("primary-terminal-labels-v01.jsonl");
    let escrow_labels_path = labels_dir.join("template-joint-escrow-v01.jsonl");
    let input_file = create_new(&input_path)?;
    let manifest_file = create_new(&manifest_path)?;
    let primary_labels_file = create_new(&primary_labels_path)?;
    let escrow_labels_file = create_new(&escrow_labels_path)?;
    let mut inputs = BufWriter::with_capacity(WRITE_BUFFER_BYTES, input_file);
    let mut manifest = BufWriter::with_capacity(WRITE_BUFFER_BYTES, manifest_file);
    let mut primary_labels = BufWriter::with_capacity(WRITE_BUFFER_BYTES, primary_labels_file);
    let mut escrow_labels = BufWriter::with_capacity(WRITE_BUFFER_BYTES, escrow_labels_file);
    let mut scratch = Vec::with_capacity(INPUT_LINE_LIMIT);
    let mut input_rows = 0_u64;
    let mut manifest_rows = 0_u64;
    let mut primary_label_rows = 0_u64;
    let mut escrow_label_rows = 0_u64;

    plan.emit_quartets(permit, |quartet| {
        if quartet.quartet_id != quartet.primary_rows[0].manifest.quartet_id
            || quartet.quartet_id != quartet.heldout_rows[0].manifest.quartet_id
        {
            return Err("generated quartet/row identity mismatch".into());
        }
        for (surface_rows, is_primary) in [
            (&quartet.primary_rows, true),
            (&quartet.heldout_rows, false),
        ] {
            for row in surface_rows {
                write_limited(&mut inputs, &row.input, INPUT_LINE_LIMIT, &mut scratch)
                    .map_err(|error| format!("write label-free panel input: {error}"))?;
                write_limited(
                    &mut manifest,
                    &row.manifest,
                    MANIFEST_LINE_LIMIT,
                    &mut scratch,
                )
                .map_err(|error| format!("write label-free row manifest: {error}"))?;
                input_rows += 1;
                manifest_rows += 1;
                if is_primary {
                    write_limited(
                        &mut primary_labels,
                        &row.label,
                        LABEL_LINE_LIMIT,
                        &mut scratch,
                    )
                    .map_err(|error| format!("write primary terminal label: {error}"))?;
                    primary_label_rows += 1;
                } else {
                    write_limited(
                        &mut escrow_labels,
                        &row.label,
                        LABEL_LINE_LIMIT,
                        &mut scratch,
                    )
                    .map_err(|error| format!("write escrowed template/joint label: {error}"))?;
                    escrow_label_rows += 1;
                }
            }
        }
        Ok(())
    })?;

    for writer in [
        &mut inputs,
        &mut manifest,
        &mut primary_labels,
        &mut escrow_labels,
    ] {
        writer
            .flush()
            .map_err(|error| format!("flush population output: {error}"))?;
        writer
            .get_ref()
            .sync_all()
            .map_err(|error| format!("sync population output: {error}"))?;
    }
    let expected = plan.receipt.selected_whole_quartet_prefix * 8;
    if input_rows != expected
        || manifest_rows != expected
        || primary_label_rows != plan.receipt.primary_rows
        || escrow_label_rows != plan.receipt.heldout_template_rows
    {
        return Err("materialized row counts differ from the sealed support plan".into());
    }

    let files = vec![
        file_receipt(
            POPULATION_INPUTS_ARTIFACT_ID,
            "population/panel-inputs-v01.jsonl",
            &input_path,
            input_rows,
        )?,
        file_receipt(
            POPULATION_ROW_MANIFEST_ARTIFACT_ID,
            "population/row-manifest-v01.jsonl",
            &manifest_path,
            manifest_rows,
        )?,
        file_receipt(
            PRIMARY_LABELS_ARTIFACT_ID,
            "labels/primary-terminal-labels-v01.jsonl",
            &primary_labels_path,
            primary_label_rows,
        )?,
        file_receipt(
            TEMPLATE_ESCROW_LABELS_ARTIFACT_ID,
            "labels/template-joint-escrow-v01.jsonl",
            &escrow_labels_path,
            escrow_label_rows,
        )?,
    ];
    let mut receipt = plan.receipt.clone();
    receipt.status = "POPULATION_COMPLETE_GATE_PASS".into();
    receipt.contract_seal_root_sha256 = Some(permit.contract_root().to_owned());
    receipt.authorization_id = Some(permit.authorization_id().to_owned());
    receipt.output_root = Some(permit.output_root().to_string_lossy().into_owned());
    receipt.population_rows_written = true;
    receipt.files = files;
    if receipt.template_truth_opened
        || receipt.template_joint_support_emitted
        || receipt.predictions_emitted
        || receipt.tokenizer_contacted
        || receipt.model_contacted
        || receipt.cuda_initialized
    {
        return Err("population receipt crossed a forbidden truth/model boundary".into());
    }
    let receipt_path = receipts_dir.join("population-generation-receipt-v01.json");
    write_json_file(&receipt_path, &receipt)?;
    Ok(receipt)
}

fn create_new(path: &Path) -> Result<File, String> {
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| format!("create-new {}: {error}", path.display()))
}

fn write_limited<W, T>(
    writer: &mut W,
    value: &T,
    limit: usize,
    scratch: &mut Vec<u8>,
) -> Result<(), String>
where
    W: Write,
    T: Serialize,
{
    scratch.clear();
    serde_json::to_writer(&mut *scratch, value)
        .map_err(|error| format!("serialize JSONL row: {error}"))?;
    if scratch.len() + 1 > limit {
        return Err(format!(
            "serialized JSONL row is {} bytes including LF; cap is {limit}",
            scratch.len() + 1
        ));
    }
    writer
        .write_all(scratch)
        .map_err(|error| format!("write JSONL row: {error}"))?;
    writer
        .write_all(b"\n")
        .map_err(|error| format!("write JSONL LF: {error}"))?;
    Ok(())
}

fn write_json_file<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let file = create_new(path)?;
    let mut writer = BufWriter::with_capacity(64 * 1024, file);
    serde_json::to_writer_pretty(&mut writer, value)
        .map_err(|error| format!("serialize receipt: {error}"))?;
    writer
        .write_all(b"\n")
        .map_err(|error| format!("terminate receipt: {error}"))?;
    writer
        .flush()
        .map_err(|error| format!("flush receipt: {error}"))?;
    writer
        .get_ref()
        .sync_all()
        .map_err(|error| format!("sync receipt: {error}"))?;
    Ok(())
}

fn file_receipt(
    artifact_id: &str,
    relative_path: &str,
    path: &Path,
    row_count: u64,
) -> Result<FileReceipt, String> {
    let file = File::open(path).map_err(|error| format!("open output for receipt: {error}"))?;
    let byte_length = file
        .metadata()
        .map_err(|error| format!("stat output: {error}"))?
        .len();
    let mut reader = std::io::BufReader::with_capacity(WRITE_BUFFER_BYTES, file);
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; WRITE_BUFFER_BYTES];
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|error| format!("hash output: {error}"))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    let sha256 = hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    Ok(FileReceipt {
        artifact_id: artifact_id.to_owned(),
        path: relative_path.to_owned(),
        byte_length,
        sha256,
        row_count,
    })
}

#[cfg(test)]
mod tests {
    use super::{MANIFEST_LINE_LIMIT, write_limited};
    use crate::schema::ModelInputRow;

    #[test]
    fn synthetic_line_serialization_enforces_exact_caps_and_lf() {
        let row = ModelInputRow {
            row_id: format!("{}:00:00", "0".repeat(64)),
            quartet_id: "0".repeat(64),
            variant_id: "A".into(),
            input_text: "synthetic".into(),
        };
        let mut bytes = Vec::new();
        let mut scratch = Vec::new();
        write_limited(&mut bytes, &row, MANIFEST_LINE_LIMIT, &mut scratch).unwrap();
        assert_eq!(bytes.last(), Some(&b'\n'));
        assert!(bytes.len() <= MANIFEST_LINE_LIMIT);
        let error = write_limited(&mut bytes, &row, 1, &mut scratch).unwrap_err();
        assert!(error.contains("cap is 1"));
    }
}
