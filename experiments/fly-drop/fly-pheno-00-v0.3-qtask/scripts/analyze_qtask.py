from __future__ import annotations
import csv
import hashlib
import json
import pathlib
from collections import defaultdict
from statistics import median

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts" / "QTASK-RUN1"
RUNG_ORDER = ("T1", "T2", "T3", "T4")
RUNG_CUES = {"T1": 16, "T2": 12, "T3": 8, "T4": 4}
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
SIDES = ("L", "R")
BLOCKS = tuple(range(32000, 32012))
HORIZON = 8192
THRESHOLD = 0.25
MARGIN = 0.20
SUPPORT = 0.80

def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def fail(msg: str) -> None: raise SystemExit(f"INTEGRITY_FAIL: {msg}")

def main() -> None:
    contract = json.loads((ROOT / "manifests/QTASK-CONTRACT.json").read_text(encoding="utf-8"))
    if sha(ROOT / "manifests/QTASK-CONTRACT.json") != (ROOT / "manifests/QTASK-CONTRACT.sha256").read_text().split()[0]: fail("contract sidecar mismatch")
    if contract["status"] != "SEALED_QUALIFICATION_ONLY": fail("contract status changed")
    rows = [json.loads(x) for x in (RUN / "task-frontier.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    expected = {(r, s, side, b, h) for r in RUNG_ORDER for s in SUBSTRATES for side in SIDES for b in BLOCKS for h in (512,1024,2048,4096,8192)}
    got = {(x["rung"], x["substrate"], x["side"], int(x["block"]), int(x["horizon"])) for x in rows}
    if len(rows) != len(expected) or got != expected: fail(f"coverage rows={len(rows)} expected={len(expected)} missing={len(expected-got)} extra={len(got-expected)}")
    if len(got) != len(rows): fail("duplicate cells")
    if any(not x["finite"] or not (0.0 <= float(x["loss"]) <= 1.0) for x in rows): fail("nonfinite/out-of-range loss")
    if any(bool(x["competent"]) != (float(x["loss"]) <= THRESHOLD) for x in rows): fail("competence flag mismatch")
    endpoint = [x for x in rows if int(x["horizon"]) == HORIZON]
    rates: dict[str, dict[str, float]] = defaultdict(dict)
    medians: dict[str, dict[str, float]] = defaultdict(dict)
    means: dict[str, dict[str, float]] = defaultdict(dict)
    for rung in RUNG_ORDER:
        for s in SUBSTRATES:
            cell = [x for x in endpoint if x["rung"] == rung and x["substrate"] == s]
            rates[rung][s] = sum(bool(x["competent"]) for x in cell) / len(cell)
            medians[rung][s] = median(float(x["loss"]) for x in cell)
            means[rung][s] = sum(float(x["loss"]) for x in cell) / len(cell)
    passes = {r: all(rates[r][s] >= SUPPORT and medians[r][s] <= MARGIN for s in SUBSTRATES) for r in RUNG_ORDER}
    selected = next((r for r in RUNG_ORDER if passes[r]), None)
    any_substrate_pass = any(any(rates[r][s] >= SUPPORT and medians[r][s] <= MARGIN for s in SUBSTRATES) for r in RUNG_ORDER)
    if selected:
        disposition = "A_TASK_RUNG_QUALIFIED"; interpretation = "The hardest prospective cue-count rung satisfied competence support and the median safety margin for every substrate."
    elif any_substrate_pass:
        disposition = "C_SUBSTRATE_DEPENDENT_TASK_ATTAINABILITY"; interpretation = "At least one substrate met the task support rule, but no common rung met it for every substrate."
    else:
        disposition = "B_NO_LADDER_RUNG_REACHES_SUPPORT"; interpretation = "No prospective ladder rung reached the frozen support and safety-margin rule across the substrate set."
    result = {"schema":"FLY-PHENO-00-v0.3-QTASK-analysis-v1", "status":"INTEGRITY_PASS", "disposition":disposition, "interpretation":interpretation, "horizon":HORIZON, "threshold":THRESHOLD, "margin_threshold":MARGIN, "support_requirement":SUPPORT, "rung_cues":RUNG_CUES, "selected_rung":selected, "passes_by_rung":passes, "competence_rate_by_rung_substrate":{r:{s:rates[r][s] for s in SUBSTRATES} for r in RUNG_ORDER}, "median_loss_by_rung_substrate":{r:{s:medians[r][s] for s in SUBSTRATES} for r in RUNG_ORDER}, "mean_loss_by_rung_substrate":{r:{s:means[r][s] for s in SUBSTRATES} for r in RUNG_ORDER}, "measured_pheno_reseal_authorized":False}
    (RUN / "integrity-receipt.json").write_text(json.dumps({"schema":"FLY-PHENO-00-v0.3-QTASK-integrity-v1", "status":"INTEGRITY_PASS", "rows":len(rows), "unique_cells":len(got), "missing_cells":0, "duplicate_cells":0, "nonfinite_rows":0}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RUN / "task-analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (RUN / "task-summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["rung", "cues", "substrate", "competence_rate", "median_loss", "mean_loss"])
        for r in RUNG_ORDER:
            for s in SUBSTRATES: w.writerow([r, RUNG_CUES[r], s, f"{rates[r][s]:.6f}", f"{medians[r][s]:.9f}", f"{means[r][s]:.9f}"])
    md = ["# FLY-PHENO-00-v0.3-QTASK", "", f"Disposition: **{disposition}**", "", interpretation, "", f"Selection rule: hardest rung with >=80% competent cells and median loss <= {MARGIN} for every substrate at {HORIZON} trials.", "", "| rung | cues | " + " | ".join(SUBSTRATES) + " |", "|---|---|" + "---|" * len(SUBSTRATES)]
    for r in RUNG_ORDER: md.append("| " + r + " | " + str(RUNG_CUES[r]) + " | " + " | ".join(f"{rates[r][s]:.1%}/{medians[r][s]:.3f}" for s in SUBSTRATES) + " |")
    md += ["", "Each cell shows competence rate / median loss. No lesion, recovery, or adaptive/frozen comparison was run."]
    (RUN / "RESULTS.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"status":"INTEGRITY_PASS", "disposition":disposition, "selected_rung":selected, "passes_by_rung":passes}, sort_keys=True))

if __name__ == "__main__": main()
