"""BANK-v2 build driver: pilot, full generation, seal.

  python -m bank2.build pilot [--scale 1.0]   # small bank exercising every action, scope, slot, disposition and ASK branch; all 18 gates; throughput receipt
  python -m bank2.build full                  # post-dedup minimum budgets (725,000 canonical worlds, 800,000 rendered rows) plus the paired panels
  python -m bank2.build seal                  # verdict from the recorded gate results

Output goes under out/ (git-ignored). Nothing here contacts a model.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import multiprocessing as mp
import sys
import time
from collections import Counter
from pathlib import Path

from . import freeze, gates, interventions, pipeline, splits
from .canon import canonical_json, sha256_hex

ROOT = freeze.ROOT
OUT = ROOT / "out"
SHARD = 2000
BUDGET = {s["name"]: s["budget"] for s in freeze.FREEZE["splits"]["list"]}
PUBLIC_SPLITS = tuple(s for s in BUDGET if s.startswith("TEST-"))
FLAGS = {"frozen_fabric_contact": False, "system_1_5_training": False, "terminal_truth_opened": False, "external_rows_imported": 0}


def _gz(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return gzip.GzipFile(filename="", mode="wb", fileobj=open(path, "wb"), mtime=0, compresslevel=3)


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def worker(job: dict) -> dict:
    """Build one shard of one split, run every per-row gate on every row (100%), and write the protected and public files."""
    split, start, end, root = job["split"], job["start"], job["end"], Path(job["out"])
    shard = job["shard"]
    acc = gates.Acc()
    samples: dict = {}
    built, failed = [], []
    files = {}
    prot = _gz(root / ("protected/test-truth" if split in PUBLIC_SPLITS else "data") / split / f"part-{shard:05d}.jsonl.gz")
    pub = _gz(root / "public/test-inputs" / split / f"part-{shard:05d}.jsonl.gz") if split in PUBLIC_SPLITS else None
    n_rows = 0
    t0 = time.time()
    need = job.get("need")
    for idx in range(start, end):
        if need is not None and len(built) >= need:
            break
        try:
            rows = pipeline.build_world(split, idx)
        except RuntimeError as e:
            failed.append([idx, str(e)[-120:]])
            continue
        except Exception as e:  # a generator defect on one index must not kill the shard; it is recorded loudly and the index is replaced
            failed.append([idx, "EXC " + repr(e)[:200]])
            continue
        built.append(idx)
        for row in rows:
            sp, i = split, idx
            regen = (lambda sp=sp, i=i, wid=row["world_id"]: next(x for x in pipeline.build_world(sp, i) if x["world_id"] == wid))
            gates.check_row(row, regen, acc)
            prot.write((canonical_json(row) + "\n").encode("utf-8"))
            if pub:
                pub.write((canonical_json(pipeline.public_view(row)) + "\n").encode("utf-8"))
            n_rows += 1
            d, r = row["TARGETS"]["disposition"]["value"], row["TARGETS"]["reason"]["value"]
            key = "EXECUTE" if d == "EXECUTE" else ("ASK" if d == "ASK" else ("IMPOSSIBLE" if r == "IMPOSSIBLE_GOAL" else None))
            if key and key not in samples:
                samples[key] = row
    prot.close()
    if pub:
        pub.close()
    return {"split": split, "shard": shard, "built": built, "failed": failed, "rows": n_rows, "acc": acc, "samples": samples, "seconds": time.time() - t0}


def pair_worker(job: dict) -> dict:
    axis, ks, root = job["axis"], job["ks"], Path(job["out"])
    f = _gz(root / "paired" / f"{axis}-{job['shard']:04d}.jsonl.gz")
    pairs, failed = [], []
    for k in ks:
        try:
            a, b = interventions.make_pair(axis, k)
        except RuntimeError as e:
            failed.append([k, str(e)[-100:]])
            continue
        pairs.append((axis, a, b))
        for x in (a, b):
            f.write((canonical_json(x) + "\n").encode("utf-8"))
    f.close()
    res = interventions.check_pairs(pairs) if pairs else {"passed": False, "checked": 0, "failures": 0, "examples": [], "per_axis": {}, "axes_without_pairs": [axis]}
    return {"axis": axis, "shard": job["shard"], "pairs": len(pairs), "failed": failed, "check": res}


def merge_pair_checks(results: list) -> dict:
    per_axis: dict = {}
    fails, examples, n = 0, [], 0
    for r in results:
        n += r["check"]["checked"]
        fails += r["check"]["failures"]
        examples += r["check"]["examples"]
        for ax, v in r["check"]["per_axis"].items():
            t = per_axis.setdefault(ax, {"pairs": 0, "failures": 0})
            t["pairs"] += v["pairs"]
            t["failures"] += v["failures"]
    missing = [a for a in interventions.AXES if a not in per_axis]
    return {"passed": n > 0 and fails == 0 and not missing, "checked": n, "failures": fails, "examples": examples[:8], "per_axis": per_axis, "axes_without_pairs": missing}


def g10_selftest(pairs_sample) -> bool:
    """G10 must notice a pair whose diff escapes its declared field set."""
    axis, a, b = pairs_sample
    import copy
    bad = copy.deepcopy(b)
    bad["WORLD_TRUTH"]["actor"] = "e_changed"
    return bool(interventions.check_pair(axis, a, bad))


def plan_jobs(counts: dict, stage_out: Path, offset: dict | None = None, shard_base: int = 0) -> list[dict]:
    jobs, shard_id = [], Counter()
    for split, n in counts.items():
        base = (offset or {}).get(split, 0)
        for start in range(base, base + n, SHARD):
            jobs.append({"split": split, "start": start, "end": min(start + SHARD, base + n), "shard": shard_base + shard_id[split], "out": str(stage_out)})
            shard_id[split] += 1
    return jobs


def run_splits(jobs, procs):
    results = []
    t0 = time.time()
    with mp.Pool(procs) as pool:
        for n, r in enumerate(pool.imap_unordered(worker, jobs), 1):
            results.append(r)
            if n % 5 == 0 or n == len(jobs):
                done = sum(x["rows"] for x in results)
                print(f"  shards {n}/{len(jobs)} rows={done} elapsed={time.time() - t0:.0f}s", flush=True)
    return results


PAIR_STAGE_FILES = ("interventions.py", "build.py")  # orchestration and the pair builders: they do not affect the rows


def source_manifest() -> dict:
    src = Path(__file__).resolve().parent
    files = sorted(list(src.glob("*.py")) + [ROOT / "bank-v2-objects.json", ROOT / "seed-registry-v2.json", ROOT / "BANK-V2-FREEZE.md"])
    return {p.name: _sha_file(p) for p in files}


def aggregate(results: list, pair_results: list, budgets: dict | None) -> dict:
    acc = gates.Acc()
    samples: dict = {}
    failed = []
    for r in results:
        acc.merge(r["acc"])
        for k, v in r["samples"].items():
            samples.setdefault(k, v)
        failed += [(r["split"], i, m) for i, m in r["failed"]]
    pair_check = merge_pair_checks(pair_results) if pair_results else None
    selftest = gates.selftests(samples, samples["ASK"]) if {"EXECUTE", "ASK", "IMPOSSIBLE"} <= set(samples) else {"samples_missing": False}
    if pair_results:
        from . import interventions as I
        a, b = I.make_pair("P1", 0)
        selftest["G10"] = g10_selftest(("P1", a, b))
    else:
        selftest["G10"] = False
    verdict = gates.finalize(acc, selftest, pair_check)
    verdict["G16"]["sampled_gates"] = []
    return {"verdict": verdict, "acc": acc, "failed_indices": failed, "pair_check": pair_check}


def pilot_coverage(acc: gates.Acc, verdict: dict) -> dict:
    cells = ["generated", "available", "legal", "illegal", "truth_optimal", "executed_in_shortest_plan_witness"]
    exempt = freeze.FREEZE["action_algebra"]["coverage_receipt"]["exempt_cells"]
    checks = {
        "all_nine_actions_in_every_cell": all(acc.cells[a][c] > 0 for a in acc.cells for c in cells if c not in exempt.get(a, [])),
        "all_five_required_facts_scopes_nonempty": all(acc.scope_nonempty[s] > 0 for s in ("schema", "goal", "plan", "action", "query")),
        "all_four_query_source_scopes_used": set(acc.scopes) >= {"SCHEMA", "GOAL", "PLAN", "ACTION"},
        "all_five_slot_types_in_requirements": set(acc.slots) >= set(freeze.SLOTS),
        "all_five_dispositions": set(acc.dispositions) >= set(freeze.DISPOSITIONS),
        "ask_cardinality_branches": {"ASK:1", "ESCALATE:2", "DECLINE_UNAVAILABLE:1", "DECLINE_UNAVAILABLE:2"} <= set(acc.ask_m),
        "both_zero_missing_classifications": {"NO_MISSING_REQUIRED", "IRRELEVANT_MISSING"} <= set(acc.classif),
        "all_sixteen_reasons": all(acc.reasons[r] > 0 for r, v in freeze.REASONS.items() if v["in_reason_field"]),
        "all_twelve_splits_present": set(acc.split_rows) == set(BUDGET),
    }
    checks["pilot_ok"] = all(checks.values())
    return checks


def write_report(name: str, payload: dict) -> Path:
    OUT.mkdir(exist_ok=True)
    p = OUT / name
    p.write_text(json.dumps(payload, indent=1, sort_keys=True, default=lambda o: sorted(o) if isinstance(o, set) else str(o)), encoding="utf-8", newline="\n")
    return p


def cmd_pilot(scale: float, procs: int) -> int:
    stage_out = OUT / "pilot"
    counts = {"TRAIN": int(1600 * scale), "DEV": int(300 * scale), "TEST-IID": int(300 * scale)}
    counts.update({s: int(300 * scale) for s in splits.OOD_SPLITS})
    t0 = time.time()
    print(f"pilot: {sum(counts.values())} canonical worlds on {procs} processes", flush=True)
    results = run_splits(plan_jobs(counts, stage_out), procs)
    gen_s = time.time() - t0
    per_axis = max(int(60 * scale), 6)
    pair_jobs = [{"axis": ax, "ks": list(range(i, min(i + 20, per_axis))), "shard": i // 20, "out": str(stage_out)} for ax in interventions.AXES for i in range(0, per_axis, 20)]
    with mp.Pool(procs) as pool:
        pair_results = pool.map(pair_worker, pair_jobs)
    agg = aggregate(results, pair_results, None)
    acc, verdict = agg["acc"], agg["verdict"]
    cov = pilot_coverage(acc, verdict)
    rows = sum(r["rows"] for r in results)
    report = {"stage": "pilot", "version": freeze.VERSION, "freeze_sha256": freeze.FREEZE_SHA, "scale": scale, "canonical_world_counts": counts, "rows": rows, "seconds": {"generate_and_gate": gen_s, "total": time.time() - t0},
              "ms_per_row_all_gates": 1000 * gen_s * procs / max(rows, 1), "coverage": cov, "gates": verdict, "build_failures": agg["failed_indices"][:20], "n_build_failures": len(agg["failed_indices"]),
              "pairs": {"per_axis": agg["pair_check"]["per_axis"] if agg["pair_check"] else None}, "source_manifest": source_manifest()}
    p = write_report("pilot-report.json", report)
    passed = {g: v["passed"] for g, v in verdict.items() if g.startswith("G")}
    print("gates:", {g: ("PASS" if ok else "FAIL") for g, ok in sorted(passed.items())})
    print("coverage:", {k: v for k, v in cov.items()})
    print(f"rows={rows}  {report['ms_per_row_all_gates']:.1f} ms/row/core (incl. all gates)  report: {p}")
    return 0 if all(passed.values()) and cov["pilot_ok"] else 1


def cmd_full(procs: int) -> int:
    stage_out = OUT / "full"
    budgets = dict(BUDGET)
    t0 = time.time()
    print(f"full: {sum(budgets.values())} canonical worlds on {procs} processes", flush=True)
    results = run_splits(plan_jobs(budgets, stage_out), procs)
    built = Counter()
    for r in results:
        built.update({r["split"]: len(r["built"])})
    deficit = {s: budgets[s] - built[s] for s in budgets if built[s] < budgets[s]}
    round_no = 1
    while deficit and round_no <= 5:
        print(f"  topping up the build failures (round {round_no}): {deficit}", flush=True)
        jobs = []
        for i, (sp, n) in enumerate(deficit.items()):
            start = budgets[sp] + 100_000 * round_no
            jobs.append({"split": sp, "start": start, "end": start + 40 * n + 500, "need": n, "shard": 10_000 * round_no + i, "out": str(stage_out)})
        more = run_splits(jobs, min(procs, len(jobs)))
        results += more
        for r in more:
            built.update({r["split"]: len(r["built"])})
        deficit = {sp: budgets[sp] - built[sp] for sp in budgets if built[sp] < budgets[sp]}
        round_no += 1
    per_axis = interventions_budget()
    pair_jobs = [{"axis": ax, "ks": list(range(i, min(i + 100, per_axis))), "shard": i // 100, "out": str(stage_out)} for ax in interventions.AXES for i in range(0, per_axis, 100)]
    print(f"paired panels: {len(pair_jobs)} jobs", flush=True)
    with mp.Pool(procs) as pool:
        pair_results = pool.map(pair_worker, pair_jobs)
    agg = aggregate(results, pair_results, budgets)
    acc, verdict = agg["acc"], agg["verdict"]
    worlds = {sp: acc.worlds[sp] for sp in budgets}
    short = {sp: budgets[sp] - worlds[sp] for sp in budgets if worlds[sp] < budgets[sp]}
    report = {"stage": "full", "version": freeze.VERSION, "freeze_sha256": freeze.FREEZE_SHA, "canonical_worlds": worlds, "budget_shortfall": short, "rows": acc.rows, "gates": verdict,
              "seconds": time.time() - t0, "n_build_failures": len(agg["failed_indices"]), "pair_panels": agg["pair_check"]["per_axis"] if agg["pair_check"] else None, "source_manifest": source_manifest()}
    write_report("full-report.json", report)
    passed = {g: v["passed"] for g, v in verdict.items() if g.startswith("G")}
    print("gates:", {g: ("PASS" if ok else "FAIL") for g, ok in sorted(passed.items())}, "shortfall:", short, "rows:", acc.rows)
    return 0 if all(passed.values()) and not short else 1


def cmd_seal() -> int:
    """The verdict. BANK_v2_SEALED is written only when every gate passed, the minimum budgets are met and the accounting identity holds; otherwise SEAL_REFUSED lists why."""
    rp = OUT / "full-report.json"
    if not rp.exists():
        print("no full-report.json: run `full` first")
        return 2
    rep = json.loads(rp.read_text(encoding="utf-8"))
    v = rep["gates"]
    problems = [f"{g} did not pass" for g, x in sorted(v.items()) if g.startswith("G") and not x["passed"]]
    worlds = rep["canonical_worlds"]
    problems += [f"{sp}: {worlds[sp]} canonical worlds < budget {BUDGET[sp]}" for sp in BUDGET if worlds[sp] < BUDGET[sp]]
    canonical = sum(worlds.values())
    expected_rows = canonical + 3 * worlds["TEST-TEMPLATE"]
    if rep["rows"] != expected_rows:
        problems.append(f"rendered_rows {rep['rows']} != canonical_worlds + 3 x TEST-TEMPLATE = {expected_rows}")
    if rep["freeze_sha256"] != freeze.FREEZE_SHA:
        problems.append("the freeze changed after generation")
    cur = source_manifest()
    drift = [k for k in cur if k not in PAIR_STAGE_FILES and rep["source_manifest"].get(k) != cur[k]]
    if drift:
        problems.append(f"the row-stage source changed after generation: {drift}")
    pairs_manifest = rep.get("pairs_stage", {}).get("source_manifest", rep["source_manifest"])
    if pairs_manifest != cur:
        problems.append("the pair-stage source changed after the paired panels were generated")
    files = {}
    root = OUT / "full"
    for p in sorted(root.rglob("*.gz")):
        files[p.relative_to(root).as_posix()] = {"sha256": _sha_file(p), "bytes": p.stat().st_size}
    manifest = {"BANK_v2_SEALED": not problems, "release": "BANK-v2", "constitution_version": freeze.VERSION, "freeze_sha256": freeze.FREEZE_SHA, "canonical_worlds": worlds,
                "canonical_worlds_total": canonical, "rendered_rows": rep["rows"], "rendered_rows_identity": f"{canonical} + 3 x {worlds['TEST-TEMPLATE']} = {expected_rows}",
                "gates": {g: {"passed": x["passed"], "checked": x["checked"]} for g, x in sorted(v.items()) if g.startswith("G")}, "class_shares": v["_summary"], **FLAGS,
                "escrow": {"public": "public/test-inputs label-free", "protected": "protected/test-truth escrowed"}, "files": files, "source_manifest": rep["source_manifest"], "pairs_stage_source_manifest": rep.get("pairs_stage", {}).get("source_manifest"), "problems": problems}
    name = "BANK_v2_SEALED.json" if not problems else "SEAL_REFUSED.json"
    (root / name).write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    print("SEALED" if not problems else f"SEAL REFUSED: {problems}", f"-> {root / name}")
    return 0 if not problems else 1


def cmd_pairs(procs: int) -> int:
    """Regenerate only the paired panels and re-run G10; the 800,000 verified rows are untouched. The rows-stage source hashes (everything except the pair builders and this driver)
    must still match the full-report, and the pair stage records its own complete source manifest."""
    import shutil
    rp = OUT / "full-report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    cur = source_manifest()
    drift = [k for k in cur if k not in PAIR_STAGE_FILES and rep["source_manifest"].get(k) != cur[k]]
    if drift:
        print("the rows-stage sources changed since generation; run `full` again:", drift)
        return 2
    stage_out = OUT / "full"
    shutil.rmtree(stage_out / "paired", ignore_errors=True)
    t0 = time.time()
    per_axis = interventions_budget()
    pair_jobs = [{"axis": ax, "ks": list(range(i, min(i + 100, per_axis))), "shard": i // 100, "out": str(stage_out)} for ax in interventions.AXES for i in range(0, per_axis, 100)]
    print(f"paired panels: {len(pair_jobs)} jobs", flush=True)
    with mp.Pool(procs) as pool:
        pair_results = pool.map(pair_worker, pair_jobs)
    g10 = merge_pair_checks(pair_results)
    a, b = interventions.make_pair("P1", 0)
    g10_detects = g10_selftest(("P1", a, b))
    rep["gates"]["G10"] = {"passed": g10["passed"], "checked": g10["checked"], **{k: v for k, v in g10.items() if k not in ("passed", "checked")}}
    g07 = rep["gates"]["G07"]
    if not g10_detects:
        g07["passed"], g07["failures"] = False, g07["failures"] + 1
        g07.setdefault("undetected", []).append("G10")
    rep["pair_panels"] = g10["per_axis"]
    rep["pairs_stage"] = {"source_manifest": cur, "seconds": time.time() - t0, "g10_selftest_detects": g10_detects}
    write_report("full-report.json", rep)
    print("G10:", "PASS" if g10["passed"] else "FAIL", {k: g10[k] for k in ("checked", "failures")}, g10["examples"][:3])
    return 0 if g10["passed"] and g10_detects else 1


def interventions_budget() -> int:
    return freeze.BUDGETS["paired_identities_per_intervention_axis"]


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    procs = max(1, mp.cpu_count() - 1)
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "pilot":
        scale = float(argv[argv.index("--scale") + 1]) if "--scale" in argv else 1.0
        return cmd_pilot(scale, procs)
    if cmd == "full":
        return cmd_full(procs)
    if cmd == "pairs":
        return cmd_pairs(procs)
    if cmd == "seal":
        return cmd_seal()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
