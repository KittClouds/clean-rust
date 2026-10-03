from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import numpy as np
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

WORKSPACE_ROOT = Path(__file__).resolve().parents[5]
FROZEN_MATH_PATH = WORKSPACE_ROOT / (
    "experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/"
    "e4_fresh_scorer_v04/scorer.py"
)
FROZEN_MATH_BYTES = 33616
FROZEN_MATH_SHA256 = "58bc957de63d430933570430ee0760a5833bc9c6ef5a82dae6dba78115b8b866"
SCORING_RUNTIME = ("3.13.15", "2.5.3", "2.11.0+cu128")
CONTRACT_SHA256 = "21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f"
CONTRACT_SEAL_MANIFEST_SHA256 = "0635de4a384b4d5121d8b2295e88a73f649c53e402ffcda311fcaf9c8d93099c"
CONTRACT_SEAL_ROOT_SHA256 = "278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1"
RUN_ID = "frozen-fabrique.e4-0.supervised.v1"
STAGE_ID = "E4_0_FRESH_QUALIFICATION_SCORING_V1"
PRIMARY_LABEL_ARTIFACT_ID = "E4_PRIMARY_TERMINAL_LABELS_V01"
PRIMARY_PANEL_ID = "e4-0-primary-terminal-v01"
PRIMARY_LABEL_RELATIVE_SOURCE_PATH = "labels/primary-terminal-labels-v01.jsonl"
PRIMARY_LABEL_SOURCE_SHA256 = "225787239ffb3d3920e2c299f0f05cdb59df88a89ddc11ed22edde9ac312a365"
PRIMARY_LABEL_SOURCE_BYTES = 39363264
PRIMARY_LABEL_ROWS = 74668
PRIMARY_LABEL_MAX_LINE_BYTES = 1024
POPULATION_ROOT_SHA256 = "27731b483b8242aaef15ca22b97796b7b305a79db9bbb235765e13dcd9d08967"
POPULATION_AUDIT_ROOT_SHA256 = "7dd3eea3133dbed779071fd14e22df06ff5a0ddce994e4446cf4c6ef7b9cbe5a"
PARITY_PANEL_ROOT_SHA256 = "6ef00306df0df20ada7b7a86b09567ae46e07f112f66d974d7885e8f1e5d4d95"
PARITY_STAGE_ROOT_SHA256 = "21b5cdd1f1dfbaaa132ffc8cea38f31bb26612bc438fb7e10ac3bffcb673ae73"
FEATURE_STAGE_ROOT_SHA256 = "b0395dd693fb115c74540647722c2e8f36c624fb5621097e9eb197b39acff17a"
FEATURE_CACHE_SHA256 = "49236412bf7409bd5f8d2c15f43436afa17940d51cc4bfdcdaf9d773029deac4"
FEATURE_CACHE_BYTES = 1223360512
FEATURE_CACHE_ROWS = 149336
FEATURE_DIMENSION = 2048
FEATURE_DTYPE = "<f4"
POPULATION_ROW_MANIFEST_SHA256 = "234a616bbbe1e392704e21c3d1b6402067d836b9f47a59d5432d01cd92c261b6"
POPULATION_ROW_MANIFEST_BYTES = 39686934
E3_BUNDLE_ROOT_SHA256 = "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1"
PREDECESSOR_ROOTS = {
    "e0_v10_root_sha256": "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
    "e1_v04_root_sha256": "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
    "e2_v07_root_sha256": "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
    "e3_v02_bundle_root_sha256": E3_BUNDLE_ROOT_SHA256,
    "e4_population_root_sha256": POPULATION_ROOT_SHA256,
    "e4_population_audit_root_sha256": POPULATION_AUDIT_ROOT_SHA256,
    "e4_parity_panel_root_sha256": PARITY_PANEL_ROOT_SHA256,
    "e4_parity_receipt_root_sha256": PARITY_STAGE_ROOT_SHA256,
    "e4_feature_cache_root_sha256": FEATURE_STAGE_ROOT_SHA256,
}
E3_HEAD_FILES = {
    "context_identity.bias.f32le": ("9a227cfb01b11139342724602166d63e1e0d28628a1584b2a83951ccd5810849", 128),
    "context_identity.mean.f32le": ("5e766a9b32ccf90d1af5eb7c95355bd68ee4eee4d323cd0649d82b915b8d0a83", 8192),
    "context_identity.scale.f32le": ("f4cb47ec89b1589216fe7065b019cf2187a36ac56200d3b91129d4f7a6eab4dd", 8192),
    "context_identity.weight.f32le": ("c7c820a399bd4ca2881a4d3ef3ba9714fdb9c13e4b65f5e73524fa4ac782129f", 262144),
    "entity_identity.bias.f32le": ("344252ca7e9dd53b834d9cfd6b08b08c2f824eb287085e2cf71524a0fc430258", 128),
    "entity_identity.mean.f32le": ("5e766a9b32ccf90d1af5eb7c95355bd68ee4eee4d323cd0649d82b915b8d0a83", 8192),
    "entity_identity.scale.f32le": ("f4cb47ec89b1589216fe7065b019cf2187a36ac56200d3b91129d4f7a6eab4dd", 8192),
    "entity_identity.weight.f32le": ("3ca325df60e5eb759217905b94393fbfa0c7ecae7f892199a3c6a4e29b48e26a", 262144),
    "exact_target.bias.f32le": ("14babc0c5434e65cf422f4442df1a30fc53a955c7c66cc14fba6513fa563c1bf", 12),
    "exact_target.mean.f32le": ("cfc6e158fdca8ea6de1e0900984540369b2cb4256b5dba312647065aa63e4ae9", 8192),
    "exact_target.scale.f32le": ("47c875c82247e90df2b85e47c156a6efe5c70f98e2785f50c120b91e15966396", 8192),
    "exact_target.weight.f32le": ("1378e7b2adf01954f4dffd998b636043da419bae95ff3f69a35edafc7ad26806", 24576),
    "observed_state.bias.f32le": ("16296373d974ad7d2470f82d8f51a88615c17171dad9d4d0dd28ac988f67d984", 12),
    "observed_state.mean.f32le": ("cfc6e158fdca8ea6de1e0900984540369b2cb4256b5dba312647065aa63e4ae9", 8192),
    "observed_state.scale.f32le": ("47c875c82247e90df2b85e47c156a6efe5c70f98e2785f50c120b91e15966396", 8192),
    "observed_state.weight.f32le": ("7aabdce61d23581677bc9247c3d01a73921048a445251f0e81538c46e1c92459", 24576),
    "relation.bias.f32le": ("8419828c927c49a7222bf92e56e1b385d4e48fc23f3aca69d2ffbb519a395317", 8),
    "relation.mean.f32le": ("cfc6e158fdca8ea6de1e0900984540369b2cb4256b5dba312647065aa63e4ae9", 8192),
    "relation.scale.f32le": ("47c875c82247e90df2b85e47c156a6efe5c70f98e2785f50c120b91e15966396", 8192),
    "relation.weight.f32le": ("5201ddab4060b7448c866647fdd50cc3ef401167eed70a2f867b7d4802cefd6c", 16384),
}
INVOCATION_SCHEMA = "FAS_E4_0_LEDGER_SCORING_HANDOFF_V01"
PANEL_DELIVERY_SCHEMA = "FAS_E4_0_LEDGER_PANEL_MATERIALIZATION_V01"
PANEL_DELIVERY_RELATIVE_PATH = "ledger-inputs/primary-panel-e4-v01.jsonl"
EXPECTED_SCOPE = {
    "evaluation_label_opening": True, "scoring": True,
    "population_generation": False, "tokenizer_contact": False, "model_contact": False,
    "feature_extraction": False, "fitting": False, "e4_a": False,
    "heldout_template_label_opening": False, "joint_template_label_opening": False,
}


