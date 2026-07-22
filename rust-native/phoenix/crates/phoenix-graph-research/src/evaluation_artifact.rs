use crate::{
    BaselineLadderReport, ResearchEvaluationError, ResearchEvaluationPaths,
    ResearchEvaluationProtocol,
};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

pub struct ResearchEvaluationBundle;

impl ResearchEvaluationBundle {
    pub fn write(
        protocol: &ResearchEvaluationProtocol,
        baselines: &BaselineLadderReport,
        root: impl AsRef<Path>,
    ) -> Result<ResearchEvaluationPaths, ResearchEvaluationError> {
        if baselines.protocol_id != protocol.protocol_id {
            return Err(ResearchEvaluationError::ReportProtocolMismatch);
        }
        let root = root.as_ref();
        std::fs::create_dir_all(root)?;
        let protocol_path = root.join(format!("{}.evaluation.json", protocol.protocol_id));
        let baseline_path = root.join(format!("{}.baselines.json", baselines.report_id));
        let protocol_bytes = serde_json::to_vec_pretty(protocol)?;
        let baseline_bytes = serde_json::to_vec_pretty(baselines)?;
        write_immutable(&protocol_path, &protocol_bytes)?;
        write_immutable(&baseline_path, &baseline_bytes)?;
        Ok(ResearchEvaluationPaths {
            protocol: protocol_path,
            baselines: baseline_path,
        })
    }
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), ResearchEvaluationError> {
    if path.exists() {
        return if std::fs::read(path)? == bytes {
            Ok(())
        } else {
            Err(ResearchEvaluationError::ArtifactExists(path.to_path_buf()))
        };
    }
    let temporary = temporary_path(path);
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)?;
    if let Err(error) = file.write_all(bytes).and_then(|_| file.sync_all()) {
        let _ = std::fs::remove_file(&temporary);
        return Err(error.into());
    }
    if path.exists() {
        let _ = std::fs::remove_file(&temporary);
        return if std::fs::read(path)? == bytes {
            Ok(())
        } else {
            Err(ResearchEvaluationError::ArtifactExists(path.to_path_buf()))
        };
    }
    std::fs::rename(temporary, path)?;
    Ok(())
}

fn temporary_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("evaluation");
    path.with_file_name(format!(".{name}.tmp-{}", std::process::id()))
}
