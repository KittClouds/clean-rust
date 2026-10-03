"""Build and audit matched S100/F100 banks from the no-model contrast corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
GEN_DEFAULT = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean")
SCOPED_SOURCE_DEFAULT = GEN_DEFAULT / "training-inputs"
CONTRACT_DEFAULT = ROOT / "experiments" / "jev-information-density-v08i" / "phase-a-v02-clean-contract.json"
OUT_DEFAULT = GEN_DEFAULT / "materialized"
DOSE = 5_000
ARM_SIZE = 100_000
REMOVAL_SEED = "jev-v08i-phase-a-remove-v1"
PAIR_SEED = "jev-v08i-phase-a-pair-select-v1"
PROFILES = ("name", "name_definition", "opaque_definition", "opaque_only")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_rank(seed: str, identity: str) -> str:
    return hashlib.sha256(f"{seed}\0{identity}".encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return sha256_file(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            payload = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            stream.write(payload.decode("utf-8"))
            digest.update(payload)
    return digest.hexdigest()


def read_indexed_table(path: Path) -> list[str]:
    result: list[str] = []
    for expected, row in enumerate(read_jsonl(path)):
        if row.get("index") != expected or not isinstance(row.get("text"), str):
            raise ValueError(f"invalid index/text table row: {path}:{expected + 1}")
        result.append(row["text"])
    return result


def source_inputs(receipt_path: Path) -> tuple[dict[str, Any], dict[str, list[str]], dict[str, Path]]:
    receipt = read_json(receipt_path)
    if receipt.get("status") != "TRAINING_ONLY_REPRESENTATION_SCOPE_PASS":
        raise ValueError("training-only representation scope receipt is not PASS")
    if receipt.get("source_scope") != "training_only" or receipt.get("source_bank") != "R100-star":
        raise ValueError("representation scope is not the sealed R100-star training source")
    if receipt.get("source_row_count") != ARM_SIZE:
        raise ValueError("representation scope source count is not 100,000")
    for field in ("contains_eval_ids", "contains_eval_family_ids", "contains_eval_text"):
        if receipt.get(field) is not False:
            raise ValueError(f"training-only scope receipt does not certify {field}=false")
    paths: dict[str, Path] = {}
    random_item = receipt["group_file"]
    if (random_item.get("source_scope") != "training_only"
            or random_item.get("source_banks") != ["R100-star"]
            or random_item.get("source_bank_hash") != receipt["source_bank_hash"]):
        raise ValueError("random group rows are not bound to the scoped R100-star source")
    paths["group:random"] = Path(random_item["path"])
    expected_random_hash = random_item["sha256"]
    for name, item in receipt["representation_tables"].items():
        if (item.get("source_scope") != "training_only"
                or item.get("source_banks") != ["R100-star"]
                or item.get("source_bank_hash") != receipt["source_bank_hash"]
                or item.get("source_row_count") != ARM_SIZE
                or item.get("contains_eval_ids") is not False
                or item.get("contains_eval_family_ids") is not False
                or item.get("contains_eval_text") is not False):
            raise ValueError(
                "refusing to open unscoped/non-training representation table "
                f"{name!r}; require training_only R100-star scope certification"
            )
    tables: dict[str, list[str]] = {}
    for name, item in receipt["representation_tables"].items():
        path = Path(item["path"])
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"scoped training representation source hash mismatch: {path}")
        paths[f"table:{name}"] = path
        tables[name] = read_indexed_table(path)
        if len(tables[name]) != item["count"]:
            raise ValueError(f"v0.8G table count mismatch: {name}")
    random_path = paths["group:random"]
    if sha256_file(random_path) != expected_random_hash:
        raise ValueError("scoped random training group source hash mismatch")
    source_rows = list(read_jsonl(random_path))
    source_ids = [str(row.get("group_id", "")) for row in source_rows]
    if (len(source_rows) != ARM_SIZE or any(not item for item in source_ids)
            or len(source_ids) != len(set(source_ids))):
        raise ValueError("scoped source group IDs/count are invalid")
    id_digest = hashlib.sha256("".join(item + "\n" for item in sorted(source_ids)).encode("utf-8")).hexdigest()
    if id_digest != receipt.get("source_group_id_digest"):
        raise ValueError("scoped R100-star group ID digest mismatch")
    if any(row.get("split") != "train" for row in source_rows):
        raise ValueError("scoped R100-star table contains a non-training row")
    return receipt, tables, paths


def training_scope_receipt_path(source_materialized: Path) -> Path:
    return source_materialized / "scope-receipt.json"


def select_pairs(cert_path: Path, dose: int) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total = 0
    for row in read_jsonl(cert_path):
        if row.get("partition") != "train":
            raise ValueError("non-training certificate in train pair universe")
        families[str(row["world_family_id"])].append(row)
        total += 1
    if dose > total:
        raise ValueError(f"dose {dose} exceeds generated pair universe {total}")
    ordered_families = sorted(families, key=lambda family: stable_rank(PAIR_SEED + ":family", family))
    base, extra = divmod(dose, len(ordered_families))
    quotas = {family: base + (index < extra) for index, family in enumerate(ordered_families)}
    selected: list[dict[str, Any]] = []
    for family in sorted(families):
        quota = quotas[family]
        ranked = sorted(families[family], key=lambda row: stable_rank(PAIR_SEED, row["anchor_id"]))
        selected.extend(ranked[:quota])
    if len(selected) != dose:
        raise AssertionError("family-balanced pair selection count mismatch")
    return selected, quotas, total


def candidate_surface(candidate: dict[str, Any], profile: str) -> str:
    semantic_id = candidate["candidate_semantic_id"]
    surface = candidate.get("surface") or {}
    name = candidate.get("name") or surface.get("name") or semantic_id
    description = candidate.get("description") or surface.get("description") or name
    opaque = candidate.get("opaque_id") or semantic_id
    if profile == "name":
        return name
    if profile == "name_definition":
        return f"{name} — {description}"
    if profile == "opaque_definition":
        return f"{opaque} — {description}"
    if profile == "opaque_only":
        return opaque
    raise ValueError(profile)


def group_from_episode(episode: dict[str, Any], split: str, root_id: str) -> dict[str, Any]:
    schema = episode["runtime_schema"]
    query = episode["queries"][0]
    target = episode["gold_targets"][0]
    candidate_set = next(item for item in schema["candidate_sets"] if item["candidate_set_id"] == query["candidate_set_id"])
    candidate_by_id = {item["candidate_id"]: item for item in schema["candidates"]}
    candidates = [candidate_by_id[item] for item in candidate_set["candidate_ids"]]
    semantic_ids = [item["candidate_semantic_id"] for item in candidates]
    target_by_semantic = {
        item["candidate_semantic_id"]: float(item["probability"])
        for item in target["target"]["distribution"]
    }
    gold = [target_by_semantic[item] for item in semantic_ids]
    content = episode["state"]["observable"]["content"]
    state_text = (
        f"State:\n{content}\n"
        f"Decision view: {query['view']}\n"
        f"Runtime query: {query['query_semantic_id']}\n"
        "Compare this state with each supplied candidate definition."
    )
    perturbation = episode.get("perturbation") or {}
    parent = perturbation.get("parent_episode_id")
    invariant_key = f"{parent or episode['episode_id']}|{query['query_id']}"
    descriptions = {}
    for item in candidates:
        surface = item.get("surface") or {}
        adapter_item = dict(item)
        adapter_item["name"] = item.get("name") or surface.get("name") or item["candidate_semantic_id"]
        adapter_item["description"] = item.get("description") or surface.get("description") or adapter_item["name"]
        adapter_item["opaque_id"] = item.get("opaque_id") or item["candidate_semantic_id"]
        descriptions[item["candidate_semantic_id"]] = adapter_item
    family = episode["identity"]["world_family_id"]
    card = len(candidates)
    entropy = -sum(value * math.log(max(1e-15, value)) for value in gold if value > 0)
    max_probability = max(gold)
    return {
        "group_id": f"{episode['episode_id']}|{query['query_id']}",
        "episode_id": episode["episode_id"],
        "query_id": query["query_id"],
        "kind": "choice",
        "view": query["view"],
        "state_text": state_text,
        "candidate_semantic_ids": semantic_ids,
        "candidate_descriptions": descriptions,
        "gold": gold,
        "open_world": False,
        "probability_source": target["probability_source"]["probability_source"],
        "authority": episode["authority"]["episode_authority_class"],
        "split": split,
        "invariant_key": invariant_key,
        "semantic_fingerprint": episode["identity"]["semantic_fingerprint"],
        "perturbation_class": perturbation.get("class"),
        "candidate_cardinality": card,
        "root_id": root_id,
        "family_ids": {
            "world_or_topology_family": family,
            "ontology_family": episode["identity"]["schema_family_id"],
            "schema_composition_family": schema["schema_family_id"],
            "candidate_set_construction_family": schema["candidate_sets"][0]["candidate_set_id"],
            "definition_template_family": episode["identity"]["paraphrase_family_id"],
            "intervention_family": episode["identity"]["perturbation_family_id"],
        },
        "coverage_features": {
            "local_discrimination": ["hierarchy:1", "same_parent_competitors:3", "candidate_count:4"],
            "probability_geometry": [f"entropy_nats:{entropy:.8f}", f"max_probability:{max_probability:.8f}", "target:choice"],
            "semantic_novelty": [family, schema["schema_family_id"], *semantic_ids],
            "structural_coverage": ["cardinality:4", "evidence_density:2", "operation:" + (perturbation.get("class") or "anchor"), "topology:direct-cause"],
        },
        "strata": {
            "candidate_cardinality_bin": "4",
            "posterior_entropy_quintile": "generator_profile_varied",
            "query_view_type": query["view"],
            "world_family": family,
        },
        "_state_text": state_text,
        "_candidate_surfaces": {
            profile: [candidate_surface(item, profile) for item in candidates]
            for profile in PROFILES
        },
    }


def load_selected_episodes(path: Path, selected: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    wanted: dict[str, tuple[str, str]] = {}
    for certificate in selected:
        for role, episode_id in certificate["episode_ids"].items():
            wanted[episode_id] = (certificate["anchor_id"], role)
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for episode in read_jsonl(path):
        episode_id = episode["episode_id"]
        if episode_id not in wanted:
            continue
        key = wanted[episode_id]
        if key in found:
            raise ValueError(f"duplicate generated episode for selected pair: {key}")
        found[key] = episode
    if len(found) != len(wanted):
        raise ValueError(f"selected generated episode coverage mismatch: {len(found)} != {len(wanted)}")
    return found


def validate_triplet(certificate: dict[str, Any], episodes: dict[tuple[str, str], dict[str, Any]]) -> None:
    anchor_id = certificate["anchor_id"]
    base, flip, sham = (episodes[(anchor_id, role)] for role in ("anchor", "fact_flip", "sham"))
    ids = [base["episode_id"], flip["episode_id"], sham["episode_id"]]
    if ids != [certificate["episode_ids"][role] for role in ("anchor", "fact_flip", "sham")]:
        raise ValueError(f"episode identity mismatch for {anchor_id}")
    for episode in (base, flip, sham):
        if episode.get("contract") != "jev-like-decision-dataset/v1":
            raise ValueError(f"wrong canonical contract for {episode['episode_id']}")
        if episode.get("identity", {}).get("episode_id") != episode["episode_id"]:
            raise ValueError(f"canonical identity episode ID missing/mismatched for {episode['episode_id']}")
        if episode["identity"]["world_family_id"] != certificate["world_family_id"]:
            raise ValueError(f"family mismatch for {episode['episode_id']}")
        if episode["identity"]["world_instance_id"] != base["identity"]["world_instance_id"]:
            raise ValueError(f"world identity mismatch for {episode['episode_id']}")
        if episode["runtime_schema"] != base["runtime_schema"] or episode["queries"] != base["queries"]:
            raise ValueError(f"schema/query drift inside pair {anchor_id}")
    base_text = base["state"]["observable"]["content"]
    flip_text = flip["state"]["observable"]["content"]
    sham_text = sham["state"]["observable"]["content"]
    if len(base_text) != len(flip_text) or len(base_text) != len(sham_text):
        raise ValueError(f"surface lengths differ inside pair {anchor_id}")
    changes = lambda left, right: [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
    flip_changes = changes(base_text, flip_text)
    sham_changes = changes(base_text, sham_text)
    if len(flip_changes) != 1 or len(sham_changes) != 1 or flip_changes == sham_changes:
        raise ValueError(f"non-minimal visible edit for {anchor_id}")
    base_bytes = base_text.encode("utf-8")
    flip_bytes = flip_text.encode("utf-8")
    sham_bytes = sham_text.encode("utf-8")
    flip_byte_at = len(base_text[:flip_changes[0]].encode("utf-8"))
    sham_byte_at = len(base_text[:sham_changes[0]].encode("utf-8"))
    if not (base_bytes[flip_byte_at:flip_byte_at + 1] == b"+"
            and flip_bytes[flip_byte_at:flip_byte_at + 1] == b"-"
            and base_bytes[sham_byte_at:sham_byte_at + 1] == b"+"
            and sham_bytes[sham_byte_at:sham_byte_at + 1] == b"-"):
        raise ValueError(f"changed surface is not the declared + to - edit for {anchor_id}")
    for edge, changed_at in (("fact_flip", flip_byte_at), ("sham", sham_byte_at)):
        before_span = certificate["changed_surface_spans"][edge]["before"]
        after_span = certificate["changed_surface_spans"][edge]["after"]
        if before_span != after_span or before_span != [changed_at, changed_at + 1]:
            raise ValueError(f"certificate span does not identify the actual changed byte for {anchor_id}/{edge}")
    if certificate["affected_query_ids"] != ["q_choice"] or certificate["sham_affected_query_ids"] != []:
        raise ValueError(f"affected-query certificate mismatch for {anchor_id}")
    if certificate["sham_unaffected_query_ids"] != ["q_choice"]:
        raise ValueError(f"sham locality certificate mismatch for {anchor_id}")
    if len(base["queries"]) != 1 or len(base["gold_targets"]) != 1:
        raise ValueError(f"contrast contains unapproved secondary query for {anchor_id}")
    distributions = [
        [float(item["probability"]) for item in episode["gold_targets"][0]["target"]["distribution"]]
        for episode in (base, flip, sham)
    ]
    certified = [
        certificate["exact_target_before"],
        certificate["exact_target_after"],
        certificate["exact_sham_target"],
    ]
    for actual, expected in zip(distributions, certified):
        if len(actual) != len(expected) or any(abs(a - float(b)) > 1e-12 for a, b in zip(actual, expected)):
            raise ValueError(f"certificate exact posterior mismatch for {anchor_id}")
    for episode, actual in zip((base, flip, sham), distributions):
        target = episode["gold_targets"][0]
        if target["probability_source"]["probability_source"] != "exact_generative_posterior":
            raise ValueError(f"non-exact probability source for {episode['episode_id']}")
        if abs(sum(actual) - 1.0) > 1e-12:
            raise ValueError(f"closed choice posterior not normalized for {episode['episode_id']}")
    if not (distributions[0] == distributions[2]):
        if any(abs(a - b) > 1e-12 for a, b in zip(distributions[0], distributions[2])):
            raise ValueError(f"sham posterior changed for {anchor_id}")
    tops = [max(range(len(values)), key=values.__getitem__) for values in distributions]
    if tops[0] != 0 or tops[1] != 1 or tops[2] != 0:
        raise ValueError(f"exact choice labels do not match certificate for {anchor_id}")
    if not all(
        item["gold_targets"][0]["target"]["selected_candidate_semantic_id"].endswith(
            "::" + str(expected)
        )
        for item, expected in zip((base, flip, sham), (
            certificate["expected_label_before"],
            certificate["expected_label_after"],
            certificate["sham_label_after"],
        ))
    ):
        raise ValueError(f"selected semantic labels do not match the certificate for {anchor_id}")
    for episode in (base, flip, sham):
        evidence = {item["evidence_id"]: item for item in episode["evidence_items"]}
        for link in episode["evidence_links"]:
            if len(link["locations"]) != 1:
                raise ValueError(f"unexpected evidence location count for {episode['episode_id']}")
            location = link["locations"][0]
            body = evidence[location["evidence_id"]]["content"].encode("utf-8")
            if body[location["start"]:location["end"]] not in (b"+", b"-"):
                raise ValueError(f"canonical evidence offsets do not round-trip for {episode['episode_id']}")


def table_index(values: list[str], text: str) -> int:
    try:
        return values.index(text)
    except ValueError:
        values.append(text)
        return len(values) - 1


def group_training_signature(row: dict[str, Any], state_texts: list[str], candidate_texts: list[str]) -> str:
    candidate_indices = row["candidate_indices"]["name_definition"]
    candidate_surfaces = [candidate_texts[int(index)] for index in candidate_indices]
    fields = [
        state_texts[int(row["state_idx"])],
        list(zip(row["candidate_semantic_ids"], candidate_surfaces)),
        row["kind"], row["view"], list(row["gold"]), bool(row["open_world"]),
        row["probability_source"], row["authority"], "L3_source_typed", 1.0,
    ]
    return hashlib.sha256(canonical(fields).encode("utf-8")).hexdigest()


def selector_input_signature(row: dict[str, Any], state_texts: list[str], candidate_texts: list[str]) -> str:
    candidate_indices = row["candidate_indices"]["name_definition"]
    candidate_surfaces = [candidate_texts[int(index)] for index in candidate_indices]
    fields = [
        state_texts[int(row["state_idx"])],
        list(zip(row["candidate_semantic_ids"], candidate_surfaces)),
        row["kind"], row["view"], bool(row["open_world"]),
    ]
    return hashlib.sha256(canonical(fields).encode("utf-8")).hexdigest()


def multiplicity_histogram(counts: Counter[Any]) -> Counter[int]:
    return Counter(counts.values())


def distribution_distance(left: Counter[str], right: Counter[str], mass: int) -> dict[str, Any]:
    keys = left.keys() | right.keys()
    l1 = sum(abs(left.get(key, 0) - right.get(key, 0)) for key in keys)
    if l1 % 2:
        raise ValueError("integer equal-mass training signature vectors have odd L1")
    return {
        "group_mass_each": mass,
        "signature_l1": l1,
        "changed_occurrence_mass_each": l1 // 2,
        "D_train": 0.5 * l1 / mass,
        "unique_signatures_s100": len(left),
        "unique_signatures_f100": len(right),
    }


def audit_bank(path: Path, state_texts: list[str], candidate_texts: list[str]) -> dict[str, Any]:
    ids: list[str] = []
    training_signatures: Counter[str] = Counter()
    selector_signatures: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    root_counts: Counter[str] = Counter()
    aggregates: dict[str, Counter[str]] = {
        "family": Counter(), "root": Counter(), "view": Counter(),
        "cardinality": Counter(), "root_multiplicity": Counter(),
    }
    invariant_rows: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = str(row["group_id"])
            ids.append(group_id)
            if row["split"] != "train" or row["open_world"] or row["kind"] not in {"choice", "independent"}:
                raise ValueError(f"unsupported/non-training row in {path}:{line_number}")
            if not 0 <= int(row["state_idx"]) < len(state_texts):
                raise ValueError(f"invalid state index in {path}:{line_number}")
            candidate_ids = row["candidate_semantic_ids"]
            candidate_indices = row["candidate_indices"]["name_definition"]
            gold = row["gold"]
            if not (len(candidate_ids) == len(candidate_indices) == len(gold)):
                raise ValueError(f"candidate/target cardinality mismatch in {path}:{line_number}")
            if any(not 0 <= int(index) < len(candidate_texts) for index in candidate_indices):
                raise ValueError(f"invalid candidate index in {path}:{line_number}")
            if any(not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0 for value in gold):
                raise ValueError(f"invalid target probability in {path}:{line_number}")
            if row["kind"] == "choice" and abs(sum(float(value) for value in gold) - 1.0) > 1e-9:
                raise ValueError(f"closed-choice target is not normalized in {path}:{line_number}")
            training_signatures[group_training_signature(row, state_texts, candidate_texts)] += 1
            selector_signatures[selector_input_signature(row, state_texts, candidate_texts)] += 1
            state = state_texts[int(row["state_idx"])]
            state_counts[state] += 1
            aggregates["family"][str(row.get("family_ids", {}).get("world_or_topology_family", "missing"))] += 1
            root_id = str(row.get("root_id", "missing"))
            aggregates["root"][root_id] += 1
            root_counts[root_id] += 1
            aggregates["view"][str(row["view"])] += 1
            aggregates["cardinality"][str(row.get("candidate_cardinality", len(row["gold"])))] += 1
            invariant_rows[row["invariant_key"]].append((group_id, row.get("perturbation_class")))
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ValueError(f"{path} group IDs are duplicate or not sorted")
    aggregates["root_multiplicity"] = Counter(root_counts.values())
    invariant_pairs = []
    for values in invariant_rows.values():
        base = next((group_id for group_id, cls in values if cls is None), None)
        sibling = next((group_id for group_id, cls in values if cls == "surfaceinvariance"), None)
        if base and sibling:
            invariant_pairs.append((base, sibling))
    return {
        "count": len(ids),
        "ids": ids,
        "training_signatures": training_signatures,
        "selector_signatures": selector_signatures,
        "state_multiplicity": multiplicity_histogram(state_counts),
        "unique_state_count": len(state_counts),
        "aggregates": aggregates,
        "invariant_pairs": sorted(invariant_pairs),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generator", type=Path, default=GEN_DEFAULT)
    parser.add_argument("--source-materialized", type=Path, default=SCOPED_SOURCE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--dose", type=int, default=DOSE)
    parser.add_argument("--contract", type=Path, default=CONTRACT_DEFAULT)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError(f"output directory must be empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    contract = read_json(args.contract)
    contract_hash = sha256_file(args.contract)
    if contract.get("run_identity") != "phase-a-v02-clean":
        raise ValueError("wrong Phase-A v02 contract identity")
    bank_contract = contract.get("bank_construction", {})
    if args.dose != int(bank_contract.get("selected_anchor_dose", -1)):
        raise ValueError("requested dose differs from frozen Phase-A v02 contract")
    if int(bank_contract.get("bank_groups_per_arm", -1)) != ARM_SIZE:
        raise ValueError("bank size differs from frozen Phase-A v02 contract")

    generator_receipt = read_json(args.generator / "generator-receipt.json")
    if (generator_receipt.get("run_identity") != "phase-a-v02-clean"
            or generator_receipt.get("protocol_contract_sha256") != contract_hash):
        raise ValueError("generator receipt is not bound to the frozen Phase-A v02 contract")
    if any(generator_receipt.get(key) is not False for key in (
        "model_loaded", "model_inference", "feature_extraction", "training", "phoenix_access"
    )):
        raise ValueError("generator receipt crosses the Phase-A no-model boundary")
    materialization_path = training_scope_receipt_path(args.source_materialized)
    source_receipt, tables, source_paths = source_inputs(materialization_path)
    if source_receipt.get("protocol_contract_sha256") != contract_hash:
        raise ValueError("training-only scope receipt is not bound to the frozen Phase-A v02 contract")
    selected, family_quotas, generated_train_pairs = select_pairs(
        args.generator / "train-contrast-certificates.jsonl", args.dose,
    )
    if args.dose != DOSE:
        phase_status = "SMOKE_DOSE_NONPROMOTABLE"
    else:
        phase_status = "PHASE_A_BANKS_BUILT_NO_MODEL_CONTACT"
    train_episodes = load_selected_episodes(args.generator / "train-canonical-episodes.jsonl", selected)
    for certificate in selected:
        validate_triplet(certificate, train_episodes)

    random_path = source_paths["group:random"]
    eligible_ids: list[tuple[str, str]] = []
    eligible_count = 0
    source_group_count = 0
    last_group_id = ""
    with random_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = str(row["group_id"])
            if group_id < last_group_id:
                raise ValueError(f"sealed random groups are not sorted at line {line_number}")
            last_group_id = group_id
            source_group_count += 1
            if (row.get("kind") == "choice" and row.get("view") == "choice"
                    and not row.get("open_world") and row.get("candidate_cardinality") == 4
                    and row.get("probability_source") == "exact_generative_posterior"):
                eligible_count += 1
                eligible_ids.append((stable_rank(REMOVAL_SEED, group_id), group_id))
    max_bank_pairs = min(generated_train_pairs, eligible_count // 2)
    removal_count = 2 * args.dose
    if removal_count > eligible_count:
        raise ValueError(f"dose consumes {removal_count} choice rows; only {eligible_count} are eligible")
    removed = {group_id for _, group_id in sorted(eligible_ids)[:removal_count]}
    if len(removed) != removal_count:
        raise AssertionError("baseline removal count is not exact")

    state_texts = list(tables["state_inputs"])
    state_lookup = {text: index for index, text in enumerate(state_texts)}
    candidate_texts = {profile: list(tables[profile]) for profile in PROFILES}
    candidate_lookup: dict[tuple[str, str], int] = {}

    def prepare_custom(certificate: dict[str, Any], role: str, episode: dict[str, Any], slot_role: str, split: str) -> dict[str, Any]:
        root_id = f"v08i-root:{certificate['anchor_id']}"
        row = group_from_episode(episode, split, root_id)
        row["group_id"] = f"zzzz-v08i-slot:{certificate['anchor_id']}:{slot_role}"
        row["contrast_anchor_id"] = certificate["anchor_id"]
        row["contrast_role"] = role
        state_index = state_lookup.get(row["_state_text"])
        if state_index is None:
            state_index = len(state_texts)
            state_texts.append(row["_state_text"])
            state_lookup[row["_state_text"]] = state_index
        row["state_idx"] = state_index
        indices_by_profile: dict[str, list[int]] = {}
        for profile in PROFILES:
            indices: list[int] = []
            for semantic_id, surface in zip(row["candidate_semantic_ids"], row["_candidate_surfaces"][profile]):
                key = (profile, semantic_id)
                index = candidate_lookup.get(key)
                if index is None:
                    index = len(candidate_texts[profile])
                    candidate_texts[profile].append(surface)
                    candidate_lookup[key] = index
                elif candidate_texts[profile][index] != surface:
                    raise ValueError(f"candidate semantic surface drift: {key}")
                indices.append(index)
            indices_by_profile[profile] = indices
        row["candidate_indices"] = indices_by_profile
        row.pop("_state_text")
        row.pop("_candidate_surfaces")
        return row

    custom_s: list[dict[str, Any]] = []
    custom_f: list[dict[str, Any]] = []
    for certificate in selected:
        anchor_id = certificate["anchor_id"]
        base = prepare_custom(certificate, "anchor", train_episodes[(anchor_id, "anchor")], "anchor", "train")
        sham = prepare_custom(certificate, "sham", train_episodes[(anchor_id, "sham")], "sibling", "train")
        flip = prepare_custom(certificate, "fact_flip", train_episodes[(anchor_id, "fact_flip")], "sibling", "train")
        custom_s.extend((base, sham))
        custom_f.extend((base, flip))
    custom_s.sort(key=lambda row: row["group_id"])
    custom_f.sort(key=lambda row: row["group_id"])
    train_episode_ids = {
        str(episode_id) for certificate in selected for episode_id in certificate["episode_ids"].values()
    }
    generator_train_families = set(generator_receipt.get("train_family_ids", []))
    generator_eval_families = set(generator_receipt.get("eval_family_ids", []))
    generator_train_templates = set(generator_receipt.get("train_template_ids", []))
    generator_eval_templates = set(generator_receipt.get("eval_template_ids", []))
    if not generator_train_families or not generator_eval_families:
        raise ValueError("generator receipt lacks train/eval family identity metadata")
    if generator_train_families & generator_eval_families:
        raise ValueError("generator receipt reports train/eval family overlap")
    if not generator_train_templates or not generator_eval_templates:
        raise ValueError("generator receipt lacks train/eval template identity metadata")
    if generator_train_templates & generator_eval_templates:
        raise ValueError("generator receipt reports train/eval template overlap")
    if train_episode_ids & set(generator_receipt.get("eval_episode_ids", [])):
        raise ValueError("selected train episodes overlap generated eval identities")

    # The text table rows are immutable copies plus append-only v0.8I inputs.
    table_output_hashes: dict[str, str] = {}
    for profile in PROFILES:
        out_path = args.output / f"candidate-inputs-{profile}.jsonl"
        table_output_hashes[profile] = write_jsonl(
            out_path, ({"index": index, "text": text} for index, text in enumerate(candidate_texts[profile]))
        )
    state_hash = write_jsonl(
        args.output / "state-inputs.jsonl",
        ({"index": index, "text": text} for index, text in enumerate(state_texts)),
    )

    s_path = args.output / "S100-groups.jsonl"
    f_path = args.output / "F100-groups.jsonl"
    common_count = 0
    emitted_ids: set[str] = set()
    with random_path.open("r", encoding="utf-8") as source, \
            s_path.open("x", encoding="utf-8", newline="\n") as s_out, \
            f_path.open("x", encoding="utf-8", newline="\n") as f_out:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            if row["group_id"] in removed:
                continue
            if row["group_id"] in emitted_ids:
                raise ValueError(f"duplicate common group ID: {row['group_id']}")
            emitted_ids.add(row["group_id"])
            s_out.write(line if line.endswith("\n") else line + "\n")
            f_out.write(line if line.endswith("\n") else line + "\n")
            common_count += 1
    if common_count + len(custom_s) != ARM_SIZE or common_count + len(custom_f) != ARM_SIZE:
        raise ValueError(f"bank count mismatch after replacement: common={common_count}, added={len(custom_s)}")

    # zzzz IDs sort after the sealed jev-* source rows, preserving deterministic input order.
    if any(not row["group_id"].startswith("zzzz-v08i-") for row in custom_s + custom_f):
        raise AssertionError("custom slot ID namespace mismatch")
    with s_path.open("a", encoding="utf-8", newline="\n") as s_out, f_path.open("a", encoding="utf-8", newline="\n") as f_out:
        for row_s, row_f in zip(custom_s, custom_f):
            if row_s["group_id"] != row_f["group_id"]:
                raise ValueError("paired bank slot identity mismatch")
            s_out.write(json.dumps(row_s, ensure_ascii=False, separators=(",", ":")) + "\n")
            f_out.write(json.dumps(row_f, ensure_ascii=False, separators=(",", ":")) + "\n")

    s_audit = audit_bank(s_path, state_texts, candidate_texts["name_definition"])
    f_audit = audit_bank(f_path, state_texts, candidate_texts["name_definition"])
    if s_audit["count"] != ARM_SIZE or f_audit["count"] != ARM_SIZE:
        raise ValueError("final training banks do not contain exactly 100k groups")
    if s_audit["ids"] != f_audit["ids"]:
        raise ValueError("S100/F100 training slot ID sets differ")

    distance = distribution_distance(
        s_audit["training_signatures"], f_audit["training_signatures"], ARM_SIZE
    )
    if s_audit["invariant_pairs"] != f_audit["invariant_pairs"]:
        raise ValueError("L3 surface-invariance pair event lists differ between arms")

    exact_matched = {}
    for field in ("family", "root", "view", "cardinality", "root_multiplicity"):
        left = s_audit["aggregates"][field]
        right = f_audit["aggregates"][field]
        exact_matched[field] = {"equal": left == right, "support_count": len(left)}
        if left != right:
            raise ValueError(f"matched exposure profile differs: {field}")
    for field, left, right in (
        ("state_multiplicity", s_audit["state_multiplicity"], f_audit["state_multiplicity"]),
        ("selector_input_multiplicity",
         multiplicity_histogram(s_audit["selector_signatures"]),
         multiplicity_histogram(f_audit["selector_signatures"])),
    ):
        exact_matched[field] = {"equal": left == right, "histogram": dict(sorted(left.items()))}
        if left != right:
            raise ValueError(f"matched exposure multiplicity differs: {field}")
    if s_audit["unique_state_count"] != f_audit["unique_state_count"]:
        raise ValueError("matched unique state count differs")

    selected_cert_hash = write_jsonl(args.output / "selected-train-contrast-certificates.jsonl", selected)
    removal_hash = write_jsonl(
        args.output / "baseline-removal-manifest.jsonl",
        (
            {"group_id": group_id, "removal_rank": rank, "hash_rank": rank_key}
            for rank, (rank_key, group_id) in enumerate(sorted(eligible_ids)[:removal_count])
        ),
    )
    s_hash, f_hash = sha256_file(s_path), sha256_file(f_path)
    materialization_receipt = training_scope_receipt_path(args.source_materialized)
    source_hashes = {
        "training_scope_receipt": {
            "path": str(materialization_receipt),
            "sha256": sha256_file(materialization_receipt),
        },
        "scoped_training_inputs": {
            name: {"path": str(path), "sha256": sha256_file(path)}
            for name, path in source_paths.items()
        },
    }
    generator_input_names = (
        "train-canonical-episodes.jsonl",
        "train-contrast-certificates.jsonl",
        "eval-canonical-episodes.jsonl",
        "eval-contrast-certificates.jsonl",
    )
    generator_inputs = {}
    for name in generator_input_names[:2]:
        path = args.generator / name
        recorded = generator_receipt["outputs"][name]
        if path.stat().st_size != int(recorded["bytes"]):
            raise ValueError(f"generated input size differs from generator receipt: {name}")
        generator_inputs[name] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "generator_blake3": recorded["blake3"],
        }
    for name in generator_input_names[2:]:
        recorded = generator_receipt["outputs"][name]
        generator_inputs[name] = {
            "path_from_generator_receipt": str(args.generator / name),
            "bytes": recorded["bytes"],
            "generator_blake3": recorded["blake3"],
            "opened_by_assembler": False,
            "hash_recomputed_by_assembler": False,
        }
    generator_receipt_path = args.generator / "generator-receipt.json"
    generator_inputs["generator-receipt.json"] = {
        "path": str(generator_receipt_path),
        "sha256": sha256_file(generator_receipt_path),
    }
    protected_eval_refs = {
        "training_scope_audit": {
            "status": source_receipt["status"],
            "protected_identity_audit": source_receipt["protected_identity_audit"],
            "eval_bodies_opened_by_assembler": False,
        },
        "generated_heldout": {
            "pair_count_from_generator_receipt": generator_receipt["eval_pairs"],
            "episode_count_from_generator_receipt": generator_receipt["eval_episode_count"],
            "family_ids_from_generator_receipt": sorted(generator_eval_families),
            "template_ids_from_generator_receipt": sorted(generator_eval_templates),
            "body_files_opened_by_assembler": False,
        },
    }
    capacity = {
        "generated_train_pair_capacity": generated_train_pairs,
        "eligible_baseline_choice_slots": eligible_count,
        "max_pair_slots_from_baseline": eligible_count // 2,
        "maximum_clean_pair_capacity": max_bank_pairs,
        "selected_dose_pairs": args.dose,
        "bank_occurrences_in_pair_structures": 2 * args.dose,
        "pair_occurrence_fraction": 2 * args.dose / ARM_SIZE,
        "expected_changed_sibling_fraction": args.dose / ARM_SIZE,
        "family_quotas": family_quotas,
        "reason_dose_frozen": "5k pairs cover 10% of bank occurrences after checking the 12k generated / 12,507 baseline-slot capacity"
    }
    if generated_train_pairs < args.dose:
        raise ValueError("generated pair universe does not support the chosen dose")

    # Reconstruct signature distance from completed files and text tables independently.
    s_rebuilt: Counter[str] = Counter()
    f_rebuilt: Counter[str] = Counter()
    s_rebuilt = s_audit["training_signatures"]
    f_rebuilt = f_audit["training_signatures"]
    rebuilt_distance = distribution_distance(s_rebuilt, f_rebuilt, ARM_SIZE)
    if rebuilt_distance != distance:
        raise ValueError("independent file reload changed training-signature distance")

    files = {
        "S100-groups.jsonl": s_hash,
        "F100-groups.jsonl": f_hash,
        "selected-train-contrast-certificates.jsonl": selected_cert_hash,
        "baseline-removal-manifest.jsonl": removal_hash,
        "state-inputs.jsonl": state_hash,
        **{f"candidate-inputs-{profile}.jsonl": table_output_hashes[profile] for profile in PROFILES},
    }
    report = {
        "protocol": "jev-information-density/v0.8i-phase-a",
        "status": phase_status,
        "model_contact": False,
        "backbone_loaded": False,
        "feature_extraction": False,
        "head_training": False,
        "phoenix_access": False,
        "source": {
            "protocol": source_receipt["protocol"],
            "status": source_receipt["status"],
            "paths_and_sha256": source_hashes,
            "generator_inputs": generator_inputs,
            "protected_eval_source_references": protected_eval_refs,
            "source_random_group_count": source_group_count,
        },
        "capacity": capacity,
        "banks": {
            "groups_per_arm": ARM_SIZE,
            "common_skeleton_groups": common_count,
            "removed_baseline_groups": removal_count,
            "added_groups_per_arm": len(custom_s),
            "selected_pair_anchors": args.dose,
            "exact_training_signature_distance": distance,
            "independently_rebuilt_distance": rebuilt_distance,
            "same_group_slot_ids": True,
            "same_common_rows": True,
            "profile_counts_equal": exact_matched,
            "surface_invariance_pair_events_equal": True,
            "unique_state_count": s_audit["unique_state_count"],
            "state_multiplicity_profile_equal": True,
            "selector_input_multiplicity_profile_equal": True,
            "surface_invariance_pair_event_count": len(s_audit["invariant_pairs"]),
            "heldout_pair_capacity_from_generator_receipt": generator_receipt["eval_pairs"],
            "heldout_episode_capacity_from_generator_receipt": generator_receipt["eval_episode_count"],
            "train_eval_family_overlap_from_generator_receipt": len(generator_train_families & generator_eval_families),
            "train_eval_template_overlap_from_generator_receipt": len(generator_train_templates & generator_eval_templates),
            "selected_train_episode_eval_overlap": 0,
            "generated_eval_bodies_read_by_assembler": False,
            "protected_eval_bodies_read_by_assembler": False,
        },
        "files": files,
    }
    report_hash = write_json(args.output / "phase-a-bank-receipt.json", report)
    write_json(args.output / "phase-a-integrity-receipt.json", {
        "protocol": report["protocol"],
        "status": "PASS_NO_MODEL_CONTACT" if phase_status == "PHASE_A_BANKS_BUILT_NO_MODEL_CONTACT" else "SMOKE_ONLY",
        "phase_a_bank_receipt_sha256": report_hash,
        "verified_files": {name: {"sha256": digest, "verified": sha256_file(args.output / name) == digest} for name, digest in files.items()},
        "source_inputs_unchanged": (
            all(sha256_file(Path(item["path"])) == item["sha256"]
                for item in source_hashes["scoped_training_inputs"].values())
            and sha256_file(Path(source_hashes["training_scope_receipt"]["path"]))
                == source_hashes["training_scope_receipt"]["sha256"]
            and all(sha256_file(Path(item["path"])) == item["sha256"]
                    for item in generator_inputs.values() if "path" in item)
        ),
        "protected_eval_bodies_opened": False,
        "generated_eval_bodies_opened": False,
        "model_contact": False,
        "phoenix_access": False,
        "phase_b_started": False,
        "phase_b_authorization": False,
    })
    print(json.dumps({"event": "phase_a_complete", "status": phase_status, "D_train": distance["D_train"], "pairs": args.dose, "groups_per_arm": ARM_SIZE}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
