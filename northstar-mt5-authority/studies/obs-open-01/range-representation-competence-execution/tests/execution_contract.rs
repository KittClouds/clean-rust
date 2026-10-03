use obs_open_03b::{P2_ROOT, P2T_ROOT};

#[test]
fn joint_authority_is_required() {
    assert_ne!(P2_ROOT, P2T_ROOT);
    assert_eq!(P2_ROOT.len(), 64);
    assert_eq!(P2T_ROOT.len(), 64);
}
