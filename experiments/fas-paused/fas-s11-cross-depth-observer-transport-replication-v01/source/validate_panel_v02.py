from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


FAMILIES = [
    "STABLE", "SINGLE_SWITCH", "RETURN", "CYCLIC", "GRADUAL_DRIFT",
    "TEMPORARY_RULE", "CONTRADICTORY_NOISE", "POISON_BURST",
]
RELATIONS = ["relvane", "soprix"]
STATES = ["zavik", "nurex", "pavom"]
OBSERVATIONS = [
    "In {context}, the {entity} has {relation} {state}.",
    "For {context}: {relation} of {entity} = {state}.",
    "Within {context}, {entity} is recorded as {state} for {relation}.",
    "The {relation} entry for {entity} at {context} reads {state}.",
    "Record: {context} / {entity} / {relation} -> {state}.",
    "{entity} at {context} carries {state} under {relation}.",
    "Index {relation}: {entity} in {context} maps to {state}.",
    "Fact [{context}; {entity}; {relation}] = {state}.",
]
QUERIES = [
    "What is {relation} for {entity} in {context}?",
    "Find the {relation} of {entity} at {context}.",
    "Select {relation}({context}, {entity}).",
    "Report {entity}'s {relation} within {context}.",
    "Return current {relation}: {context} / {entity}.",
    "Which value is stored for {relation} and {entity} under {context}?",
    "Give the {relation} linked to {entity} in {context}.",
    "Look up {context} -> {entity} -> {relation}.",
]
PERMUTATIONS = [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)]
QUOTAS = {0: 1733, 1: 1815, 2: 1770}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("rb") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def identity_digest(kind: str, identifier: str) -> str:
    return sha256(f"{kind}|{identifier}".encode("ascii"))


def rebuild_ancestry_denylist(ancestry_root: Path) -> tuple[set[str], set[str]]:
    s01_path = ancestry_root / "fas-s01-frozen-sensor-transfer-cartography/s01-2-v01-sealed/corpus/counterfactual-quartets-v01.jsonl"
    s09_path = ancestry_root / "fas-s09-depthwise-decision-subspace-emergence-v09/inputs/token-only-feature-rows-v02.jsonl"
    prior_ids: set[str] = set()
    prior_inputs: set[str] = set()
    s01_count = 0
    with s01_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            quartet_id = row["quartet_id"]
            for kind in ("world", "episode", "quartet"):
                prior_ids.add(identity_digest(kind, quartet_id))
            for event in row["variants"]:
                prior_ids.add(identity_digest("event", event["event_id"]))
                prior_inputs.add(event["input_sha256"])
            s01_count += 1
    s09_count = 0
    with s09_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            event_id = row["event_id"]
            prior_ids.add(identity_digest("event", event_id))
            quartet_id, _, _ = event_id.rpartition(":")
            if quartet_id:
                for kind in ("world", "episode", "quartet"):
                    prior_ids.add(identity_digest(kind, quartet_id))
            prior_inputs.add(row["input_sha256"])
            s09_count += 1
    if (s01_count, s09_count) != (26_624, 106_496):
        raise ValueError(f"independent ancestry row counts mismatch: {s01_count}/{s09_count}")
    # S10 reused the same S09 event population and input bytes.
    return prior_ids, prior_inputs


def term_inventory(contract: dict[str, Any]) -> tuple[list[str], list[str]]:
    spec = contract["fresh_panel"]["term_inventory"]
    products = [prefix + suffix for prefix in spec["prefixes"] for suffix in spec["suffixes"]]
    return products[:32], products[32:]