@dataclass(frozen=True)
class MaterializedPrimaryPanel:
    rows: tuple[dict[str, Any], ...]
    receipt: dict[str, Any]
    local_file_open_count: int


def _file_identity(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb", buffering=0) as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _load_primary_row_manifest(path: Path) -> list[dict[str, Any]]:
    """Hash and parse the sealed row manifest in one sequential file pass."""
    digest, size = hashlib.sha256(), 0
    manifest: list[dict[str, Any]] = []
    with path.open("rb", buffering=0) as stream:
        for line_no, raw in enumerate(stream, start=1):
            digest.update(raw)
            size += len(raw)
            try:
                row = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError(f"invalid sealed row manifest at line {line_no}") from error
            if not isinstance(row, dict):
                raise RuntimeError(f"sealed row manifest line {line_no} is not an object")
            manifest.append(row)
    if (digest.hexdigest(), size) != (
        POPULATION_ROW_MANIFEST_SHA256, POPULATION_ROW_MANIFEST_BYTES
    ):
        raise RuntimeError("feature row manifest differs from the completed E4 extraction seal")
    if len(manifest) != FEATURE_CACHE_ROWS:
        raise RuntimeError("feature row manifest count differs from sealed feature cache")
    return manifest


def verify_e3_head_assets(e3_head_root: Path) -> dict[str, dict[str, Any]]:
    """Verify all five frozen E3 heads and scalers against their sealed bytes."""
    root = e3_head_root.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError("E3 observer bundle root is not a directory")
    verified: dict[str, dict[str, Any]] = {}
    for name, expected in E3_HEAD_FILES.items():
        path = root / name
        if _file_identity(path) != expected:
            raise RuntimeError(f"frozen E3 head asset identity mismatch: {name}")
        verified[name] = {"sha256": expected[0], "bytes": expected[1]}
    return verified


def load_frozen_math() -> SimpleNamespace:
    """Load immutable v04 science code after checking exact source identity."""
    if _file_identity(FROZEN_MATH_PATH) != (FROZEN_MATH_SHA256, FROZEN_MATH_BYTES):
        raise RuntimeError("frozen E4 scorer dependency hash or length changed")
    spec = importlib.util.spec_from_file_location("_e4_frozen_scorer_v04", FROZEN_MATH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load bound frozen E4 scoring implementation")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    required = {
        "DIMENSION": 2048, "MINIMUM_ROWS_PER_CLASS": 200, "PERFORMANCE_FLOOR": 0.90,
        "BOOTSTRAP_REPLICATES": 10000, "BOOTSTRAP_SEED": 2026092604,
        "BOOTSTRAP_CHUNK_REPLICATES": 64, "BOOTSTRAP_ALPHA": 0.00625,
        "ENDPOINT_ORDER": (
            "context_identity", "entity_identity", "relation", "observed_state",
            "exact_target_in_domain", "exact_target_context_novel",
            "exact_target_entity_novel", "exact_target_both_novel",
        ),
    }
    for name, value in required.items():
        if getattr(module, name, None) != value:
            raise RuntimeError(f"bound scorer differs from frozen contract field {name}")
    observed_runtime = (sys.version.split()[0], np.__version__, module.torch.__version__)
    if observed_runtime != SCORING_RUNTIME:
        raise RuntimeError("E4 scoring runtime differs from the E3 v02 bound environment")
    return SimpleNamespace(**required, validate_primary_manifest=module.validate_primary_manifest, load_frozen_heads=module.load_frozen_heads, predict_primary_rows=module.predict_primary_rows, join_primary_labels=module.join_primary_labels, score_primary_population=module.score_primary_population)


def prepare_primary_predictions(
    *, invocation: Mapping[str, Any], feature_cache_path: Path,
    row_manifest_path: Path, e3_head_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, np.ndarray], list[dict[str, Any]]]:
    """Verify sealed non-truth inputs and infer only registered primary rows."""
    validate_invocation(invocation)
    if _file_identity(feature_cache_path) != (FEATURE_CACHE_SHA256, FEATURE_CACHE_BYTES):
        raise RuntimeError("feature cache differs from the completed E4 extraction seal")
    manifest = _load_primary_row_manifest(row_manifest_path)
    cache = np.memmap(feature_cache_path, dtype=FEATURE_DTYPE, mode="r",
                      shape=(FEATURE_CACHE_ROWS, FEATURE_DIMENSION), order="C")
    math = load_frozen_math()
    verify_e3_head_assets(e3_head_root)
    heads = math.load_frozen_heads(e3_head_root)
    primary, predictions = math.predict_primary_rows(cache, manifest, heads)
    if len(primary) != PRIMARY_LABEL_ROWS:
        raise RuntimeError("primary inference selection differs from sealed population")
    return primary, predictions, manifest

