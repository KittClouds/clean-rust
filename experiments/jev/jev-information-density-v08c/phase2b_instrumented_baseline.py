"""Run one instrumented, time-bounded CM100 baseline on the pinned CP-SAT path.

The sealed optimizer remains untouched. A spawned worker loads the sources,
then the parent starts the 15-minute post-load clock and supervises progress.
Only metadata and an optional ID-only candidate manifest are written outside
the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
import queue
import sys
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "jev-information-density-v08"))
sys.path.insert(0, str(HERE.parent / "jev-information-density-v08b"))


def emit(events: Any, kind: str, **fields: Any) -> None:
    events.put({
        "kind": kind,
        "utc": datetime.now(timezone.utc).isoformat(),
        "monotonic": time.monotonic(),
        **fields,
    })


def input_id(group: Any) -> str:
    values = [key.removeprefix("model_input:") for key in group.overlap_keys if key.startswith("model_input:")]
    if len(values) != 1:
        raise ValueError(f"group {group.group_id} has {len(values)} model_input keys")
    return values[0]


def entropy_band(value: float) -> str:
    if value < 0.20:
        return "very_low"
    if value < 0.55:
        return "low"
    if value < 0.95:
        return "medium"
    if value < 1.30:
        return "high"
    return "very_high"


def joint_cell(group: Any) -> tuple[str, ...]:
    world, query, cardinality, quintile = group.strata
    return (
        world, group.split_family_bundle_id, query, cardinality, quintile,
        entropy_band(group.posterior_entropy_nats),
    )


def hist(values: Counter[Any]) -> Counter[int]:
    return Counter(values.values())


def tv(left: Counter[Any], right: Counter[Any]) -> float:
    left_n, right_n = sum(left.values()), sum(right.values())
    if not left_n or not right_n:
        return 0.0 if left_n == right_n == 0 else 1.0
    return 0.5 * sum(
        abs(left.get(key, 0) / left_n - right.get(key, 0) / right_n)
        for key in set(left) | set(right)
    )


def group_profile(groups: list[Any]) -> dict[str, Counter[Any]]:
    result = {name: Counter() for name in ("cells", "inputs", "roots", "topology", "interventions")}
    for group in groups:
        result["cells"][joint_cell(group)] += 1
        result["inputs"][input_id(group)] += 1
        result["roots"][group.root_id] += 1
        result["interventions"][dict(group.families)["intervention_family"]] += 1
        result["topology"].update(
            feature.removeprefix("topology:")
            for feature in group.features[3]
            if feature.startswith("topology:")
        )
    return result


def independent_profile_audit(candidate: list[Any], reference: list[Any]) -> dict[str, Any]:
    selected = group_profile(candidate)
    target = group_profile(reference)
    selected_inputs, target_inputs = len(selected["inputs"]), len(target["inputs"])
    selected_roots, target_roots = len(selected["roots"]), len(target["roots"])

    def within_2pct(actual: int, expected: int) -> bool:
        return math.floor(expected * 0.98) <= actual <= math.ceil(expected * 1.02)

    metrics = {
        "group_count": len(candidate),
        "joint_cells_exact": selected["cells"] == target["cells"],
        "unique_inputs": {
            "selected": selected_inputs,
            "target": target_inputs,
            "relative_error": abs(selected_inputs - target_inputs) / target_inputs,
            "multiplicity_histogram_tv": tv(hist(selected["inputs"]), hist(target["inputs"])),
        },
        "unique_roots": {
            "selected": selected_roots,
            "target": target_roots,
            "relative_error": abs(selected_roots - target_roots) / target_roots,
            "multiplicity_histogram_tv": tv(hist(selected["roots"]), hist(target["roots"])),
        },
        "topology_tv": tv(selected["topology"], target["topology"]),
        "intervention_tv": tv(selected["interventions"], target["interventions"]),
    }
    metrics["all_hard_constraints_pass"] = all((
        len(candidate) == 100_000,
        metrics["joint_cells_exact"],
        within_2pct(selected_inputs, target_inputs),
        metrics["unique_inputs"]["multiplicity_histogram_tv"] <= 0.02 + 1e-12,
        within_2pct(selected_roots, target_roots),
        metrics["unique_roots"]["multiplicity_histogram_tv"] <= 0.02 + 1e-12,
        metrics["topology_tv"] <= 0.02 + 1e-12,
        metrics["intervention_tv"] <= 0.02 + 1e-12,
    ))
    return metrics


def worker(payload: dict[str, str], events: Any) -> None:
    try:
        import optimize_matched_banks as opt
        from ortools.sat.python import cp_model

        args = argparse.Namespace(
            group_records=Path(payload["groups"]),
            r100=Path(payload["r100"]),
            c100=Path(payload["c100"]),
            eval=Path(payload["eval"]),
            phase1_receipt=Path(payload["phase1_receipt"]),
            out=Path(payload["out"]),
        )
        contract, contract_path = opt.load_contract()
        source_started = time.perf_counter()
        emit(events, "stage_started", stage="source_hash_verification_and_loading")
        pins = opt.verify_pins(args, contract, contract_path)
        train_groups, atoms, capacities, profiles, references = opt.train_groups_and_profiles(
            args.group_records, args.eval, args.r100, args.c100
        )
        emit(
            events,
            "source_loaded",
            stage="source_hash_verification_and_loading",
            eligible_groups=len(train_groups),
            compressed_atoms=len(atoms),
            reference_groups={name: len(rows) for name, rows in references.items()},
            pins=pins,
            source_load_seconds=time.perf_counter() - source_started,
        )
        emit(events, "stage_finished", stage="source_hash_verification_and_loading")

        emit(events, "stage_started", stage="candidate_indexing_and_priority_ranks")
        members_by_atom: dict[tuple[Any, ...], list[Any]] = defaultdict(list)
        for group in train_groups:
            members_by_atom[opt.group_atom(group)].append(group)
        if set(members_by_atom) != set(atoms):
            raise ValueError("loaded atom identities differ from frozen atom table")
        for atom in atoms:
            members_by_atom[atom].sort(key=lambda group: group.group_id)
            if len(members_by_atom[atom]) != capacities[atom]:
                raise ValueError("atom capacity differs from source membership")
        priorities = opt.priority_ranks(
            train_groups, "curated", contract["objective"]["curated_seed"]
        )
        reference = references["R100"]
        reference_profile = group_profile(reference)
        reference_ids = {group.group_id for group in reference}
        identity_objective = sum(priorities[group_id] for group_id in reference_ids)
        emit(
            events,
            "stage_finished",
            stage="candidate_indexing_and_priority_ranks",
            atom_members=len(members_by_atom),
            priority_count=len(priorities),
            identity_objective=identity_objective,
        )

        emit(events, "stage_started", stage="cp_sat_variable_and_constraint_construction")
        model, bundle = opt.v08c.add_profile_model(
            atoms,
            capacities,
            profiles["R100"],
            contract["solver"]["random_seed"],
            contract["solver"]["wall_time_limit_seconds_per_bank"],
        )
        selected_vars, selected_var_count = opt.add_priority_objective(
            model, bundle["atom_vars"], atoms, members_by_atom, priorities
        )
        # The identity witness is a profile-feasibility hint only, not a valid
        # counterfactual incumbent. Partial aggregate hints avoid serializing
        # hundreds of thousands of individual Boolean hints.
        atom_counts = Counter(opt.group_atom(group) for group in reference)
        for atom, variable in zip(bundle["atoms"], bundle["atom_vars"]):
            model.add_hint(variable, atom_counts[atom])
        emit(
            events,
            "stage_finished",
            stage="cp_sat_variable_and_constraint_construction",
            atom_variable_count=len(bundle["atom_vars"]),
            selection_variable_count=selected_var_count,
            model_variable_count=len(model.proto.variables),
            model_constraint_count=len(model.proto.constraints),
            identity_hints="aggregate_atom_counts",
        )

        emit(events, "stage_started", stage="model_validation")
        model_error = model.validate()
        if model_error:
            raise ValueError(f"CP-SAT model validation failed: {model_error}")
        emit(events, "stage_finished", stage="model_validation", validation="PASS")

        class IncumbentReporter(cp_model.CpSolverSolutionCallback):
            def __init__(self) -> None:
                super().__init__()
                self.best_solver_objective: int | None = None
                self.best_validated_objective: int | None = None
                self.best_validated_groups: list[Any] | None = None
                self.best_validated_metrics: dict[str, Any] | None = None
                self.best_bound: float | None = None
                self.best_checkpoint: Path | None = None
                self.best_checkpoint_hash: str | None = None
                self.last_validated_improvement = time.monotonic()
                self.last_solver_improvement = time.monotonic()

            def on_solution_callback(self) -> None:
                objective = int(round(self.ObjectiveValue()))
                now = time.monotonic()
                if self.best_solver_objective is not None and objective <= self.best_solver_objective:
                    return
                self.best_solver_objective = objective
                self.last_solver_improvement = now
                bound = float(self.BestObjectiveBound())
                chosen = [group for group, variable in selected_vars if self.BooleanValue(variable)]
                audit_start = time.perf_counter()
                metrics = independent_profile_audit(chosen, reference)
                audit_seconds = time.perf_counter() - audit_start
                chosen_ids = {group.group_id for group in chosen}
                distinct = chosen_ids != reference_ids
                selected_objective = sum(priorities[group.group_id] for group in chosen)
                if selected_objective != objective:
                    raise ValueError("callback objective does not reproduce from selected IDs")
                separated = distinct and selected_objective >= identity_objective + 1
                validated = metrics["all_hard_constraints_pass"] and distinct
                if validated and (
                    self.best_validated_objective is None
                    or selected_objective > self.best_validated_objective
                ):
                    self.best_validated_objective = selected_objective
                    self.best_validated_groups = chosen
                    self.best_validated_metrics = metrics
                    self.best_bound = bound
                    self.last_validated_improvement = now
                    checkpoint = args.out / "cm100-best-audited-ids.jsonl"
                    checkpoint_tmp = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
                    with checkpoint_tmp.open("w", encoding="utf-8", newline="\n") as output:
                        for group in chosen:
                            output.write(json.dumps({"group_id": group.group_id, "episode_id": group.episode_id}, separators=(",", ":")) + "\n")
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(checkpoint_tmp, checkpoint)
                    self.best_checkpoint = checkpoint
                    self.best_checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
                best_separated = (
                    self.best_validated_objective is not None
                    and self.best_validated_objective >= identity_objective + 1
                )
                checkpoint = self.best_checkpoint
                checkpoint_hash = self.best_checkpoint_hash
                overlap_count = len(chosen_ids & reference_ids)
                emit(
                    events,
                    "solver_incumbent",
                    stage="cp_sat_presolve_and_search",
                    objective=objective,
                    bound=bound,
                    elapsed_solver_seconds=float(self.WallTime()),
                    independently_audited=metrics["all_hard_constraints_pass"],
                    nonidentical=distinct,
                    separated=separated,
                    changed_group_count=len(chosen_ids ^ reference_ids),
                    reference_overlap_count=overlap_count,
                    reference_overlap_fraction=overlap_count / len(reference_ids),
                    best_independently_validated_objective=self.best_validated_objective,
                    best_independently_validated_bound=self.best_bound,
                    best_independently_validated_separated=best_separated,
                    best_candidate_checkpoint=str(checkpoint) if checkpoint else None,
                    best_candidate_checkpoint_sha256=checkpoint_hash,
                    audit_seconds=audit_seconds,
                    time_since_validated_improvement_seconds=now - self.last_validated_improvement,
                )

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = contract["solver"]["workers"]
        solver.parameters.random_seed = contract["solver"]["random_seed"]
        solver.parameters.max_time_in_seconds = contract["solver"]["wall_time_limit_seconds_per_bank"]
        reporter = IncumbentReporter()
        emit(events, "stage_started", stage="cp_sat_presolve_and_search", identity_objective=identity_objective)
        solve_started = time.perf_counter()
        status_code = solver.solve(model, reporter)
        solve_seconds = time.perf_counter() - solve_started
        status_map = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE_NOT_PROVEN",
            cp_model.INFEASIBLE: "INFEASIBLE_MODEL_RESULT_REQUIRES_DIAGNOSIS",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "SEARCH_EXHAUSTED_OR_NO_SOLUTION",
        }
        emit(
            events,
            "stage_finished",
            stage="cp_sat_presolve_and_search",
            solver_status=status_map.get(status_code, f"UNRECOGNIZED_{status_code}"),
            solver_seconds=solve_seconds,
            solver_wall_seconds=float(solver.wall_time),
            objective=float(solver.objective_value) if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
            bound=float(solver.best_objective_bound) if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
            conflicts=int(solver.num_conflicts),
            branches=int(solver.num_branches),
            best_independently_validated_objective=reporter.best_validated_objective,
            time_since_validated_improvement_seconds=time.monotonic() - reporter.last_validated_improvement,
        )

        candidate_path = None
        candidate_hash = None
        candidate_status = "NO_VALID_NONIDENTICAL_CANDIDATE"
        if reporter.best_validated_groups is not None:
            emit(events, "stage_started", stage="final_independent_incumbent_validation")
            final_audit = independent_profile_audit(reporter.best_validated_groups, reference)
            if not final_audit["all_hard_constraints_pass"]:
                raise ValueError("best incumbent failed final independent audit")
            selected_ids = {group.group_id for group in reporter.best_validated_groups}
            if selected_ids == reference_ids:
                raise ValueError("identity witness cannot be emitted as a counterfactual bank")
            candidate_status = (
                "SEPARATED"
                if reporter.best_validated_objective is not None
                and reporter.best_validated_objective >= identity_objective + 1
                else "NOT_SEPARATED"
            )
            candidate_path = args.out / "cm100-best-audited-ids.jsonl"
            candidate_hash = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
            emit(
                events,
                "stage_finished",
                stage="final_independent_incumbent_validation",
                candidate_status=candidate_status,
                objective=reporter.best_validated_objective,
                identity_objective=identity_objective,
                objective_delta=(reporter.best_validated_objective - identity_objective) if reporter.best_validated_objective is not None else None,
                candidate_path=str(candidate_path),
                candidate_sha256=candidate_hash,
                audit=final_audit,
            )
        emit(
            events,
            "worker_complete",
            status=status_map.get(status_code, f"UNRECOGNIZED_{status_code}"),
            candidate_status=candidate_status,
            candidate_path=str(candidate_path) if candidate_path else None,
            candidate_sha256=candidate_hash,
            solver_seconds=solve_seconds,
            solver_objective=float(solver.objective_value) if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
            solver_bound=float(solver.best_objective_bound) if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
            best_validated_objective=reporter.best_validated_objective,
            identity_objective=identity_objective,
            pins=pins,
        )
    except BaseException as error:
        emit(events, "worker_error", error=repr(error), traceback=traceback.format_exc())
        raise


def process_peak_working_set(pid: int) -> int | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return None
            return int(counters.PeakWorkingSetSize)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def append_event(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def supervise(args: argparse.Namespace) -> dict[str, Any]:
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite baseline output directory: {args.out}")
    args.out.mkdir(parents=True, exist_ok=False)
    trace_path = args.out / "progress.jsonl"
    context = mp.get_context("spawn")
    events = context.Queue()
    payload = {
        "groups": str(args.groups), "r100": str(args.r100), "c100": str(args.c100),
        "eval": str(args.eval), "phase1_receipt": str(args.phase1_receipt), "out": str(args.out),
    }
    process = context.Process(target=worker, args=(payload, events), name="jev-v08c-phase2b-baseline")
    process.start()
    launched = time.monotonic()
    source_loaded_at: float | None = None
    active_stage = "worker_startup"
    best_obj: int | None = None
    best_bound: float | None = None
    last_improvement_at: float | None = None
    last_receipt_at = launched
    worker_result: dict[str, Any] | None = None
    worker_error: dict[str, Any] | None = None
    timed_out = False
    peak_rss = 0
    best_candidate_path: str | None = None
    best_candidate_hash: str | None = None
    best_candidate_separated: bool | None = None
    best_candidate_overlap: int | None = None
    idle_after_exit = 0
    while True:
        try:
            event = events.get(timeout=1.0)
            idle_after_exit = 0
            append_event(trace_path, event)
            if event["kind"] == "source_loaded":
                source_loaded_at = time.monotonic()
                active_stage = "source_loaded"
            elif event["kind"] == "stage_started":
                active_stage = event.get("stage", active_stage)
            elif event["kind"] == "solver_incumbent":
                active_stage = event.get("stage", active_stage)
                if event.get("best_independently_validated_objective") is not None:
                    best_obj = event["best_independently_validated_objective"]
                    best_bound = event.get("best_independently_validated_bound", best_bound)
                if event.get("best_candidate_checkpoint"):
                    best_candidate_path = event["best_candidate_checkpoint"]
                    best_candidate_hash = event.get("best_candidate_checkpoint_sha256")
                    best_candidate_separated = event.get("best_independently_validated_separated")
                    best_candidate_overlap = event.get("reference_overlap_count")
                if event.get("nonidentical") and event.get("independently_audited"):
                    last_improvement_at = time.monotonic()
            elif event["kind"] == "worker_complete":
                worker_result = event
            elif event["kind"] == "worker_error":
                worker_error = event
        except queue.Empty:
            if process.is_alive():
                idle_after_exit = 0
            else:
                idle_after_exit += 1
                if idle_after_exit >= 2:
                    break
        now = time.monotonic()
        current_rss = process_peak_working_set(process.pid) if process.is_alive() else None
        if current_rss is not None:
            peak_rss = max(peak_rss, current_rss)
        if source_loaded_at is not None and now - last_receipt_at >= 60:
            heartbeat = {
                "kind": "heartbeat",
                "utc": datetime.now(timezone.utc).isoformat(),
                "post_load_elapsed_seconds": now - source_loaded_at,
                "active_stage": active_stage,
                "best_independently_validated_objective": best_obj,
                "best_available_bound": best_bound,
                "best_candidate_checkpoint": best_candidate_path,
                "best_candidate_checkpoint_sha256": best_candidate_hash,
                "best_candidate_separated": best_candidate_separated,
                "best_candidate_reference_overlap": best_candidate_overlap,
                "seconds_since_last_validated_improvement": None if last_improvement_at is None else now - last_improvement_at,
                "peak_working_set_bytes": peak_rss or None,
            }
            append_event(trace_path, heartbeat)
            last_receipt_at = now
        if source_loaded_at is not None and now - source_loaded_at >= args.post_load_budget_seconds and process.is_alive():
            timed_out = True
            process.terminate()
            process.join(timeout=10)
            append_event(trace_path, {
                "kind": "budget_terminated",
                "utc": datetime.now(timezone.utc).isoformat(),
                "post_load_elapsed_seconds": now - source_loaded_at,
                "active_stage": active_stage,
                "best_independently_validated_objective": best_obj,
                "best_available_bound": best_bound,
                "peak_working_set_bytes": peak_rss or None,
            })
            break
    process.join()
    if timed_out:
        status = "SEARCH_EXHAUSTED"
    elif worker_error is not None:
        status = "INTERRUPTED"
    elif worker_result is not None:
        status = "SEARCH_COMPLETE"
    else:
        status = "INTERRUPTED"
    summary = {
        "experiment": "jev-information-density-v08c-phase2b-instrumented-baseline/v1",
        "status": status,
        "baseline_bank": "CM100 only; first bank attempted by the prior sealed pipeline",
        "post_load_budget_seconds": args.post_load_budget_seconds,
        "source_loaded": source_loaded_at is not None,
        "post_load_elapsed_seconds": None if source_loaded_at is None else time.monotonic() - source_loaded_at,
        "active_stage_at_stop": active_stage,
        "peak_working_set_bytes": peak_rss or None,
        "worker_exit_code": process.exitcode,
        "worker_result": worker_result,
        "worker_error": worker_error,
        "trace_path": str(trace_path),
        "model_contact": False,
        "phoenix_access": False,
        "candidate_is_counterfactual": bool(best_candidate_path or (worker_result and worker_result.get("candidate_path"))),
        "candidate_manifest_path": best_candidate_path if worker_result is None else worker_result.get("candidate_path"),
        "candidate_manifest_sha256": best_candidate_hash if worker_result is None else worker_result.get("candidate_sha256"),
        "candidate_policy_separated": best_candidate_separated if worker_result is None else worker_result.get("candidate_status") == "SEPARATED",
        "candidate_reference_overlap": best_candidate_overlap,
        "best_independently_validated_objective": best_obj,
        "best_available_bound": best_bound,
        "limitation": "A timeout is a bounded-search/runtime result, not infeasibility or evidence of low policy headroom.",
    }
    summary_path = args.out / "baseline-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": status,
        "active_stage_at_stop": active_stage,
        "post_load_elapsed_seconds": summary["post_load_elapsed_seconds"],
        "peak_working_set_bytes": peak_rss or None,
        "candidate_manifest_path": summary["candidate_manifest_path"],
        "summary": str(summary_path),
    }, ensure_ascii=False))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\full-universe-500k-v08\group-records.jsonl"))
    parser.add_argument("--r100", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-r100-group-ids.jsonl"))
    parser.add_argument("--c100", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-c100-group-ids.jsonl"))
    parser.add_argument("--eval", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-eval-group-ids.jsonl"))
    parser.add_argument("--phase1-receipt", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08c\preflight-v03\preflight.json"))
    parser.add_argument("--out", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08c\phase2b-v01\instrumented-baseline"))
    parser.add_argument("--post-load-budget-seconds", type=int, default=900)
    args = parser.parse_args()
    supervise(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