def expected_designs() -> Iterable[dict[str, Any]]:
    ordinal = 0
    for context_split in range(2):
        for entity_split in range(2):
            for family in range(8):
                for relation in range(2):
                    for state in range(3):
                        for query in range(8):
                            observation = (query + family + relation + 3 * state) % 8
                            offset = (3 * family + 5 * relation + 7 * state
                                      + 11 * context_split + 13 * entity_split) % 16
                            for pair in range(16):
                                order_index = (3 * family + 5 * relation + 7 * query + pair) % 6
                                yield design_row(
                                    ordinal, "FACTORIAL_BALANCED", context_split, entity_split,
                                    family, relation, state, observation, query, pair,
                                    (pair + offset) % 16, order_index,
                                )
                                ordinal += 1
    for context_split in range(2):
        for entity_split in range(2):
            for context_pair in range(16):
                for entity_pair in range(16):
                    order_index = (context_pair + entity_pair + 3 * context_split + entity_split) % 6
                    yield design_row(
                        ordinal, "BINDING_CONTEXT", context_split, entity_split, 0, 0, 0,
                        0, 0, context_pair, entity_pair, order_index,
                    )
                    ordinal += 1
    for context_split in range(2):
        for entity_split in range(2):
            for entity_pair in range(16):
                for context_pair in range(16):
                    order_index = (entity_pair + context_pair + context_split + 3 * entity_split) % 6
                    yield design_row(
                        ordinal, "BINDING_ENTITY", context_split, entity_split, 0, 0, 0,
                        0, 0, context_pair, entity_pair, order_index,
                    )
                    ordinal += 1


def design_row(
    ordinal: int, track: str, context_split: int, entity_split: int, family: int,
    relation: int, state: int, observation: int, query: int,
    context_pair: int | None, entity_pair: int | None, order_index: int,
) -> dict[str, Any]:
    order = PERMUTATIONS[order_index]
    exact_target = order.index(state)
    values = {
        "ordinal": ordinal, "track_id": track,
        "context_split": context_split, "entity_split": entity_split,
        "world_family_id": family, "relation_id": relation, "state_id": state,
        "observation_template_id": observation, "query_template_id": query,
        "context_pair_id": context_pair, "entity_pair_id": entity_pair,
        "candidate_order_index": order_index, "target_class": exact_target,
    }
    fields = [
        track, str(context_split), str(entity_split), str(family), str(relation), str(state),
        str(observation), str(query), "" if context_pair is None else str(context_pair),
        "" if entity_pair is None else str(entity_pair), str(order_index), str(ordinal),
    ]
    key = "|".join(fields)
    values["canonical_candidate_key"] = key
    values["selection_sha256"] = sha256(
        f"FAS-S11-V01|SELECT|{exact_target}|{key}".encode("ascii")
    )
    return values


def expected_selected(
    rows: list[dict[str, Any]], denied_ids: set[str], denied_inputs: set[str]
) -> tuple[set[int], set[int]]:
    grouped: dict[int, list[dict[str, Any]]] = {0: [], 1: [], 2: []}
    for row in rows:
        ordinal = row["ordinal"]
        identity_ok = all(
            digest not in denied_ids
            for kind, fmt in (
                ("world", f"fas-s11-v01-world-{ordinal:06d}"),
                ("episode", f"fas-s11-v01-episode-{ordinal:06d}"),
                ("quartet", f"fas-s11-v01-quartet-{ordinal:06d}"),
            )
            for digest in [identity_digest(kind, fmt)]
        )
        event_ok = all(
            identity_digest("event", f"fas-s11-v01-event-{ordinal:06d}-{variant}") not in denied_ids
            for variant in "ACEP"
        )
        input_ok = all(input_hash not in denied_inputs for input_hash in row["rendered_input_sha256"])
        if identity_ok and event_ok and input_ok:
            grouped[row["target_class"]].append(row)
    selected: set[int] = set()
    duplicate_rejected: set[int] = set()
    admitted_inputs: set[str] = set()
    for target_class, group in grouped.items():
        group.sort(key=lambda row: (row["selection_sha256"], row["ordinal"]))
        admitted = 0
        for row in group:
            if admitted == QUOTAS[target_class]:
                break
            hashes = row["rendered_input_sha256"]
            if len(set(hashes)) != 4 or any(value in admitted_inputs for value in hashes):
                duplicate_rejected.add(row["ordinal"])
                continue
            selected.add(row["ordinal"])
            admitted_inputs.update(hashes)
            admitted += 1
        if admitted != QUOTAS[target_class]:
            raise ValueError(f"collision-aware class {target_class} admits only {admitted} quartets")
    return selected, duplicate_rejected


def render(template: str, context: str, entity: str, relation: str, state: str) -> str:
    return (template.replace("{context}", context).replace("{entity}", entity)
            .replace("{relation}", relation).replace("{state}", state))


