use std::collections::HashSet;

use serde::{Deserialize, Serialize};

use crate::observer::{ActionOption, OBSERVER_INPUT_SCHEMA};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObservationEvidence {
    pub kind: String,
    pub source_id: String,
    pub content_blake3: String,
    pub content: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionProposalOption {
    pub action: ActionOption,
    pub summary: String,
    pub diff_excerpt: String,
    pub patch_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CodingObservationFrame {
    pub schema_id: String,
    pub task_id: String,
    pub task_family: String,
    pub task_prompt: String,
    pub repository_revision: String,
    pub snapshot_sha256: String,
    pub evidence: Vec<ObservationEvidence>,
    pub action_options: Vec<ActionProposalOption>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FrameError {
    WrongSchema,
    EmptyRequiredField,
    InvalidHash,
    DuplicateActionId,
    NoActionOptions,
    EvidenceDigestMismatch,
}

impl CodingObservationFrame {
    pub fn normalize(&mut self) {
        self.task_prompt = normalize_line_endings(&self.task_prompt);
        for item in &mut self.evidence {
            item.kind = normalize_line_endings(&item.kind);
            item.source_id = normalize_line_endings(&item.source_id);
            item.content = normalize_line_endings(&item.content);
        }
        for option in &mut self.action_options {
            option.summary = normalize_line_endings(&option.summary);
            option.diff_excerpt = normalize_line_endings(&option.diff_excerpt);
        }
    }

    pub fn validate(&self) -> Result<(), FrameError> {
        if self.schema_id != OBSERVER_INPUT_SCHEMA {
            return Err(FrameError::WrongSchema);
        }
        if [
            &self.task_id,
            &self.task_family,
            &self.task_prompt,
            &self.repository_revision,
        ]
        .iter()
        .any(|field| field.trim().is_empty())
        {
            return Err(FrameError::EmptyRequiredField);
        }
        if !is_sha256_hex(&self.snapshot_sha256) {
            return Err(FrameError::InvalidHash);
        }
        if self.action_options.is_empty() {
            return Err(FrameError::NoActionOptions);
        }
        let mut action_ids = HashSet::with_capacity(self.action_options.len());
        for option in &self.action_options {
            if !action_ids.insert(option.action.id) {
                return Err(FrameError::DuplicateActionId);
            }
            if option.summary.trim().is_empty() || !is_sha256_hex(&option.patch_sha256) {
                return Err(FrameError::InvalidHash);
            }
        }
        for item in &self.evidence {
            if item.kind.trim().is_empty()
                || item.source_id.trim().is_empty()
                || item.content_blake3 != blake3::hash(item.content.as_bytes()).to_hex().as_str()
            {
                return Err(FrameError::EvidenceDigestMismatch);
            }
        }
        Ok(())
    }

    pub fn canonical_json(&self) -> Result<Vec<u8>, serde_json::Error> {
        serde_json::to_vec(self)
    }

    pub fn frame_hash(&self) -> Result<[u8; 32], serde_json::Error> {
        Ok(*blake3::hash(&self.canonical_json()?).as_bytes())
    }
}

pub fn normalize_line_endings(value: &str) -> String {
    if !value.as_bytes().contains(&b'\r') {
        return value.to_owned();
    }
    let mut normalized = String::with_capacity(value.len());
    let mut chars = value.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch == '\r' {
            if chars.peek() == Some(&'\n') {
                chars.next();
            }
            normalized.push('\n');
        } else {
            normalized.push(ch);
        }
    }
    normalized
}

fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn line_endings_are_normalized_without_changing_code_or_spacing() {
        assert_eq!(normalize_line_endings("a\r\nb\rc\n"), "a\nb\nc\n");
        assert_eq!(
            normalize_line_endings("  let x = 1;  \n"),
            "  let x = 1;  \n"
        );
    }
}
