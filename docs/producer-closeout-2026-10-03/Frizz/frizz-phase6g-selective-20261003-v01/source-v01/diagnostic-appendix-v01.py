"""Post-endpoint explanatory recorder, no fit/selection/survival-rule changes."""
from collections import Counter
from common import *
from metrics import selective
setup();lock();prior=read(F6/'PHASE6F-SEALED.json')
for p,h in prior['artifacts'].items():
    if sha(F6/p)!=h:raise ValueError('observability parent artifact drift '+p)
old=sys.modules['common'];spec=importlib.util.spec_from_file_location('common',F6/'source-v01/common.py');f=importlib.util.module_from_spec(spec)
try:
    sys.modules['common']=f;spec.loader.exec_module(f)
finally:sys.modules['common']=old
a=load(C6/'DEV-ABI.pt');t=load(OUT/'DEV-targets.pt');results=read(OUT/'results.json')
byroot={(cid,a['renderer'][2*i+j]):(i,'primary' if j==0 else 'paired') for i,cid in enumerate(a['canonical_ids']) for j in (0,1)}
counts={name:{path:Counter() for path in ('model','observable_oracle')} for name in ('primary','paired')}
for p,r in f.population('DEV'):
    i,name=byroot[r['META']['canonical_id'],p['renderer_family']]
    for path in counts[name]:
        idx=results['results']['trained'][name]['selection'][path]['full_authority']['chosen_candidate_indices'][i]
        counts[name][path][p['actions'][idx]['type']]+=1
subset={}
arms=binary_panel();saved=load(OUT/'DEV-logits.pt')
for name,l in arms.items():
    pred=torch.where(l>0,0,1);ix=torch.arange(0,len(pred),2)
    subset[name]=selective(pred[ix],t['status'][ix],t['mask'][ix]&(t['status'][ix]!=2),t['canonical'][ix])
for name,l in saved.items():
    pred=l.argmax(-1);ix=torch.arange(0,len(pred),2)
    subset['selective_'+name]=selective(pred[ix],t['status'][ix],t['mask'][ix]&(t['status'][ix]!=2),t['canonical'][ix])
receipt(OUT/'diagnostic-appendix.json',{'status':'PASS','chosen_full_menu_action_types':counts,
    'certain_case_only_primary_metrics':subset,'scope':'explanatory only, survival and thresholds unchanged',
    'prior_observability_seal_artifacts_verified':len(prior['artifacts']),
    'source_sha256':sha(Path(__file__)),'protected_evaluation_opened':False})
print('DIAGNOSTIC APPENDIX',counts,flush=True)
