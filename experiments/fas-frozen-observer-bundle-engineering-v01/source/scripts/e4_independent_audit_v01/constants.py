from __future__ import annotations

from dataclasses import dataclass


SEAL_SCHEMA = "FAS_E4_0_ARTIFACT_SEAL_V01"
CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V05"
CONTRACT_SEAL_ID = "FAS_E4_0_CONTRACT_V05_SEAL"
CONTRACT_STAGE = "E4_0_CONTRACT"
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
