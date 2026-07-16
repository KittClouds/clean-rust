use crate::{
    import_tkgl_smallpedia, import_wd50k, ExternalDatasetError, ExternalDatasetMapped,
    ExternalFactSplit, ExternalSplitPolicy,
};
use std::fmt::Write as _;
use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};
use std::path::Path;
use std::time::{Duration, Instant};

#[test]
fn smallpedia_import_is_deterministic_mmap_exact_and_temporal() {
    let first = tempfile::tempdir().expect("first");
    let second = tempfile::tempdir().expect("second");
    write_smallpedia(first.path());
    write_smallpedia(second.path());
    let first_output = first.path().join("artifact");
    let second_output = second.path().join("artifact");
    let first_paths = import_tkgl_smallpedia(first.path(), &first_output).expect("first import");
    let second_paths =
        import_tkgl_smallpedia(second.path(), &second_output).expect("second import");
    assert_eq!(first_paths.dataset_id, second_paths.dataset_id);

    let mapped = ExternalDatasetMapped::open(&first_paths.manifest).expect("open");
    let manifest = mapped.manifest();
    assert_eq!(manifest.entities, 13);
    assert_eq!(manifest.relations, 3);
    assert_eq!(manifest.facts, 12);
    assert_eq!(manifest.temporal_facts, 10);
    assert_eq!(manifest.static_facts, 2);
    assert_eq!(manifest.qualifiers, 0);
    assert!(matches!(
        manifest.split_policy,
        ExternalSplitPolicy::TemporalQuantile {
            train_through: 7,
            validation_through: 9,
            ..
        }
    ));
    assert_eq!(mapped.entity(0), Some("Q1"));
    assert_eq!(mapped.relation(0), Some("P2"));
    let facts = mapped.facts().expect("facts");
    assert_eq!(facts[0].observed_at(), Some(1));
    assert_eq!(facts[0].split(), ExternalFactSplit::Train as u8);
    assert_eq!(facts[7].split(), ExternalFactSplit::Validation as u8);
    assert_eq!(facts[9].split(), ExternalFactSplit::Test as u8);
    assert!(facts[10].is_static());
    assert_eq!(facts[10].observed_at(), None);
    assert_eq!(facts[10].split(), ExternalFactSplit::Unsplit as u8);
}

#[test]
fn wd50k_preserves_fixed_splits_and_qualifier_pairs_without_fake_time() {
    let root = tempfile::tempdir().expect("root");
    let statements = root.path().join("statements");
    std::fs::create_dir_all(&statements).expect("statements");
    write(
        &statements.join("train.txt"),
        b"Q1,P1,Q2,PQ,Q3,PQ2,Q4\nQ2,P2,Q5\n",
    );
    write(&statements.join("valid.txt"), b"Q5,P1,Q6,PQ,Q7\n");
    write(&statements.join("test.txt"), b"Q7,P3,Q1\n");
    let paths = import_wd50k(root.path(), root.path().join("artifact")).expect("import");
    let mapped = ExternalDatasetMapped::open(paths.manifest).expect("open");
    let manifest = mapped.manifest();
    assert_eq!(manifest.facts, 4);
    assert_eq!(manifest.qualifiers, 3);
    assert_eq!(manifest.temporal_facts, 0);
    assert_eq!(manifest.static_facts, 0);
    assert!(matches!(
        manifest.split_policy,
        ExternalSplitPolicy::OfficialFixed { .. }
    ));
    let facts = mapped.facts().expect("facts");
    assert_eq!(facts[0].qualifier_count(), 2);
    assert_eq!(facts[0].observed_at(), None);
    assert_eq!(facts[0].split(), ExternalFactSplit::Train as u8);
    assert_eq!(facts[2].split(), ExternalFactSplit::Validation as u8);
    assert_eq!(facts[3].split(), ExternalFactSplit::Test as u8);
    let qualifiers = mapped.qualifiers().expect("qualifiers");
    assert_eq!(mapped.relation(qualifiers[0].predicate()), Some("PQ"));
    assert_eq!(mapped.entity(qualifiers[0].object()), Some("Q3"));
}

