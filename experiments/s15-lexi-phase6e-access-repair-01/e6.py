"""One clean raw-local/T0 adapter; packed candidates, frozen provenance."""
import sys,time,json,hashlib
from pathlib import Path
import numpy as np
import torch
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'s15-lexi-phase6d-raw-legality-01'))
import d6
read,write,sha=d6.read,d6.write,d6.sha
OUT=Path('C:/phoenix-target-overgraph/lexi-phase6e-access-repair-20261002-v01')
SEED=20261002

def audit_train():
    d=d6.load('TRAIN');old=read(d6.OUT/'heads/entity_final-tiny_MLP/RESULT.json')
    p=d6.c6.sigmoid(np.load(d6.OUT/'heads/entity_final-tiny_MLP/TRAIN-logits.npy'))>=old['threshold_TRAIN']
    y=d['y']>=.5;m=d['mask'];fp=p&~y&m;fn=~p&y&m;r={'rows':len(m),'roots':len(m)//2,'FP':int(fp.sum()),'FN':int(fn.sum()),'exact_sets':d6.c6.set_metrics(y,p,m)['exact_set'],'families':{}}
    for name,take in [('positive_preconditions_failed',d['factors'][:,:,5]<1),('negative_preconditions_failed',d['factors'][:,:,6]<.5),('actor_binding_matches',d['factors'][:,:,2]>=.5),('goal_argument_matches',d['factors'][:,:,3]>0)]:
        take=take&m;r['families'][name]={'candidates':int(take.sum()),'illegal_candidates':int((~y&take).sum()),'FP':int((fp&take).sum()),'FN':int((fn&take).sum()),'FP_rate_among_illegal':float((fp&take).sum()/max(1,(~y&take).sum()))}
    r['type_errors']={n:{'FP':int((fp&(d['types']==i)).sum()),'FN':int((fn&(d['types']==i)).sum())} for i,n in enumerate(d6.c6.parent.adapter.VOCAB) if i}
    r['feature_decision']='No gold precondition/permission flags admitted. Positive-precondition failures dominate FP counts but families overlap and legality itself depends on them; no new observable derivation is invented. Same raw+argument inputs, unchanged T0 e.'
    return r

def freeze():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'SPEC.json').exists():return verify()
    d6.verify();parents={}
    for root in [d6.OUT,d6.OUT.parent/'lexi-phase6d-access-adapter-20261002-v02',d6.OUT.parent/'lexi-phase6d-raw-legality-20261002-v03']:
        status=read(root/'FINAL-STATUS.json')
        if 'SEALED' not in status['status']:raise ValueError('Prior unsealed')
        for name,h in read(root/'MANIFEST.json')['files'].items():
            if sha(root/name)!=h:raise ValueError('Prior identity changed '+name)
        parents[str(root/'MANIFEST.json')]=sha(root/'MANIFEST.json')
    parents.update(read(d6.OUT/'SPEC.json')['parents'])
    for n in ['head.pt','RESULT.json','TRAIN-logits.npy','DEV-logits.npy']:
        parents[str(d6.OUT/'heads/entity_final-tiny_MLP'/n)]=sha(d6.OUT/'heads/entity_final-tiny_MLP'/n)
    for split in ('TRAIN','DEV'):
        for n in ['entity.npy','presence.npy','m4.npy']:parents[str(d6.OUT/'raw'/split/n)]=sha(d6.OUT/'raw'/split/n)
    audit=audit_train();write(OUT/'TRAIN-ERROR-AUDIT.json',audit)
    spec={'question':'Can root-set supervision operationalize raw-local legality access?',
      'inputs':'winning entity_final5394 plus frozen normalized T0 e64; all candidate identities, four observable ordinal bindings, exact mention vectors and final world view inherited unchanged; no truth inputs',
      'architecture':'fresh Linear5458->64 GELU Linear64->1; append learned64 coordinates to unchanged T0 e64; original completed heads unchanged',
      'parameters':349441,'initialization':'fresh torch seed20261002; no probe/head weight reuse',
      'objective':'root(row)-normalized ordinary candidate BCE + .25*(1-softJaccard) + .10*softplus(maxIllegalLogit-minLegalLogit+1). Margin only rows with both classes; each paired renderer gets equal row weight. No candidate comparator at inference.',
      'soft_jaccard':'sum(p*y)/(sum(p)+sum(y)-sum(p*y)), eps1e-6 in numerator/denominator; no cardinality oracle at inference',
      'optimization':'fixed20epochs AdamW lr.001 wd.0001; CPU4threads; paired16roots per batch; same seed/order as Phase6D; finalepoch only',
      'threshold':'fixed global probability grid .05:.01:.99,.995,.999,1.001; TRAIN exact-set recovery then fewer FP+FN then higher threshold; no DEV weights/threshold selection',
      'packing':'valid canonical candidates only, dense FP32 mmap; row offsets preserve root/candidate order. Pads excluded from all loss, norms and endpoint metrics; reconstructed full171-width output masks pads.',
      'normalization':'raw TRAIN scaler from Phase6D winning readout, same eligible universe; new T0 TRAIN valid-candidate mean/std floor1e-4',
      'population':'matched eligible TRAIN1333/DEV333 canonical roots, each two renderings; conditional EXECUTE panel, not full BANK population; every canonical candidate retained',
      'disposition':'compare exact-set and filtered ranking changes descriptively with root-paired intervals; no external qualification, widening or rescue',
      'TRAIN_audit_sha256':sha(OUT/'TRAIN-ERROR-AUDIT.json'),'parents':parents,
      'sources':{p.name:sha(p) for p in HERE.glob('*.py')},'protected_evaluation_opened':False,'backbone_adaptation':False}
    write(OUT/'SPEC.json',spec);return spec

