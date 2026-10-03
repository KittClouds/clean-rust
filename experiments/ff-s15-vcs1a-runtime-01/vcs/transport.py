"""The transport harness: fit on TRAIN, freeze, apply unchanged to other splits.

    fit(train_cases) -> Frozen(vector, scalar)        # the ONLY thing that ever sees TRAIN labels; it is handed TRAIN cases and nothing else
    for each split: apply the frozen vector authority and the frozen scalar authority unchanged; record metrics and drift from TRAIN

Drift is measured for both policies so the question "does region geometry transport better than an absolute scalar threshold?" has a direct answer; the split's own hindsight-best scalar is reported as a (scalar-favouring) reference.
Nothing here binds data. A FIXTURE schema marks every output as no evidence. A FROZEN schema additionally requires the hash of a preregistration file, so a scientific run cannot be produced without one."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import harness as H
from .authority import Authority
from .canon import NotBound, VcsError
from .scalar import ScalarAuthority
from .schema import Schema


@dataclass(frozen=True)
class Frozen:
    vector: Authority
    scalar: ScalarAuthority
    scalar_src: object   # one scalar source {score, at_or_above, below}, or a list of them (a family): what the hindsight reference sweeps


def evidence_grade(schema: Schema, preregistration: str | Path | None) -> dict:
    if schema.fixture:
        return {"grade": "NONE (fixture schema)", "preregistration_sha256": None}
    if preregistration is None or not Path(preregistration).is_file():
        raise NotBound("a FROZEN schema may only be scored under a preregistration file; none was given")
    circular = sorted(n for n, c in schema.coords.items() if c.audit["target_derived"] or c.audit["downstream_of_target"])
    if circular:
        raise NotBound(f"coordinates {circular} are declared derived from, or downstream of, the target: a region over them rediscovers the label-generation function, not geometry")
    shared = sorted(n for n, c in schema.coords.items() if c.audit["shared_generator"])
    return {"grade": "preregistered run", "preregistration_sha256": hashlib.sha256(Path(preregistration).read_bytes()).hexdigest(), "shared_generator_coordinates": shared}


def vs_transported_scalar(vm: dict, sm: dict) -> dict:
    """The vector policy against the ONE scalar point frozen from TRAIN. `vector_weakly_dominates` = no worse on harm and cost and no less coverage; `strict` adds at least one strict improvement."""
    d = {k: vm[k] - sm[k] for k in ("harm", "cost", "coverage")}
    weak = d["harm"] <= 1e-12 and d["cost"] <= 1e-12 and d["coverage"] >= -1e-12
    return {"diff_vector_minus_scalar": d, "vector_weakly_dominates": weak, "vector_strictly_dominates": weak and (d["harm"] < -1e-12 or d["cost"] < -1e-12 or d["coverage"] > 1e-12)}


def run_transport(*, schema: Schema, fit, splits: dict, train: str = "TRAIN", preregistration=None, resamples: int = 1000, seed: str = "vcs1a") -> dict:
    if train not in splits:
        raise VcsError(f"splits must include {train}")
    grade = evidence_grade(schema, preregistration)
    for name, cases in splits.items():
        for c in cases:
            H.check_case(schema, c)
    frozen = fit(list(splits[train]))
    if not isinstance(frozen, Frozen):
        raise VcsError("fit must return Frozen(vector, scalar, scalar_src)")
    ids = (frozen.vector.authority_id, frozen.scalar.authority_id)
    report: dict = {"evidence": grade, "train": train, "frozen": {"vector_authority_id": ids[0], "scalar_authority_id": ids[1]}, "splits": {}}
    base = None
    for name in [train] + [s for s in splits if s != train]:
        cases = splits[name]
        v_outs, _ = H.run_policy(H.vector_decider(frozen.vector), cases)
        s_outs, _ = H.run_policy(H.scalar_decider(frozen.scalar), cases)
        vm, sm = H.metrics(v_outs), H.metrics(s_outs)
        sweep = H.build_sweeps(schema, frozen.scalar_src, cases)
        row = {"n": len(cases), "vector": vm, "scalar_frozen": sm, "vs_transported_scalar": vs_transported_scalar(vm, sm),
               "hindsight_scalar_reference": H.matched(vm, sweep.points()),
               "bootstrap_vs_hindsight_scalar": H.paired_bootstrap(v_outs, sweep, resamples=resamples, seed=f"{seed}|{name}")}
        if base is None:
            base = {"vector": vm, "scalar": sm}
        else:
            row["drift_from_train"] = {p: {k: row_m[k] - base[p][k] for k in ("harm", "coverage", "cost")} for p, row_m in (("vector", vm), ("scalar", sm))}
        report["splits"][name] = row
        if (frozen.vector.authority_id, frozen.scalar.authority_id) != ids:
            raise VcsError("a frozen authority changed while it was being applied")
    return report
