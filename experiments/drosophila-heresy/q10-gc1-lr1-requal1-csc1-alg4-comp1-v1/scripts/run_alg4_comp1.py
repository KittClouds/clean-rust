from __future__ import annotations
import hashlib, importlib.util, itertools, json, os, struct, sys
from pathlib import Path

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
EXP = REPO / "experiments" / "drosophila-heresy"
R2 = EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-r2-v3"
EXH1 = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-exh1-v1" / "scripts" / "run_exh1.py"
ALG1 = EXP / "q10-gc1-lr1-requal1-csc1-alg1-v2"
CONTEXT = ("seed9731-R-tau4.json", 3)
A3_ROWS = (161, 357, 749)
ANCHORS = (360, 362)
ANCHOR_GROUP = 45
EXPECTED_COUNT = 31_596_544
ALLOW = {Path("PLAN.md"), Path("CONTRACT.json"), Path("PREEXECUTION.json"), Path("STATUS.json"), Path("execution.json"), Path("REPORT.md"), Path("preflight-domain.json"), Path("scripts"), Path("scripts/run_alg4_comp1.py"), Path("tests"), Path("tests/test_alg4_comp1_static.py"), Path("anchors"), Path("anchors/a3_manifest.json"), Path("anchors/footprint_manifest.json"), Path("domains"), Path("domains/comp1a_manifest.json"), Path("domains/comp1b_manifest.json")}
PARENTS = [
    ("r2v3_contract", R2 / "CONTRACT.json"),
    ("r2v3_preexecution", R2 / "PREEXECUTION.json"),
    ("r2v3_execution", R2 / "execution.json"),
    ("r2v3_order1_hits", R2 / "results" / "order1_hits.jsonl"),
    ("r2v3_semantics_test", R2 / "tests" / "test_action_mapping_semantics.py"),
    ("exh1_runner", EXH1),
    ("alg1_runner", ALG1 / "scripts" / "run_alg1.py"),
    ("alg1_descriptor", ALG1 / "descriptors" / "seed9731-R-tau4__set3.json"),
]

def require(ok: bool, msg: str) -> None:
    if not ok:
        raise RuntimeError(msg)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().upper()

def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

