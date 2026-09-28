"""Run the frozen deterministic, profile-checked Phase 2C atom-count search."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "jev-information-density-v08"))
sys.path.insert(0, str(HERE.parent / "jev-information-density-v08b"))
import optimize_matched_banks as optimizer  # noqa: E402
import phase2c_training_signatures as signatures  # noqa: E402
import audit_phase2c_training_signatures as signature_audit  # noqa: E402

DEFAULT_CONTRACT = HERE / "v08c-phase2c-search-contract.json"
DEFAULT_FREEZE = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\cross-atom-search-v01\freeze-receipt.json")
DEFAULT_ROOT = DEFAULT_FREEZE.parent
LIMIT = 100_000
TV_LIMIT = 0.02


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_manifest(path: Path, expected: int = LIMIT) -> set[str]:
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            group_id = json.loads(line)["group_id"]
            if not isinstance(group_id, str) or not group_id or group_id in ids:
                raise ValueError(f"invalid or duplicate ID at {path}:{line_no}")
            ids.add(group_id)
    if len(ids) != expected:
        raise ValueError(f"{path} contains {len(ids)} IDs; expected {expected}")
    return ids


def verify_freeze(contract_path: Path, receipt_path: Path) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if contract.get("status") != "frozen_before_candidate_optimization":
        raise ValueError("search protocol is not frozen")
    if receipt.get("status") != "SEALED_BEFORE_CROSS_ATOM_SEARCH":
        raise ValueError("search freeze receipt status mismatch")
    if receipt.get("contract_sha256") != sha256_file(contract_path):
        raise ValueError("search contract hash mismatch")
    for relative, expected in receipt["repository_sources"].items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"frozen search source changed: {relative}")
    for name, record in contract["inputs"].items():
        if sha256_file(Path(record["path"])) != record["sha256"]:
            raise ValueError(f"search input hash mismatch: {name}")
    for name, record in receipt["external_inputs"].items():
        if sha256_file(Path(record["path"])) != record["sha256"]:
            raise ValueError(f"frozen external input changed: {name}")
    mobility = json.loads(Path(contract["inputs"]["mobility_report"]["path"]).read_text(encoding="utf-8"))
    if mobility.get("status") != "PASS_METADATA_SUPPORT_CENSUS":
        raise ValueError("parent support mobility census is not a PASS")
    if mobility.get("same_core_cross_atom_one_unit_swaps", {}).get("C100", {}).get("one_unit_full_profile_valid_edges") != 0:
        raise ValueError("mobility report no longer supports the frozen search-neighborhood rationale")
    expected_ortools = receipt.get("runtime", {}).get("ortools_expected_version")
    if importlib.metadata.version("ortools") != expected_ortools:
        raise ValueError("OR-Tools runtime differs from the frozen search receipt")
    return contract


def apply_hist_move(histogram: Counter[int], source_count: int, destination_count: int) -> Counter[int]:
    result = histogram.copy()
    result[source_count] -= 1
    if result[source_count] == 0:
        del result[source_count]
    if source_count > 1:
        result[source_count - 1] += 1
    if destination_count > 0:
        result[destination_count] -= 1
        if result[destination_count] == 0:
            del result[destination_count]
    result[destination_count + 1] += 1
    return result


def moved_unique_count(current_unique: int, source_count: int, destination_count: int) -> int:
    return current_unique - int(source_count == 1) + int(destination_count == 0)


def counter_after_delta(base: Counter[str], remove: tuple[str, ...], add: tuple[str, ...]) -> Counter[str]:
    result = base.copy()
    result.subtract(remove)
    result.update(add)
    return +result


@dataclass(slots=True)
class ProfileState:
    current: dict[str, Counter[Any]]
    reference: dict[str, Counter[Any]]
    input_hist: Counter[int]
    root_hist: Counter[int]
    reference_input_hist: Counter[int]
    reference_root_hist: Counter[int]
    input_unique: int
    root_unique: int

    @classmethod
    def from_groups(cls, selected: list[Any], reference_groups: list[Any]) -> "ProfileState":
        import build_factorial_banks as v08b

        current = v08b.profile(selected)
        reference = v08b.profile(reference_groups)
        return cls(
            current=current,
            reference=reference,
            input_hist=v08b.histogram(current["inputs"]),
            root_hist=v08b.histogram(current["roots"]),
            reference_input_hist=v08b.histogram(reference["inputs"]),
            reference_root_hist=v08b.histogram(reference["roots"]),
            input_unique=len(current["inputs"]),
            root_unique=len(current["roots"]),
        )

    def feasible_after(self, source: "Atom", destination: "Atom") -> bool:
        import build_factorial_banks as v08b

        source_input = source.input_id
        destination_input = destination.input_id
        source_root = source.root_id
        destination_root = destination.root_id
        new_input_unique = self.input_unique
        new_root_unique = self.root_unique
        new_input_hist = self.input_hist
        new_root_hist = self.root_hist
        if source_input != destination_input:
            a = self.current["inputs"][source_input]
            b = self.current["inputs"].get(destination_input, 0)
            new_input_unique = moved_unique_count(self.input_unique, a, b)
            new_input_hist = apply_hist_move(self.input_hist, a, b)
        if source_root != destination_root:
            a = self.current["roots"][source_root]
            b = self.current["roots"].get(destination_root, 0)
            new_root_unique = moved_unique_count(self.root_unique, a, b)
            new_root_hist = apply_hist_move(self.root_hist, a, b)
        ref_inputs = len(self.reference["inputs"])
        ref_roots = len(self.reference["roots"])
        if abs(new_input_unique - ref_inputs) / ref_inputs > 0.02 + 1e-12:
            return False
        if abs(new_root_unique - ref_roots) / ref_roots > 0.02 + 1e-12:
            return False
        if v08b.tv_distance(new_input_hist, self.reference_input_hist) > TV_LIMIT + 1e-12:
            return False
        if v08b.tv_distance(new_root_hist, self.reference_root_hist) > TV_LIMIT + 1e-12:
            return False
        topology = counter_after_delta(self.current["topology"], source.topology, destination.topology)
        interventions = counter_after_delta(
            self.current["interventions"], (source.intervention,), (destination.intervention,)
        )
        return (
            v08b.tv_distance(topology, self.reference["topology"]) <= TV_LIMIT + 1e-12
            and v08b.tv_distance(interventions, self.reference["interventions"]) <= TV_LIMIT + 1e-12
        )

    def apply(self, source: "Atom", destination: "Atom") -> None:
        import build_factorial_banks as v08b

        if source.input_id != destination.input_id:
            a, b = self.current["inputs"][source.input_id], self.current["inputs"].get(destination.input_id, 0)
            self.input_hist = apply_hist_move(self.input_hist, a, b)
            self.input_unique = moved_unique_count(self.input_unique, a, b)
            self.current["inputs"][source.input_id] -= 1
            if self.current["inputs"][source.input_id] == 0:
                del self.current["inputs"][source.input_id]
            self.current["inputs"][destination.input_id] += 1
        if source.root_id != destination.root_id:
            a, b = self.current["roots"][source.root_id], self.current["roots"].get(destination.root_id, 0)
            self.root_hist = apply_hist_move(self.root_hist, a, b)
            self.root_unique = moved_unique_count(self.root_unique, a, b)
            self.current["roots"][source.root_id] -= 1
            if self.current["roots"][source.root_id] == 0:
                del self.current["roots"][source.root_id]
            self.current["roots"][destination.root_id] += 1
        self.current["topology"] = counter_after_delta(self.current["topology"], source.topology, destination.topology)
        self.current["interventions"] = counter_after_delta(
            self.current["interventions"], (source.intervention,), (destination.intervention,)
        )
        if source.cell != destination.cell:
            raise AssertionError("joint-cell counts must be invariant under every accepted move")
        if self.current["cells"][source.cell] <= 0:
            raise AssertionError("accepted transfer has no source joint-cell mass")


@dataclass(slots=True)
class Atom:
    atom_id: str
    input_id: str
    root_id: str
    cell: tuple[str, ...]
    topology: tuple[str, ...]
    intervention: str
    members: list[Any]
    priorities: list[int]
    signatures: list[str]
    selected_count: int = 0

    @property
    def capacity(self) -> int:
        return len(self.members)

    def selected_objective(self) -> int:
        return sum(self.priorities[: self.selected_count])


def update_distance_mass(distance_mass: int, current: Counter[str], reference: Counter[str], old: str, new: str) -> int:
    if old == new:
        return distance_mass
    before_old = abs(current[old] - reference.get(old, 0))
    current[old] -= 1
    if current[old] == 0:
        del current[old]
    after_old = abs(current.get(old, 0) - reference.get(old, 0))
    before_new = abs(current.get(new, 0) - reference.get(new, 0))
    current[new] += 1
    after_new = abs(current[new] - reference.get(new, 0))
    return distance_mass + after_old - before_old + after_new - before_new


def distance_from_mass(mass: int) -> float:
    return mass / (2 * LIMIT)


def selected_groups(atoms: dict[str, Atom]) -> list[Any]:
    result: list[Any] = []
    for atom in atoms.values():
        result.extend(atom.members[: atom.selected_count])
    return result


def read_atom_support(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            atom_id = row["atom_id"]
            if atom_id in result:
                raise ValueError(f"duplicate atom support ID: {atom_id}")
            result[atom_id] = row
    return result


def read_signatures(path: Path) -> dict[str, str]:
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        return dict(connection.execute("SELECT group_id,supervised_signature_sha256 FROM training_groups WHERE held_out=0"))
    finally:
        connection.close()


def build_atoms(
    groups: list[Any],
    selected_ids: set[str],
    priorities: dict[str, int],
    supervised_signatures: dict[str, str],
    support: dict[str, dict[str, Any]],
) -> dict[str, Atom]:
    import build_factorial_banks as v08b

    members: dict[str, list[Any]] = defaultdict(list)
    fields: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[Any, ...]]] = {}
    for group in groups:
        atom_key = optimizer.group_atom(group)
        input_id, root_id, cell, topology_full, intervention = atom_key
        topology = tuple(sorted(value.removeprefix("topology:") for value in topology_full))
        atom_id = canonical_digest([input_id, root_id, list(cell), list(topology_full), intervention])
        if atom_id not in support:
            raise ValueError(f"group maps to atom absent from frozen support table: {group.group_id}")
        reference = support[atom_id]
        if (
            reference["input_id"] != input_id
            or reference["root_id"] != root_id
            or reference["joint_cell"] != list(cell)
            or reference["topology"] != list(topology_full)
            or reference["intervention"] != intervention
        ):
            raise ValueError(f"frozen atom table metadata mismatch: {atom_id}")
        fields[atom_id] = (input_id, root_id, tuple(cell), topology, intervention, atom_key)
        members[atom_id].append(group)

    result: dict[str, Atom] = {}
    for atom_id, atom_members in members.items():
        atom_members.sort(key=lambda group: (-priorities[group.group_id], group.group_id))
        input_id, root_id, cell, topology, intervention, _atom_key = fields[atom_id]
        selected_count = sum(group.group_id in selected_ids for group in atom_members)
        prefix = {group.group_id for group in atom_members[:selected_count]}
        observed = {group.group_id for group in atom_members if group.group_id in selected_ids}
        if prefix != observed:
            raise ValueError(f"starting bank is not the frozen policy prefix inside atom {atom_id}")
        result[atom_id] = Atom(
            atom_id=atom_id,
            input_id=input_id,
            root_id=root_id,
            cell=cell,
            topology=topology,
            intervention=intervention,
            members=atom_members,
            priorities=[priorities[group.group_id] for group in atom_members],
            signatures=[supervised_signatures[group.group_id] for group in atom_members],
            selected_count=selected_count,
        )
    if len(members) != len(support):
        # The support table covers all eligible groups; the atom set must match it exactly.
        missing = set(support) - set(members)
        if missing:
            raise ValueError(f"training group atom universe differs from frozen support; missing={len(missing)}")
    return result


def make_candidates(atoms: dict[str, Atom], epoch: int, mode: str, seed: str, side_limit: int) -> list[tuple[int, str, str, str]]:
    by_cell: dict[tuple[str, ...], list[Atom]] = defaultdict(list)
    for atom in atoms.values():
        by_cell[atom.cell].append(atom)
    result: list[tuple[int, str, str, str]] = []
    for cell in sorted(by_cell):
        cell_atoms = by_cell[cell]
        donors = [atom for atom in cell_atoms if atom.selected_count > 0]
        receivers = [atom for atom in cell_atoms if atom.selected_count < atom.capacity]
        donors.sort(key=lambda atom: (atom.priorities[atom.selected_count - 1], atom.atom_id))
        receivers.sort(key=lambda atom: (-atom.priorities[atom.selected_count], atom.atom_id))
        donors = donors[:side_limit]
        receivers = receivers[:side_limit]
        for source in donors:
            for destination in receivers:
                if source.atom_id == destination.atom_id:
                    continue
                gain = destination.priorities[destination.selected_count] - source.priorities[source.selected_count - 1]
                if gain <= 0:
                    continue
                tie = hashlib.sha256(
                    f"{seed}|{epoch}|{source.atom_id}|{destination.atom_id}".encode("utf-8")
                ).hexdigest()
                result.append((gain, tie, source.atom_id, destination.atom_id))
    result.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    return result


def write_manifest(path: Path, groups: list[Any]) -> str:
    digest = hashlib.sha256()
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for group in sorted(groups, key=lambda item: item.group_id):
            line = json.dumps({"group_id": group.group_id, "episode_id": group.episode_id}, separators=(",", ":")) + "\n"
            stream.write(line)
            digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def exact_training_distance(ids: set[str], reference_ids: set[str], sqlite_path: Path) -> dict[str, Any]:
    uri = f"file:{sqlite_path.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        candidate_rows = signature_audit.bank_rows(connection, {group_id: "" for group_id in ids})
        reference_rows = signature_audit.bank_rows(connection, {group_id: "" for group_id in reference_ids})
    finally:
        connection.close()
    candidate_final, candidate_pairs = signatures.attach_invariance_context(candidate_rows)
    reference_final, reference_pairs = signatures.attach_invariance_context(reference_rows)
    supervised_distance = signatures.multiset_distance(
        (row["supervised_signature_sha256"] for row in candidate_rows),
        (row["supervised_signature_sha256"] for row in reference_rows),
    )
    training_distance = signatures.multiset_distance(candidate_final.values(), reference_final.values())
    return {
        "supervised_multiset_distance": supervised_distance,
        "exact_training_signature_distance": training_distance,
        "candidate_selected_invariance_pair_count": len(candidate_pairs),
        "reference_selected_invariance_pair_count": len(reference_pairs),
        "candidate_pair_hashes": candidate_pairs,
        "reference_pair_hashes": reference_pairs,
        "candidate_training_signature_multiset_sha256": signatures.digest(sorted(candidate_final.values())),
        "reference_training_signature_multiset_sha256": signatures.digest(sorted(reference_final.values())),
    }


def run_bank(contract: dict[str, Any], bank: str, out_root: Path) -> dict[str, Any]:
    import build_factorial_banks as v08b

    if bank not in {"RM100", "CM100"}:
        raise ValueError("bank must be RM100 or CM100")
    mode = "random" if bank == "RM100" else "curated"
    base_name = "C100" if bank == "RM100" else "CM100_atom"
    reference_name = "C100" if bank == "RM100" else "R100"
    input_names = {"R100": "r100", "C100": "c100", "Eval": "eval", "CM100_atom": "cm100_atom", "RM100_atom": "rm100_atom"}
    paths = {name: Path(contract["inputs"][input_names[name]]["path"]) for name in input_names}
    manifest_ids = {name: read_manifest(path) for name, path in paths.items() if name != "Eval"}
    eval_ids = read_manifest(paths["Eval"], expected=83_328)
    if any(ids & eval_ids for ids in manifest_ids.values()):
        raise ValueError("training bank intersects NewTight-Eval")

    groups, _atoms, _capacities, _profiles, refs = optimizer.train_groups_and_profiles(
        Path(contract["inputs"]["group_records"]["path"]),
        paths["Eval"], paths["R100"], paths["C100"],
    )
    if len(groups) != 416_672:
        raise ValueError(f"frozen training population changed: {len(groups)}")
    references = {"R100": refs["R100"], "C100": refs["C100"]}
    base_ids = manifest_ids[base_name]
    reference_ids = manifest_ids[reference_name]
    if base_name in {"R100", "C100"}:
        base_ids = manifest_ids[base_name]
    selected_initial = [group for group in groups if group.group_id in base_ids]
    reference_groups = references[reference_name]
    if len(selected_initial) != LIMIT or len(reference_groups) != LIMIT:
        raise ValueError("start/reference bank membership is incomplete")

    seed = contract["search"]["policy_seeds"][bank]
    priorities = optimizer.priority_ranks(groups, mode, seed)
    signatures_by_group = read_signatures(Path(contract["inputs"]["training_signatures_sqlite"]["path"]))
    support = read_atom_support(Path(contract["inputs"]["atom_support"]["path"]))
    atoms = build_atoms(groups, base_ids, priorities, signatures_by_group, support)
    if sum(atom.selected_count for atom in atoms.values()) != LIMIT:
        raise ValueError("start atom counts do not sum to the frozen bank size")
    current_groups = selected_groups(atoms)
    profile = ProfileState.from_groups(current_groups, reference_groups)
    baseline_compare = v08b.compare(v08b.profile(reference_groups), v08b.profile(current_groups))
    if not v08b.all_pass(baseline_compare):
        raise ValueError(f"start state does not satisfy full frozen profile: {baseline_compare}")

    signatures_counter = Counter(signatures_by_group[group.group_id] for group in current_groups)
    ref_signatures_counter = Counter(signatures_by_group[group.group_id] for group in reference_groups)
    l1_mass = sum(abs(signatures_counter[key] - ref_signatures_counter[key]) for key in signatures_counter.keys() | ref_signatures_counter.keys())
    base_objective = sum(priorities[group_id] for group_id in base_ids)
    reference_objective = sum(priorities[group_id] for group_id in reference_ids)
    current_objective = base_objective
    search = contract["search"]
    epoch_limit = int(search["deterministic_neighborhood"]["epochs_max"])
    side_limit = int(search["deterministic_neighborhood"]["candidate_limit_per_side_per_cell"])
    eval_limit = int(search["deterministic_neighborhood"]["candidate_pair_evaluations_max"])
    accepted_limit = int(search["deterministic_neighborhood"]["accepted_unit_transfers_max"])
    target_distance = float(search["deterministic_neighborhood"]["stop_when_supervised_multiset_distance_reaches"])
    evaluation_count = accepted_count = 0
    epoch_receipts: list[dict[str, Any]] = []
    run_dir = out_root / bank.lower()
    run_dir.mkdir(parents=True, exist_ok=False)
    progress_path = run_dir / "optimizer-events.jsonl"
    start = time.perf_counter()
    last_event = start
    stop_reason = "EPOCH_LIMIT"

    with progress_path.open("x", encoding="utf-8", newline="\n") as progress:
        for epoch in range(1, epoch_limit + 1):
            candidates = make_candidates(atoms, epoch, mode, seed, side_limit)
            epoch_accepted = 0
            epoch_evaluations = 0
            for _gain_hint, _tie, source_id, destination_id in candidates:
                if evaluation_count >= eval_limit:
                    stop_reason = "PAIR_EVALUATION_LIMIT"
                    break
                if accepted_count >= accepted_limit:
                    stop_reason = "ACCEPTED_TRANSFER_LIMIT"
                    break
                source, destination = atoms[source_id], atoms[destination_id]
                if source.selected_count <= 0 or destination.selected_count >= destination.capacity:
                    continue
                gain = destination.priorities[destination.selected_count] - source.priorities[source.selected_count - 1]
                if gain <= 0:
                    continue
                evaluation_count += 1
                epoch_evaluations += 1
                now = time.perf_counter()
                if (
                    evaluation_count % 5000 == 0
                    or (evaluation_count % 1000 == 0 and now - last_event >= 60)
                ):
                    event = {
                        "stage": "cross_atom_search",
                        "bank": bank,
                        "epoch": epoch,
                        "candidate_pair_evaluations": evaluation_count,
                        "accepted_transfers": accepted_count,
                        "objective": current_objective,
                        "objective_gain_from_start": current_objective - base_objective,
                        "supervised_distance": distance_from_mass(l1_mass),
                        "elapsed_seconds": round(now - start, 3),
                    }
                    progress.write(json.dumps(event, separators=(",", ":")) + "\n")
                    progress.flush()
                    print(json.dumps(event, separators=(",", ":")), flush=True)
                    last_event = now
                if now - start >= float(search["per_bank_wall_time_seconds"]):
                    stop_reason = "WALL_TIME_LIMIT"
                    break
                if not profile.feasible_after(source, destination):
                    continue

                removed_group = source.members[source.selected_count - 1]
                added_group = destination.members[destination.selected_count]
                old_signature = source.signatures[source.selected_count - 1]
                new_signature = destination.signatures[destination.selected_count]
                l1_mass = update_distance_mass(l1_mass, signatures_counter, ref_signatures_counter, old_signature, new_signature)
                profile.apply(source, destination)
                source.selected_count -= 1
                destination.selected_count += 1
                current_objective += gain
                accepted_count += 1
                epoch_accepted += 1

                if distance_from_mass(l1_mass) >= target_distance:
                    stop_reason = "SUPERVISED_TREATMENT_PROXY_REACHED"
                    break

            selected_now = selected_groups(atoms)
            checkpoint = run_dir / f"checkpoint-epoch-{epoch:02d}-ids.jsonl"
            checkpoint_sha = write_manifest(checkpoint, selected_now)
            epoch_receipts.append({
                "epoch": epoch,
                "candidate_pairs_generated": len(candidates),
                "candidate_pairs_evaluated_this_epoch": epoch_evaluations,
                "accepted_transfers_this_epoch": epoch_accepted,
                "objective": current_objective,
                "objective_gain": current_objective - base_objective,
                "supervised_multiset_distance": distance_from_mass(l1_mass),
                "checkpoint_path": str(checkpoint),
                "checkpoint_sha256": checkpoint_sha,
            })
            progress.write(json.dumps({"stage": "epoch_complete", "bank": bank, **epoch_receipts[-1]}, separators=(",", ":")) + "\n")
            progress.flush()
            if stop_reason in {"PAIR_EVALUATION_LIMIT", "ACCEPTED_TRANSFER_LIMIT", "SUPERVISED_TREATMENT_PROXY_REACHED"}:
                break
            if epoch_accepted == 0:
                stop_reason = "NO_ADMISSIBLE_POSITIVE_GAIN_MOVE_IN_NEIGHBORHOOD"
                break
            if time.perf_counter() - start >= float(search["per_bank_wall_time_seconds"]):
                stop_reason = "WALL_TIME_LIMIT"
                break

    candidate_groups = selected_groups(atoms)
    candidate_ids = {group.group_id for group in candidate_groups}
    profile_report = v08b.compare(v08b.profile(reference_groups), v08b.profile(candidate_groups))
    if not v08b.all_pass(profile_report):
        raise AssertionError("incremental profile allowed an invalid final candidate")
    training = exact_training_distance(candidate_ids, reference_ids, Path(contract["inputs"]["training_signatures_sqlite"]["path"]))
    candidate_manifest = run_dir / "candidate-ids.jsonl"
    manifest_sha = write_manifest(candidate_manifest, candidate_groups)
    report = {
        "protocol": "jev-decision-data-information-density/v0.8c-phase2c-cross-atom-search",
        "status": "PROVISIONAL_CANDIDATE_READY_FOR_INDEPENDENT_VALIDATION" if candidate_ids != base_ids else "NO_DISTINCT_CANDIDATE",
        "bank": bank,
        "objective_mode": mode,
        "start_bank": base_name,
        "reference_bank": reference_name,
        "start_group_count": len(base_ids),
        "candidate_group_count": len(candidate_ids),
        "start_to_candidate_changed_ids": len(base_ids ^ candidate_ids),
        "objective": {
            "identity_or_start_sum": base_objective,
            "start_sum": base_objective,
            "reference_sum": reference_objective,
            "candidate_sum": current_objective,
            "gain_from_start": current_objective - base_objective,
            "gain_vs_reference": current_objective - reference_objective,
            "positive_vs_reference": current_objective > reference_objective,
        },
        "distance": training,
        "full_profile_recomputed_by_search": profile_report,
        "search": {
            "stop_reason": stop_reason,
            "epochs_completed": epoch_receipts,
            "candidate_pairs_evaluated": evaluation_count,
            "accepted_unit_transfers": accepted_count,
            "elapsed_seconds": round(time.perf_counter() - start, 3),
            "optimality": "NOT_PROVEN_BOUNDED_GREEDY_SEARCH",
        },
        "candidate_manifest": {"path": str(candidate_manifest), "sha256": manifest_sha},
        "model_contact": False,
        "training_materialized": False,
        "phoenix_access": False,
    }
    report_path = run_dir / "search-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "bank": bank,
        "status": report["status"],
        "stop_reason": stop_reason,
        "objective_gain_from_start": current_objective - base_objective,
        "objective_gain_vs_reference": current_objective - reference_objective,
        "D_supervised": training["supervised_multiset_distance"],
        "D_train": training["exact_training_signature_distance"],
        "profile_pass": v08b.all_pass(profile_report),
        "manifest_sha256": manifest_sha,
        "report": str(report_path),
    }, separators=(",", ":")), flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", choices=("RM100", "CM100"), required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--out", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    contract = verify_freeze(args.contract, args.freeze_receipt)
    if args.out.resolve() != args.freeze_receipt.parent.resolve():
        raise ValueError("search output must use the frozen external run directory")
    if args.bank == "CM100":
        rm_report = args.out / "rm100" / "search-report.json"
        rm_validation = args.out / "rm100" / "candidate-validation.json"
        if not rm_report.exists() or not rm_validation.exists():
            raise ValueError("CM100 search requires completed RM100 search and independent validation")
        rm = json.loads(rm_report.read_text(encoding="utf-8"))
        validation = json.loads(rm_validation.read_text(encoding="utf-8"))
        if rm.get("distance", {}).get("exact_training_signature_distance", 0.0) < 0.10 or validation.get("status") != "PASS_MODEL_COUNTERFACTUAL_AND_POLICY_SEPARATION":
            raise ValueError("RM100 did not clear the frozen readiness gates; CM100 remains conditional")
    run_bank(contract, args.bank, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
