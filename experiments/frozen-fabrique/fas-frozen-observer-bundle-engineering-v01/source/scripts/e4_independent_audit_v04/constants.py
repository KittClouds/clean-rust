from __future__ import annotations

from dataclasses import dataclass


SEAL_SCHEMA = "FAS_E4_0_ARTIFACT_SEAL_V01"
CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V08"
CONTRACT_SEAL_ID = "FAS_E4_0_CONTRACT_V08_SEAL"
CONTRACT_STAGE = "E4_0_CONTRACT"

# The v06 population and tokenizer-only parity-panel artifacts are immutable
# inherited stages. Later stages must bind the v07 engineering amendment.
INHERITED_V06_CONTRACT = {
    "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06",
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v06-final.json",
    "bytes": 43_208,
    "sha256": "ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958",
}
INHERITED_V06_SEAL = {
    "seal_id": "FAS_E4_0_CONTRACT_V06_SEAL",
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v06-seal.json",
    "manifest_bytes": 35_340,
    "manifest_sha256": "799d1535a16ea6fbf2269206443addf96736ef8a70ca5ab3373cdd5e6a44605c",
    "root_sha256": "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64",
    "contract_member_artifact_id": "E4_0_CONTRACT_V06_FINAL",
}
INHERITED_V06_LINEAGE = {
    "contract": INHERITED_V06_CONTRACT,
    "seal": INHERITED_V06_SEAL,
}
INHERITED_V06_SEAL_MEMBERS = {
    "contract_artifact_id": "E4_0_CONTRACT_V06_SUPERSEDED",
    "seal_artifact_id": "E4_0_CONTRACT_V06_SEAL_SUPERSEDED",
}
IMMEDIATE_V07_CONTRACT = {
    "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V07",
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v07-final.json",
    "bytes": 48_881,
    "sha256": "33b56e95cbf083036f436b5496c2db3c0c052bacfdce593869a6f4aa3125a2d7",
}
IMMEDIATE_V07_SEAL = {
    "seal_id": "FAS_E4_0_CONTRACT_V07_SEAL",
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v07-seal.json",
    "manifest_bytes": 52_723,
    "manifest_sha256": "22e2d05255a87334d27713d222fc4023fd1cac61dafc4264c5de434bbf4c71ef",
    "root_sha256": "ee7339c3ab04272354b4cae03294c794a6e823fdb1766ad44f71978dfee0c62c",
    "contract_member_artifact_id": "E4_0_CONTRACT_V07_FINAL",
}
IMMEDIATE_V07_POSTSEAL_AUDIT = {
    "receipt_id": "FAS_E4_0_TRACK_E_V07_POSTSEAL_AUDIT_V01",
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-postseal-receipt-v07.json",
    "bytes": 48_718,
    "sha256": "b328770fbdf25b96b40bac33ccec67ca1673c331328e5413727392d586f857f2",
    "status": "E4_0_TRACK_E_POSTSEAL_PASS_V07_SEAL_ROOT_AND_MEMBERS_RECOMPUTED",
    "root_sha256": "ee7339c3ab04272354b4cae03294c794a6e823fdb1766ad44f71978dfee0c62c",
}
IMMEDIATE_V07_AMENDMENT_AUDIT = {
    key: IMMEDIATE_V07_POSTSEAL_AUDIT[key]
    for key in ("path", "bytes", "sha256", "status", "root_sha256")
}
IMMEDIATE_V07_LINEAGE = {
    "contract": IMMEDIATE_V07_CONTRACT,
    "seal": IMMEDIATE_V07_SEAL,
}
IMMEDIATE_V07_SEAL_MEMBERS = {
    "contract_artifact_id": "E4_0_CONTRACT_V07_SUPERSEDED",
    "seal_artifact_id": "E4_0_CONTRACT_V07_SEAL_SUPERSEDED",
}
V07_PREVIOUS_LINEAGE = {
    "contract": INHERITED_V06_CONTRACT,
    "seal": INHERITED_V06_SEAL,
}
INHERITED_V06_STAGE_NAMES = frozenset({"POPULATION_GENERATION", "PARITY_PANEL_MATERIALIZATION"})
V08_STAGE_NAMES = frozenset({"ONLINE_CACHE_PARITY", "FRESH_FEATURE_EXTRACTION", "FRESH_SCORING"})
INHERITED_V06_POPULATION_SEAL_RUN_RELATIVE_PATH = "stage-seal-v01.json"
INHERITED_V06_POPULATION_AUDIT_WORKSPACE_RELATIVE_PATH = (
    "experiments/fas-frozen-observer-bundle-engineering-v01/"
    "audits/e4-0-execution/population-independent-audit-receipt-v01.json"
)

