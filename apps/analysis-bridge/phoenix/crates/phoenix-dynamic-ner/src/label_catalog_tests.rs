use smallvec::SmallVec;

use crate::label_catalog::{
    domain_pack, label_description, labels_are_confusable, labels_for_domain,
    negative_labels_for_domain, push_labels, LABEL_ONTOLOGY_VERSION,
};
use crate::types::{DomainProfile, EntityLabel};

#[test]
fn story_catalog_keeps_character_adjacent_labels_small() {
    assert!(labels_for_domain(DomainProfile::Story).contains(&"Npc"));
    assert!(labels_for_domain(DomainProfile::Story).contains(&"Creature"));
    assert!(labels_for_domain(DomainProfile::Story).len() <= 8);
}

#[test]
fn technical_domain_has_negative_noise_labels() {
    let negatives = negative_labels_for_domain(DomainProfile::Technical);
    assert!(negatives.iter().any(|label| label.as_str() == "FilePath"));
}

#[test]
fn label_aliases_canonicalize_before_pack_insert() {
    let mut labels = SmallVec::<[EntityLabel; 16]>::new();
    push_labels(&mut labels, &["person", "Character", "crate"], 8);

    assert_eq!(
        labels
            .iter()
            .filter(|label| label.as_str() == "Character")
            .count(),
        1
    );
    assert!(labels.iter().any(|label| label.as_str() == "Library"));
}

#[test]
fn domain_packs_are_versioned_and_described() {
    let pack = domain_pack(DomainProfile::Story);
    assert_eq!(pack.version, LABEL_ONTOLOGY_VERSION);
    assert_eq!(pack.subdomain, "story-cast-world");
    assert!(pack.confusion_groups.contains(&"person-role-creature"));
    assert!(label_description("Npc").is_some());
}

#[test]
fn confusion_rules_cover_identity_split_risks() {
    assert!(labels_are_confusable("Character", "Npc"));
    assert!(labels_are_confusable("artifact", "weapon"));
    assert!(!labels_are_confusable("Location", "Benchmark"));
}
