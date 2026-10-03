use crate::model::{AuthorityBinding, FiberCertificate, SyntheticMachine};
use crate::{G3_ROOT, G4_ROOT, G5_ROOT, G6_ROOT, G7_ROOT, THETA_STAR_ID};
use serde::Serialize;
use sha2::{Digest, Sha256};

pub const SEPARATOR_SCHEMA_ID: &str = "FINITE_SEPARATOR_CERTIFICATE_V1";
pub const SEPARATOR_SCHEMA_VERSION: u32 = 1;
pub const VERIFIER_CONTRACT_ID: &str = "G8_EXACT_SEPARATOR_VERIFIER_V1";
pub const FIBER_CERTIFICATE_SCHEMA: &str = "QUALIFIED_COMPARISON_FIBER_CERTIFICATE_V1";
pub const SYNTHETIC_FIBER_SOURCE: &str = "SYNTHETIC_FINITE_SYSTEM_CONSTRUCTION";
pub const UNIVERSAL_PROOF_SYSTEM_ID: &str = "FINITE_PRODUCT_INDUCTIVE_RELATION_V1";

pub fn sha256(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

pub fn hash_json<T: Serialize + ?Sized>(value: &T) -> String {
    sha256(&serde_json::to_vec(value).expect("serializable authority object"))
}

pub fn verifier_contract_hash() -> String {
    sha256(b"G8_EXACT_SEPARATOR_VERIFIER_V1|PRIMITIVE_EVIDENCE_ONLY|RECOMPUTE_FIBER_PRESENTABILITY_KERNEL_CORRESPONDENCE_G4_MISMATCH|CHECKED_I64|NO_EXPLORER_DEPENDENCY")
}

pub fn authority_bundle_hash() -> String {
    sha256(
        format!(
            "{G3_ROOT}|{G4_ROOT}|{G5_ROOT}|{G6_ROOT}|{G7_ROOT}|{THETA_STAR_ID}|{}|{}",
            verifier_contract_hash(),
            SEPARATOR_SCHEMA_VERSION
        )
        .as_bytes(),
    )
}

pub fn expected_binding() -> AuthorityBinding {
    AuthorityBinding {
        g3_root: G3_ROOT.into(),
        g4_root: G4_ROOT.into(),
        g5_root: G5_ROOT.into(),
        g6_root: G6_ROOT.into(),
        g7_root: G7_ROOT.into(),
        theta_star_id: THETA_STAR_ID.into(),
        certificate_schema_id: SEPARATOR_SCHEMA_ID.into(),
        certificate_schema_version: SEPARATOR_SCHEMA_VERSION,
        g8_verifier_contract_hash: verifier_contract_hash(),
        authority_bundle_hash: authority_bundle_hash(),
    }
}

pub fn synthetic_fiber_certificate(
    left: &SyntheticMachine,
    right: &SyntheticMachine,
) -> FiberCertificate {
    let construction = (
        FIBER_CERTIFICATE_SCHEMA,
        SYNTHETIC_FIBER_SOURCE,
        &left.fiber_id,
        &left.machine_id,
        &right.machine_id,
        left,
        right,
    );
    FiberCertificate {
        schema_id: FIBER_CERTIFICATE_SCHEMA.into(),
        source: SYNTHETIC_FIBER_SOURCE.into(),
        fiber_id: left.fiber_id.clone(),
        left_machine_id: left.machine_id.clone(),
        right_machine_id: right.machine_id.clone(),
        construction_proof_hash: hash_json(&construction),
    }
}

pub fn verify_synthetic_fiber_certificate(
    certificate: &FiberCertificate,
    left: &SyntheticMachine,
    right: &SyntheticMachine,
) -> bool {
    if left.fiber_id != right.fiber_id
        || certificate.schema_id != FIBER_CERTIFICATE_SCHEMA
        || certificate.source != SYNTHETIC_FIBER_SOURCE
        || certificate.fiber_id != left.fiber_id
        || certificate.left_machine_id != left.machine_id
        || certificate.right_machine_id != right.machine_id
    {
        return false;
    }
    certificate == &synthetic_fiber_certificate(left, right)
}
