use std::time::Instant;

use compact_str::CompactString;
use phoenix_revision_impact::{
    resolve_revision_identity, IdentityFingerprint, RevisionIdentityKind, RevisionIdentityRecord,
    RevisionIdentitySnapshot,
};
use phoenix_types::{DocumentId, EntityId};
use smallvec::smallvec;

const RECORD_COUNT: usize = 10_000;

fn main() {
    let previous = snapshot(1, 0);
    let current = snapshot(2, 4_096);
    let started = Instant::now();
    let identity = resolve_revision_identity(&previous, &current).expect("identity benchmark");
    let elapsed = started.elapsed();
    let matched =
        identity.scene_matches.len() + identity.event_matches.len() + identity.fact_matches.len();
    assert_eq!(matched, RECORD_COUNT);
    assert!(identity.ambiguous.is_empty());
    assert!(identity.splits.is_empty());
    assert!(identity.merges.is_empty());

    println!(
        "records={} elapsed_ms={:.3} records_per_second={:.0}",
        RECORD_COUNT,
        elapsed.as_secs_f64() * 1_000.0,
        RECORD_COUNT as f64 / elapsed.as_secs_f64()
    );
}

fn snapshot(revision: u64, offset_shift: u32) -> RevisionIdentitySnapshot {
    let records = (0..RECORD_COUNT)
        .map(|index| {
            let semantic = fingerprint(&format!("semantic:{index}"));
            let anchor = fingerprint(&format!("anchor:{index}"));
            RevisionIdentityRecord {
                stable_id: CompactString::from(format!("scene:r{revision}:{index}")),
                kind: RevisionIdentityKind::Scene,
                document_id: DocumentId(format!("document:{}", index / 100)),
                semantic_fingerprint: semantic,
                evidence_anchor_fingerprints: smallvec![anchor],
                participant_entity_ids: smallvec![EntityId(format!("entity:{}", index % 128))],
                neighbor_event_fingerprints: smallvec![fingerprint(&format!(
                    "neighbor:{}",
                    index % 512
                ))],
                source_start: (index as u32).saturating_mul(128) + offset_shift,
                source_end: (index as u32).saturating_mul(128) + offset_shift + 96,
            }
        })
        .collect();
    RevisionIdentitySnapshot { revision, records }
}

fn fingerprint(value: &str) -> IdentityFingerprint {
    IdentityFingerprint::from_normalized_text(value)
}
