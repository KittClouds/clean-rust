"""Core build identity; imports pinned ancestor source, never ancestor populations."""
import os
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import sys,json,hashlib,gzip,shutil
from pathlib import Path

SOURCE=Path(__file__).resolve().parent
REPO=SOURCE.parents[2]
ANCESTOR=REPO/'experiments/ff-s15-bank-02'
OUTPUT=Path('C:/phoenix-target-overgraph/bank-v3-core-20261002-v04')
sys.path.insert(0,str(ANCESTOR/'src'))
from bank2 import algebra as A, facts as F, requirements as R, intents,worldgen,targets,render,sim,refsim,gates,freeze
from bank2.canon import canonical_json,sha256_hex,rng

NAMESPACE='BANK-v3-core-v04-20261002'
BUDGET={'TRAIN':12000,'DEV':3000,'EVAL':3000}
AXES=['binding','evidence_support','counterevidence','missing_requirements','conflict',
      'composition_depth','transition_depth','candidate_comparison','globalization','nuisance_invariance']
INTENTS=[n for n,w in worldgen.INTENT_WEIGHTS]
CORE_TARGETS=['disposition','reason','missing_cardinality','requestability','first_action_type','conflict']

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(obj,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')

def pin_ancestor():
    seal=read(ANCESTOR/'receipts/BANK_v2_SEALED.json')
    result={}
    for name,h in seal['pairs_stage_source_manifest'].items():
        p=ANCESTOR/name if name.endswith(('.json','.md')) else ANCESTOR/'src/bank2'/name
        if sha(p)!=h:raise ValueError('Ancestor source mismatch: '+name)
        result[str(p)]=h
    return result

def freeze_build():
    pins=pin_ancestor()
    for name in ('features.py','learners.py'):
        p=REPO/'experiments/ff-s15-v2-eval-00'/name;pins[str(p)]=sha(p)
    history=[SOURCE.parent/'BANK-V3-FREEZE.md',SOURCE.parent/'bank-v3-objects.json',
       SOURCE.parent/'bank-v3-target-contract-v1.json',SOURCE.parent/'o1-permission-verification.json',
       REPO/'experiments/ff-s15-v2-eval-00/results/v2-0-receipt.json',
       ANCESTOR/'receipts/BANK_v2_SEALED.json',
       REPO/'experiments/ff-s15-ladder-scaffold-00/ladder-scaffold-v1.json']
    spec={'release':'BANK-v3-core','version':'0.4','namespace':NAMESPACE,
      'provenance_class':'SYNTHETIC_ONLY','external_roots_imported':0,'external_rows_imported':0,
      'human_extension':'PENDING_PERMISSION_AND_RECONSTRUCTION; original requirements unchanged',
      'canonical_root_budgets':BUDGET,'renderings_per_root':2,'generation_attempt_limit':320,
      'intents':INTENTS,'curriculum':'equal cyclic intent cells; alternate shallow/deeper plan requests',
      'reliability_floor_DEV_per_class_or_slice':200,'capability_axes':AXES,
      'axis_definitions':{'binding':'introduced entities / ambiguous or unknown goal binding',
       'evidence_support':'count of derived decision evidence facts','counterevidence':'supported contradiction flag',
       'missing_requirements':'canonical unresolved requirement count','conflict':'supported contradiction flag',
       'composition_depth':'number of contiguous action-type runs in shortest canonical plan',
       'transition_depth':'shortest canonical plan length; null if not solved',
       'candidate_comparison':'count of environment-legal canonical candidates',
       'globalization':'number of obligations in required_facts.query','nuisance_invariance':'paired renderings=2'},
      'targets':{'admissible':['disposition','reason','first_action_type'],
       'restricted':{'requestability':['renderer','length_decile','temporal_phrase_signature'],
                     'missing_cardinality':['hidden_fact_count','requirement_count','bookkeeping_intervention']},
       'diagnostic_only':['conflict'],'support_only_action_types':['TRANSFER','WAIT'],
       'B3_caveat':'100k head subsample has no guaranteed one-way DEV bias; negative cue findings qualified',
       'B0_scope':'semantic derivation instrument only; not blanket learner/renderer validation',
       'reason_interpretation':'0.0382 slightly above majority 0.0342; weak lexical recovery',
       'action_type_interpretation':'type classification, not candidate selection or proof of MOVE wall; 0.9032 defined score headroom only'},
      'weights':{'independent_target_family':1,'action_endpoint':.5,'conflict':0,'aliases':'one source unit'},
      'candidate_order':'lexicographic content-derived action id; exhaustive; no fixed bank cap',
      'optimal_set':'environment shortest-path first actions intersect permitted candidates; operational eligibility EXECUTE only',
      'empty_set':'ineligible for hit denominator; never automatic success','normalization':'none bank-defined; downstream fit TRAIN only',
      'protected_policy':'construction+independent seal replay only; no model-facing evaluation truth grant',
      'model_weights_opened':False,'ancestor_pins':pins,'historical_pins':{str(p):sha(p) for p in history},
      'source_hashes':{p.name:sha(p) for p in SOURCE.iterdir() if p.suffix in ('.py','.md')},
      'G19_scope':'all emitted rows checked; complete declared phrase-signature tables and B4 cue learner, not universal lexical proof',
      'G14_CORE':'zero external roots/rows, synthetic-only, pinned ancestor semantic machinery'}
    spec['renderer_preflight_sha256']=sha(OUTPUT/'engineering/pilot-canonical/CUE-RECHECK.json')
    spec['python_hash_seed']='0'
    spec['supervision_ABI']={
      'disposition':'TARGETS.disposition.value; canonical information/policy decision',
      'reason':'TARGETS.reason.value exactly; null retained as canonical absence-of-reason category, never relabeled disposition',
      'first_action_type':'type of TARGETS.executed_action ID; EXECUTE-only; NA masked otherwise',
      'requestability':'missing-information witness.nonreq; NA if M_size=0, else ALL_REQUESTABLE/SOME_UNAVAILABLE',
      'missing_cardinality':'witness.M_size binned 0/1/2+; not total hidden-fact count',
      'conflict':'TARGETS.contradiction.value; diagnostic-only, zero training weight',
      'candidate_legal':'simulator legal at initial state/tick0',
      'candidate_permitted':'environment legal AND action-type policy permitted',
      'candidate_satisfies_goal':'legal action, apply at tick0, goal holds at tick1; immediate effect, not future plan viability',
      'on_environment_shortest_path':'membership in exhaustive shortest successful first-action set, ignores policy',
      'solvable':'environment search SOLVED vs UNSAT_EXHAUSTED; other status unavailable',
      'goal_satisfied':'environment initial goal holds at tick0',
      'missing_information_present':'witness.M_size > 0; alias source with missing_cardinality, not independent weight',
      'unavailable':['candidate_supported','candidate_has_counterevidence','candidate_requires_missing_information']}
    spec['ontology_availability']={
      'solvable':{'availability':'PARTIAL','source':'SUPERVISION_ABI.global_targets.solvable','mask':'solvable_available'},
      'goal_satisfied':{'availability':'AVAILABLE','source':'SUPERVISION_ABI.global_targets.goal_satisfied'},
      'missing_information_present':{'availability':'AVAILABLE','source':'witness.M_size>0','alias_source':'missing_cardinality'},
      'contradiction_present':{'availability':'DIAGNOSTIC_ONLY','source':'TARGETS.contradiction.value','alias_source':'conflict'},
      'requestable_information_present':{'availability':'UNAVAILABLE_IN_MODEL_ABI','note':'requestability classification is not this ontology target'},
      'number_or_structure_of_missing_requirements':{'availability':'PARTIAL','source':'missing_information.witness.M_size','channels':'count only; structure unavailable'},
      'candidate_legal':{'availability':'AVAILABLE','source':'SUPERVISION_ABI.candidates.candidate_legal'},
      'candidate_satisfies_goal':{'availability':'AVAILABLE','source':'SUPERVISION_ABI.candidates.candidate_satisfies_goal'},
      **{n:{'availability':'UNAVAILABLE_IN_MODEL_ABI'} for n in ('candidate_supported','candidate_has_counterevidence',
              'candidate_has_unmet_requirements','candidate_applicable','candidate_requires_missing_information')}}
    write(OUTPUT/'BUILD-CONTRACT.json',spec)
    for name in spec['source_hashes']:
        dest=OUTPUT/'source/core-v04'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(SOURCE/name,dest)
    for field in ('ancestor_pins','historical_pins'):
        for origin,h in spec[field].items():
            dest=OUTPUT/'source/dependencies'/h/Path(origin).name;dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists():shutil.copyfile(origin,dest)
    return spec

def verify_spec():
    spec=read(OUTPUT/'BUILD-CONTRACT.json')
    for field in ('ancestor_pins','historical_pins'):
        for p,h in spec[field].items():
            if sha(p)!=h:raise ValueError('Frozen dependency changed: '+p)
    for name,h in spec['source_hashes'].items():
        if sha(SOURCE/name)!=h:raise ValueError('Frozen build source changed: '+name)
    return spec

def iter_rows(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:
        for line in f:yield json.loads(line)

def gz_writer(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    return gzip.GzipFile(filename='',mode='wb',fileobj=path.open('xb'),mtime=0,compresslevel=2)

def emit(f,row):f.write((canonical_json(row)+'\n').encode())

def core_labels(rec):
    t=rec['TARGETS'];w=t['missing_information'].get('witness') or {}
    missing=int(w.get('M_size',0));d=t['disposition']['value']
    selected=t['executed_action']['value'];byid={a['id']:a for a in rec['ACTION_POLICY']['available_actions']}
    return {'disposition':d,'reason':t['reason']['value'],
      'missing_cardinality':str(missing) if missing<2 else '2+',
      'requestability':'NA' if not missing else ('SOME_UNAVAILABLE' if w.get('nonreq') else 'ALL_REQUESTABLE'),
      'first_action_type':byid[selected]['type'] if d=='EXECUTE' else 'NA',
      'conflict':bool(t['contradiction']['value'])}
