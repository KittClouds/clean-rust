from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


INTERFACE_VERSION = "MST_RG2_RESEARCH_INTERFACE_V1_1"
EXPECTED_CORPUS_CONTRACT = "MST_RG2_IMMUTABLE_CORPUS_SEAL_V1"
EXPECTED_DATASET_CONTRACT = "MST_AUCTION_RELATIONAL_V1"
EXPECTED_RESEARCH_GENERATION = "2"
EXPECTED_DATASET_SCHEMA = "7"
NULL_TOKEN = "\\N"

DATASETS = ("events", "attempts", "episodes", "context", "features", "transits", "runs")
PRIMARY_KEYS = {
    "events": ("run_key", "event_id"),
    "attempts": ("run_key", "attempt_id"),
    "episodes": ("run_key", "episode_id"),
    "features": ("run_key", "attempt_id"),
    "transits": ("run_key", "transit_id"),
}
BEHAVIORAL_ATTEMPT_OUTCOMES = frozenset({
    "REJECT_TO_ORIGIN",
    "RECLAIM_AFTER_BREAK",
    "ACCEPT_THROUGH_NODE",
    "ACCEPT_AND_HOLD_RETEST",
    "ACCEPT_AND_FAIL_RETEST",
})
ACCEPTANCE_OUTCOMES = frozenset({
    "ACCEPT_THROUGH_NODE", "ACCEPT_AND_HOLD_RETEST", "ACCEPT_AND_FAIL_RETEST",
})
BEHAVIORAL_TRANSIT_OUTCOMES = frozenset({"TRANSIT_TO_NEXT_NODE", "RETURN_TO_SOURCE_NODE"})

ID_COLUMNS = frozenset({
    "run_key", "invocation_id", "event_id", "attempt_id", "episode_id", "transit_id",
    "node_id", "evidence_id", "related_node_id", "source_node_id", "destination_node_id",
    "nearest_above_id", "nearest_below_id", "source_key", "local_id", "run_key_hash",
    "terminal_hash", "receipt_hash", "contract_receipt_hash", "structure_snapshot_hash",
    "regional_basis_hash", "source_fingerprint_hash",
})
INTEGER_COLUMNS = frozenset({
    "dataset_schema", "contract_version", "research_generation", "ordinal", "is_retest",
    "start", "contact", "break", "accepted", "end", "timestamp", "bar_time", "frozen_at",
    "frozen_bar_time", "window_start", "window_end", "start_bar", "contact_bar", "end_bar",
    "event_sequence", "bar_sequence", "attempt_event_sequence", "direction", "resolution_code",
    "completion_status_code", "censor_reason_code", "record_type_code", "run_status_code",
    "producer_code", "producer_instance", "family_code", "source_kind", "attempts", "breaks",
    "reclaims", "retests", "duration_bars", "duration_seconds", "inside_updates", "inside_seconds",
    "far_closes", "family_mask", "family_count", "member_count", "developing_count",
    "frozen_count", "node_revision", "corridor_up_level_count", "corridor_down_level_count",
    "corridor_up_noise_count", "corridor_down_noise_count", "regional_valid", "sigma_valid",
    "basis_changed", "structure_generation", "population_count", "population_count_delta",
    "velocity_elapsed_bars", "raw_level_count", "noise_level_count", "active_node_count",
    "has_cog", "has_c3", "has_lattice", "has_field", "has_profile", "first_direction",
    "attempts_started", "attempts_resolved", "attempts_censored", "episodes_started",
    "episodes_resolved", "episodes_censored", "transits_started", "transits_resolved",
    "transits_censored", "events_emitted", "active_attempts", "active_episodes",
    "active_transits", "balanced", "event_rows", "attempt_rows", "episode_rows",
    "context_rows", "feature_rows", "transit_rows", "contract_violations",
    "duplicate_primary_keys", "orphan_foreign_keys", "invalid_required_values",
    "invalid_completion_rows", "invalid_transit_nodes", "missing_feature_rows",
    "missing_context_attempts", "enum_codes_valid", "row_balances_valid", "relational_valid",
    "run_complete", "contract_valid", "digits", "tester", "visual_mode",
})


class CorpusContractError(RuntimeError):
    pass


