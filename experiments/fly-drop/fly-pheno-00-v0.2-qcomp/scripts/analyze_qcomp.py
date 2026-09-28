"""Independent, outcome-opened QCOMP integrity and frontier readout."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts" / "QCOMP-RUN1"
HORIZONS = (512, 1024, 2048, 4096, 8192)
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
SIDES = ("L", "R")
BLOCKS = tuple(range(22000, 22012))
THRESHOLD = 0.25
REQUIREMENT = 0.80


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fail(msg: str) -> None:
    raise SystemExit(f"INTEGRITY_FAIL: {msg}")


def main() -> None:
    contract = json.loads((ROOT / "manifests/QCOMP-CONTRACT.json").read_text(encoding="utf-8"))
    sidecar = (ROOT / "manifests/QCOMP-CONTRACT.sha256").read_text(encoding="utf-8").split()[0]
    if sha(ROOT / "manifests/QCOMP-CONTRACT.json") != sidecar:
        fail("contract sidecar mismatch")
    if contract["status"] != "SEALED_QUALIFICATION_ONLY":
        fail("contract status changed")
    path = RUN / "competence-frontier.jsonl"
    if not path.exists(): fail("frontier missing")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = {(s, side, b, h) for s in SUBSTRATES for side in SIDES for b in BLOCKS for h in HORIZONS}
    got = {(r["substrate"], r["side"], int(r["block"]), int(r["horizon"])) for r in rows}
    if len(rows) != len(expected) or got != expected:
        fail(f"coverage rows={len(rows)} expected={len(expected)} missing={len(expected-got)} extra={len(got-expected)}")
    if len(got) != len(rows): fail("duplicate cells")
    if any(not r["finite"] or not (float(r["loss"]) >= 0.0 and float(r["loss"]) <= 1.0) for r in rows):
        fail("nonfinite or out-of-range loss")
    if any(bool(r["competent"]) != (float(r["loss"]) <= THRESHOLD) for r in rows):
        fail("competence flag mismatch")
    receipt = json.loads((RUN / "collection-receipt.json").read_text(encoding="utf-8"))
    if receipt["completed_blocks"] != 216 or receipt["expected_rows"] != 1080:
        fail("collection receipt cardinality")

    rates = defaultdict(dict)
    losses = defaultdict(dict)
    for substrate in SUBSTRATES:
        for horizon in HORIZONS:
            subset = [r for r in rows if r["substrate"] == substrate and int(r["horizon"]) == horizon]
            rates[substrate][horizon] = sum(bool(r["competent"]) for r in subset) / len(subset)
            losses[substrate][horizon] = sum(float(r["loss"]) for r in subset) / len(subset)
    common = [h for h in HORIZONS if all(rates[s][h] >= REQUIREMENT for s in SUBSTRATES)]
    max_rate = {s: max(rates[s].values()) for s in SUBSTRATES}
    if common:
        disposition = "A_COMPETENCE_ESTABLISHED"
        status_text = "At least 80% of fresh qualification blocks were competent for every substrate at a common fixed horizon."
    elif max(max_rate.values()) < REQUIREMENT:
        disposition = "B_HOST_TASK_MISMATCH"
        status_text = "The unchanged host/task improved or plateaued without reaching the predeclared 80% support requirement."
    else:
        disposition = "C_SUBSTRATE_COMPETENCE_DIFFERENTIAL"
        status_text = "Some substrates reached the support requirement but competence attainment was not common across substrate classes."
    result = {
        "schema": "FLY-PHENO-00-v0.2-QCOMP-analysis-v1",
        "status": "INTEGRITY_PASS",
        "disposition": disposition,
        "interpretation": status_text,
        "threshold": THRESHOLD,
        "competence_rate_requirement": REQUIREMENT,
        "horizons": list(HORIZONS),
        "rows": len(rows), "unique_cells": len(got), "missing_cells": 0, "duplicate_cells": 0,
        "competence_rate_by_substrate": {s: {str(h): rates[s][h] for h in HORIZONS} for s in SUBSTRATES},
        "mean_loss_by_substrate": {s: {str(h): losses[s][h] for h in HORIZONS} for s in SUBSTRATES},
        "common_supported_horizons": common,
        "max_rate_by_substrate": max_rate,
        "scientific_pheno_execution_authorized": False,
        "measured_v0_2_reseal_authorized": bool(common),
    }
    (RUN / "integrity-receipt.json").write_text(json.dumps({"schema":"FLY-PHENO-00-v0.2-QCOMP-integrity-v1", "status":"INTEGRITY_PASS", "rows":len(rows), "unique_cells":len(got), "missing_cells":0, "duplicate_cells":0, "nonfinite_rows":0}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RUN / "frontier-analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (RUN / "frontier-summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f); writer.writerow(["substrate", *HORIZONS])
        for s in SUBSTRATES: writer.writerow([s, *[f"{rates[s][h]:.6f}" for h in HORIZONS]])
    md = ["# FLY-PHENO-00-v0.2-QCOMP", "", f"Disposition: **{disposition}**", "", status_text, "", f"Competence threshold: `{THRESHOLD}`; support requirement: `{REQUIREMENT:.0%}` per substrate at a common fixed horizon.", "", "## Competence rates", "", "| substrate | " + " | ".join(map(str, HORIZONS)) + " |", "|---|" + "---|" * len(HORIZONS)]
    for s in SUBSTRATES: md.append("| " + s + " | " + " | ".join(f"{rates[s][h]:.1%}" for h in HORIZONS) + " |")
    md += ["", "No lesions, recovery arms, adaptive/frozen comparison, or PHENO estimand was run in this namespace."]
    (RUN / "RESULTS.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"status":"INTEGRITY_PASS", "disposition":disposition, "common_supported_horizons":common, "max_rate_by_substrate":max_rate}, sort_keys=True))


if __name__ == "__main__":
    main()
