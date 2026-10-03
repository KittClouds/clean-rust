"""Fixture-only tests for the sealed FLY-PHENO analysis contract."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
from contract import Outcome, compute_b, compute_c, compute_d_a_r, validate_competence_support, validate_rows  # noqa: E402


def fixture() -> list[Outcome]:
    rows: list[Outcome] = []
    specs = [("fly", "fly"), ("null", "g001")]
    for substrate, graph in specs:
        for checkpoint in [-1, 0, 512]:
            for family, m, severity in [("sham", 0, 0.0), ("uniform_random", 1, 0.10)]:
                for arm in ("adaptive", "weight_frozen"):
                    base = 0.20 if checkpoint == -1 else 0.55 if checkpoint == 0 else 0.30
                    if family == "uniform_random":
                        base += 0.15 if checkpoint == 0 else 0.05
                    if arm == "weight_frozen":
                        base += 0.04
                    rows.append(Outcome(substrate, graph, 12000, m, family, severity, arm, checkpoint, base))
    return rows


def assert_rejects(mutated: list[Outcome]) -> None:
    try:
        validate_rows(mutated)
    except ValueError:
        return
    raise AssertionError("fixture mutation was accepted")


def main() -> None:
    rows = fixture()
    validate_rows(rows)
    assert abs(compute_b(rows, substrate="fly", graph="fly", block=12000, m=1, family="uniform_random", severity=0.10) - 0.04) < 1e-12
    assert abs(compute_c(rows, substrate="fly", graph="fly", block=12000, m=1, family="uniform_random", severity=0.10) - 0.0) < 1e-12
    trajectory = compute_d_a_r(rows, substrate="fly", graph="fly", block=12000, m=1, family="uniform_random", severity=0.10)
    assert trajectory[0][2] == 0.0
    missing = copy.copy(rows)
    missing.pop()
    assert_rejects(missing)
    duplicate = copy.copy(rows)
    duplicate.append(rows[0])
    assert_rejects(duplicate)
    extra = copy.copy(rows)
    extra.append(Outcome("fly", "fly", 12000, 99, "uniform_random", 0.20, "adaptive", 512, 0.1))
    assert_rejects(extra)
    wrong_pair = copy.copy(rows)
    wrong_pair[0] = Outcome(**{**wrong_pair[0].__dict__, "arm": "unexpected"})
    assert_rejects(wrong_pair)
    flags = {(substrate, block): True for substrate in ("fly", "g001") for block in range(12000, 12008)}
    assert validate_competence_support(flags) == set(range(12000, 12008))
    try:
        validate_competence_support({("fly", 12000): True, ("g001", 12000): False}, min_complete=1)
    except ValueError:
        pass
    else:
        raise AssertionError("insufficient competence support was accepted")
    print("analysis fixture contract: PASS")


if __name__ == "__main__":
    main()
