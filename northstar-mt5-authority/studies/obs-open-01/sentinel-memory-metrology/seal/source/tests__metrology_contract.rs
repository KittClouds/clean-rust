use obs_open_04a::model::{RelationClass, RepresentationId};

#[test]
fn representation_ids_are_distinct() {
    assert_ne!(RepresentationId::History, RepresentationId::SemanticTape);
    assert_ne!(RepresentationId::SourceTape, RepresentationId::CurrentState);
    assert_ne!(
        RepresentationId::CurrentState,
        RepresentationId::ReducedState
    );
}

#[test]
fn relation_vocabulary_is_typed() {
    let classes = [
        RelationClass::LossyQuotient,
        RelationClass::ReconstructibleWithContext,
        RelationClass::NonReconstructible,
    ];
    assert_eq!(classes.len(), 3);
}