def validate_invocation(invocation: Mapping[str, Any]) -> Path:
    """Validate a Library worker handoff; never create or issue authority."""
    if invocation.get("schema") != INVOCATION_SCHEMA or invocation.get("status") != "AUTHORIZED":
        raise RuntimeError("missing Ledger-authorized E4 scoring worker handoff")
    if (invocation.get("run_id"), invocation.get("stage_id")) != (RUN_ID, STAGE_ID):
        raise RuntimeError("Ledger handoff names another E4 run or stage")
    if invocation.get("contract_sha256") != CONTRACT_SHA256:
        raise RuntimeError("scoring handoff contract hash mismatch")
    if invocation.get("contract_seal_manifest_sha256") != CONTRACT_SEAL_MANIFEST_SHA256:
        raise RuntimeError("scoring handoff seal-manifest hash mismatch")
    if invocation.get("contract_seal_root_sha256") != CONTRACT_SEAL_ROOT_SHA256:
        raise RuntimeError("scoring handoff contract root mismatch")
    if invocation.get("predecessor_roots") != PREDECESSOR_ROOTS:
        raise RuntimeError("scoring handoff predecessor roots mismatch")
    authority = invocation.get("authority")
    if not isinstance(authority, Mapping) or not authority.get("authorization_id"):
        raise RuntimeError("Ledger handoff lacks a stage authorization identity")
    if authority.get("scope") != EXPECTED_SCOPE:
        raise RuntimeError("Ledger stage scope is broader or narrower than frozen E4 scoring")
    if authority.get("grant_verification") != "LEDGER_VERIFIED_BY_WORKER":
        raise RuntimeError("worker did not attest that Ledger verified the stage grant")
    attempt = invocation.get("attempt_root")
    if not isinstance(attempt, str) or not Path(attempt).is_absolute():
        raise RuntimeError("Ledger handoff lacks an absolute stage attempt root")
    return Path(attempt).resolve()


