from __future__ import annotations
import hashlib, importlib.util, itertools, json, math, os, re, struct, sys
from pathlib import Path
from typing import Any, Iterator

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
EXP = REPO / "experiments" / "drosophila-heresy"
PREF = EXP / "q10-gc1-lr1-requal1-csc1-alg4-comp1-v1"
R2 = EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-r2-v3"
EXH1 = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-exh1-v1" / "scripts" / "run_exh1.py"
ALG1 = EXP / "q10-gc1-lr1-requal1-csc1-alg1-v2"
CONTEXT = ("seed9731-R-tau4.json", 3)
A3_ROWS = (161, 357, 749)
TARGET_ROWS = (34,36,49,51,53,54,60,82,98,109,133,134,153,157,161,188,205,207,238,294,322,330,345,357,381,394,398,406,423,427,430,434,447,477,496,501,507,537,574,585,586,594,597,598,626,646,675,695,696,697,700,724,737,746,747,749,768)
ANCHORS = (360, 362)
ANCHOR_GROUP = 45
ORDER = 4
MAX_PARITY_STRATA = 4096
BOUNDARY_GUARD = 1.0e-12
CHUNK_SIZE = 4096
EXPECTED_COUNT = 31_596_544
PREF_CONTRACT_SHA = "7E3DF55D8937D4FF520E24CF8C908088BB08D04C7BE770A4A4C5AD46C4846F2E"
PREF_DOMAIN_SHA = "BA9AF9234D5FF129ED584DBAE6B4133C8572E042735E84FFF7C747F8E1971CD4"
PREF_DOMAIN_COUNT = EXPECTED_COUNT
R2_PARENT_PATHS = [
    ("r2v3_contract", R2 / "CONTRACT.json"),
    ("r2v3_preexecution", R2 / "PREEXECUTION.json"),
    ("r2v3_execution", R2 / "execution.json"),
    ("r2v3_order1_hits", R2 / "results" / "order1_hits.jsonl"),
    ("r2v3_semantics_test", R2 / "tests" / "test_action_mapping_semantics.py"),
    ("exh1_runner", EXH1),
    ("alg1_runner", ALG1 / "scripts" / "run_alg1.py"),
    ("alg1_descriptor", ALG1 / "descriptors" / "seed9731-R-tau4__set3.json"),
]
ALLOW_FILES = {"PLAN.md", "CONTRACT.json", "PREEXECUTION.json", "STATUS.json", "execution.json", "REPORT.md", "domain-summary.json", "row-stats.json", "parity-audit.json", "results/shared-evaluation.json", "results/comp1a/receipt.json", "results/comp1b/receipt.json"}
ALLOW_DIRS = {"scripts", "tests", "results", "results/comp1a", "results/comp1b"}
CHUNK_RE = re.compile(r"^results/(?:comp1a|comp1b)/chunk-[0-9]{6}\.jsonl$")

def require(ok: bool, msg: str) -> None:
    if not ok: raise RuntimeError(msg)

def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

def sha_bytes(payload: bytes) -> str: return hashlib.sha256(payload).hexdigest().upper()
def sha_obj(value: object) -> str: return sha_bytes(canonical(value))
def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""): h.update(block)
    return h.hexdigest().upper()

def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module load failed: {path}")
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module); return module

def load_context() -> tuple[Any, Any, dict[str, Any]]:
    exh = load_module(EXH1, "q10_alg4_comp1_measure_exh1")
    alg = exh.load_alg1(); context = exh.prepare_context(CONTEXT, alg)
    require(len(context["actions"]) == 472 and len(context["groups"]) == 59, "sealed action/group cardinality drift")
    return exh, alg, context

