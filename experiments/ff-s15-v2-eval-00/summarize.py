import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
r = json.load(open(r"results/v2-0-receipt.json", encoding="utf-8"))

print("=== per-baseline macro-F1 on DEV (50,000 rows) ===")
print("%-22s %7s %7s %7s %7s %7s   %-8s %-8s %s" %
      ("target", "B1", "B2", "B3", "B4", "B5", "best", "headroom", "CUE"))
for k, v in r["targets"].items():
    b = v["baselines"]
    print("%-22s %7.4f %7.4f %7.4f %7.4f %7.4f   %-8s %-8.4f %s" % (
        k, b["B1_majority"]["macro_f1"], b["B2_schema_frequency"]["macro_f1"],
        b["B3_lexical"]["macro_f1"], b["B4_surface_cue"]["macro_f1"],
        b["B5_graph_only"]["macro_f1"], v["best_non_oracle"]["baseline"],
        v["headroom"], v["CUE_ACCESSIBLE"]))

print()
print("=== decision rule 3: cue-bearing features ===")
for k in ("conflict", "requestability", "missing_cardinality", "first_action_type"):
    v = r["targets"][k]
    best = v["best_non_oracle"]["baseline"]
    bf = v["best_non_oracle"]["macro_f1"]
    print("-- %s: best=%s macroF1=%.4f" % (k, best, bf))
    print("   classes on DEV:", json.dumps(v["class_distribution_dev"]))
    for f in v["baselines"][best]["top_features"][:8]:
        print("     ", json.dumps(f))

print()
print("=== B3 record ===")
b3 = r["targets"]["disposition"]["baselines"]["B3_lexical"]
print(json.dumps(b3, indent=2)[:600])

print()
print("=== recorded deviations ===")
for d in r["recorded_deviations"]:
    print(" *", d["id"], "-", d["what"])

print()
print("=== strata: conflict by renderer family (B4, the winner) ===")
for row in r["strata"]["conflict"]["by"]["renderer_family"]:
    print("   ", json.dumps(row))
