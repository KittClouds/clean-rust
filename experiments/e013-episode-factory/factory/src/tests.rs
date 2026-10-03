use std::{collections::BTreeMap, fs, path::PathBuf};

use tempfile::tempdir;

use crate::{
    audit_episode_draft, build_episode, candidate_order, materialize_snapshot, root_hash,
    verify_episode, Asset, BuildEpisodeOptions, CandidatePatch, CommandSpec, EpisodeDraft,
    GenerationContext, HiddenAdjudicator, Provenance, RepoTemplate, SealEntry, SourceReference,
    Task, ValidationPlan,
};

#[test]
fn candidate_order_is_deterministic_and_input_order_independent() {
    let first = vec!["cand-a".into(), "cand-b".into(), "cand-c".into()];
    let second = vec!["cand-c".into(), "cand-a".into(), "cand-b".into()];
    assert_eq!(candidate_order(17, &first), candidate_order(17, &second));
    assert_ne!(candidate_order(18, &first), candidate_order(17, &first));
}

#[test]
fn root_hash_is_entry_order_independent() {
    let first = vec![
        SealEntry {
            artifact_id: "b".into(),
            path: "b".into(),
            byte_len: 1,
            sha256: "a".repeat(64),
        },
        SealEntry {
            artifact_id: "a".into(),
            path: "a".into(),
            byte_len: 2,
            sha256: "b".repeat(64),
        },
    ];
    let reversed = vec![first[1].clone(), first[0].clone()];
    assert_eq!(root_hash(&first), root_hash(&reversed));
}

#[test]
fn snapshot_and_episode_smoke_replay_every_patch_from_clean_baseline() {
    let temp = tempdir().unwrap();
    let template_root = temp.path().join("template");
    fs::create_dir_all(&template_root).unwrap();
    fs::write(template_root.join("value.txt"), b"base\n").unwrap();
    let snapshot_root = temp.path().join("snapshot");
    let repo = materialize_snapshot(
        &RepoTemplate {
            repo_id: "repo-smoke".into(),
            template_root: template_root.clone(),
        },
        &snapshot_root,
    )
    .unwrap();
    let context = GenerationContext {
        bank_id: "E013-C".into(),
        family_id: "c.smoke".into(),
        episode_id: "episode-smoke".into(),
        task_id: "task-smoke".into(),
        cell_id: "E013-C:repo-smoke:c.smoke".into(),
        cell_task_ordinal: 0,
        cell_task_count: 16,
        cell_empty_ordinal: 15,
        cell_seed: 42,
        generation_seed: 17,
        candidate_order_seed: 19,
        matched_pair: None,
        repo,
        repo_snapshot_root: snapshot_root,
    };
    let provenance = Provenance {
        generator_name: "smoke".into(),
        generator_version: "0.1".into(),
        generator_source_sha256: "a".repeat(64),
        source_refs: vec![SourceReference {
            artifact_id: "fixture-definition".into(),
            sha256: "b".repeat(64),
            role: "test-source".into(),
        }],
    };
    let draft = EpisodeDraft {
        task: Task {
            text: "Choose the compatible patch for this task.".into(),
        },
        candidates: vec![
            CandidatePatch {
                candidate_id: "cand-a".into(),
                unified_diff: b"diff --git a/value.txt b/value.txt\n--- a/value.txt\n+++ b/value.txt\n@@ -1 +1 @@\n-base\n+left\n".to_vec(),
                provenance: provenance.clone(),
            },
            CandidatePatch {
                candidate_id: "cand-b".into(),
                unified_diff: b"diff --git a/value.txt b/value.txt\n--- a/value.txt\n+++ b/value.txt\n@@ -1 +1 @@\n-base\n+right\n".to_vec(),
                provenance: provenance.clone(),
            },
        ],
        visible_fixtures: vec![Asset {
            path: "screen.txt".into(),
            media_type: "text/plain".into(),
            bytes: b"visible screen case".to_vec(),
        }],
        visible_evidence: vec![Asset {
            path: "task.txt".into(),
            media_type: "text/plain".into(),
            bytes: b"public task evidence".to_vec(),
        }],
        hidden_adjudicator: HiddenAdjudicator {
            path: "completion.json".into(),
            bytes: br#"{"expected":"left"}"#.to_vec(),
            leakage_canaries: vec!["expected=left".into()],
        },
        validation: ValidationPlan {
            compile: git_status(),
            visible: git_status(),
            hidden: git_status(),
        },
        provenance,
    };
    audit_episode_draft(&context, &draft).unwrap();
    let output_dir = temp.path().join("episode");
    let built = build_episode(
        &context,
        &draft,
        &BuildEpisodeOptions {
            output_dir: output_dir.clone(),
            protocol_sha256: "c".repeat(64),
            protocol_lock_sha256: "d".repeat(64),
            construction_contract_sha256: "e".repeat(64),
        },
    )
    .unwrap();
    assert_eq!(built.private_receipt.replay.len(), 2);
    assert!(built.private_receipt.replay.iter().all(|row| row.valid));
    assert_ne!(
        built.private_receipt.replay[0].patched_tree_sha,
        built.private_receipt.replay[1].patched_tree_sha
    );
    let verified = verify_episode(&output_dir).unwrap();
    assert_eq!(verified.seal.root_sha256, built.seal.root_sha256);
    assert_eq!(verified.private_receipt.valid_candidate_ids.len(), 2);
}

fn git_status() -> CommandSpec {
    CommandSpec {
        program: "git".into(),
        args: vec!["status".into(), "--porcelain".into()],
        env: BTreeMap::new(),
    }
}

#[allow(dead_code)]
fn _runtime_path(_: PathBuf) {}