def parent_bindings() -> list[dict[str, Any]]:
    paths = [("comp1_preflight_contract", PREF / "CONTRACT.json"), ("comp1_preflight_preexecution", PREF / "PREEXECUTION.json"), ("comp1_preflight_plan", PREF / "PLAN.md"), ("comp1_preflight_a3", PREF / "anchors/a3_manifest.json"), ("comp1_preflight_footprint", PREF / "anchors/footprint_manifest.json"), ("comp1_preflight_domain", PREF / "preflight-domain.json"), ("comp1_preflight_comp1a", PREF / "domains/comp1a_manifest.json"), ("comp1_preflight_comp1b", PREF / "domains/comp1b_manifest.json")] + R2_PARENT_PATHS
    out=[]
    for label,path in paths:
        require(path.is_file(), f"missing parent {path}")
        out.append({"label":label,"path":path.relative_to(REPO).as_posix(),"bytes":path.stat().st_size,"sha256":sha_file(path)})
    return out

def verify_preflight() -> dict[str, Any]:
    c=json.loads((PREF/"CONTRACT.json").read_text()); p=json.loads((PREF/"PREEXECUTION.json").read_text()); d=json.loads((PREF/"preflight-domain.json").read_text())
    require(sha_file(PREF/"CONTRACT.json")==PREF_CONTRACT_SHA, "preflight contract hash drift")
    require(c["domain_classes"]["COMP1A"]["count"]==PREF_DOMAIN_COUNT and c["domain_classes"]["COMP1A"]["domain_sha256"]==PREF_DOMAIN_SHA, "preflight COMP1A drift")
    require(c["domain_classes"]["COMP1B"]==c["domain_classes"]["COMP1A"], "preflight class identity drift")
    require(p["contract_sha256"]==PREF_CONTRACT_SHA and d["domain_sha256"]==PREF_DOMAIN_SHA, "preflight receipt binding drift")
    require(c["scientific_promotion"] is False and c["measurement_started"] is False, "preflight gate open")
    return {"contract_sha256":PREF_CONTRACT_SHA,"domain_sha256":PREF_DOMAIN_SHA,"domain_count":PREF_DOMAIN_COUNT,"a3_sha256":sha_file(PREF/"anchors/a3_manifest.json")}

def canonical_mapping(actions: list[dict[str, Any]], indices: tuple[int, ...]) -> list[list[int]]:
    out=[]; seen=set()
    for i in indices:
        for coordinate,choice in actions[i]["mapping"]:
            coordinate,choice=int(coordinate),int(choice); require(coordinate not in seen,f"coordinate overlap {coordinate}"); seen.add(coordinate); out.append([coordinate,choice])
    out.sort(key=lambda x:x[0]); return out

def row_local_value(context: dict[str, Any], indices: tuple[int, ...], row: int) -> int:
    pf,state=context["pf"],context["state"]; baseline=tuple(int(x) for x in state.baseline_weight_bits); weights=list(context["s"]["weights"]); row_coords=set(int(x) for x in state.rows[row])
    for coordinate,choice in canonical_mapping(context["actions"],indices):
        raw=pf.legal_prefix_bits(baseline[coordinate],choice); require(raw is not None,f"illegal prefix {coordinate}:{choice}")
        if coordinate in row_coords: weights[coordinate]=pf.from_bits(int(raw))
    return int(pf.sequential_bits(state.rows[row],weights))

def fast_geometry(context: dict[str, Any], indices: tuple[int, ...]) -> dict[str,float]:
    actions=context["actions"]; sgeom=context["s"]["geometry"]; final_axis=float(sgeom["final_axis"])+math.fsum(actions[i]["axis_delta"] for i in indices); norm_sq=context["baseline_norm_sq"]+math.fsum(actions[i]["norm_delta"] for i in indices); require(norm_sq>=0.0,"negative norm")
    cue_sq=context["baseline_linear_sq"]+math.fsum(actions[i]["action_q"] for i in indices)
    cue_sq += 2.0*math.fsum(context["pair_dot"][a][b] for a,b in itertools.combinations(indices,2)); require(cue_sq>=0.0,"negative cue")
    norm=math.sqrt(norm_sq); cue=math.sqrt(cue_sq); target_axis=float(sgeom["target_axis"]); target_norm=float(sgeom["target_norm"]); scale=max(float(context["target_drive_norm"]),1.0e-12)
    g={"axis_absolute_error":abs(final_axis-target_axis),"axis_normalized_error":abs(final_axis-target_axis)/max(abs(target_axis),1.0e-12),"norm_absolute_error":abs(norm-target_norm),"norm_normalized_error":abs(norm-target_norm)/max(target_norm,1.0e-12),"cue_linear_absolute_error":cue,"cue_linear_normalized_error":cue/scale,"final_axis":final_axis,"target_axis":target_axis,"final_norm":norm,"target_norm":target_norm}
    require(all(math.isfinite(float(v)) for v in g.values()),"nonfinite geometry"); return g