def sha256_obj(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest().upper()

def write_new(path: Path, value: object) -> None:
    require(not path.exists(), f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module load failed: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def parent_bindings() -> list[dict[str, object]]:
    out = []
    for label, path in PARENTS:
        require(path.is_file(), f"missing parent: {path}")
        out.append({"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return out

def read_a3() -> dict[str, object]:
    path = R2 / "results" / "order1_hits.jsonl"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    require(len(lines) == 2, f"A3 source line count drift: {len(lines)}")
    records = [json.loads(line) for line in lines]
    require([r.get("actions") for r in records] == [[360], [362]], "A3 action ordinals drift")
    require(records[0]["target_rows"] and records[1]["target_rows"], "A3 target rows missing")
    rows = sorted(int(x["row"]) for r in records for x in r["target_rows"])
    require(rows == list(A3_ROWS), f"A3 rows drift: {rows}")
    for r in records:
        require(r.get("geometry_valid") is False, "A3 geometry gate drift")
        require(all(x.get("direction") == "equal" and int(x.get("ulp")) == 0 for x in r["target_rows"]), "A3 equality drift")
    anchors = [{"ordinal": int(r["actions"][0]), "action_keys": list(r["action_keys"]), "target_rows": [int(x["row"]) for x in r["target_rows"]], "readout_sha256": r.get("readout_sha256"), "weight_state_sha256": r.get("weight_state_sha256")} for r in records]
    return {"source_path": path.relative_to(REPO).as_posix(), "source_sha256": sha256_file(path), "source_bytes": path.stat().st_size, "source_line_count": 2, "context": list(CONTEXT), "anchor_ordinals": list(ANCHORS), "anchor_rows": list(A3_ROWS), "anchors": anchors, "derivation": "R2-v3 results/order1_hits.jsonl only"}

def prepare() -> tuple[dict[str, object], dict[str, object], dict[int, dict[str, object]], tuple[int, ...], dict[int, tuple[int, ...]], dict[int, tuple[int, ...]]]:
    exh = load_module(EXH1, "q10_alg4_comp1_exh1")
    alg = exh.load_alg1()
    context = exh.prepare_context(CONTEXT, alg)
    actions = context["actions"]
    groups = tuple(int(x) for x in context["groups"])
    by_group = {int(g): tuple(int(x) for x in context["by_group"][g]) for g in groups}
    require(len(actions) == 472 and len(groups) == 59, "action/group cardinality drift")
    require(set(by_group) == set(groups) and all(len(v) == 8 for v in by_group.values()), "group arity drift")
    coords = {i: frozenset(int(c) for c, _ in actions[i]["mapping"]) for i in range(len(actions))}
    for left, right in itertools.combinations(groups, 2):
        require(coords[by_group[left][0]].isdisjoint(coords[by_group[right][0]]), f"group coordinate overlap {left},{right}")
    anchor_rows = set(A3_ROWS)
    footprints = {i: tuple(sorted(int(x) for x in actions[i]["dependency_rows"])) for i in range(len(actions))}
    excluded = tuple(i for i in range(len(actions)) if i not in ANCHORS and set(footprints[i]) & anchor_rows)
    require(all(actions[i]["group"] == ANCHOR_GROUP for i in ANCHORS), "anchor group drift")
    require(set(excluded).issubset(set(by_group[ANCHOR_GROUP])), "footprint exclusion escaped anchor group")
    fp_payload = {"context": list(CONTEXT), "anchor_rows": list(A3_ROWS), "actions": [{"ordinal": i, "group": int(actions[i]["group"]), "to": str(actions[i]["to"]), "dependency_rows": list(footprints[i])} for i in range(len(actions))]}
    footprint = {"context": list(CONTEXT), "source_runner": EXH1.relative_to(REPO).as_posix(), "source_runner_sha256": sha256_file(EXH1), "action_count": len(actions), "group_count": len(groups), "anchor_group": ANCHOR_GROUP, "anchor_rows": list(A3_ROWS), "excluded_action_ordinals_comp1a": list(excluded), "excluded_count": len(excluded), "footprint_sha256": sha256_obj(fp_payload)}
    return context, footprint, actions, groups, by_group, footprints

def hash_domain(actions, groups, by_group, footprints) -> tuple[int, str, dict[str, int]]:
    h = hashlib.sha256(); total = 0; per_anchor = {}
    anchor_rows = set(A3_ROWS)
    comp_groups = tuple(g for g in groups if g != ANCHOR_GROUP)
    for anchor in ANCHORS:
        count = 0
        for triple in itertools.combinations(comp_groups, 3):
            for a, b, c in itertools.product(*(by_group[g] for g in triple)):
                require(not (set(actions[a]["mapping_coordinates"]) if "mapping_coordinates" in actions[a] else set()).intersection(set()), "internal mapping marker error") if False else True
                if set(footprints[a]) & anchor_rows or set(footprints[b]) & anchor_rows or set(footprints[c]) & anchor_rows:
                    continue
                h.update(struct.pack("<4H", anchor, a, b, c)); count += 1
        per_anchor[str(anchor)] = count; total += count
    return total, h.hexdigest().upper(), per_anchor

def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE=1 required")
    require(sys.argv[1:] == ["--preflight"], "only --preflight is authorized")
    for rel in ROOT.rglob("*"):
        require(rel.relative_to(ROOT) in ALLOW, f"unexpected pre-existing output: {rel.relative_to(ROOT)}")
    bindings = parent_bindings(); a3 = read_a3(); _context, footprint, actions, groups, by_group, footprints = prepare()
    count, domain_sha, per_anchor = hash_domain(actions, groups, by_group, footprints)
    require(count == EXPECTED_COUNT and per_anchor == {"360": 15_798_272, "362": 15_798_272}, f"domain count drift: {count} {per_anchor}")
    write_new(ROOT / "anchors" / "a3_manifest.json", a3)
    write_new(ROOT / "anchors" / "footprint_manifest.json", footprint)
    common = {"context": list(CONTEXT), "order": 4, "anchor_group": ANCHOR_GROUP, "anchor_ordinals": list(ANCHORS), "compensator_group_count": 58, "compensator_arity": 3, "count": count, "per_anchor_count": per_anchor, "domain_sha256": domain_sha, "record_encoding": "little-endian four u16 values: anchor ordinal then three action ordinals", "coordinate_disjointness": True}
    write_new(ROOT / "domains" / "comp1a_manifest.json", dict(common, **{"class": "COMP1A", "footprint_exclusion": "compensator dependency_rows intersecting A3 rows excluded"}))
    write_new(ROOT / "domains" / "comp1b_manifest.json", dict(common, **{"class": "COMP1B", "footprint_exclusion": "none beyond group and coordinate compatibility"}))
    source = {"protocol": "Q10-ALG4-COMP1", "identity": ROOT.name, "context": list(CONTEXT), "parent_bindings": bindings, "a3_manifest_sha256": sha256_file(ROOT / "anchors" / "a3_manifest.json"), "footprint_manifest_sha256": sha256_file(ROOT / "anchors" / "footprint_manifest.json"), "domain_manifests": {"COMP1A": sha256_file(ROOT / "domains" / "comp1a_manifest.json"), "COMP1B": sha256_file(ROOT / "domains" / "comp1b_manifest.json")}, "domain_count": count, "domain_sha256": domain_sha}
    write_new(ROOT / "preflight-domain.json", source)
    contract = {"protocol": "Q10-ALG4-COMP1", "identity": ROOT.name, "status": "SEALED_PREMEASUREMENT", "context": list(CONTEXT), "parent_bindings": bindings, "a3_anchor_rows": list(A3_ROWS), "a3_anchor_ordinals": list(ANCHORS), "order": 4, "domain_classes": {"COMP1A": {"count": count, "domain_sha256": domain_sha}, "COMP1B": {"count": count, "domain_sha256": domain_sha}}, "domain_definition": "distinguished group-45 anchor plus three singleton actions from distinct non-anchor groups; coordinate-disjoint; COMP1A excludes A3 footprint intersections and COMP1B does not", "geometry_prefilter": False, "functional_evaluation_before_geometry_classification": True, "engineering_only": True, "scientific_promotion": False, "replay_executed": False, "measurement_started": False, "shared_evaluation": True, "write_allowlist": sorted(str(x).replace(chr(92), "/") for x in ALLOW)}
    impl = {"plan_sha256": sha256_file(ROOT / "PLAN.md"), "runner_sha256": sha256_file(ROOT / "scripts" / "run_alg4_comp1.py"), "static_test_sha256": sha256_file(ROOT / "tests" / "test_alg4_comp1_static.py")}
    contract["implementation_bindings"] = impl
    write_new(ROOT / "CONTRACT.json", contract)
    pre = {"protocol": "Q10-ALG4-COMP1", "identity": ROOT.name, "status": "PREEXECUTION_SEALED", "contract_sha256": sha256_file(ROOT / "CONTRACT.json"), "domain_count": count, "domain_sha256": domain_sha, "engineering_only": True, "scientific_promotion": False, "measurement_started": False}
    write_new(ROOT / "PREEXECUTION.json", pre)
    status = {"protocol": "Q10-ALG4-COMP1", "identity": ROOT.name, "status": "PREFLIGHT_PASS", "measurement_started": False, "scientific_promotion": False, "domain_count": count, "domain_sha256": domain_sha}
    write_new(ROOT / "STATUS.json", status)
    report = "Q10-ALG4-COMP1 preflight PASS. No long measurement was launched. COMP1A and COMP1B are separately sealed and share the same compatible domain identity: 31,596,544 order-4 tuples, 15,798,272 per anchor, domain stream SHA-256 " + domain_sha + ".\n"
    write_new(ROOT / "REPORT.md", report)
    execution = {"protocol": "Q10-ALG4-COMP1", "identity": ROOT.name, "status": "PREFLIGHT_PASS", "engineering_only": True, "scientific_promotion": False, "measurement_started": False, "replay_executed": False, "contract_sha256": sha256_file(ROOT / "CONTRACT.json"), "preexecution_sha256": sha256_file(ROOT / "PREEXECUTION.json"), "domain_sha256": domain_sha, "domain_count": count}
    write_new(ROOT / "execution.json", execution)
    print(json.dumps({"status": "PREFLIGHT_PASS", "domain_count": count, "per_anchor": per_anchor, "domain_sha256": domain_sha}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