class HoldoutAccessError(CorpusContractError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _one(root: Path, pattern: str) -> Path:
    matches = list(root.glob(pattern))
    if len(matches) != 1:
        raise CorpusContractError(f"expected one {pattern} under {root}, found {len(matches)}")
    return matches[0]


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def verify_run_seal(run_directory: Path) -> dict[str, Any]:
    seal_path = run_directory / "seal.json"
    if not seal_path.is_file():
        raise CorpusContractError(f"missing run seal: {seal_path}")
    seal = json.loads(seal_path.read_text(encoding="utf-8-sig"))
    if seal.get("contract") != "MST_IMMUTABLE_RUN_SEAL_V1" or seal.get("status") != "SEALED":
        raise CorpusContractError(f"invalid run seal contract/status: {run_directory.name}")

    listed: set[str] = set()
    material: list[str] = []
    for receipt in seal.get("files", []):
        relative = str(receipt["path"]).replace("\\", "/")
        listed.add(relative)
        path = run_directory / Path(relative)
        if not path.is_file():
            raise CorpusContractError(f"sealed file missing: {relative}")
        size = path.stat().st_size
        digest = _sha256(path)
        if size != int(receipt["bytes"]) or digest != receipt["sha256"]:
            raise CorpusContractError(f"sealed file mismatch: {relative}")
        material.append(f"{relative}\t{size}\t{digest}")

    actual_files = {
        path.relative_to(run_directory).as_posix()
        for path in run_directory.rglob("*") if path.is_file() and path != seal_path
    }
    if actual_files != listed:
        extra = sorted(actual_files - listed)
        missing = sorted(listed - actual_files)
        raise CorpusContractError(f"unsealed run file set: extra={extra} missing={missing}")
    payload = hashlib.sha256("\n".join(material).encode("utf-8")).hexdigest()
    if payload != seal.get("sealed_payload_sha256"):
        raise CorpusContractError(f"sealed payload mismatch: {run_directory.name}")
    if int(seal.get("file_count", -1)) != len(listed):
        raise CorpusContractError(f"sealed file count mismatch: {run_directory.name}")
    return seal


def _canonical_corpus_hash(run_receipts: Sequence[dict[str, Any]], manifest_sha: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"MST_RG2_CANONICAL_CORPUS_V1\0")
    digest.update(manifest_sha.encode())
    for row in sorted(run_receipts, key=lambda value: value["terminal"]["run_key"]):
        terminal, seal = row["terminal"], row["seal"]
        fields = [
            terminal["run_key"], terminal["config_hash"], terminal["dataset_schema_version"],
            terminal["data_source_id"], terminal["data_fingerprint"],
            seal["canonical_dataset_hash"], seal["sealed_payload_sha256"],
        ]
        digest.update(("\t".join(map(str, fields)) + "\n").encode())
    return digest.hexdigest()


def verify_corpus(workspace: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    seal_root = workspace / "phase10" / "seal"
    corpus_root = workspace / "furnace" / "corpus"
    seal_path = seal_root / "corpus_seal.json"
    if not seal_path.is_file():
        raise CorpusContractError("Phase 10 corpus seal is absent")
    corpus_seal = json.loads(seal_path.read_text(encoding="utf-8-sig"))
    if (corpus_seal.get("contract") != EXPECTED_CORPUS_CONTRACT
            or corpus_seal.get("status") != "SEALED"):
        raise CorpusContractError("Phase 10 corpus is not sealed")
    if str(corpus_seal.get("research_generation")) != EXPECTED_RESEARCH_GENERATION:
        raise CorpusContractError("unexpected research generation")
    for name, expected in corpus_seal.get("artifacts", {}).items():
        path = seal_root / name
        if not path.is_file() or _sha256(path) != expected:
            raise CorpusContractError(f"corpus seal artifact mismatch: {name}")

    rows: list[dict[str, Any]] = []
    for directory in sorted(corpus_root.iterdir()):
        if not directory.is_dir():
            continue
        run_seal = verify_run_seal(directory)
        admission = json.loads((directory / "receipts" / "admission_receipt.json").read_text(encoding="utf-8-sig"))
        terminal = json.loads((directory / "receipts" / "terminal_run_receipt.json").read_text(encoding="utf-8-sig"))
        if run_seal["run_key"] != terminal["run_key"] or admission["run_key"] != terminal["run_key"]:
            raise CorpusContractError(f"run identity mismatch: {directory.name}")
        if terminal.get("contract_id") != EXPECTED_DATASET_CONTRACT:
            raise CorpusContractError(f"dataset contract mismatch: {directory.name}")
        if str(terminal.get("research_generation")) != EXPECTED_RESEARCH_GENERATION:
            raise CorpusContractError(f"generation mismatch: {directory.name}")
        if str(terminal.get("dataset_schema_version")) != EXPECTED_DATASET_SCHEMA:
            raise CorpusContractError(f"schema mismatch: {directory.name}")
        if terminal.get("run_status") != "COMPLETE" or str(terminal.get("contract_valid")) != "1":
            raise CorpusContractError(f"incomplete run: {directory.name}")
        rows.append({"directory": directory, "seal": run_seal, "admission": admission, "terminal": terminal})

    if len(rows) != int(corpus_seal.get("run_count", -1)):
        raise CorpusContractError("corpus run count mismatch")
    actual_hash = _canonical_corpus_hash(rows, corpus_seal["campaign_manifest_sha256"])
    if actual_hash != corpus_seal.get("canonical_corpus_sha256"):
        raise CorpusContractError("canonical corpus hash mismatch")
    return corpus_seal, rows


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if column in ID_COLUMNS or column.endswith("_hash"):
            result[column] = result[column].astype("string")
        elif column in INTEGER_COLUMNS or column.endswith("_code"):
            result[column] = pd.to_numeric(result[column], errors="coerce").astype("Int64")
        elif column in {
            "contract_id", "record_type", "run_status", "build_id", "controller_version",
            "topology_version", "auction_grammar_version", "feature_schema_version",
            "dataset_schema_version", "producer_bundle_version", "preset_id", "canonical_instrument",
            "data_source_id", "data_fingerprint", "symbol", "timeframe", "account_server",
            "account_company", "terminal_reason", "config_hash", "config_text", "timestamp_encoding",
            "timestamp_timezone", "null_token", "price_precision_rule", "migration_rule", "resolution",
            "completion_status", "censor_reason", "event_type", "producer", "family", "price_region",
            "cog_region", "start_region", "end_region", "node_region", "initial_region",
            "terminal_region", "source_region", "destination_region", "start_price_region",
            "end_price_region",
        }:
            result[column] = result[column].astype("string")
        else:
            converted = pd.to_numeric(result[column], errors="coerce")
            nonnull = result[column].notna().sum()
            if nonnull == 0 or converted.notna().sum() == nonnull:
                result[column] = converted.astype("float64")
            else:
                result[column] = result[column].astype("string")
    return result


@dataclass(frozen=True)
class QuerySpec:
    target: str
    group_by: tuple[str, ...] = ()
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    partition: str = "RG2_EXPLORATORY"
    censoring_treatment: str = "exclude_censored_from_estimate_retain_counts"

    @classmethod
    def create(
        cls,
        target: str,
        group_by: Iterable[str] = (),
        filters: Mapping[str, Iterable[Any] | Any] | None = None,
        partition: str = "RG2_EXPLORATORY",
    ) -> "QuerySpec":
        frozen_filters = []
        for key, value in sorted((filters or {}).items()):
            values = value if isinstance(value, (list, tuple, set, frozenset)) else (value,)
            frozen_filters.append((key, tuple(sorted(map(str, values)))))
        return cls(target=target, group_by=tuple(group_by), filters=tuple(frozen_filters), partition=partition)


@dataclass
class ResearchResult:
    table: pd.DataFrame
    receipt: dict[str, Any]

    def write(self, output_directory: Path, workspace: Path) -> tuple[Path, Path]:
        output = output_directory.resolve()
        protected = [workspace / "furnace" / "corpus", workspace / "phase10" / "seal"]
        if any(_inside(output, root) or output == root.resolve() for root in protected):
            raise CorpusContractError("research results cannot be written inside sealed corpus paths")
        output.mkdir(parents=True, exist_ok=True)
        query_hash = self.receipt["query_spec_sha256"]
        data_path = output / f"result_{query_hash[:16]}.tsv"
        receipt_path = output / f"result_{query_hash[:16]}.receipt.json"
        self.table.to_csv(data_path, sep="\t", index=False, na_rep=NULL_TOKEN)
        receipt = dict(self.receipt)
        receipt["result_file"] = data_path.name
        receipt["result_sha256"] = _sha256(data_path)
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        return data_path, receipt_path


@dataclass
class TargetCohort:
    frame: pd.DataFrame
    receipt: dict[str, Any]


class ResearchCorpus:
    """Verified, copy-on-read interface to the sealed RG2 corpus."""

    def __init__(self, workspace: Path, verify: bool = True) -> None:
        self.workspace = workspace.resolve()
        if not verify:
            raise CorpusContractError("seal verification cannot be disabled")
        self.corpus_seal, self._run_receipts = verify_corpus(self.workspace)
        self._schema = json.loads(
            (self.workspace / "phase10" / "seal" / "schema_dictionary.json").read_text(encoding="utf-8-sig")
        )
        self._replay_keys = self._load_replay_keys()
        self._holdouts = self._load_holdouts()
        self._tables = self._load_tables()
        self._node_birth = self._load_node_births()
        self._validate_relations()
        self._assert_holdouts_untouched()
        self._attempt_view = self._build_attempt_view()
        self._chain_view = self._build_attempt_chain_view()
        self._transit_view = self._build_transit_view()

    @property
    def corpus_hash(self) -> str:
        return str(self.corpus_seal["canonical_corpus_sha256"])

    @property
    def interface_code_hash(self) -> str:
        root = Path(__file__).parent
        digest = hashlib.sha256()
        for path in sorted(root.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _load_replay_keys(self) -> set[str]:
        path = self.workspace / "furnace" / "replay_verification.json"
        if not path.is_file():
            raise CorpusContractError("replay verification receipt missing")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if value.get("status") != "PASS":
            raise CorpusContractError("replay verification is not PASS")
        keys: set[str] = set()
        for item in value.get("replays", value.get("verified", [])):
            if isinstance(item, Mapping) and item.get("run_key"):
                keys.add(str(item["run_key"]))
        if not keys:
            # Older receipt shape stores the sampled run directly.
            for item in value.values():
                if isinstance(item, Mapping) and item.get("run_key"):
                    keys.add(str(item["run_key"]))
                elif isinstance(item, list):
                    keys.update(str(row["run_key"]) for row in item if isinstance(row, Mapping) and row.get("run_key"))
        if not keys:
            raise CorpusContractError("PASS replay receipt contains no run key")
        return keys

    def _load_holdouts(self) -> pd.DataFrame:
        path = self.workspace / "campaign_holdout_reservations.tsv"
        frame = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, na_values=[NULL_TOKEN])
        for column in ("research_generation", "window_start", "window_end_exclusive"):
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype("Int64")
        if not frame["status"].eq("RESERVED_UNTOUCHED").all():
            raise CorpusContractError("holdout reservation status drift")
        return frame

    def _load_tables(self) -> dict[str, pd.DataFrame]:
        pieces: dict[str, list[pd.DataFrame]] = {name: [] for name in DATASETS}
        schema_datasets = self._schema["datasets"]
        for row in self._run_receipts:
            auction = row["directory"] / "raw" / "auction"
            expected_run = row["terminal"]["run_key"]
            for name in DATASETS:
                path = _one(auction, f"*_{name}.tsv")
                raw = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, na_values=[NULL_TOKEN])
                expected_columns = schema_datasets[name]["columns"]
                if list(raw.columns) != expected_columns:
                    raise CorpusContractError(f"{name} schema drift in {expected_run}")
                if not raw["run_key"].eq(expected_run).all():
                    raise CorpusContractError(f"foreign run key in {name}: {expected_run}")
                if not raw["contract_id"].eq(EXPECTED_DATASET_CONTRACT).all():
                    raise CorpusContractError(f"contract drift in {name}: {expected_run}")
                if not raw["research_generation"].eq(EXPECTED_RESEARCH_GENERATION).all():
                    raise CorpusContractError(f"generation drift in {name}: {expected_run}")
                if not raw["dataset_schema"].eq(EXPECTED_DATASET_SCHEMA).all():
                    raise CorpusContractError(f"dataset schema drift in {name}: {expected_run}")
                expected_rows = row["admission"].get("row_counts", {}).get(name)
                if expected_rows is not None and len(raw) != int(expected_rows):
                    raise CorpusContractError(f"row count drift in {name}: {expected_run}")
                raw["canonical_instrument"] = row["terminal"]["canonical_instrument"]
                raw["window_id"] = row["admission"]["window_id"]
                raw["data_source"] = row["terminal"]["data_source_id"]
                pieces[name].append(_typed(raw))
        return {name: pd.concat(values, ignore_index=True) for name, values in pieces.items()}

    def _validate_relations(self) -> None:
        for name, key in PRIMARY_KEYS.items():
            if self._tables[name].duplicated(list(key)).any():
                raise CorpusContractError(f"duplicate primary key in {name}")
        attempts = self._tables["attempts"]
        episodes = self._tables["episodes"]
        features = self._tables["features"]
        context = self._tables["context"]
        events = self._tables["events"]
        transits = self._tables["transits"]
        attempt_keys = set(zip(attempts["run_key"], attempts["attempt_id"]))
        episode_keys = set(zip(episodes["run_key"], episodes["episode_id"]))
        feature_keys = set(zip(features["run_key"], features["attempt_id"]))
        context_keys = set(zip(context["run_key"], context["attempt_id"]))
        if feature_keys != attempt_keys:
            raise CorpusContractError("attempt to frozen-feature cardinality is not exactly one")
        if context_keys != attempt_keys:
            raise CorpusContractError("one or more attempts lack contributor context")
        if not set(zip(attempts["run_key"], attempts["episode_id"])).issubset(episode_keys):
            raise CorpusContractError("attempt references missing episode")
        event_attempts = events[events["attempt_id"].notna()]
        if not set(zip(event_attempts["run_key"], event_attempts["attempt_id"])).issubset(attempt_keys):
            raise CorpusContractError("event references missing attempt")
        event_episodes = events[events["episode_id"].notna()]
        if not set(zip(event_episodes["run_key"], event_episodes["episode_id"])).issubset(episode_keys):
            raise CorpusContractError("event references missing episode")
        if not set(zip(transits["run_key"], transits["attempt_id"])).issubset(attempt_keys):
            raise CorpusContractError("transit references missing attempt")
        if not set(zip(transits["run_key"], transits["episode_id"])).issubset(episode_keys):
            raise CorpusContractError("transit references missing episode")
        if transits[["source_node_id", "destination_node_id"]].isna().any(axis=None):
            raise CorpusContractError("transit has null source or destination node")

    def _load_node_births(self) -> pd.DataFrame:
        pieces = []
        expected = {
            "schema", "run_key", "invocation_id", "market_time", "event", "node_id", "revision",
        }
        for row in self._run_receipts:
            path = _one(row["directory"] / "raw" / "structure", "*_events.tsv")
            raw = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, na_values=[NULL_TOKEN])
            if not expected.issubset(raw.columns):
                raise CorpusContractError(f"structure event schema drift: {row['directory'].name}")
            if not raw["run_key"].eq(row["terminal"]["run_key"]).all():
                raise CorpusContractError(f"foreign structure event run key: {row['directory'].name}")
            parsed = pd.to_datetime(raw["market_time"], format="%Y.%m.%d %H:%M:%S", errors="coerce")
            raw["event_epoch"] = parsed.astype("datetime64[s]").astype("int64").where(parsed.notna(), np.nan)
            raw["revision"] = pd.to_numeric(raw["revision"], errors="coerce")
            order = raw.sort_values(["run_key", "node_id", "event_epoch", "revision"])
            created = order[order["event"].eq("CREATED")].drop_duplicates(["run_key", "node_id"])
            fallback = order.drop_duplicates(["run_key", "node_id"])
            births = fallback[["run_key", "node_id", "event_epoch"]].merge(
                created[["run_key", "node_id", "event_epoch"]].rename(columns={"event_epoch": "created_epoch"}),
                on=["run_key", "node_id"], how="left", validate="one_to_one",
            )
            births["created_epoch"] = births["created_epoch"].fillna(births["event_epoch"])
            pieces.append(births[["run_key", "node_id", "created_epoch"]])
        result = pd.concat(pieces, ignore_index=True)
        return result.sort_values("created_epoch").drop_duplicates(["run_key", "node_id"], keep="first")

    def _assert_holdouts_untouched(self) -> None:
        run_rows = pd.DataFrame([{
            "run_key": row["terminal"]["run_key"],
            "instrument": row["terminal"]["canonical_instrument"],
            "start": int(row["terminal"]["window_start"]),
            "end": int(row["terminal"]["window_end"]),
        } for row in self._run_receipts])
        for holdout in self._holdouts.itertuples(index=False):
            overlaps = run_rows[
                run_rows["instrument"].eq(holdout.canonical_instrument)
                & run_rows["start"].lt(int(holdout.window_end_exclusive))
                & run_rows["end"].gt(int(holdout.window_start))
            ]
            if not overlaps.empty:
                raise CorpusContractError(f"admitted corpus overlaps reserved holdout: {holdout.holdout_id}")

    def _build_attempt_view(self) -> pd.DataFrame:
        attempts = self._tables["attempts"].copy()
        features = self._tables["features"].copy()
        context = self._tables["context"]
        identity = {"run_key", "invocation_id", "attempt_id", "canonical_instrument", "window_id", "data_source"}
        features = features.rename(columns={column: f"feature_{column}" for column in features if column not in identity})
        feature_columns = ["run_key", "attempt_id"] + [column for column in features if column.startswith("feature_")]
        aggregate = context.groupby(["run_key", "attempt_id"], dropna=False).agg(
            contributor_count=("source_key", "size"),
            contributor_families=("family", lambda values: "|".join(sorted(set(values.dropna().astype(str))))),
            contributor_producers=("producer", lambda values: "|".join(sorted(set(values.dropna().astype(str))))),
            contributor_source_keys=("source_key", lambda values: "|".join(sorted(set(values.dropna().astype(str))))),
        ).reset_index()
        result = attempts.merge(features[feature_columns], on=["run_key", "attempt_id"], how="left", validate="one_to_one")
        result = result.merge(aggregate, on=["run_key", "attempt_id"], how="left", validate="one_to_one")
        births = getattr(self, "_node_birth", pd.DataFrame(columns=["run_key", "node_id", "created_epoch"]))
        result = result.merge(births, on=["run_key", "node_id"], how="left", validate="many_to_one")
        result["node_age_seconds"] = (
            pd.to_numeric(result["start"], errors="coerce")
            - pd.to_numeric(result["created_epoch"], errors="coerce")
        ).clip(lower=0)
        right_censored = result["completion_status"].ne("RESOLVED")
        resolution = result["resolution"]
        result["termination_class"] = np.select(
            [
                right_censored.fillna(True),
                resolution.eq("NODE_RETIRED").fillna(False),
                resolution.eq("TIMEOUT").fillna(False),
                resolution.isin(BEHAVIORAL_ATTEMPT_OUTCOMES),
            ],
            ["RIGHT_CENSORED", "STRUCTURAL_ADMINISTRATIVE", "ATTEMPT_TIMEOUT_BOUNDARY", "BEHAVIORAL"],
            default="UNRESOLVED_NONE",
        )
        result["is_behavior_censored"] = result["termination_class"].ne("BEHAVIORAL")
        result["behavioral_attempt_outcome"] = resolution.where(result["termination_class"].eq("BEHAVIORAL"), pd.NA)
        result["administrative_attempt_end"] = result["termination_class"].isin({"RIGHT_CENSORED", "STRUCTURAL_ADMINISTRATIVE"})
        result["attempt_timeout_boundary"] = result["termination_class"].eq("ATTEMPT_TIMEOUT_BOUNDARY")
        return result

    def _build_attempt_chain_view(self) -> pd.DataFrame:
        result = self._attempt_view.sort_values(["run_key", "episode_id", "ordinal", "start"]).copy()
        groups = result.groupby(["run_key", "episode_id"], sort=False, dropna=False)
        result["prior_attempt_resolution"] = groups["resolution"].shift(1)
        result["next_attempt_resolution"] = groups["resolution"].shift(-1)
        result["attempt_position"] = groups.cumcount() + 1
        result["is_terminal_attempt"] = result["attempt_position"].eq(groups["attempt_id"].transform("size"))
        flags = {
            "episode_contains_rejection": {"REJECT_TO_ORIGIN"},
            "episode_contains_acceptance": set(ACCEPTANCE_OUTCOMES),
            "episode_contains_initial_acceptance": {"ACCEPT_THROUGH_NODE"},
            "episode_contains_reclaim": {"RECLAIM_AFTER_BREAK"},
            "episode_contains_retest_hold": {"ACCEPT_AND_HOLD_RETEST"},
            "episode_contains_retest_failure": {"ACCEPT_AND_FAIL_RETEST"},
        }
        keys = ["run_key", "episode_id"]
        for column, outcomes in flags.items():
            observed = result["behavioral_attempt_outcome"].isin(outcomes)
            result[column] = observed.groupby([result[key] for key in keys]).transform("any")
        transit = self._tables["transits"]
        transit_flags = transit.assign(
            _transit=transit["resolution"].eq("TRANSIT_TO_NEXT_NODE"),
            _return=transit["resolution"].eq("RETURN_TO_SOURCE_NODE"),
        ).groupby(keys, as_index=False).agg(
            episode_contains_transit=("_transit", "any"),
            episode_contains_return_to_source=("_return", "any"),
        )
        result = result.merge(transit_flags, on=keys, how="left", validate="many_to_one")
        result[["episode_contains_transit", "episode_contains_return_to_source"]] = result[
            ["episode_contains_transit", "episode_contains_return_to_source"]
        ].fillna(False)
        episodes = self._tables["episodes"][[
            "run_key", "episode_id", "resolution", "completion_status", "censor_reason", "end",
        ]].rename(columns={
            "resolution": "episode_terminal_receipt",
            "completion_status": "episode_completion_status",
            "censor_reason": "episode_censor_reason",
            "end": "episode_end",
        })
        result = result.merge(episodes, on=keys, how="left", validate="many_to_one")
        result["episode_is_right_censored"] = result["episode_completion_status"].ne("RESOLVED")
        result["episode_terminal_is_behavioral"] = result["episode_terminal_receipt"].isin(
            BEHAVIORAL_ATTEMPT_OUTCOMES | BEHAVIORAL_TRANSIT_OUTCOMES
        )
        return result

    def _build_transit_view(self) -> pd.DataFrame:
        transit = self._tables["transits"].copy()
        snapshot = self._attempt_view[[
            "run_key", "attempt_id", "behavioral_attempt_outcome", "termination_class",
            "start_region", "node_region", "contributor_families", "contributor_producers",
        ]]
        result = transit.merge(snapshot, on=["run_key", "attempt_id"], how="left", validate="many_to_one")
        result["transit_timeout_boundary"] = result["resolution"].eq("TIMEOUT")
        result["is_transit_censored"] = (
            result["completion_status"].ne("RESOLVED") | result["transit_timeout_boundary"]
        )
        result["behavioral_transit_outcome"] = result["resolution"].where(
            result["resolution"].isin(BEHAVIORAL_TRANSIT_OUTCOMES), pd.NA
        )
        return result

    def _partition_keys(self, partition: str) -> set[str]:
        all_keys = {str(row["terminal"]["run_key"]) for row in self._run_receipts}
        if partition == "RG2_EXPLORATORY":
            return all_keys
        if partition == "RG2_REPLAY_QC":
            return set(self._replay_keys)
        if partition == "FUTURE_HOLDOUT":
            raise HoldoutAccessError("FUTURE_HOLDOUT is reserved and intentionally absent from RG2")
        raise CorpusContractError(f"unknown partition: {partition}")

    def _copy_partition(self, frame: pd.DataFrame, partition: str) -> pd.DataFrame:
        keys = self._partition_keys(partition)
        return frame[frame["run_key"].astype(str).isin(keys)].copy(deep=True).reset_index(drop=True)

    def attempt_view(self, partition: str = "RG2_EXPLORATORY") -> pd.DataFrame:
        return self._copy_partition(self._attempt_view, partition)

    def attempt_chain_view(self, partition: str = "RG2_EXPLORATORY") -> pd.DataFrame:
        return self._copy_partition(self._chain_view, partition)

    def episode_timeline_view(self, partition: str = "RG2_EXPLORATORY") -> pd.DataFrame:
        events = self._copy_partition(self._tables["events"], partition)
        semantics = self._attempt_view[[
            "run_key", "attempt_id", "termination_class", "behavioral_attempt_outcome",
            "administrative_attempt_end", "attempt_timeout_boundary",
        ]]
        return events.merge(semantics, on=["run_key", "attempt_id"], how="left", validate="many_to_one")

    def transit_view(self, partition: str = "RG2_EXPLORATORY") -> pd.DataFrame:
        return self._copy_partition(self._transit_view, partition)

    def node_context_view(self, partition: str = "RG2_EXPLORATORY") -> pd.DataFrame:
        context = self._copy_partition(self._tables["context"], partition)
        snapshot = self._attempt_view[[
            "run_key", "attempt_id", "termination_class", "behavioral_attempt_outcome",
            "start_region", "node_region", "start_median_sigma", "node_from_median_sigma",
        ]]
        return context.merge(snapshot, on=["run_key", "attempt_id"], how="left", validate="many_to_one")

    def partition_manifest(self) -> pd.DataFrame:
        corpus_rows = []
        for row in self._run_receipts:
            key = str(row["terminal"]["run_key"])
            corpus_rows.append({
                "partition": "RG2_EXPLORATORY", "run_key": key,
                "instrument": row["terminal"]["canonical_instrument"],
                "window_start": int(row["terminal"]["window_start"]),
                "window_end": int(row["terminal"]["window_end"]),
                "replay_qc": key in self._replay_keys, "status": "SEALED_AVAILABLE",
            })
        holdouts = self._holdouts.rename(columns={
            "canonical_instrument": "instrument", "window_end_exclusive": "window_end",
        }).assign(partition="FUTURE_HOLDOUT", run_key=pd.NA, replay_qc=False)[[
            "partition", "run_key", "instrument", "window_start", "window_end", "replay_qc", "status",
        ]]
        return pd.concat([pd.DataFrame(corpus_rows), holdouts], ignore_index=True)

    def type_contract(self) -> dict[str, Any]:
        return {
            "contract": INTERFACE_VERSION,
            "null_representation_in_memory": "pandas.NA_or_NaN",
            "null_representation_on_disk": NULL_TOKEN,
            "timestamp_storage": "Int64_unix_seconds",
            "timestamp_timezone": "MT5_SERVER_not_coerced_to_UTC",
            "identifier_storage": "pandas.StringDtype",
            "integer_storage": "pandas.Int64_nullable",
            "continuous_storage": "float64",
            "price_precision": "symbol_digits_from_runs",
        }

    def estimate(self, spec: QuerySpec) -> ResearchResult:
        cohort = self.target_frame(spec)
        frame = cohort.frame
        observed = frame["target_observed"]
        censored = frame["target_censored"]
        eligible = pd.Series(True, index=frame.index)
        missing_groups = [column for column in spec.group_by if column not in frame]
        if missing_groups:
            raise CorpusContractError(f"group columns absent: {missing_groups}")
        work = frame.loc[:, list(spec.group_by)].copy() if spec.group_by else pd.DataFrame(index=frame.index)
        work["eligible"] = eligible.astype(bool)
        work["observed"] = observed.astype(bool)
        work["censored"] = censored.astype(bool)
        if spec.group_by:
            grouped = work.groupby(list(spec.group_by), dropna=False, as_index=False).agg(
                eligible_count=("eligible", "size"),
                observed_count=("observed", "sum"),
                censored_count=("censored", "sum"),
            )
        else:
            grouped = pd.DataFrame([{
                "eligible_count": len(work), "observed_count": int(work["observed"].sum()),
                "censored_count": int(work["censored"].sum()),
            }])
        grouped["analyzable_count"] = grouped["eligible_count"] - grouped["censored_count"]
        grouped["estimate"] = grouped["observed_count"] / grouped["analyzable_count"].replace(0, np.nan)
        grouped["censoring_rate"] = grouped["censored_count"] / grouped["eligible_count"].replace(0, np.nan)
        receipt = dict(cohort.receipt)
        receipt["contract"] = "MST_RG2_RESEARCH_RESULT_RECEIPT_V1"
        receipt["result_rows"] = len(grouped)
        return ResearchResult(grouped, receipt)

    def target_frame(self, spec: QuerySpec) -> TargetCohort:
        frame, eligible, observed, censored = self._target_masks(spec)
        for column, values in spec.filters:
            if column not in frame:
                raise CorpusContractError(f"filter column absent: {column}")
            keep = frame[column].astype(str).isin(values)
            frame, eligible, observed, censored = (
                frame.loc[keep], eligible.loc[keep], observed.loc[keep], censored.loc[keep]
            )
        frame = frame.loc[eligible.astype(bool)].copy().reset_index(drop=True)
        observed = observed.loc[eligible.astype(bool)].reset_index(drop=True).astype(bool)
        censored = censored.loc[eligible.astype(bool)].reset_index(drop=True).astype(bool)
        frame["target_observed"] = observed
        frame["target_censored"] = censored
        frame["target_analyzable"] = ~censored
        if "target_time_seconds" not in frame:
            frame["target_time_seconds"] = (
                pd.to_numeric(frame["end"], errors="coerce")
                - pd.to_numeric(frame["start"], errors="coerce")
            ).clip(lower=0)
        frame["target_label"] = pd.Series(pd.NA, index=frame.index, dtype="Int8")
        frame.loc[~censored, "target_label"] = observed.loc[~censored].astype("int8")
        query = asdict(spec)
        receipt = {
            "contract": "MST_RG2_TARGET_COHORT_RECEIPT_V1",
            "interface_version": INTERFACE_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "corpus_sha256": self.corpus_hash,
            "analysis_code_sha256": self.interface_code_hash,
            "query_spec": query,
            "query_spec_sha256": _stable_hash(query),
            "eligibility_rule": self._target_description(spec.target),
            "censoring_treatment": spec.censoring_treatment,
            "eligible_rows": len(frame),
            "observed_rows": int(observed.sum()),
            "censored_rows": int(censored.sum()),
            "analyzable_rows": int((~censored).sum()),
        }
        return TargetCohort(frame, receipt)

    def _target_masks(self, spec: QuerySpec) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
        if spec.target in {"reclaim_given_break", "initial_acceptance_given_initial_contact",
                           "rejection_given_initial_contact", "retest_hold_given_retest_contact"}:
            frame = self.attempt_view(spec.partition)
            if spec.target == "reclaim_given_break":
                eligible = frame["break"].notna()
                observed = frame["behavioral_attempt_outcome"].eq("RECLAIM_AFTER_BREAK").fillna(False)
            elif spec.target == "initial_acceptance_given_initial_contact":
                eligible = frame["contact"].notna() & frame["is_retest"].eq(0)
                observed = frame["behavioral_attempt_outcome"].eq("ACCEPT_THROUGH_NODE").fillna(False)
            elif spec.target == "rejection_given_initial_contact":
                eligible = frame["contact"].notna() & frame["is_retest"].eq(0)
                observed = frame["behavioral_attempt_outcome"].eq("REJECT_TO_ORIGIN").fillna(False)
            else:
                eligible = frame["contact"].notna() & frame["is_retest"].eq(1)
                observed = frame["behavioral_attempt_outcome"].eq("ACCEPT_AND_HOLD_RETEST").fillna(False)
            return frame, eligible, observed, frame["is_behavior_censored"]
        if spec.target == "transit_given_episode_acceptance":
            chain = self.attempt_chain_view(spec.partition)
            frame = chain[chain["behavioral_attempt_outcome"].eq("ACCEPT_THROUGH_NODE")].copy()
            frame = frame.sort_values(["run_key", "episode_id", "end"]).drop_duplicates(
                ["run_key", "episode_id"], keep="first"
            )
            frame["first_acceptance_end"] = frame["end"]
            transit = self.transit_view(spec.partition)
            transit = transit[transit["behavioral_transit_outcome"].eq("TRANSIT_TO_NEXT_NODE")]
            transit = transit.groupby(["run_key", "episode_id"], as_index=False).agg(
                first_transit_start=("start", "min")
            )
            frame = frame.merge(transit, on=["run_key", "episode_id"], how="left", validate="one_to_one")
            eligible = frame["first_acceptance_end"].notna()
            observed = frame["first_transit_start"].ge(frame["first_acceptance_end"]).fillna(False)
            censored = (
                frame["episode_is_right_censored"]
                | frame["episode_terminal_receipt"].isin({"NODE_RETIRED", "TIMEOUT", "NONE"})
            ) & ~observed
            terminal_time = pd.to_numeric(frame["episode_end"], errors="coerce")
            observed_time = pd.to_numeric(frame["first_transit_start"], errors="coerce")
            frame["target_time_seconds"] = (
                observed_time.where(observed, terminal_time)
                - pd.to_numeric(frame["first_acceptance_end"], errors="coerce")
            ).clip(lower=0)
            return frame, eligible, observed, censored
        raise CorpusContractError(f"unknown target: {spec.target}")

    @staticmethod
    def _target_description(target: str) -> str:
        return {
            "reclaim_given_break": "attempt has a recorded break; reclaim is observed behavioral outcome",
            "initial_acceptance_given_initial_contact": "non-retest attempt has contact; ACCEPT_THROUGH_NODE is observed",
            "rejection_given_initial_contact": "non-retest attempt has contact; REJECT_TO_ORIGIN is observed",
            "retest_hold_given_retest_contact": "retest attempt has contact; ACCEPT_AND_HOLD_RETEST is observed",
            "transit_given_episode_acceptance": "episode has ACCEPT_THROUGH_NODE; later TRANSIT_TO_NEXT_NODE receipt observed",
        }.get(target, "unknown")