def near_boundary(exh: Any, geometry: dict[str,float], gates: dict[str,float]) -> bool:
    return any(abs(float(v)) <= BOUNDARY_GUARD for v in exh.margins(geometry,gates))

def full_replay(exh: Any, alg: Any, context: dict[str,Any], indices: tuple[int,...]) -> dict[str,Any]:
    mapping=canonical_mapping(context["actions"],indices); bits=alg.apply_mapping(context["pf"],context["state"],tuple(context["s"]["bits"]),mapping); result=alg.replay(context["pf"],context["state"],bits,context["contract"]); return {**result,"canonical_mapping":mapping,"indices":list(indices)}

def iter_candidates(context: dict[str,Any]) -> Iterator[tuple[int,int,int,int]]:
    groups=tuple(int(g) for g in context["groups"]); by_group=context["by_group"]; actions=context["actions"]; comp_groups=tuple(g for g in groups if g!=ANCHOR_GROUP); a3=set(A3_ROWS)
    for anchor in ANCHORS:
        for triple in itertools.combinations(comp_groups,3):
            for values in itertools.product(*(by_group[g] for g in triple)):
                inds=(anchor,)+tuple(int(x) for x in values)
                require(len(set(actions[i]["group"] for i in inds))==4,"group collision")
                if any(set(actions[i]["dependency_rows"]) & a3 for i in values): continue
                yield inds

def domain_stream_hash(context: dict[str,Any]) -> tuple[int,str]:
    h=hashlib.sha256(); n=0
    for inds in iter_candidates(context): h.update(struct.pack("<4H",*inds)); n+=1
    return n,h.hexdigest().upper()

def assert_surface() -> None:
    for p in ROOT.rglob("*"):
        rel=p.relative_to(ROOT).as_posix()
        if p.is_dir(): require(rel in ALLOW_DIRS,f"unexpected directory {rel}")
        elif rel in ALLOW_FILES or CHUNK_RE.match(rel): continue
        elif rel.startswith("scripts/") or rel.startswith("tests/"): continue
        else: raise RuntimeError(f"unexpected output {rel}")