def independent_input_hashes(design: dict[str, Any], context_terms: list[str], entity_terms: list[str]) -> list[str]:
    cs, es = design["context_split"], design["entity_split"]
    cp, ep = design["context_pair_id"], design["entity_pair_id"]
    cb, ca = cs * 16 + cp, cs * 16 + (cp + 7) % 16
    eb, ea = es * 16 + ep, es * 16 + (ep + 7) % 16
    variants = [
        (cb, eb, design["observation_template_id"]),
        (ca, eb, design["observation_template_id"]),
        (cb, ea, design["observation_template_id"]),
        (cb, eb, (design["observation_template_id"] + 4) % 8),
    ]
    order = PERMUTATIONS[design["candidate_order_index"]]
    options = ", ".join(STATES[candidate] for candidate in order)
    relation, state = RELATIONS[design["relation_id"]], STATES[design["state_id"]]
    hashes = []
    for context_id, entity_id, obs_id in variants:
        observation = render(OBSERVATIONS[obs_id], context_terms[context_id], entity_terms[entity_id], relation, state)
        query = render(QUERIES[design["query_template_id"]], context_terms[context_id], entity_terms[entity_id], relation, "")
        hashes.append(sha256(f"{observation}\n{query}\nOptions: {options}".encode("ascii")))
    return hashes


def splitmix64(value: int) -> int:
    mask = (1 << 64) - 1
    value = (value + 0x9E3779B97F4A7C15) & mask
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & mask
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & mask
    return value ^ (value >> 31)