def verify():
    spec=read(OUT/'SPEC.json')
    for name,h in spec['sources'].items():
        if sha(HERE/name)!=h:raise ValueError('Source changed '+name)
    return spec

def prepare(split):
    if split not in ('TRAIN','DEV'):raise ValueError('Protected boundary')
    d=d6.load(split);folder=OUT/'data'/split;folder.mkdir(parents=True,exist_ok=True)
    if (folder/'RECEIPT.json').exists():return
    scaler=OUT/'normalization.pt'
    if not scaler.exists():
        if split!='TRAIN':raise ValueError('TRAIN statistics required')
        a=torch.load(d6.OUT/'heads/entity_final-tiny_MLP/head.pt',weights_only=True,map_location='cpu')
        x=np.array(d['e'][d['mask']],dtype=np.float64);mean=x.mean(0).astype(np.float32);std=np.maximum(x.std(0),1e-4).astype(np.float32)
        torch.save({'raw_mean':a['mean'],'raw_std':a['std'],'e_mean':torch.from_numpy(mean),'e_std':torch.from_numpy(std)},scaler)
    a=torch.load(scaler,weights_only=True,map_location='cpu');offset=np.r_[0,np.cumsum(d['mask'].sum(1))].astype(np.int64)
    x=np.lib.format.open_memmap(folder/'X.npy',mode='w+',dtype=np.float32,shape=(int(offset[-1]),5458))
    for at in range(0,len(d['mask']),16):
        rows=np.arange(at,min(at+16,len(d['mask'])));m=d['mask'][rows]
        raw=(d6.features(d,rows,'entity_final')-a['raw_mean'].numpy())/a['raw_std'].numpy()
        e=(np.array(d['e'][rows])-a['e_mean'].numpy())/a['e_std'].numpy()
        x[offset[at]:offset[rows[-1]+1]]=np.concatenate((raw[m],e[m]),-1)
    x.flush();np.save(folder/'offset.npy',offset);np.save(folder/'y.npy',d['y'][d['mask']].astype(np.float32))
    write(folder/'RECEIPT.json',{'rows':len(d['mask']),'roots':len(d['mask'])//2,'valid_candidates':int(offset[-1]),'width':5458,'files':{n:sha(folder/n) for n in ['X.npy','y.npy','offset.npy']},'protected_contact':False})

def packed(split):
    folder=OUT/'data'/split
    return np.load(folder/'X.npy',mmap_mode='r'),np.load(folder/'y.npy'),np.load(folder/'offset.npy')

def net():return torch.nn.Sequential(torch.nn.Linear(5458,64),torch.nn.GELU(),torch.nn.Linear(64,1))

def losses(logits,y,owner,n):
    counts=torch.bincount(owner,minlength=n).to(logits.dtype)
    bce=torch.zeros(n).scatter_add_(0,owner,torch.nn.functional.binary_cross_entropy_with_logits(logits,y,reduction='none'))/counts
    p=torch.sigmoid(logits);positive=torch.zeros(n).scatter_add_(0,owner,y)
    intersect=torch.zeros(n).scatter_add_(0,owner,p*y);psum=torch.zeros(n).scatter_add_(0,owner,p)
    jac=1-(intersect+1e-6)/(psum+positive-intersect+1e-6)
    low=torch.full((n,),float('inf')).scatter_reduce_(0,owner,torch.where(y>=.5,logits,torch.inf),reduce='amin',include_self=True)
    high=torch.full((n,),-float('inf')).scatter_reduce_(0,owner,torch.where(y<.5,logits,-torch.inf),reduce='amax',include_self=True)
    active=(positive>0)&(positive<counts);margin=torch.nn.functional.softplus(high[active]-low[active]+1).mean() if active.any() else logits.sum()*0
    terms=(bce.mean(),jac.mean(),margin)
    return terms[0]+.25*terms[1]+.10*terms[2],terms

@torch.no_grad()
def infer(model,split):
    X,_,off=packed(split);d=d6.load(split);out=np.zeros_like(d['y']);model.eval()
    for at in range(0,len(out),32):
        end=min(at+32,len(out));z=model(torch.from_numpy(np.array(X[off[at]:off[end]]))).squeeze(-1).numpy();k=0
        for row in range(at,end):
            count=int(off[row+1]-off[row]);out[row,d['mask'][row]]=z[k:k+count];k+=count
    return out

def record(d,p,prob):
    r=d6.record(d,p,prob);mask=d['mask'];y=d['y']>=.5;tp=(p&y&mask).sum(1);fp=(p&~y&mask).sum(1);fn=(~p&y&mask).sum(1)
    r['row_set_precision']=float((tp/np.maximum((p&mask).sum(1),1)).mean());r['row_set_recall']=float((tp/np.maximum((y&mask).sum(1),1)).mean())
    r['error_distributions']={name:{'row_quantiles':np.quantile(v,[0,.25,.5,.75,.9,1]).tolist(),'per_root_two_renderer_total_quantiles':np.quantile(v.reshape(-1,2).sum(1),[0,.25,.5,.75,.9,1]).tolist(),'histogram':{str(int(k)):int(n) for k,n in zip(*np.unique(v,return_counts=True))}} for name,v in [('FP',fp),('FN',fn)]}
    return r