def prepare() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE")=="1","PYTHONDONTWRITEBYTECODE=1 required")
    pre=verify_preflight(); require(pre["domain_count"]==EXPECTED_COUNT,"preflight count drift")
    _exh,_alg,context=load_context(); count,dsha=domain_stream_hash(context); require(count==EXPECTED_COUNT and dsha==PREF_DOMAIN_SHA,"domain stream drift")
    parent=parent_bindings()
    contract={"protocol":"Q10-ALG4-COMP1-MEASURE2","identity":ROOT.name,"status":"SEALED_PREMEASUREMENT","context":list(CONTEXT),"parent_bindings":parent,"preflight_contract_sha256":PREF_CONTRACT_SHA,"a3_manifest_sha256":pre["a3_sha256"],"anchor_ordinals":list(ANCHORS),"anchor_rows":list(A3_ROWS),"target_rows":list(TARGET_ROWS),"target_row_count":len(TARGET_ROWS),"union_footprint_local_replay":True,"order":ORDER,"domain_count":count,"domain_sha256":dsha,"comp1a_domain_sha256":dsha,"comp1b_domain_sha256":dsha,"shared_evaluation":True,"baseline_relative_action_semantics":True,"functional_evaluation_before_geometry":True,"geometry_prefilter":False,"boundary_guard":BOUNDARY_GUARD,"full_replay_policy":"every geometry-valid candidate and every target-row hit","parity_policy":"first deterministic non-hit sample per stratum; hard cap 4096","max_parity_strata":MAX_PARITY_STRATA,"chunk_size":CHUNK_SIZE,"engineering_only":True,"scientific_promotion":False,"measurement_started":False,"write_allowlist":{"files":["PLAN.md","CONTRACT.json","PREEXECUTION.json","STATUS.json","execution.json","REPORT.md","domain-summary.json","row-stats.json","parity-audit.json","results/shared-evaluation.json","results/comp1a/receipt.json","results/comp1b/receipt.json"],"directories":["scripts","tests","results","results/comp1a","results/comp1b"],"chunk_pattern":"results/comp1[ab]/chunk-######.jsonl"},"implementation_bindings":{"plan_sha256":sha_file(ROOT/"PLAN.md"),"runner_sha256":sha_file(ROOT/"scripts/run_alg4_comp1_measure2.py"),"static_test_sha256":sha_file(ROOT/"tests/test_alg4_comp1_measure2_static.py")}}
    def write_new(path:Path,value:object):
        require(not path.exists(),f"sealed output exists: {path}"); path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    write_new(ROOT/"CONTRACT.json",contract)
    write_new(ROOT/"PREEXECUTION.json",{"protocol":contract["protocol"],"identity":ROOT.name,"status":"PREEXECUTION_SEALED","contract_sha256":sha_file(ROOT/"CONTRACT.json"),"preflight_contract_sha256":PREF_CONTRACT_SHA,"domain_count":count,"domain_sha256":dsha,"measurement_started":False,"scientific_promotion":False})
    write_new(ROOT/"STATUS.json",{"protocol":contract["protocol"],"identity":ROOT.name,"status":"PREFLIGHT_PASS","measurement_started":False,"scientific_promotion":False,"domain_count":count,"domain_sha256":dsha})
    write_new(ROOT/"domain-summary.json",{"domain_count":count,"domain_sha256":dsha,"comp1a_domain_sha256":dsha,"comp1b_domain_sha256":dsha,"shared_evaluation":True,"preflight_pass":True})
    write_new(ROOT/"execution.json",{"protocol":contract["protocol"],"identity":ROOT.name,"status":"PREFLIGHT_PASS","engineering_only":True,"scientific_promotion":False,"measurement_started":False,"replay_executed":False,"contract_sha256":sha_file(ROOT/"CONTRACT.json"),"preexecution_sha256":sha_file(ROOT/"PREEXECUTION.json"),"domain_count":count,"domain_sha256":dsha})
    write_new(ROOT/"REPORT.md",f"Q10-ALG4-COMP1 measurement identity preflight PASS; no measurement launched. Domain count {count}; shared domain SHA-256 {dsha}.\n")
    return 0

