"""Lexi v3 bridge boundary: exhaustive candidates, typed targets, no EVAL I/O."""
import gzip,json,hashlib,itertools
from pathlib import Path
import numpy as np

ROOT=Path('C:/phoenix-target-overgraph/bank-v3-core-20261002-v04')
OUT=Path('C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v02')
SOURCE=Path(__file__).resolve().parent
VOCAB=('PAD','MOVE','TAKE','DROP','ACTIVATE','DEACTIVATE','OPEN','CLOSE','WAIT','TRANSFER')
OBSERVABLE=('input_text','goal_mentions','bindings','actions','requests')

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,o):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(o,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
def rows(p):
    with gzip.open(p,'rt',encoding='utf-8') as f:
        for line in f:yield json.loads(line)
def model_inputs(p):return {k:p[k] for k in OBSERVABLE}
def align(p,t):
    a=t['SUPERVISION_ABI'];ids=[v['id'] for v in p['actions']]
    if p['world_id']!=t['world_id'] or ids!=a['candidate_order'] or ids!=[v['id'] for v in a['candidates']]:
        raise ValueError('Candidate/row join mismatch')
    if ids!=sorted(set(ids)):raise ValueError('Candidate order not canonical')
    if a['selected_action_eligible']:
        i=a['selected_action_index']
        if not isinstance(i,int) or ids[i]!=a['selected_action_id'] or a['selected_action_id'] not in a['optimal_action_ids']:
            raise ValueError('Selected action outside canonical optimum')
    elif a['selected_action_index'] is not None:raise ValueError('Ineligible action populated')
    if not set(a['optimal_action_ids'])<=set(ids):raise ValueError('Unknown optimal candidate')
    return a
def pairs(split,handoff):
    if split not in ('TRAIN','DEV'):raise ValueError('Only TRAIN/DEV allowed')
    h=handoff['splits'][split]
    for name,digest in sorted(h['input_files'].items()):
        counterpart=name.replace('public/','data/',1)
        if sha(ROOT/name)!=digest or sha(ROOT/counterpart)!=h['supervision_files'][counterpart]:raise ValueError('Changed shard')
        for p,t in itertools.zip_longest(rows(ROOT/name),rows(ROOT/counterpart)):
            if p is None or t is None:raise ValueError('Shard count mismatch')
            yield p,t

def prepare():
    handoff=read(ROOT/'PHASE5-HANDOFF-v02.json');correction=read(ROOT/'HANDOFF-CORRECTION-v02.json')
    if sha(ROOT/'PHASE5-HANDOFF-v02.json')!=correction['corrected_handoff_sha256']:raise ValueError('Handoff changed')
    if (OUT/'ADAPTER-RECEIPT.json').exists():raise ValueError('Adapter already frozen')
    OUT.mkdir(parents=True,exist_ok=True);audit={};schemas={};max_entities=0;max_fields=0
    material={}
    for split in ('TRAIN','DEV'):
        collected=list(pairs(split,handoff));material[split]=collected
        for p,t in collected:
            align(p,t)
            for a in p['actions']:
                if a['type'] not in VOCAB:raise ValueError('Unknown type')
                keys=tuple(sorted(a['args']));schemas.setdefault(a['type'],set()).add(keys);max_fields=max(max_fields,len(keys))
            entities={e['id'] for e in p['bindings']}|{v for a in p['actions'] for v in a['args'].values()}
            if any(not isinstance(e,str) for e in entities):raise ValueError('Non-entity action argument needs declared encoding')
            max_entities=max(max_entities,len(entities))
    role_schema={k:list(next(iter(v))) for k,v in schemas.items() if len(v)==1}
    if len(role_schema)!=len(schemas):raise ValueError('Multiple argument schemas per type need explicit identity contract')
    if max_fields>4 or max_entities>64:raise ValueError('Existing four-slot/64-entity family cannot losslessly encode this schema')
    for split,collected in material.items():
        n=len(collected);m=handoff['candidate_contract']['max_count'];dest=OUT/'data'/split;dest.mkdir(parents=True)
        A=np.zeros((n,m,5),np.int16);mask=np.zeros((n,m),bool);cy=np.zeros((n,m,7),np.float32)
        gy=np.zeros((n,6),np.float32);ga=np.zeros((n,6),bool);ca=np.zeros_like(cy,bool)
        action=np.full(n,-1,np.int32);opt=np.zeros((n,m),bool);meta=[];root_labels={}
        with (dest/'texts.jsonl').open('x',encoding='utf-8') as f:
            for i,(p,t) in enumerate(collected):
                abi=align(p,t);entities=sorted({e['id'] for e in p['bindings']}|{v for a in p['actions'] for v in a['args'].values()})
                bindings={e:j+1 for j,e in enumerate(entities)};c=len(p['actions']);mask[i,:c]=True
                for j,a in enumerate(p['actions']):
                    A[i,j,0]=VOCAB.index(a['type'])
                    for k,key in enumerate(role_schema[a['type']]):A[i,j,k+1]=bindings[a['args'][key]]
                    for r,name in enumerate(('candidate_legal','candidate_satisfies_goal')):cy[i,j,r]=abi['candidates'][j][name];ca[i,j,r]=True
                global_=abi['global_targets'];gy[i,:3]=[global_['solvable'],global_['goal_satisfied'],global_['missing_information_present']]
                ga[i,:3]=[global_['solvable_available'],True,True]
                gy[i,5]=(t['TARGETS']['missing_information'].get('witness') or {}).get('M_size',0);ga[i,5]=True
                if abi['selected_action_eligible']:action[i]=abi['selected_action_index']
                opt[i,:c]=[a['id'] in abi['optimal_action_ids'] for a in p['actions']]
                signature=json.dumps(abi,sort_keys=True)
                root=p['canonical_id']
                if root in root_labels and root_labels[root]!=signature:raise ValueError('Pair target drift')
                root_labels[root]=signature
                meta.append({'id':p['world_id'],'root':root,'renderer':p['renderer_family'],
                  'types':[a['type'] for a in p['actions']],'action_ids':[a['id'] for a in p['actions']],
                  'goal_initial':global_['goal_satisfied'],'axes':t['CAPABILITY_AXES'],
                  'action_type':abi['core_targets']['first_action_type'],'optimal_eligible':abi['optimal_set_eligible']})
                # Backbone sees only the earned input_text surface; no metadata/targets.
                f.write(json.dumps({'input_text':model_inputs(p)['input_text']},ensure_ascii=False)+'\n')
        for name,value in {'A':A,'mask':mask,'cy':cy,'ca':ca,'gy':gy,'ga':ga,'action':action,'optimal':opt}.items():np.save(dest/(name+'.npy'),value)
        write(dest/'metadata.json',meta)
        if n!=handoff['splits'][split]['rows'] or len(root_labels)!=handoff['splits'][split]['canonical_roots']:raise ValueError('Population mismatch')
        audit[split]={'rows':n,'roots':len(root_labels),'candidate_slots':int(mask.sum()),'max_candidates':int(mask.sum(1).max()),
                      'action_eligible_rows':int((action>=0).sum()),'truncated_candidates':0}
    receipt={'status':'QUALIFIED','handoff_sha256':sha(ROOT/'PHASE5-HANDOFF-v02.json'),
       'release_identity':correction['original_release_identity'],'evaluation_files_opened':0,'model_contact':False,
       'role_schema':role_schema,'encoding':'type + up to four type-specific alphabetically ordered argument slots; observable entity IDs sorted; padding zero',
       'max_observable_entities':max_entities,'max_argument_fields':max_fields,'splits':audit,
       'global_availability':[True,True,True,False,False,True],'candidate_availability':[True,True,False,False,False,False,False],
       'global_alias_group':[2,5],'conflict_weight':0,'input_surface':'final_plus_mean of input_text only',
       'files':{str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in (OUT/'data').rglob('*') if p.is_file()},
       'architecture_migration':'same graft family; expanded action-type vocabulary only; no new access mechanism'}
    write(OUT/'ADAPTER-RECEIPT.json',receipt);print(json.dumps(audit),flush=True)

if __name__=='__main__':prepare()
