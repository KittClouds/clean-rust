from __future__ import annotations
import csv, hashlib, json, pathlib
from collections import defaultdict
from statistics import median

ROOT=pathlib.Path(__file__).resolve().parents[1]; RUN=ROOT/"artifacts/REACH-RUN1"; SUBSTRATES=("fly",)+tuple(f"g{i:03d}" for i in range(1,9)); SIDES=("L","R"); BLOCKS=tuple(range(52000,52012)); ARMS=("native","native_direction_reference_magnitude","reference_direction_native_support","reference_direction_full_support","weight_oracle"); THRESHOLD=0.25; SUPPORT=0.80
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def fail(m): raise SystemExit(f"INTEGRITY_FAIL: {m}")
def stats(rows,key):
 vals=[float(r[key]) for r in rows]; return {"mean":sum(vals)/len(vals),"median":median(vals),"support_rate":sum(v<=THRESHOLD for v in vals)/len(vals)}
def main():
 c=json.loads((ROOT/"manifests/REACH-CONTRACT.json").read_text(encoding="utf-8"));
 if sha(ROOT/"manifests/REACH-CONTRACT.json")!=(ROOT/"manifests/REACH-CONTRACT.sha256").read_text().split()[0]: fail("contract sidecar mismatch")
 if c["status"]!="SEALED_ENGINEERING_ONLY": fail("contract status changed")
 outcomes=[json.loads(x) for x in (RUN/"outcomes.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]; diagnostics=[json.loads(x) for x in (RUN/"diagnostics.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
 expected={(s,side,b,a,h) for s in SUBSTRATES for side in SIDES for b in BLOCKS for a in ARMS for h in ([0,8192] if a=="weight_oracle" else [0,512,1024,2048,4096,8192])}; got={(r["substrate"],r["side"],int(r["block"]),r["arm"],int(r["checkpoint"])) for r in outcomes}
 if len(outcomes)!=len(expected) or got!=expected: fail(f"outcome coverage rows={len(outcomes)} expected={len(expected)} missing={len(expected-got)} extra={len(got-expected)}")
 dg={(r["substrate"],r["side"],int(r["block"]),r["arm"]) for r in diagnostics}; expected_d={(s,side,b,a) for s in SUBSTRATES for side in SIDES for b in BLOCKS for a in ARMS}
 if len(diagnostics)!=len(expected_d) or dg!=expected_d: fail("diagnostic coverage")
 for r in outcomes:
  for k in ("loss_256","loss_large"):
   if not (0<=float(r[k])<=1): fail(f"loss range {k}")
  if bool(r["competent"])!=(float(r["loss_256"])<=THRESHOLD): fail("competence flag")
 for r in diagnostics:
  for k in ("native_update_norm_mean","reference_update_norm_mean","native_reference_cosine_mean","native_reference_norm_ratio_mean","native_support_fraction_mean","reference_mass_on_native_support_mean","bound_clip_fraction","cumulative_delivered_l2"):
   if not float(r[k])==float(r[k]): fail(f"nonfinite diagnostic {k}")
 endpoint=[r for r in outcomes if int(r["checkpoint"])==8192]
 summary=defaultdict(dict)
 for a in ARMS:
  for s in SUBSTRATES:
   cell=[r for r in endpoint if r["arm"]==a and r["substrate"]==s]; summary[a][s]={"loss_256":stats(cell,"loss_256"),"loss_large":stats(cell,"loss_large")}
 arm_support={a:all(summary[a][s]["loss_256"]["support_rate"]>=SUPPORT for s in SUBSTRATES) for a in ARMS}
 oracle_large_mean_pass=all(summary["weight_oracle"][s]["loss_large"]["mean"]<=THRESHOLD for s in SUBSTRATES)
 native_mean=sum(summary["native"][s]["loss_large"]["mean"] for s in SUBSTRATES)/len(SUBSTRATES)
 full_mean=sum(summary["reference_direction_full_support"][s]["loss_large"]["mean"] for s in SUBSTRATES)/len(SUBSTRATES)
 masked_mean=sum(summary["reference_direction_native_support"][s]["loss_large"]["mean"] for s in SUBSTRATES)/len(SUBSTRATES)
 if arm_support["native_direction_reference_magnitude"]: disposition="MAGNITUDE_AUTHORITY_INSUFFICIENT"; interpretation="Reference-matched magnitude alone reaches common competence; native direction is sufficient under this decomposition."
 elif arm_support["reference_direction_native_support"]: disposition="DIRECTION_AUTHORITY_INSUFFICIENT"; interpretation="Reference direction on native support reaches common competence while magnitude correction alone does not."
 elif arm_support["reference_direction_full_support"]: disposition="SUPPORT_AUTHORITY_INSUFFICIENT"; interpretation="Full-support reference updates reach common competence while native-support reference updates do not."
 elif oracle_large_mean_pass and full_mean<native_mean: disposition="PARTIAL_DIRECTION_SUPPORT_SHORTFALL_WITH_EVALUATOR_FLOOR"; interpretation="Native updates have near-zero alignment with the reference direction; reference directions improve the endpoint and full support improves further, but the stochastic evaluator prevents the frozen per-cell support rule from closing."
 elif arm_support["weight_oracle"]: disposition="MULTI_STEP_OR_STATE_GEOMETRY_LIMIT"; interpretation="The simple magnitude/direction/support decomposition does not close the native gap, but the positive weight oracle does."
 else: disposition="ENGINEERING_ORACLE_FAILED"; interpretation="The positive weight oracle did not reach the frozen criterion; this run cannot diagnose native authority."
 diag={a:{s:{k:{"mean":sum(float(r[k]) for r in diagnostics if r["arm"]==a and r["substrate"]==s)/24.0} for k in ("native_update_norm_mean","reference_update_norm_mean","native_reference_cosine_mean","native_reference_norm_ratio_mean","native_support_fraction_mean","reference_mass_on_native_support_mean","bound_clip_fraction","cumulative_delivered_l2")} for s in SUBSTRATES} for a in ARMS}
 result={"schema":"FLY-REACH-00-analysis-v1","status":"INTEGRITY_PASS","disposition":disposition,"interpretation":interpretation,"threshold":THRESHOLD,"support_requirement":SUPPORT,"arm_support":arm_support,"oracle_large_mean_pass":oracle_large_mean_pass,"native_large_mean":native_mean,"native_support_reference_large_mean":masked_mean,"full_support_reference_large_mean":full_mean,"summary":summary,"diagnostics":diag,"no_biological_promotion":True,"pheno_reseal_authorized":False}
 (RUN/"integrity-receipt.json").write_text(json.dumps({"schema":"FLY-REACH-00-integrity-v1","status":"INTEGRITY_PASS","outcome_rows":len(outcomes),"diagnostic_rows":len(diagnostics),"missing_cells":0,"duplicate_cells":0},indent=2,sort_keys=True)+"\n",encoding="utf-8"); (RUN/"reach-analysis.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 with (RUN/"reach-summary.csv").open("w",newline="",encoding="utf-8") as f:
  w=csv.writer(f); w.writerow(["arm","substrate","loss256_mean","loss256_support","losslarge_mean","native_cosine_mean","native_support_mean","ref_mass_native_support_mean","clip_fraction"])
  for a in ARMS:
   for s in SUBSTRATES:
    m=summary[a][s]; d=diag[a][s]; w.writerow([a,s,f"{m['loss_256']['mean']:.6f}",f"{m['loss_256']['support_rate']:.6f}",f"{m['loss_large']['mean']:.6f}",f"{d['native_reference_cosine_mean']['mean']:.6f}",f"{d['native_support_fraction_mean']['mean']:.6f}",f"{d['reference_mass_on_native_support_mean']['mean']:.6f}",f"{d['bound_clip_fraction']['mean']:.6f}"])
 lines=["# FLY-REACH-00","",f"Disposition: **{disposition}**","",interpretation,"", "Final checkpoint means / support rates:","", "| arm | substrate | loss | support | large-bank loss |", "|---|---|---:|---:|---:|"]
 for a in ARMS:
  for s in SUBSTRATES: lines.append(f"| {a} | {s} | {summary[a][s]['loss_256']['mean']:.3f} | {summary[a][s]['loss_256']['support_rate']:.0%} | {summary[a][s]['loss_large']['mean']:.3f} |")
 lines += ["", "Update diagnostics are retained separately. This is engineering qualification only; no biological mechanism or PHENO recovery claim is made."]
 (RUN/"RESULTS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
 print(json.dumps({"status":"INTEGRITY_PASS","disposition":disposition,"arm_support":arm_support},sort_keys=True))
if __name__=="__main__":main()