def _under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_panel_delivery(
    invocation: Mapping[str, Any], delivery: Mapping[str, Any], attempt_root: Path,
    staged_panel_file: Path | None = None,
) -> Path:
    """Bind one terminal exposure event to the primary sealed panel only."""
    expected = {
        "schema": PANEL_DELIVERY_SCHEMA, "status": "MATERIALIZED",
        "run_id": RUN_ID, "stage_id": STAGE_ID, "purpose": "terminal",
        "artifact_id": PRIMARY_LABEL_ARTIFACT_ID, "panel_id": PRIMARY_PANEL_ID,
        "source_population_root_sha256": POPULATION_ROOT_SHA256,
        "source_sha256": PRIMARY_LABEL_SOURCE_SHA256,
        "source_bytes": PRIMARY_LABEL_SOURCE_BYTES, "source_rows": PRIMARY_LABEL_ROWS,
        "open_panel_event_count": 1, "escrow_panel_open_count": 0,
        "escrow_materialized": False,
        "panel_id_resolves_to_artifact_id": PRIMARY_LABEL_ARTIFACT_ID,
        "materialized_relative_path": PANEL_DELIVERY_RELATIVE_PATH,
    }
    for field, value in expected.items():
        if delivery.get(field) != value:
            raise RuntimeError(f"Ledger panel delivery differs from expected field {field}")
    if not delivery.get("exposure_event_id"):
        raise RuntimeError("Ledger exposure event ID is missing")
    if delivery.get("exposure_event_id") != invocation.get("exposure_event_id"):
        raise RuntimeError("materialization is not tied to the Ledger exposure event")
    rel = PurePosixPath(PANEL_DELIVERY_RELATIVE_PATH)
    expected_path = attempt_root.joinpath(*rel.parts).resolve()
    path = expected_path if staged_panel_file is None else staged_panel_file.resolve(strict=True)
    if rel.is_absolute() or not _under_root(expected_path, attempt_root):
        raise RuntimeError("Library materialized input escaped the authorized attempt root")
    if path != expected_path or not _under_root(path, attempt_root):
        raise RuntimeError("worker source-file path differs from the staged primary-panel path")
    if path.name == Path(PRIMARY_LABEL_RELATIVE_SOURCE_PATH).name and path.parent.name != "ledger-inputs":
        raise RuntimeError("original protected label path is not an execution input")
    if not path.is_file():
        raise RuntimeError("Library materialized primary panel is missing")
    return path


