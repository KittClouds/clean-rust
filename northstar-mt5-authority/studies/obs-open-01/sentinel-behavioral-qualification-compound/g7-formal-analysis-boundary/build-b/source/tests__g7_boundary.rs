use obs_open_04a_g7::analysis::{invariant_languages, machinery_permissions, property_records};
use obs_open_04a_g7::fixtures::corpus;
use std::collections::BTreeSet;

#[test]
fn six_primary_properties_have_unique_signatures() {
    let records = property_records();
    assert_eq!(records.len(), 6);
    let ids = records
        .iter()
        .map(|row| row.property_id)
        .collect::<BTreeSet<_>>();
    let signatures = records
        .iter()
        .map(|row| row.problem_signature_id)
        .collect::<BTreeSet<_>>();
    assert_eq!(ids.len(), 6);
    assert_eq!(signatures.len(), 6);
}

#[test]
fn every_property_has_machinery_permissions() {
    let records = property_records();
    let permissions = machinery_permissions();
    assert_eq!(permissions.len(), records.len());
    for record in records {
        assert!(
            permissions
                .iter()
                .any(|row| row.problem_signature_id == record.problem_signature_id)
        );
    }
}

#[test]
fn witness_is_recognizable_but_global_minimality_is_unknown() {
    let records = property_records();
    let witness = records
        .iter()
        .find(|row| row.property_id == "DISTINGUISHING_WITNESS_EXISTENCE")
        .unwrap();
    let minimum = records
        .iter()
        .find(|row| row.property_id == "DISTINGUISHING_WITNESS_MINIMALITY")
        .unwrap();
    assert_eq!(witness.metatheoretic_status, "RECOGNIZABLE");
    assert_eq!(minimum.metatheoretic_status, "UNKNOWN");
}

#[test]
fn invariant_authority_is_language_parameterized() {
    let languages = invariant_languages();
    assert!(languages.len() >= 7);
    assert!(
        languages
            .iter()
            .any(|row| row.invariant_language_id == "TRACE_RELATIONAL_V1")
    );
    assert!(
        languages
            .iter()
            .all(|row| !row.invariant_language_id.is_empty())
    );
}

#[test]
fn semantic_fixtures_pass_without_earning_metatheory() {
    let fixtures = corpus();
    assert!(fixtures.len() >= 28);
    assert!(fixtures.iter().all(|row| row.status == "PASS"));
    assert!(fixtures.iter().all(|row| !row.earns_metatheorem));
}