PREVIOUS_CONTRACT_LINEAGE = {
    "contract": IMMEDIATE_V07_CONTRACT,
    "seal": IMMEDIATE_V07_SEAL,
    "seal_members": IMMEDIATE_V07_SEAL_MEMBERS,
}
ENDPOINT_ORDER = (
    "context_identity",
    "entity_identity",
    "relation",
    "observed_state",
    "exact_target_in_domain",
    "exact_target_context_novel",
    "exact_target_entity_novel",
    "exact_target_both_novel",
)
TASKS = {
    "context_identity": ("context_term_id", 32, "all"),
    "entity_identity": ("entity_term_id", 32, "all"),
    "relation": ("relation_id", 2, "train_side"),
    "observed_state": ("state_id", 3, "train_side"),
    "exact_target": ("exact_target", 3, "all"),
}
ENDPOINT_SPECS = {
    "context_identity": ("context_term_id", 32, "context_identity", None),
    "entity_identity": ("entity_term_id", 32, "entity_identity", None),
    "relation": ("relation_id", 2, "relation", None),
    "observed_state": ("state_id", 3, "observed_state", None),
    "exact_target_in_domain": ("exact_target", 3, "exact_target", "IN_DOMAIN"),
    "exact_target_context_novel": ("exact_target", 3, "exact_target", "CONTEXT_NOVEL"),
    "exact_target_entity_novel": ("exact_target", 3, "exact_target", "ENTITY_NOVEL"),
    "exact_target_both_novel": ("exact_target", 3, "exact_target", "BOTH_NOVEL"),
}
VARIANTS = ("A", "C", "E", "P")
SURFACES = (
    ("PRIMARY_SEEN", "PRIMARY_TERMINAL"),
    ("HELDOUT_TEMPLATE", "TEMPLATE_ESCROW"),
)
PRIMARY_LABEL_ID = "E4_PRIMARY_TERMINAL_LABELS_V01"
ESCROW_LABEL_ID = "E4_TEMPLATE_JOINT_ESCROW_LABELS_V01"
TRUTH_MEMBER_IDS = frozenset((PRIMARY_LABEL_ID, ESCROW_LABEL_ID))
EXPECTED_PREDECESSORS = {
    "e0_v10_root_sha256": "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
    "e1_v04_root_sha256": "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
    "e2_v07_root_sha256": "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
    "e3_v02_bundle_root_sha256": "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1",
}
E4_ROOT_KEYS = (
    "e0_v10_root_sha256",
    "e1_v04_root_sha256",
    "e2_v07_root_sha256",
    "e3_v02_bundle_root_sha256",
    "e4_population_root_sha256",
    "e4_population_audit_root_sha256",
    "e4_parity_panel_root_sha256",
    "e4_parity_receipt_root_sha256",
    "e4_feature_cache_root_sha256",
)


@dataclass(frozen=True)
class FrozenGates:
    quartets: int = 18_667
    total_rows: int = 149_336
    primary_rows: int = 74_668
    feature_dimension: int = 2_048
    feature_bytes: int = 1_223_360_512
    support_minimum: int = 200
    support_construction_target: int = 250
    bootstrap_replicates: int = 10_000
    bootstrap_seed: int = 2_026_092_604
    bootstrap_chunk: int = 64
    alpha: float = 0.00625
    performance_floor: float = 0.90


GATES = FrozenGates()