#[test]
fn malformed_qualifier_fails_before_artifact_installation() {
    let root = tempfile::tempdir().expect("root");
    let statements = root.path().join("statements");
    std::fs::create_dir_all(&statements).expect("statements");
    write(&statements.join("train.txt"), b"Q1,P1,Q2,PQ\n");
    write(&statements.join("valid.txt"), b"Q1,P1,Q2\n");
    write(&statements.join("test.txt"), b"Q1,P1,Q2\n");
    let output = root.path().join("artifact");
    assert!(matches!(
        import_wd50k(root.path(), &output),
        Err(ExternalDatasetError::InvalidRow {
            reason: "unpaired qualifier",
            ..
        })
    ));
    assert!(!output.exists());
}

#[test]
fn binary_corruption_fails_before_mmap_access() {
    let root = tempfile::tempdir().expect("root");
    write_smallpedia(root.path());
    let paths = import_tkgl_smallpedia(root.path(), root.path().join("artifact")).expect("import");
    let mut file = OpenOptions::new()
        .write(true)
        .open(&paths.binary)
        .expect("binary");
    file.seek(SeekFrom::Start(8)).expect("seek");
    file.write_all(&[0xff]).expect("corrupt");
    file.sync_all().expect("sync");
    assert!(matches!(
        ExternalDatasetMapped::open(paths.manifest),
        Err(ExternalDatasetError::CorruptArtifact("binary identity"))
    ));
}

#[test]
fn source_receipt_drift_fails_before_mmap_access() {
    let root = tempfile::tempdir().expect("root");
    write_smallpedia(root.path());
    let paths = import_tkgl_smallpedia(root.path(), root.path().join("artifact")).expect("import");
    let mut manifest: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&paths.manifest).expect("manifest")).expect("json");
    manifest["upstreamVersion"] = "drifted".into();
    std::fs::write(
        &paths.manifest,
        serde_json::to_vec_pretty(&manifest).expect("encode"),
    )
    .expect("drift");
    assert!(matches!(
        ExternalDatasetMapped::open(paths.manifest),
        Err(ExternalDatasetError::CorruptArtifact("source identity"))
    ));
}

#[test]
fn imports_one_hundred_thousand_temporal_rows_within_gate() {
    let root = tempfile::tempdir().expect("root");
    let mut temporal = String::with_capacity(3_000_000);
    temporal.push_str("ts,head,tail,relation_type\n");
    for index in 0..100_000 {
        writeln!(
            temporal,
            "{},Q{index},Q{},P{}",
            1900 + index % 125,
            index + 1,
            index % 10
        )
        .expect("row");
    }
    write(
        &root.path().join("tkgl-smallpedia_edgelist.csv"),
        temporal.as_bytes(),
    );
    write(
        &root.path().join("tkgl-smallpedia_static_edgelist.csv"),
        b"head,tail,relation_type\nQ0,Q100001,Pstatic\n",
    );
    write(
        &root.path().join("tkgl-smallpedia_val_ns.pkl"),
        b"opaque-val",
    );
    write(
        &root.path().join("tkgl-smallpedia_test_ns.pkl"),
        b"opaque-test",
    );
    let started = Instant::now();
    let paths = import_tkgl_smallpedia(root.path(), root.path().join("artifact"))
        .expect("performance import");
    assert!(started.elapsed() < Duration::from_secs(5));
    let mapped = ExternalDatasetMapped::open(paths.manifest).expect("open");
    assert_eq!(mapped.manifest().facts, 100_001);
}

fn write_smallpedia(root: &Path) {
    let mut temporal = String::from("ts,head,tail,relation_type\n");
    for year in 1..=10 {
        temporal.push_str(&format!("{year},Q{year},Q{},P{}\n", year + 1, year % 2 + 1));
    }
    write(
        &root.join("tkgl-smallpedia_edgelist.csv"),
        temporal.as_bytes(),
    );
    write(
        &root.join("tkgl-smallpedia_static_edgelist.csv"),
        b"head,tail,relation_type\nQ1,Q12,P3\nQ12,Q13,P3\n",
    );
    write(&root.join("tkgl-smallpedia_val_ns.pkl"), b"opaque-val");
    write(&root.join("tkgl-smallpedia_test_ns.pkl"), b"opaque-test");
}

fn write(path: &Path, bytes: &[u8]) {
    std::fs::write(path, bytes).expect("write fixture");
}
