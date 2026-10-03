import shutil
from common import *
OUT.mkdir(parents=True,exist_ok=False)
files=[BANK/'PHASE5-HANDOFF-v02.json',E6/'PHASE6E-SEALED.json',E6/'seal-replay.json',E6/'TRAIN-OBSERVABILITY-CAVEAT.json']
for split in ('TRAIN','DEV'):files.extend([C6/f'{split}-ABI.pt',C6/f'{split}-ABI.json'])
files+=list((REPO/'experiments/ff-s15-bank-02/src/bank2').glob('*.py'))
files += [REPO/'experiments/ff-s15-bank-02/bank-v2-objects.json',REPO/'experiments/ff-s15-bank-02/bank-v2-objects.sha256',CORE/'generation.py',CORE/'common.py']
# Preserve completed machinery via inherited model/input pins, without loading it.
for name in ('RAW-SPECIFICATION.json','PILOT-SPECIFICATION.json'):
    inherited=read(E6/name)
    files += [Path(p) for p in inherited['inputs']]
sources={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.md')}
receipt(OUT/'SPECIFICATION.json',{'sources':sources,'inputs':{str(p):sha(p) for p in files},
    'training':False,'population':{'TRAIN':1333,'DEV':333},'protected_evaluation_opened':False})
folder=OUT/'source-v01';folder.mkdir()
for n in sources:shutil.copy2(HERE/n,folder/n)
receipt(OUT/'OBSERVATION-CONTRACT.json',{'text_source':'public.input_text -> untruncated frozen Qwen -> six aggregates/final mention means',
    'typed_source':'public.actions type and sorted argument keys -> nine types/four roles/four binding vectors',
    'binding_source':'public.bindings name/aliases; first text mention; unmatched arguments zero, no canonical repair',
    'goal_source':'public.goal_mentions surface/role matching public.bindings; empty/multiple retained',
    'public_superset_not_encoded_directly':['action text','action IDs','request IDs','world/canonical IDs','renderer metadata'],
    'excluded':['hidden facts','simulator state','truth-only locations','unsupported predicates','selected ID','gold legality','distance','support labels','unrendered slot markers'],
    'semantic_signature':'full source-traced observation plus ordered candidate menu, wording/order removed only at semantic level',
    'exact_signature':'raw full text plus binding/goal/candidate-coordinate ABI, no renderer normalization',
    'canonical_legal_not_permission':True,'counterfactuals_not_corpus_changes':True})
receipt(OUT/'CANONICAL-LEGALITY-DERIVATION.json',{'source':str(REPO/'experiments/ff-s15-bank-02/src/bank2/sim.py'),
    'source_sha256':sha(REPO/'experiments/ff-s15-bank-02/src/bank2/sim.py'),
    'rule':'all action.pre present at tick 0 AND all action.neg absent at tick 0',
    'active_schedule':'valid_from <= 0 AND (valid_to is null OR 0 < valid_to)',
    'positive_clauses':'Act.pre reconstructed by pinned Sim.from_world; MOVE includes emitted gate conditions',
    'negative_clauses':'Act.neg reconstructed by pinned simulator',
    'not_clauses':['action permission','selected action','transition distance'],
    'candidate_literal_derivations':'clauses.jsonl.gz preserves each primitive fact/polarity/truth/observable support',
    'unknown':'no observable truth support; never substituted with canonical label'})
print('SEMANTIC AUDIT FROZEN',flush=True)