def reconstruct_quartet(q: dict[str, Any], context_terms: list[str], entity_terms: list[str]) -> None:
    ordinal = q["ordinal"]
    if q["world_id"] != f"fas-s11-v01-world-{ordinal:06d}" or q["episode_id"] != f"fas-s11-v01-episode-{ordinal:06d}":
        raise ValueError(f"ordinal {ordinal}: world or episode identity mismatch")
    if q["quartet_id"] != f"fas-s11-v01-quartet-{ordinal:06d}":
        raise ValueError(f"ordinal {ordinal}: quartet identity mismatch")
    if [event["variant_id"] for event in q["variants"]] != list("ACEP"):
        raise ValueError(f"ordinal {ordinal}: A/C/E/P order mismatch")
    latent = q["latent_world"]
    if (latent["regime_id"] != q["world_family_id"]
            or latent["regime_name"] != FAMILIES[q["world_family_id"]]
            or latent["time_step"] != 0 or latent["feedback_marker"] != "NONE"):
        raise ValueError(f"ordinal {ordinal}: latent regime metadata mismatch")
    facts = latent["facts"]
    if len(facts) != 1:
        raise ValueError(f"ordinal {ordinal}: exact-world fact count mismatch")
    state = facts[0]["state_id"]
    matches = [fact for fact in facts if (
        fact["canonical_context_id"] == q["latent_world"]["current_exact_world_state"]["canonical_context_id"]
        and fact["canonical_entity_id"] == q["latent_world"]["current_exact_world_state"]["canonical_entity_id"]
        and fact["relation_id"] == q["relation_id"]
    )]
    if len(matches) != 1:
        raise ValueError(f"ordinal {ordinal}: query does not resolve to one fact")
    current = latent["current_exact_world_state"]
    if (current["state_id"] != state or current["relation_id"] != q["relation_id"]
            or current["target_candidate_identity"] != state):
        raise ValueError(f"ordinal {ordinal}: serialized current state mismatch")
    candidate_by_state = {candidate["state_id"]: candidate for candidate in latent["candidate_semantics"]}
    if len(candidate_by_state) != 3 or set(candidate_by_state) != {0, 1, 2}:
        raise ValueError(f"ordinal {ordinal}: candidate authority is incomplete")
    if [candidate_by_state[i]["candidate_identity"] for i in range(3)] != [0, 1, 2]:
        raise ValueError(f"ordinal {ordinal}: candidate identity/state mapping mismatch")
    order = q["candidate_identity_order"]
    expected_target = order.index(candidate_by_state[state]["candidate_identity"])
    if expected_target != q["exact_target"] or expected_target != q["variants"][0]["exact_target"]:
        raise ValueError(f"ordinal {ordinal}: independent answer reconstruction disagrees")
    if q["target_candidate_identity"] != state:
        raise ValueError(f"ordinal {ordinal}: target candidate identity mismatch")

    a, c, e, p = q["variants"]
    expected_factors = ["NONE", "CONTEXT", "ENTITY", "OBSERVATION_TEMPLATE"]
    if [event["changed_factor"] for event in q["variants"]] != expected_factors:
        raise ValueError(f"ordinal {ordinal}: declared intervention mismatch")
    if not (a["context_term_id"] == e["context_term_id"] == p["context_term_id"]
            and a["entity_term_id"] == c["entity_term_id"] == p["entity_term_id"]):
        raise ValueError(f"ordinal {ordinal}: A/C/E/P factor isolation failed")
    if a["context_term_id"] == c["context_term_id"] or a["entity_term_id"] == e["entity_term_id"]:
        raise ValueError(f"ordinal {ordinal}: declared substitution did not change term")
    if a["context_term_id"] != q["context_split"] * 16 + q["context_pair_id"]:
        raise ValueError(f"ordinal {ordinal}: context term ID does not match split/pair")
    if a["entity_term_id"] != q["entity_split"] * 16 + q["entity_pair_id"]:
        raise ValueError(f"ordinal {ordinal}: entity term ID does not match split/pair")
    if c["context_term_id"] != q["context_split"] * 16 + (q["context_pair_id"] + 7) % 16:
        raise ValueError(f"ordinal {ordinal}: context partner schedule mismatch")
    if e["entity_term_id"] != q["entity_split"] * 16 + (q["entity_pair_id"] + 7) % 16:
        raise ValueError(f"ordinal {ordinal}: entity partner schedule mismatch")

    for index, event in enumerate(q["variants"]):
        variant = "ACEP"[index]
        context_term = context_terms[event["context_term_id"]]
        entity_term = entity_terms[event["entity_term_id"]]
        if event["context_term"] != context_term or event["entity_term"] != entity_term:
            raise ValueError(f"ordinal {ordinal}/{variant}: term surface/identity mismatch")
        expected_obs = (q["observation_template_id"] + 4) % 8 if variant == "P" else q["observation_template_id"]
        if event["observation_template_id"] != expected_obs or event["query_template_id"] != q["query_template_id"]:
            raise ValueError(f"ordinal {ordinal}/{variant}: template schedule mismatch")
        relation = RELATIONS[q["relation_id"]]
        state_surface = STATES[q["state_id"]]
        obs = render(OBSERVATIONS[expected_obs], context_term, entity_term, relation, state_surface)
        query = render(QUERIES[q["query_template_id"]], context_term, entity_term, relation, "")
        candidate_text = [candidate_by_state[state_id]["surface"] for state_id in order]
        full_input = f"{obs}\n{query}\nOptions: {', '.join(candidate_text)}"
        if event["observation_text"] != obs or event["query_text"] != query or event["input_text"] != full_input:
            raise ValueError(f"ordinal {ordinal}/{variant}: rendered text differs from frozen template")
        if sha256(full_input.encode("ascii")) != event["input_sha256"]:
            raise ValueError(f"ordinal {ordinal}/{variant}: input hash mismatch")
        semantics = event["query_semantics"]
        if (semantics["canonical_context_id"] != current["canonical_context_id"]
                or semantics["canonical_entity_id"] != current["canonical_entity_id"]
                or semantics["relation_id"] != q["relation_id"]):
            raise ValueError(f"ordinal {ordinal}/{variant}: query semantics changed")
        if event["candidate_identity_order"] != order or event["candidate_text_order"] != candidate_text:
            raise ValueError(f"ordinal {ordinal}/{variant}: candidate ordering changed")
        if event["target_candidate_identity"] != state or event["exact_target"] != expected_target:
            raise ValueError(f"ordinal {ordinal}/{variant}: target mismatch")
        if event["event_id"] != f"fas-s11-v01-event-{ordinal:06d}-{variant}":
            raise ValueError(f"ordinal {ordinal}/{variant}: event identity mismatch")


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: validate_panel_v02.py <sealed-contract.json> <panel-output-dir> <codex-runs-dir>")
    contract_path = Path(sys.argv[1])
    root = Path(sys.argv[2])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    deny_dir = root / "preflight"
    deny_id_path = deny_dir / "denylist-identities-v02-sha256.txt"
    deny_input_path = deny_dir / "denylist-input-v02-sha256.txt"
    denied_ids = set(deny_id_path.read_text(encoding="ascii").splitlines())
    denied_inputs = set(deny_input_path.read_text(encoding="ascii").splitlines())
    deny_receipt = json.loads((deny_dir / "ancestry-denylist-receipt-v02.json").read_text())
    if sha256(b"".join((item + "\n").encode("ascii") for item in sorted(denied_ids))) != deny_receipt["identity_hash_file_sha256"]:
        raise ValueError("identity denylist digest mismatch")
    if sha256(b"".join((item + "\n").encode("ascii") for item in sorted(denied_inputs))) != deny_receipt["input_hash_file_sha256"]:
        raise ValueError("input denylist digest mismatch")
    if len(denied_ids) != deny_receipt["identity_hash_count"] or len(denied_inputs) != deny_receipt["input_hash_count"]:
        raise ValueError("denylist counts mismatch")
    actual_denied_ids, actual_denied_inputs = rebuild_ancestry_denylist(Path(sys.argv[3]))
    if actual_denied_ids != denied_ids or actual_denied_inputs != denied_inputs:
        raise ValueError("independent ancestry denylist reconstruction mismatch")

    context_terms, entity_terms = term_inventory(contract)
    serialized_terms = json.loads((root / "corpus/term-inventory-v02.json").read_text())
    if serialized_terms["context_terms"] != context_terms or serialized_terms["entity_terms"] != entity_terms:
        raise ValueError("serialized term inventory differs from the prospective contract")
    ledger = read_jsonl(root / "corpus/candidate-ledger-v02.jsonl")
    panel = read_jsonl(root / "corpus/selected-quartets-v02.jsonl")
    event_rows = read_jsonl(root / "corpus/selected-events-v02.jsonl")
    if len(ledger) != 26_624 or [row["ordinal"] for row in ledger] != list(range(26_624)):
        raise ValueError("candidate ledger does not account for the full ordered universe")

    expected = list(expected_designs())
    if len(expected) != 26_624:
        raise ValueError("independent design reconstruction has wrong size")
    for actual, design in zip(ledger, expected, strict=True):
        for field, value in design.items():
            if actual.get(field) != value:
                raise ValueError(f"candidate ordinal {design['ordinal']}: design field {field} mismatch")
        ordinal = design["ordinal"]
        expected_ids = [
            identity_digest("world", f"fas-s11-v01-world-{ordinal:06d}"),
            identity_digest("episode", f"fas-s11-v01-episode-{ordinal:06d}"),
            identity_digest("quartet", f"fas-s11-v01-quartet-{ordinal:06d}"),
        ]
        if (actual["world_identity_sha256"], actual["episode_identity_sha256"], actual["quartet_identity_sha256"]) != tuple(expected_ids):
            raise ValueError(f"candidate ordinal {ordinal}: identity hashes do not match namespace")
        expected_event_ids = [identity_digest("event", f"fas-s11-v01-event-{ordinal:06d}-{variant}") for variant in "ACEP"]
        if actual["event_identity_sha256"] != expected_event_ids:
            raise ValueError(f"candidate ordinal {ordinal}: event identity hashes do not match")
        if actual["rendered_input_sha256"] != independent_input_hashes(design, context_terms, entity_terms):
            raise ValueError(f"candidate ordinal {ordinal}: independently rendered input hashes mismatch")
        identity_ok = not any(token in denied_ids for token in expected_ids + expected_event_ids)
        input_ok = all(value not in denied_inputs for value in actual["rendered_input_sha256"])
        if actual["identity_fresh"] != identity_ok or actual["input_hashes_fresh"] != input_ok:
            raise ValueError(f"candidate ordinal {ordinal}: freshness disposition mismatch")

    selected_ordinals, duplicate_rejected = expected_selected(ledger, denied_ids, denied_inputs)
    for row in ledger:
        ordinal = row["ordinal"]
        if not row["identity_fresh"] or not row["input_hashes_fresh"]:
            expected_disposition = "FRESHNESS_REJECTED"
        elif ordinal in selected_ordinals:
            expected_disposition = "SELECTED"
        elif ordinal in duplicate_rejected:
            expected_disposition = "INTRA_PANEL_DUPLICATE_REJECTED"
        else:
            expected_disposition = "NOT_SELECTED"
        if row["disposition"] != expected_disposition:
            raise ValueError(f"candidate ordinal {ordinal}: rejection/admission accounting mismatch")
    ledger_selected = {row["ordinal"] for row in ledger if row["selected"]}
    if selected_ordinals != ledger_selected:
        raise ValueError("selected candidate set does not equal deterministic duplicate-aware admission order")
    if any(row["selected"] != (row["ordinal"] in selected_ordinals) for row in ledger):
        raise ValueError("candidate ledger selection flags are inconsistent")
    if len(panel) != 5_318 or {row["ordinal"] for row in panel} != selected_ordinals:
        raise ValueError("selected panel ordinals differ from the fixed sample")
    if len(event_rows) != 21_272:
        raise ValueError("selected event row count differs from contract")

    panel_by_ordinal = {row["ordinal"]: row for row in panel}
    seen_ids: dict[str, set[str]] = {kind: set() for kind in ("world", "episode", "quartet", "event")}
    seen_inputs: set[str] = set()
    class_counts: Counter[int] = Counter()
    family_counts: Counter[int] = Counter()
    track_counts: Counter[str] = Counter()
    obs_counts: Counter[int] = Counter()
    query_counts: Counter[int] = Counter()
    template_cells: Counter[str] = Counter()
    context_marginals: Counter[int] = Counter()
    entity_marginals: Counter[int] = Counter()
    row_counts: Counter[str] = Counter()
    ancestry_identity_rejections = sum(not row["identity_fresh"] for row in ledger)
    ancestry_input_rejections = sum(not row["input_hashes_fresh"] for row in ledger)
    if any(row["selected"] and (not row["identity_fresh"] or not row["input_hashes_fresh"]) for row in ledger):
        raise ValueError("freshness-rejected candidate was admitted")
    for ordinal in sorted(selected_ordinals):
        q = panel_by_ordinal[ordinal]
        reconstruct_quartet(q, context_terms, entity_terms)
        ledger_row = ledger[ordinal]
        if ledger_row["rendered_input_sha256"] != [event["input_sha256"] for event in q["variants"]]:
            raise ValueError(f"selected ordinal {ordinal}: candidate ledger/input payload mismatch")
        compact = json.dumps(q, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if sha256(compact) != ledger_row["quartet_payload_sha256"]:
            raise ValueError(f"selected ordinal {ordinal}: selected payload hash mismatch")
        if q["render_seed"] != splitmix64(contract["fresh_panel"]["generator_seed_u64"] ^ ordinal):
            raise ValueError(f"selected ordinal {ordinal}: render seed derivation mismatch")
        class_counts[q["exact_target"]] += 1
        family_counts[q["world_family_id"]] += 1
        track_counts[q["track_id"]] += 1
        obs_counts[q["observation_template_id"]] += 1
        query_counts[q["query_template_id"]] += 1
        template_cells[f"{q['observation_template_id']}:{q['query_template_id']}"] += 1
        context_marginals[q["context_split"]] += 1
        entity_marginals[q["entity_split"]] += 1
        for kind, value in (("world", q["world_id"]), ("episode", q["episode_id"]), ("quartet", q["quartet_id"])):
            if value in seen_ids[kind]:
                raise ValueError(f"duplicate selected {kind} identity")
            seen_ids[kind].add(value)
        for event in q["variants"]:
            if event["event_id"] in seen_ids["event"]:
                raise ValueError("duplicate selected event identity")
            seen_ids["event"].add(event["event_id"])
            if event["input_sha256"] in denied_inputs:
                raise ValueError("selected input collides with ancestry")
            if event["input_sha256"] in seen_inputs:
                raise ValueError("selected rendered input is duplicated")
            seen_inputs.add(event["input_sha256"])
            row_counts[event["variant_id"]] += 1

    if dict(class_counts) != QUOTAS:
        raise ValueError(f"exact class quotas differ: {dict(class_counts)}")
    if set(family_counts) != set(range(8)) or set(obs_counts) != set(range(8)) or set(query_counts) != set(range(8)):
        raise ValueError("minimum family or template presence gate failed")
    if len(template_cells) != 64:
        raise ValueError("not all 64 observation/query template cells are represented")
    if row_counts != Counter({variant: 5_318 for variant in "ACEP"}):
        raise ValueError("A/C/E/P event row accounting mismatch")

    expected_flat = []
    for q in panel:
        for event in q["variants"]:
            expected_flat.append((q, event))
    if len(expected_flat) != len(event_rows):
        raise ValueError("flat event accounting mismatch")
    flat_by_id = {row["event_id"]: row for row in event_rows}
    if len(flat_by_id) != len(event_rows):
        raise ValueError("duplicate flat event identity")
    for q, event in expected_flat:
        flat = flat_by_id[event["event_id"]]
        for field, value in {
            "world_id": q["world_id"], "episode_id": q["episode_id"], "quartet_id": q["quartet_id"],
            "world_family_id": q["world_family_id"], "track_id": q["track_id"],
            "context_split": q["context_split"], "entity_split": q["entity_split"],
            "latent_regime_id": q["latent_world"]["regime_id"], "context_term_id": event["context_term_id"],
            "entity_term_id": event["entity_term_id"], "observation_template_id": event["observation_template_id"],
            "query_template_id": event["query_template_id"], "state_id": q["state_id"],
            "variant_id": event["variant_id"], "exact_target": event["exact_target"],
            "target_candidate_identity": event["target_candidate_identity"],
            "candidate_identity_order": event["candidate_identity_order"],
            "candidate_text_order": event["candidate_text_order"], "query_semantics": event["query_semantics"],
            "current_exact_world_state": q["latent_world"]["current_exact_world_state"],
            "time_step": q["latent_world"]["time_step"], "feedback_marker": q["latent_world"]["feedback_marker"],
            "feedback_reveal_step": None, "render_seed": q["render_seed"],
            "input_text": event["input_text"], "input_sha256": event["input_sha256"],
            "context_term": event["context_term"], "entity_term": event["entity_term"],
        }.items():
            if flat.get(field) != value:
                raise ValueError(f"flat event {event['event_id']}: field {field} mismatch")

    construction = json.loads((root / "receipts/construction-receipt-v02.json").read_text())
    project_root = contract_path.resolve().parent.parent
    for source_rel, copied_rel in (
        ("FAS-S11-PROTOCOL-V01.md", "inputs/protocol/FAS-S11-PROTOCOL-V01.md"),
        ("contracts/s11-confirmatory-contract-v01.json", "inputs/protocol/s11-confirmatory-contract-v01.json"),
        ("seals/protocol-seal-v01.json", "inputs/protocol/protocol-seal-v01.json"),
    ):
        if (root / copied_rel).read_bytes() != (project_root / source_rel).read_bytes():
            raise ValueError(f"copied sealed protocol input changed: {source_rel}")
    authorization = json.loads((root / "authorization-v02.json").read_text())
    parent_verification = json.loads((root / "preflight/parent-verification-v02.json").read_text())
    if (authorization["panel_construction_authorized"] is not True
            or any(authorization[key] is not False for key in (
                "tokenizer_loaded", "model_loaded", "feature_extraction_performed",
                "observer_replay_performed", "probe_fitting_performed"))
            or parent_verification["status"] != "PASS"
            or parent_verification["model_loaded"] is not False
            or parent_verification["tokenizer_loaded"] is not False):
        raise ValueError("panel-only authority or parent preflight state mismatch")
    amendment_json = project_root / "amendments/s11-panel-collision-admission-correction-v01.json"
    amendment_md = project_root / "amendments/S11-PANEL-COLLISION-ADMISSION-CORRECTION-V01.md"
    copied_json = root / "inputs/amendment/s11-panel-collision-admission-correction-v01.json"
    copied_md = root / "inputs/amendment/S11-PANEL-COLLISION-ADMISSION-CORRECTION-V01.md"
    if copied_json.read_bytes() != amendment_json.read_bytes() or copied_md.read_bytes() != amendment_md.read_bytes():
        raise ValueError("copied collision correction differs from its frozen project-side object")
    if (file_sha(copied_json) != construction["panel_correction_json_sha256"]
            or file_sha(copied_md) != construction["panel_correction_markdown_sha256"]):
        raise ValueError("collision correction receipt hash mismatch")
    old_attempt = root.parent / "panel-construction-v01"
    old_receipt = old_attempt / "receipts/construction-receipt-v01.json"
    old_ledger = old_attempt / "corpus/candidate-ledger-v01.jsonl"
    old_failure = json.loads((old_attempt / "construction-failure-v01.json").read_text())
    if (old_failure["status"] != "PANEL_CONSTRUCTION_FAIL_CLOSED"
            or old_failure["duplicate_selected_input_hashes"] != "189"
            or file_sha(old_receipt) != construction["failed_v01_construction_receipt_sha256"]
            or file_sha(old_ledger) != construction["failed_v01_candidate_ledger_sha256"]):
        raise ValueError("failed v01 construction provenance changed or no longer matches correction")
    if (construction["status"] != "PANEL_CONSTRUCTED_PENDING_INDEPENDENT_VALIDATION"
            or construction["candidate_quartets"] != 26_624
            or construction["selected_quartets"] != 5_318
            or construction["selected_event_rows"] != 21_272
            or construction["duplicate_rejected_candidates"] != len(duplicate_rejected)
            or construction["deterministic_repeat_parity"] is not True):
        raise ValueError("construction receipt state/count/repeat gate failed")
    if file_sha(root / "corpus/candidate-ledger-v02.jsonl") != construction["candidate_ledger_sha256"]:
        raise ValueError("candidate ledger receipt hash mismatch")
    if file_sha(root / "corpus/selected-quartets-v02.jsonl") != construction["selected_quartets_sha256"]:
        raise ValueError("selected quartet receipt hash mismatch")
    if file_sha(root / "corpus/selected-events-v02.jsonl") != construction["selected_events_sha256"]:
        raise ValueError("selected event receipt hash mismatch")

    report = {
        "report_id": "FAS_S11_PANEL_INDEPENDENT_WORLD_VALIDATION_V02",
        "status": "S11_PANEL_CONSTRUCTION_VALID",
        "construction_only": True,
        "candidate_quartets": len(ledger),
        "selected_quartets": len(panel),
        "selected_event_rows": len(event_rows),
        "exact_target_class_counts": {str(k): class_counts[k] for k in sorted(class_counts)},
        "world_family_counts": {str(k): family_counts[k] for k in sorted(family_counts)},
        "track_counts": dict(sorted(track_counts.items())),
        "observation_template_counts": {str(k): obs_counts[k] for k in sorted(obs_counts)},
        "query_template_counts": {str(k): query_counts[k] for k in sorted(query_counts)},
        "observation_query_template_cell_counts": {key: template_cells.get(key, 0) for key in (f"{i}:{j}" for i in range(8) for j in range(8))},
        "context_split_marginals": {str(k): context_marginals[k] for k in sorted(context_marginals)},
        "entity_split_marginals": {str(k): entity_marginals[k] for k in sorted(entity_marginals)},
        "variant_row_counts": dict(sorted(row_counts.items())),
        "freshness": {
            "candidate_identity_rejections": ancestry_identity_rejections,
            "candidate_input_rejections": ancestry_input_rejections,
            "selected_panel_duplicate_input_hashes": 0,
            "duplicate_rejected_candidate_quartets": len(duplicate_rejected),
            "denylist_identity_hash_count": len(denied_ids),
            "denylist_input_hash_count": len(denied_inputs),
        },
        "gates": {
            "WORLD_TARGETS_EXACT": "PASS",
            "A_C_E_P_COUNTERFACTUAL_INVARIANTS": "PASS",
            "CLASS_QUOTAS_AND_FAMILY_TEMPLATE_SUPPORT": "PASS",
            "FRESH_IDENTITY_AND_INPUTS": "PASS",
            "COLLISION_AWARE_DETERMINISTIC_ADMISSION": "PASS",
            "ZERO_SELECTED_RENDERED_INPUT_COLLISIONS": "PASS",
            "FULL_CANDIDATE_ACCOUNTING": "PASS",
            "DETERMINISTIC_SELECTION_RECONSTRUCTION": "PASS",
            "FLAT_EVENT_BINDING": "PASS",
        },
        "tokenizer_loaded": False,
        "model_loaded": False,
        "features_extracted": False,
        "observer_replay_performed": False,
        "probe_fitting_performed": False,
    }
    report_path = root / "reports/panel-validation-report-v02.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("S11_PANEL_VALIDATION_PASS selected=5318 rows=21272 candidates=26624 model_contact=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