class OneShotLibraryPanelReader:
    """Read only the Library materialization after Ledger event validation."""
    def __init__(self) -> None:
        self.attempted = False
        self.local_file_open_count = 0
        self.local_file_open_attempt_count = 0
        self.last_receipt: dict[str, Any] | None = None

    def read_once(
        self, invocation: Mapping[str, Any], delivery: Mapping[str, Any],
        staged_panel_file: Path | None = None,
    ) -> MaterializedPrimaryPanel:
        if self.attempted:
            raise RuntimeError("primary panel materialization is one-shot")
        attempt_root = validate_invocation(invocation)
        path = validate_panel_delivery(invocation, delivery, attempt_root, staged_panel_file)
        self.attempted = True
        digest, size, rows = hashlib.sha256(), 0, []
        self.local_file_open_attempt_count = 1
        self.last_receipt = {
            "schema": "FAS_E4_0_PRIMARY_LABEL_OPEN_RECEIPT_V03",
            "status": "PRIMARY_PANEL_READ_IN_PROGRESS",
            "artifact_id": PRIMARY_LABEL_ARTIFACT_ID,
            "population_root_sha256": POPULATION_ROOT_SHA256,
            "expected_source_sha256": PRIMARY_LABEL_SOURCE_SHA256,
            "expected_source_bytes": PRIMARY_LABEL_SOURCE_BYTES,
            "expected_rows": PRIMARY_LABEL_ROWS,
            "ledger_panel_id": delivery["panel_id"],
            "ledger_exposure_event_id": delivery["exposure_event_id"],
            "ledger_open_panel_event_count": 1,
            "scorer_materialized_file_open_attempt_count": 1,
            "scorer_materialized_file_open_count": 0,
            "scorer_semantic_label_parse_count": 0,
            "bytes_read_before_validation": 0,
            "library_source_file_hash_read_expected": True,
            "heldout_template_labels_opened": False,
            "joint_template_labels_opened": False,
        }
        with path.open("rb", buffering=0) as stream:
            self.local_file_open_count = 1
            for line_no, raw in enumerate(stream, start=1):
                digest.update(raw)
                size += len(raw)
                if len(raw) > PRIMARY_LABEL_MAX_LINE_BYTES:
                    raise RuntimeError(f"primary label line exceeds frozen limit at line {line_no}")
                try:
                    row = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise RuntimeError(f"invalid primary label JSONL at line {line_no}") from error
                if not isinstance(row, dict):
                    raise RuntimeError(f"primary label row is not an object at line {line_no}")
                rows.append(row)
                self.last_receipt["scorer_materialized_file_open_count"] = 1
                self.last_receipt["scorer_semantic_label_parse_count"] = len(rows)
                self.last_receipt["bytes_read_before_validation"] = size
        observed = digest.hexdigest()
        if size != PRIMARY_LABEL_SOURCE_BYTES or observed != PRIMARY_LABEL_SOURCE_SHA256:
            raise RuntimeError("Library materialization differs from sealed primary panel bytes")
        if len(rows) != PRIMARY_LABEL_ROWS:
            raise RuntimeError("Library materialization row count differs from sealed primary panel")
        receipt = {
            "schema": "FAS_E4_0_PRIMARY_LABEL_OPEN_RECEIPT_V03",
            "artifact_id": PRIMARY_LABEL_ARTIFACT_ID,
            "population_root_sha256": POPULATION_ROOT_SHA256,
            "source_sha256": observed, "source_bytes": size, "rows": len(rows),
            "ledger_panel_id": delivery["panel_id"],
            "ledger_exposure_event_id": delivery["exposure_event_id"],
            "ledger_open_panel_event_count": 1,
            "scorer_materialized_file_open_attempt_count": 1,
            "scorer_materialized_file_open_count": 1,
            "scorer_semantic_label_parse_count": len(rows),
            "library_source_file_hash_read_expected": True,
            "heldout_template_labels_opened": False, "joint_template_labels_opened": False,
        }
        self.last_receipt = receipt
        return MaterializedPrimaryPanel(tuple(rows), receipt, 1)


def score_from_ledger_materialization(
    *, invocation: Mapping[str, Any], delivery: Mapping[str, Any],
    manifest: Sequence[Mapping[str, Any]], predictions: Mapping[str, Any],
    reader: OneShotLibraryPanelReader, staged_panel_file: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Score supplied frozen-head predictions against one Ledger-gated panel."""
    math = load_frozen_math()
    primary = math.validate_primary_manifest(manifest)
    if len(primary) != PRIMARY_LABEL_ROWS:
        raise RuntimeError("primary manifest count differs from the frozen population")
    panel = reader.read_once(invocation, delivery, staged_panel_file)
    joined = math.join_primary_labels(primary, panel.rows, predictions)
    return math.score_primary_population(joined), panel.receipt, joined
