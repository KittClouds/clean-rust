use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use crate::{
    DecisionBaselineLadderReport, NativeDecisionEvaluationError, NativeDecisionEvaluationReport,
};

pub struct NativeDecisionEvaluationBundle;

impl NativeDecisionEvaluationBundle {
    pub fn write_report(
        directory: &Path,
        report: &NativeDecisionEvaluationReport,
    ) -> Result<PathBuf, NativeDecisionEvaluationError> {
        write_immutable_json(directory, report.report_id.as_str(), "evaluation", report)
    }

    pub fn write_ladder(
        directory: &Path,
        report: &DecisionBaselineLadderReport,
    ) -> Result<PathBuf, NativeDecisionEvaluationError> {
        write_immutable_json(directory, report.ladder_id.as_str(), "ladder", report)
    }

    pub fn open_report(
        path: &Path,
    ) -> Result<NativeDecisionEvaluationReport, NativeDecisionEvaluationError> {
        let bytes = fs::read(path)?;
        let report: NativeDecisionEvaluationReport = serde_json::from_slice(&bytes)?;
        let mut candidate = report.clone();
        let expected = candidate.report_id.clone();
        candidate.report_id = "pending".into();
        let actual = content_id(&candidate)?;
        if actual != expected || !filename_contains(path, expected.as_str()) {
            return Err(NativeDecisionEvaluationError::CorruptArtifact(
                "evaluation identity",
            ));
        }
        Ok(report)
    }

    pub fn open_ladder(
        path: &Path,
    ) -> Result<DecisionBaselineLadderReport, NativeDecisionEvaluationError> {
        let bytes = fs::read(path)?;
        let report: DecisionBaselineLadderReport = serde_json::from_slice(&bytes)?;
        let mut candidate = report.clone();
        let expected = candidate.ladder_id.clone();
        candidate.ladder_id = "pending".into();
        let actual = content_id(&candidate)?;
        if actual != expected || !filename_contains(path, expected.as_str()) {
            return Err(NativeDecisionEvaluationError::CorruptArtifact(
                "ladder identity",
            ));
        }
        Ok(report)
    }
}

fn write_immutable_json<T: serde::Serialize>(
    directory: &Path,
    identity: &str,
    kind: &str,
    value: &T,
) -> Result<PathBuf, NativeDecisionEvaluationError> {
    if identity.trim().is_empty() || identity == "pending" {
        return Err(NativeDecisionEvaluationError::Identity("artifact"));
    }
    fs::create_dir_all(directory)?;
    let path = directory.join(format!("{identity}.{kind}.json"));
    let bytes = serde_json::to_vec(value)?;
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&path)
        .map_err(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                NativeDecisionEvaluationError::ArtifactExists(path.clone())
            } else {
                NativeDecisionEvaluationError::Io(error)
            }
        })?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(path)
}

fn filename_contains(path: &Path, identity: &str) -> bool {
    path.file_name()
        .and_then(|value| value.to_str())
        .is_some_and(|value| value.starts_with(identity))
}

fn content_id(value: &impl serde::Serialize) -> Result<String, NativeDecisionEvaluationError> {
    Ok(format!(
        "b3-{}",
        blake3::hash(&serde_json::to_vec(value)?).to_hex()
    ))
}
