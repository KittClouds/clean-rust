"""Outcome-blind analysis contract for FLY-PHENO-00.

The functions operate on already collected rows but are exercised here only
with synthetic fixture data. They enforce one cell per arm and compute the
predeclared B, C, D, A, and R quantities without opening a measured run.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable


PRIMARY_SEVERITY = 0.10
PRIMARY_FAMILY = "uniform_random"
RECOVERY_ENDPOINT = 512
EPSILON_D = 0.015625


@dataclass(frozen=True)
class Outcome:
    substrate: str
    graph: str
    block: int
    lesion_m: int
    family: str
    severity: float
    arm: str
    checkpoint: int
    loss: float
    competent: bool = True


def _key(row: Outcome) -> tuple:
    return (
        row.substrate,
        row.graph,
        row.block,
        row.lesion_m,
        row.family,
        round(row.severity, 8),
        row.checkpoint,
    )


def validate_rows(rows: Iterable[Outcome]) -> list[Outcome]:
    rows = list(rows)
    seen: set[tuple] = set()
    for row in rows:
        if row.arm not in {"adaptive", "weight_frozen"}:
            raise ValueError("unexpected arm")
        if row.loss != row.loss or row.loss < 0:
            raise ValueError("non-finite or negative loss")
        key = _key(row) + (row.arm,)
        if key in seen:
            raise ValueError("duplicate outcome cell")
        seen.add(key)
    paired = defaultdict(set)
    for row in rows:
        paired[_key(row)].add(row.arm)
    if any(arms != {"adaptive", "weight_frozen"} for arms in paired.values()):
        raise ValueError("missing or extra paired arm")
    return rows


def _loss(rows: list[Outcome], *, substrate: str, graph: str, block: int, m: int, family: str, severity: float, arm: str, checkpoint: int) -> float:
    matches = [
        row.loss for row in rows
        if row.substrate == substrate and row.graph == graph and row.block == block
        and row.lesion_m == m and row.family == family and abs(row.severity - severity) < 1e-8
        and row.arm == arm and row.checkpoint == checkpoint
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one loss, found {len(matches)}")
    return matches[0]


def compute_b(rows: Iterable[Outcome], *, substrate: str, graph: str, block: int, m: int, family: str, severity: float) -> float:
    rows = validate_rows(rows)
    return _loss(rows, substrate=substrate, graph=graph, block=block, m=m, family=family, severity=severity, arm="weight_frozen", checkpoint=RECOVERY_ENDPOINT) - _loss(rows, substrate=substrate, graph=graph, block=block, m=m, family=family, severity=severity, arm="adaptive", checkpoint=RECOVERY_ENDPOINT)


def compute_c(rows: Iterable[Outcome], *, substrate: str, graph: str, block: int, m: int, family: str, severity: float) -> float:
    rows = validate_rows(rows)
    damaged = compute_b(rows, substrate=substrate, graph=graph, block=block, m=m, family=family, severity=severity)
    sham = compute_b(rows, substrate=substrate, graph=graph, block=block, m=0, family="sham", severity=0.0)
    return damaged - sham


def compute_d_a_r(rows: Iterable[Outcome], *, substrate: str, graph: str, block: int, m: int, family: str, severity: float) -> dict[int, tuple[float, float, float | None]]:
    rows = validate_rows(rows)
    pre = _loss(rows, substrate=substrate, graph=graph, block=block, m=0, family="sham", severity=0.0, arm="adaptive", checkpoint=-1)
    post = _loss(rows, substrate=substrate, graph=graph, block=block, m=m, family=family, severity=severity, arm="adaptive", checkpoint=0)
    damage = post - pre
    out: dict[int, tuple[float, float, float | None]] = {}
    for checkpoint in sorted({row.checkpoint for row in rows if row.checkpoint >= 0}):
        current = _loss(rows, substrate=substrate, graph=graph, block=block, m=m, family=family, severity=severity, arm="adaptive", checkpoint=checkpoint)
        absolute = post - current
        ratio = absolute / damage if damage >= EPSILON_D else None
        out[checkpoint] = (damage, absolute, ratio)
    return out


def validate_competence_support(flags: dict[tuple[str, int], bool], *, min_complete: int = 8) -> set[int]:
    substrates = sorted({substrate for substrate, _block in flags})
    blocks = sorted({block for _substrate, block in flags})
    complete = {block for block in blocks if all(flags.get((substrate, block), False) for substrate in substrates)}
    if len(complete) < min_complete:
        raise ValueError("PRIMARY_NOT_EVALUABLE: insufficient global competence support")
    return complete
