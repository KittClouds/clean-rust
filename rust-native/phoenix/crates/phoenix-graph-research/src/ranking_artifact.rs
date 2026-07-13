use crate::{RankingEvaluationError, RankingEvaluationPath, RankingEvaluationReport};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

pub struct RankingEvaluationBundle;

impl RankingEvaluationBundle {
    pub fn write(
        report: &RankingEvaluationReport,
        root: impl AsRef<Path>,
    ) -> Result<RankingEvaluationPath, RankingEvaluationError> {
        let root = root.as_ref();
        std::fs::create_dir_all(root)?;
        let path = root.join(format!("{}.ranking.json", report.report_id));
        let bytes = serde_json::to_vec_pretty(report)?;
        write_immutable(&path, &bytes)?;
        Ok(RankingEvaluationPath { report: path })
    }
}

fn write_immutable(path: &Path, bytes: &[u8]) -> Result<(), RankingEvaluationError> {
    if path.exists() {
        return if std::fs::read(path)? == bytes {
            Ok(())
        } else {
            Err(RankingEvaluationError::ArtifactExists(path.to_path_buf()))
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
    std::fs::rename(temporary, path)?;
    Ok(())
}

fn temporary_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("ranking");
    path.with_file_name(format!(".{name}.tmp-{}", std::process::id()))
}
