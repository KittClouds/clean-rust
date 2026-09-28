use std::{
    fs::{File, OpenOptions, remove_file},
    io::Write,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

use memmap2::MmapOptions;
use rdc_runtime_contracts_v1::{
    ActionCode, CandidateIdentity, CandidatePresentationError, SequencedCandidate,
    encode_candidate_presentation, order_by_producer_ordinal, resolve_candidate_proposal,
    validate_candidate_presentation,
};

static NEXT_FILE_ID: AtomicU64 = AtomicU64::new(0);

fn candidate(action: u16, digest_byte: u8) -> CandidateIdentity {
    CandidateIdentity {
        action: ActionCode(action),
        patch_digest: [digest_byte; 32],
    }
}

fn fixture() -> ([u8; 32], Vec<CandidateIdentity>) {
    (
        [0xA5; 32],
        vec![candidate(11, 1), candidate(37, 2), candidate(68, 3)],
    )
}

#[test]
fn receipt_accepts_the_original_order_and_rejects_reordering() {
    let (task_digest, candidates) = fixture();
    let receipt = encode_candidate_presentation(task_digest, &candidates).unwrap();
    assert_eq!(
        validate_candidate_presentation(&receipt, task_digest, &candidates),
        Ok(())
    );

    let reordered = [candidates[1], candidates[0], candidates[2]];
    assert_eq!(
        validate_candidate_presentation(&receipt, task_digest, &reordered),
        Err(CandidatePresentationError::CandidateSequenceChanged)
    );
}

#[test]
fn receipt_rejects_action_id_or_task_changes() {
    let (task_digest, candidates) = fixture();
    let receipt = encode_candidate_presentation(task_digest, &candidates).unwrap();
    let reassigned = [candidate(91, 1), candidates[1], candidates[2]];
    assert_eq!(
        validate_candidate_presentation(&receipt, task_digest, &reassigned),
        Err(CandidatePresentationError::CandidateSequenceChanged)
    );
    assert_eq!(
        validate_candidate_presentation(&receipt, [0x5A; 32], &candidates),
        Err(CandidatePresentationError::TaskChanged)
    );
}

#[test]
fn proposal_resolution_checks_the_receipt_before_mapping_to_a_patch() {
    let (task_digest, candidates) = fixture();
    let receipt = encode_candidate_presentation(task_digest, &candidates).unwrap();
    assert_eq!(
        resolve_candidate_proposal(&receipt, task_digest, &candidates, Some(ActionCode(37))),
        Ok(Some(candidates[1]))
    );
    assert_eq!(
        resolve_candidate_proposal(&receipt, task_digest, &candidates, None),
        Ok(None)
    );
    assert_eq!(
        resolve_candidate_proposal(&receipt, task_digest, &candidates, Some(ActionCode(94))),
        Err(CandidatePresentationError::ProposalNotOffered)
    );

    let reordered = [candidates[1], candidates[0], candidates[2]];
    assert_eq!(
        resolve_candidate_proposal(&receipt, task_digest, &reordered, Some(ActionCode(37))),
        Err(CandidatePresentationError::CandidateSequenceChanged)
    );
}

#[test]
fn ambiguous_candidate_sets_are_rejected_before_sealing() {
    let task_digest = [0xA5; 32];
    assert_eq!(
        encode_candidate_presentation(task_digest, &[]),
        Err(CandidatePresentationError::EmptyCandidateSet)
    );
    assert_eq!(
        encode_candidate_presentation(task_digest, &[candidate(11, 1), candidate(11, 2)]),
        Err(CandidatePresentationError::DuplicateActionCode)
    );
    assert_eq!(
        encode_candidate_presentation(task_digest, &[candidate(11, 1), candidate(37, 1)]),
        Err(CandidatePresentationError::DuplicatePatchDigest)
    );
    assert_eq!(
        encode_candidate_presentation(task_digest, &[candidate(u16::MAX, 1)]),
        Err(CandidatePresentationError::ReservedActionCode)
    );
}

#[test]
fn candidate_count_has_a_small_bounded_limit() {
    let candidates = (0u16..257)
        .map(|index| {
            let mut digest = [0; 32];
            digest[..2].copy_from_slice(&index.to_le_bytes());
            CandidateIdentity {
                action: ActionCode(index),
                patch_digest: digest,
            }
        })
        .collect::<Vec<_>>();
    assert_eq!(
        encode_candidate_presentation([0xA5; 32], &candidates),
        Err(CandidatePresentationError::TooManyCandidates)
    );
}

#[test]
fn producer_ordinals_restore_order_after_transport_permutation() {
    let mut candidates = [
        SequencedCandidate {
            producer_ordinal: 2,
            value: "third",
        },
        SequencedCandidate {
            producer_ordinal: 0,
            value: "first",
        },
        SequencedCandidate {
            producer_ordinal: 3,
            value: "fourth",
        },
        SequencedCandidate {
            producer_ordinal: 1,
            value: "second",
        },
    ];
    order_by_producer_ordinal(&mut candidates).unwrap();
    assert_eq!(
        candidates.map(|candidate| candidate.value),
        ["first", "second", "third", "fourth"]
    );
}

#[test]
fn duplicate_producer_ordinals_fail_closed() {
    let mut candidates = [
        SequencedCandidate {
            producer_ordinal: 4,
            value: 1,
        },
        SequencedCandidate {
            producer_ordinal: 4,
            value: 2,
        },
    ];
    assert_eq!(
        order_by_producer_ordinal(&mut candidates),
        Err(CandidatePresentationError::DuplicateProducerOrdinal)
    );
}

#[test]
fn mapped_receipt_validates_without_deserializing_the_candidate_sequence() {
    let (task_digest, candidates) = fixture();
    let receipt = encode_candidate_presentation(task_digest, &candidates).unwrap();
    let path = unique_temp_path();
    {
        let mut file = File::create(&path).unwrap();
        file.write_all(&receipt).unwrap();
        file.sync_all().unwrap();
    }
    let file = OpenOptions::new().read(true).open(&path).unwrap();
    // SAFETY: the file is held open and is not mutated while the read-only map lives.
    let mapping = unsafe { MmapOptions::new().map(&file).unwrap() };
    assert_eq!(
        validate_candidate_presentation(&mapping, task_digest, &candidates),
        Ok(())
    );
    drop(mapping);
    drop(file);
    remove_file(path).unwrap();
}

#[test]
fn receipt_detects_digest_corruption() {
    let (task_digest, candidates) = fixture();
    let mut receipt = encode_candidate_presentation(task_digest, &candidates).unwrap();
    let sequence_digest_last_byte = std::mem::size_of::<u32>()
        + std::mem::size_of::<u16>()
        + std::mem::size_of::<u32>()
        + 32
        + 31;
    receipt[sequence_digest_last_byte] ^= 0x80;
    assert_eq!(
        validate_candidate_presentation(&receipt, task_digest, &candidates),
        Err(CandidatePresentationError::SequenceDigestMismatch)
    );
}

fn unique_temp_path() -> PathBuf {
    let id = NEXT_FILE_ID.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "rdc-candidate-presentation-{}-{id}.bin",
        std::process::id()
    ))
}