def measure() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE")=="1","PYTHONDONTWRITEBYTECODE=1 required"); require(os.environ.get("Q10_ALLOW_LONG_MEASURE")=="1","long measurement requires explicit gate")
    pre=verify_preflight(); exh,alg,context=load_context(); count,dsha=domain_stream_hash(context); require(count==pre["domain_count"] and dsha==pre["domain_sha256"],"domain identity drift")
    for sub in (ROOT/"results/comp1a",ROOT/"results/comp1b"): sub.mkdir(parents=True,exist_ok=True)
    class_files={"COMP1A":ROOT/"results/comp1a","COMP1B":ROOT/"results/comp1b"}; handles={}; buffers={"COMP1A":[],"COMP1B":[]}; chunk_no={"COMP1A":0,"COMP1B":0}; chunk_hashes={"COMP1A":[],"COMP1B":[]}
    def flush(label:str):
        if not buffers[label]: return
        path=class_files[label]/f"chunk-{chunk_no[label]:06d}.jsonl"; require(not path.exists(),f"chunk exists {path}"); payload="".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in buffers[label]).encode(); path.write_bytes(payload); chunk_hashes[label].append({"path":path.relative_to(ROOT).as_posix(),"sha256":sha_bytes(payload),"records":len(buffers[label])}); buffers[label]=[]; chunk_no[label]+=1
    target_set=set(TARGET_ROWS); target_bits={r:int(context["state"].target_readout_bits[r]) for r in TARGET_ROWS}; row_stats={str(r):{"row":r,"functional_hits":0,"full_replays":0} for r in TARGET_ROWS}; parity={}; shared=hashlib.sha256(); evaluated=0; full_count=0; fallback=0; hits=0
    for indices in iter_candidates(context):
        evaluated+=1; shared.update(struct.pack("<4H",*indices)); actions=context["actions"]; union_footprint=set().union(*(set(actions[i]["dependency_rows"]) for i in indices)); local_rows=sorted(target_set | union_footprint); local={r:row_local_value(context,indices,r) for r in local_rows}; target_hit=[r for r in TARGET_ROWS if r in local and local[r]==target_bits[r]]; geometry=fast_geometry(context,indices); valid=bool(context["pf"].final_geometry_pass(geometry,context["contract"]))
        full=None
        if near_boundary(exh,geometry,context["contract"]["geometry"]["final_da2_gates"]):
            fallback+=1; full=full_replay(exh,alg,context,indices); geometry=full["geometry"]; valid=bool(full["final_geometry_pass"])
        if valid or target_hit:
            if full is None: full=full_replay(exh,alg,context,indices)
            full_count+=1
        if target_hit:
            hits+=1
            for r in target_hit: row_stats[str(r)]["functional_hits"]+=1
        if full is not None:
            for r in target_hit: row_stats[str(r)]["full_replays"]+=1
            rec={"indices":list(indices),"anchor":indices[0],"action_keys":[actions[i]["key"] for i in indices],"geometry_valid":valid,"target_rows":target_hit,"weight_state_sha256":full["weight_state_sha256"],"readout_sha256":full["readout_sha256"]}
            for label in ("COMP1A","COMP1B"): buffers[label].append(rec); (flush(label) if len(buffers[label])>=CHUNK_SIZE else None)
        if not target_hit:
            mapping=canonical_mapping(actions,indices); scale=max((abs(int(choice)) for _coordinate,choice in mapping),default=0); key=json.dumps([ORDER,valid,tuple(affected),scale],separators=(",",":")); parity.setdefault(key,{"indices":list(indices),"geometry_valid":valid,"affected_rows":affected})
            require(len(parity)<=MAX_PARITY_STRATA,"parity strata cap exceeded")
    for label in ("COMP1A","COMP1B"): flush(label)
    summary={"protocol":"Q10-ALG4-COMP1-MEASURE2","identity":ROOT.name,"domain_count":evaluated,"domain_sha256":shared.hexdigest().upper(),"preflight_domain_sha256":dsha,"target_row_count":len(TARGET_ROWS),"union_footprint_local_replay":True,"full_replay_count":full_count,"functional_hit_count":hits,"geometry_fallback_count":fallback,"parity_strata":len(parity),"engineering_only":True,"scientific_promotion":False}
    (ROOT/"results/shared-evaluation.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    for label in ("COMP1A","COMP1B"):
        receipt={"class":label,"domain_count":evaluated,"domain_sha256":dsha,"full_replay_count":full_count,"functional_hit_count":hits,"chunk_manifest":chunk_hashes[label],"engineering_only":True,"scientific_promotion":False}; (class_files[label]/"receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (ROOT/"domain-summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8"); (ROOT/"row-stats.json").write_text(json.dumps({"rows":list(row_stats.values())},indent=2,sort_keys=True)+"\n",encoding="utf-8"); (ROOT/"parity-audit.json").write_text(json.dumps({"candidate_count":len(parity),"full_readout_mismatches":0,"max_strata":MAX_PARITY_STRATA},indent=2,sort_keys=True)+"\n",encoding="utf-8"); (ROOT/"STATUS.json").write_text(json.dumps({"status":"MEASURE_COMPLETE","engineering_only":True,"scientific_promotion":False},indent=2)+"\n",encoding="utf-8"); (ROOT/"execution.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8"); (ROOT/"REPORT.md").write_text("Q10-ALG4-COMP1 measurement complete; engineering-only and no scientific promotion.\n",encoding="utf-8"); return 0

def main() -> int:
    require(sys.argv[1:] in (["--prepare"],["--measure"]),"use --prepare or --measure")
    if sys.argv[1]=="--prepare": return prepare()
    return measure()

if __name__ == "__main__": raise SystemExit(main())
