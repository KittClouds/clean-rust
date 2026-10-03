"""Frozen T0 legality calibration and one bounded interaction module."""
import sys,json,time,hashlib
from pathlib import Path
import numpy as np
import torch
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'s15-lexi-phase6b-within-type-01'))
import b6_contract as parent
from b6_probes import model
from ranking import binary,recorder
OUT=Path('C:/phoenix-target-overgraph/lexi-phase6c-grounding-20261002-v01')
P6=parent.PREVIOUS;P5=parent.inherited.P5;P6B=parent.OUT
SEED=20261002
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,v):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    Path(p).write_text(json.dumps(v,sort_keys=True,indent=2,allow_nan=False,default=lambda x:x.item() if isinstance(x,np.generic) else x)+'\n',encoding='utf-8')

def load(split):
    if split not in ['TRAIN','DEV']:raise ValueError('Protected boundary')
    folder=P6/'cache'/split;ids=np.load(folder/'ids.npy');mask=np.load(folder/'mask.npy')
    return {'e':np.load(folder/'T0-e.npy',mmap_mode='r'),'s':np.load(folder/'T0-s.npy',mmap_mode='r'),
       'H':np.load(P5/'data'/split/'H.npy',mmap_mode='r')[ids],
       'A':np.load(P5/'data'/split/'A.npy',mmap_mode='r')[ids],
       'mask':mask,'y':np.load(P6B/'gold'/split/'features.npy')[:,:,0],
       'factors':np.load(P6B/'gold'/split/'features.npy'),
       'selected':np.load(folder/'selected.npy'),'optimal':np.load(folder/'optimal.npy'),
       'types':np.load(folder/'types.npy'),'meta':read(folder/'metadata.json'),'ids':ids}

def freeze():
    OUT.mkdir(exist_ok=True)
    if (OUT/'SPEC.json').exists():return verify()
    parent.verify()
    spec={'surface':'frozen T0 projected e64/s64 plus existing H2048 and canonical five-field A; no new extraction',
      'population':'Phase6B eligible-root panel:1333TRAIN/333DEV roots, two renderings each, every candidate retained. Claims conditional on selected-action eligibility; not all BANK contexts.',
      'calibration':'linear and tinyMLP existing T0 legality heads; frozen20epoch artifacts; replay TRAIN logits; calibrate TRAIN only',
      'threshold_family':'global threshold and per-type threshold; fixed probability grid .05:.01:.99 plus .995,.999,1.001; TRAIN exact full legal-set fraction then mean FP+FN then higher threshold; per-type coordinate search two fixed passes in vocabulary order starting at global optimum',
      'affine':'TRAIN-only unweighted BCE sigmoid(a*logit+b); a=softplus(raw_a); 200Adam steps lr.03; threshold same grid',
      'calibration_selection':'highest TRAIN exact full legal set then lowest TRAIN FP+FN then fixed family order; no DEV selection',
      'module_gate':'calibration sufficient iff TRAIN and DEV exact full legal sets >=.25 and DEV exact same-type legal sets >=.25; otherwise one prospective fixed module. Threshold practical reference, not external safety claim.',
      'module':'candidate=[normalized frozen e64;type8;four role-specific entity8 embeddings] ->32 GELU; world=[normalized H2048;s64]->32 GELU; [c,w,c*w] ->32 GELU ->scalar. No setwise candidate interaction.',
      'objective':'root-mean ordinary masked BCE + .25*softplus(max illegal logit - min legal logit + 1); margin valid only roots containing both classes; no cardinality truth at inference',
      'optimization':'fixed20epochs AdamW lr.001 wd.0001;paired roots32/batch;seed20261002;CPU4threads;frozen states;no DEV checkpoint selection',
      'module_threshold':'TRAIN-only grid exact-set selection as calibrated heads; DEV evaluated after threshold frozen',
      'ranking':'fixed frozen T0 production score ranked after predicted legality mask; oracle gold legality mask diagnostic only; no fallback when selected excluded; raw grounding-score ranking separate',
      'retired':'B remains retired; A/backbone/bridge unchanged; protected evaluation unopened',
      'sources':{p.name:sha(p) for p in HERE.glob('*.py')},
      'parent_manifest_sha256':sha(P6B/'MANIFEST.json'),
      'checkpoint_sha256':sha(P5/'models/BRIDGE/best.pt')}
    write(OUT/'SPEC.json',spec);return spec
