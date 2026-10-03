from __future__ import annotations
import csv, hashlib, json, pathlib
from collections import defaultdict
from statistics import median

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts/QREAL-RUN1"
TASKS = ("four_cue", "two_cue_sanity")
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1,9))
SIDES = ("L", "R")
BLOCKS = tuple(range(42000,42012))
THRESHOLD = 0.25
SUPPORT = 0.80

def sha(p: pathlib.Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def fail(m: str) -> None: raise SystemExit(f"INTEGRITY_FAIL: {m}")

def summarize(rows: list[dict], task: str) -> dict:
    endpoint=[r for r in rows if r["task"]==task]
    out={}
    for s in SUBSTRATES:
        cell=[r for r in endpoint if r["substrate"]==s]
        metrics={}
        for key in ("representation_error","weight_oracle_expected_error","weight_oracle_error_256","weight_oracle_error_large","native_error_256","native_error_large"):
            values=[float(r[key]) for r in cell]
            metrics[key]={"mean":sum(values)/len(values),"median":median(values),"support_rate":sum(v<=THRESHOLD for v in values)/len(values)}
        out[s]=metrics
    return out

def main() -> None:
    contract=json.loads((ROOT/"manifests/QREAL-CONTRACT.json").read_text(encoding="utf-8"))
    if sha(ROOT/"manifests/QREAL-CONTRACT.json") != (ROOT/"manifests/QREAL-CONTRACT.sha256").read_text().split()[0]: fail("contract sidecar mismatch")
    if contract["status"]!="SEALED_QUALIFICATION_ONLY": fail("contract status changed")
    rows=[json.loads(x) for x in (RUN/"diagnostics.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    expected={(t,s,side,b) for t in TASKS for s in SUBSTRATES for side in SIDES for b in BLOCKS}
    got={(r["task"],r["substrate"],r["side"],int(r["block"])) for r in rows}
    if len(rows)!=len(expected) or got!=expected: fail(f"coverage rows={len(rows)} expected={len(expected)} missing={len(expected-got)} extra={len(got-expected)}")
    if len(got)!=len(rows): fail("duplicate cells")
    if any(not r["weight_oracle_finite"] or not r["native_finite"] for r in rows): fail("nonfinite diagnostics")
    for r in rows:
        for key in ("representation_error","weight_oracle_expected_error","weight_oracle_error_256","weight_oracle_error_large","native_error_256","native_error_large"):
            if not (0.0<=float(r[key])<=1.0): fail(f"bad metric {key}")
    summary={t:summarize(rows,t) for t in TASKS}
    primary=summary["four_cue"]
    rep_pass=all(primary[s]["representation_error"]["support_rate"]>=SUPPORT for s in SUBSTRATES)
    weight_pass=rep_pass and all(primary[s]["weight_oracle_expected_error"]["support_rate"]>=SUPPORT for s in SUBSTRATES)
    native_pass=weight_pass and all(primary[s]["native_error_256"]["support_rate"]>=SUPPORT for s in SUBSTRATES)
    if not rep_pass:
        disposition="REPRESENTATION_CEILING_FAIL"; interpretation="The frozen KC->MB cue representation did not support the competence criterion for every substrate."
    elif not weight_pass:
        disposition="WEIGHT_SPACE_CEILING_FAIL"; interpretation="The representation passed, but bounded optimization of KC->MB weights did not support competence for every substrate."
    elif not native_pass:
        disposition="NATIVE_ADAPTIVE_REACHABILITY_PROBLEM"; interpretation="Representation and weight-space oracles passed, but the native adaptive rule did not reach competence under the fixed contract."
    else:
        disposition="NATIVE_LEARNING_QUALIFIED"; interpretation="All three levels reached the frozen competence support rule on the primary task; PHENO may be reconsidered only through a new measured seal."
    result={"schema":"FLY-PHENO-00-v0.4-QREAL-analysis-v1","status":"INTEGRITY_PASS","disposition":disposition,"interpretation":interpretation,"threshold":THRESHOLD,"support_requirement":SUPPORT,"primary_task":"four_cue","sanity_task":"two_cue_sanity","representation_pass":rep_pass,"weight_space_pass":weight_pass,"native_pass":native_pass,"summary":summary,"measured_pheno_reseal_authorized":False,"native_reachability_earned":disposition=="NATIVE_ADAPTIVE_REACHABILITY_PROBLEM"}
    (RUN/"integrity-receipt.json").write_text(json.dumps({"schema":"FLY-PHENO-00-v0.4-QREAL-integrity-v1","status":"INTEGRITY_PASS","rows":len(rows),"unique_cells":len(got),"missing_cells":0,"duplicate_cells":0,"nonfinite_rows":0},indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (RUN/"qreal-analysis.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    with (RUN/"qreal-summary.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["task","substrate","representation_mean","representation_support","weight_expected_mean","weight_expected_support","weight_large_mean","native_256_mean","native_256_support","native_large_mean"])
        for t in TASKS:
            for s in SUBSTRATES:
                m=summary[t][s]; w.writerow([t,s,f"{m['representation_error']['mean']:.6f}",f"{m['representation_error']['support_rate']:.6f}",f"{m['weight_oracle_expected_error']['mean']:.6f}",f"{m['weight_oracle_expected_error']['support_rate']:.6f}",f"{m['weight_oracle_error_large']['mean']:.6f}",f"{m['native_error_256']['mean']:.6f}",f"{m['native_error_256']['support_rate']:.6f}",f"{m['native_error_large']['mean']:.6f}"])
    md=["# FLY-PHENO-00-v0.4-QREAL","",f"Disposition: **{disposition}**","",interpretation,"", "Primary four-cue table: mean errors / support rates at the frozen 0.25 criterion.","", "| substrate | representation | weight oracle | native 256 | native large |", "|---|---:|---:|---:|---:|"]
    for s in SUBSTRATES:
        m=primary[s]; md.append(f"| {s} | {m['representation_error']['mean']:.3f} / {m['representation_error']['support_rate']:.0%} | {m['weight_oracle_expected_error']['mean']:.3f} / {m['weight_oracle_expected_error']['support_rate']:.0%} | {m['native_error_256']['mean']:.3f} / {m['native_error_256']['support_rate']:.0%} | {m['native_error_large']['mean']:.3f} |")
    md += ["", "The two-cue sanity task is reported separately. No lesions, recovery comparisons, or PHENO inference were run."]
    (RUN/"RESULTS.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    print(json.dumps({"status":"INTEGRITY_PASS","disposition":disposition,"representation_pass":rep_pass,"weight_space_pass":weight_pass,"native_pass":native_pass},sort_keys=True))

if __name__=="__main__": main()