def verify():
    s=read(OUT/'SPEC.json');parent.verify()
    for n,h in s['sources'].items():
        if sha(HERE/n)!=h:raise ValueError('Changed source '+n)
    if sha(P6B/'MANIFEST.json')!=s['parent_manifest_sha256'] or sha(P5/'models/BRIDGE/best.pt')!=s['checkpoint_sha256']:raise ValueError('Changed parent')
    return s

@torch.no_grad()
def old_scores(data,family):
    folder=P6B/'heads'/f'T0-{family}-factors';a=torch.load(folder/'head.pt',weights_only=True,map_location='cpu')
    net=model(a['inputs'],a['outputs'],family);net.load_state_dict(a['state']);net.eval();out=[]
    for at in range(0,len(data['e']),64):
        x=(torch.tensor(np.array(data['e'][at:at+64]))-a['mean'])/a['std'];out.append(net(x).squeeze(-1).numpy())
    return np.concatenate(out)

def sigmoid(x):return 1/(1+np.exp(-np.clip(x,-60,60)))
def set_metrics(y,p,mask):
    y=y.astype(bool)&mask;p=p.astype(bool)&mask;tp=(y&p).sum(1);fp=(~y&p&mask).sum(1);fn=(y&~p&mask).sum(1)
    union=(y|p).sum(1);den=y.sum(1)+p.sum(1)
    r=binary(y[mask],p[mask]);r['precision']=int(tp.sum())/max(1,int(tp.sum()+fp.sum()));r['recall']=int(tp.sum())/max(1,int(tp.sum()+fn.sum()))
    r.update({'exact_set':float(((fp+fn)==0).mean()),'Jaccard':float(np.divide(tp,union,out=np.ones(len(tp)),where=union>0).mean()),
        'set_F1':float(np.divide(2*tp,den,out=np.ones(len(tp)),where=den>0).mean()),
        'FP_mean_per_row':float(fp.mean()),'FN_mean_per_row':float(fn.mean()),
        'FP_mean_per_root_total':float(fp.reshape(-1,2).sum(1).mean()),'FN_mean_per_root_total':float(fn.reshape(-1,2).sum(1).mean()),
        'rows':len(mask),'paired_roots':len(mask)//2,'valid_candidates':int(mask.sum())})
    return r

def record(data,pred,prob):
    mask=data['mask'];y=data['y'];types=data['types'];a=data['selected'];goldtype=types[np.arange(len(a)),a]
    same=mask&(types==goldtype[:,None]);r={'full_legal_set':set_metrics(y,pred,mask),'same_type_legal_set':set_metrics(y,pred,same)}
    split='DEV' if len(a)==666 else 'TRAIN'
    scores=np.load(P6/'cache'/split/'T0-production.npy')
    for name,allowed in [('predicted_legal',mask&pred),('gold_legal_ORACLE',mask&(y>=.5))]:
        rank,_=recorder(scores,allowed,a,data['optimal'],types,goldtype-1,data['meta']);r[name]=rank
    rank,_=recorder(prob,mask,a,data['optimal'],types,goldtype-1,data['meta']);r['grounding_score_ranking']=rank
    legal=data['y'].astype(bool);pairs={'selected_vs_illegal':[],'selected_vs_legal':[]}
    for i,k in enumerate(a):
        for j in np.flatnonzero(same[i]):
            if j==k:continue
            key='selected_vs_legal' if legal[i,j] else 'selected_vs_illegal'
            pairs[key].append(float(prob[i,k]>prob[i,j])+.5*float(prob[i,k]==prob[i,j]))
    r['same_type_pair_discrimination']={k:{'pairs':len(v),'selected_higher_with_half_ties':float(np.mean(v)) if v else None} for k,v in pairs.items()}
    r['error_slices']={}
    def candidate_slice(name,take):
        take=take&mask;r['error_slices'][name]={'candidates':int(take.sum()),'FP':int((pred&~legal&take).sum()),'FN':int((~pred&legal&take).sum()),
           'precision':float((pred&legal&take).sum()/max(1,(pred&take).sum())),'recall':float((pred&legal&take).sum()/max(1,(legal&take).sum()))}
    for typ,name in enumerate(parent.inherited.VOCAB,1):candidate_slice(name,types==typ)
    candidate_slice('missing_positive_precondition',data['factors'][:,:,5]<1)
    candidate_slice('negative_precondition_failed',data['factors'][:,:,6]<.5)
    candidate_slice('actor_binding_matches',data['factors'][:,:,2]>=.5)
    candidate_slice('goal_argument_matches',data['factors'][:,:,3]>0)
    r['root_slices']={}
    counts=mask.sum(1);legal_counts=(legal&same).sum(1)
    for lo,hi in [(1,16),(17,32),(33,64),(65,96),(97,128),(129,171)]:
        take=(counts>=lo)&(counts<=hi)
        if take.any():r['root_slices'][f'candidates_{lo}_{hi}']=set_metrics(y[take],pred[take],mask[take])
    for count in np.unique(legal_counts):
        take=legal_counts==count;r['root_slices'][f'same_type_legal_count_{int(count)}']=set_metrics(y[take],pred[take],same[take])
    r['permission_semantics']='Environment legality ignores permission. Permission is a different ABI coordinate; no relabeling legal as permitted.'
    return r

GRID=np.r_[np.arange(.05,1.,.01),.995,.999,1.001]
def quality(y,p,mask):
    errors=((y>=.5)!=p)&mask;return (float((~errors.any(1)).mean()),-float(errors.sum(1).mean()))
def threshold(prob,data):
    best=None
    for t in GRID:
        q=(*quality(data['y'],prob>=t,data['mask']),float(t))
        if best is None or q>best[0]:best=(q,float(t))
    return best[1]
def calibrated(logits,data,rule):
    p=sigmoid(logits*rule.get('slope',1)+rule.get('intercept',0))
    t=np.asarray(rule['threshold'])
    return p,p>= (t[data['types']] if t.ndim else t)

def calibrate(logits,data):
    prob=sigmoid(logits);t=threshold(prob,data);rules=[{'family':'global','threshold':t}]
    ts=np.full(10,t)
    for _ in range(2):
        for k in range(1,10):
            best=None
            for value in GRID:
                cand=ts.copy();cand[k]=value;q=(*quality(data['y'],prob>=cand[data['types']],data['mask']),float(value))
                if best is None or q>best[0]:best=(q,float(value))
            ts[k]=best[1]
    rules.append({'family':'per_type','threshold':ts.tolist()})
    x=torch.tensor(logits[data['mask']]);y=torch.tensor(data['y'][data['mask']]);a=torch.tensor(.5413249,requires_grad=True);b=torch.tensor(0.,requires_grad=True)
    opt=torch.optim.Adam([a,b],lr=.03)
    for _ in range(200):
        loss=torch.nn.functional.binary_cross_entropy_with_logits(torch.nn.functional.softplus(a)*x+b,y)
        opt.zero_grad(set_to_none=True);loss.backward();opt.step()
    slope=float(torch.nn.functional.softplus(a).detach());intercept=float(b.detach());p=sigmoid(logits*slope+intercept)
    rules.append({'family':'affine','slope':slope,'intercept':intercept,'threshold':threshold(p,data)})
    for rule in rules:
        p,pred=calibrated(logits,data,rule);rule['TRAIN_quality']=list(quality(data['y'],pred,data['mask']))
    return rules

class Grounder(torch.nn.Module):
    def __init__(self):
        super().__init__();self.typ=torch.nn.Embedding(10,8,padding_idx=0)
        self.args=torch.nn.ModuleList([torch.nn.Embedding(65,8,padding_idx=0) for _ in range(4)])
        self.c=torch.nn.Sequential(torch.nn.Linear(104,32),torch.nn.GELU())
        self.w=torch.nn.Sequential(torch.nn.Linear(2112,32),torch.nn.GELU())
        self.out=torch.nn.Sequential(torch.nn.Linear(96,32),torch.nn.GELU(),torch.nn.Linear(32,1))
    def forward(self,e,s,H,A):
        a=torch.cat([self.typ(A[:,:,0]),*[self.args[k](A[:,:,k+1]) for k in range(4)]],-1)
        c=self.c(torch.cat([e.detach(),a],-1));w=self.w(torch.cat([H.detach(),s.detach()],-1))[:,None,:].expand_as(c)
        return self.out(torch.cat([c,w,c*w],-1)).squeeze(-1)

def normalization(data):
    r={}
    for key,x in [('e',data['e'][data['mask']]),('s',data['s']),('H',data['H'])]:
        x=x.astype(np.float64);r[key]={'mean':x.mean(0).astype(np.float32),'std':np.maximum(x.std(0),1e-4).astype(np.float32)}
    return r
def batch(data,norm,ids):
    return [torch.tensor((np.array(data[k][ids])-norm[k]['mean'])/norm[k]['std']) for k in ['e','s','H']]+[torch.tensor(data['A'][ids],dtype=torch.long)]

@torch.no_grad()
def infer(net,data,norm):
    parts=[];net.eval()
    for at in range(0,len(data['e']),64):parts.append(net(*batch(data,norm,np.arange(at,min(at+64,len(data['e']))))).numpy())
    return np.concatenate(parts)

def train_module(train,dev):
    torch.manual_seed(SEED);norm=normalization(train);net=Grounder();opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.0001)
    curves=[];start=time.perf_counter()
    for epoch in range(20):
        order=np.arange(len(train['e'])//2);np.random.default_rng(SEED+epoch).shuffle(order);total=0.;cnt=0
        for at in range(0,len(order),32):
            roots=order[at:at+32];ids=np.stack([roots*2,roots*2+1],1).reshape(-1);z=net(*batch(train,norm,ids));y=torch.tensor(train['y'][ids]);mask=torch.tensor(train['mask'][ids]);legal=(y>=.5)&mask;illegal=(y<.5)&mask
            bce=torch.nn.functional.binary_cross_entropy_with_logits(z,y,reduction='none');bce=(bce*mask).sum(1)/mask.sum(1)
            valid=legal.any(1)&illegal.any(1);margin=torch.nn.functional.softplus(z.masked_fill(~illegal,-1e9).max(1).values-z.masked_fill(~legal,1e9).min(1).values+1)
            loss=bce.mean()+.25*margin[valid].mean()
            if not torch.isfinite(loss):raise ValueError('Nonfinite grounding objective')
            opt.zero_grad(set_to_none=True);loss.backward();opt.step();total+=float(loss.detach())*len(ids);cnt+=len(ids)
        curves.append({'epoch':epoch+1,'TRAIN_loss':total/cnt});print('GROUNDING',epoch+1,total/cnt,flush=True)
    seconds=time.perf_counter()-start;tr=infer(net,train,norm);dv=infer(net,dev,norm)
    artifact={'model':net.state_dict(),'norm':{k:{f:torch.tensor(v) for f,v in values.items()} for k,values in norm.items()}}
    torch.save(artifact,OUT/'grounder.pt');np.save(OUT/'grounder-TRAIN-logits.npy',tr);np.save(OUT/'grounder-DEV-logits.npy',dv)
    sample=batch(dev,norm,np.arange(64));net.eval()
    with torch.no_grad():
        for _ in range(5):net(*sample)
        start=time.perf_counter()
        for _ in range(50):net(*sample)
        latency=(time.perf_counter()-start)/50
    write(OUT/'GROUNDING-RECEIPT.json',{'epochs':20,'curves':curves,'TRAIN_only':True,'DEV_checkpoint_selection':False,
        'seconds':seconds,'params':sum(p.numel() for p in net.parameters()),'batch64_CPU_latency_seconds':latency,'threads':4,
        'state_parameters_changed':0,'protected_files_opened':0})
    return tr,dv
