"""One bounded access follow-up, justified by paired raw-local improvement."""
from d6 import *
import subprocess
ADAPT=OUT.parent/'lexi-phase6d-access-adapter-20261002-v01'

def input_batch(d,rows,raw_mean,raw_std,e_mean,e_std):
    raw=(features(d,rows,'entity_final')-raw_mean)/raw_std
    e=(np.array(d['e'][rows])-e_mean)/e_std
    return torch.from_numpy(np.concatenate((raw,e),-1))

def trigger(dev):
    r=read(OUT/'heads/entity_final-linear/RESULT.json');p=c6.sigmoid(np.load(OUT/'heads/entity_final-linear/DEV-logits.npy'))>=r['threshold_TRAIN']
    old=read(c6.OUT/'RESULT.json')['calibration']['rule'];_,q=c6.calibrated(np.load(c6.OUT/(old['head']+'-DEV-logits.npy')),dev,old)
    good_p=~(((p!=(dev['y']>=.5))&dev['mask']).any(1));good_q=~(((q!=(dev['y']>=.5))&dev['mask']).any(1))
    delta=(good_p.astype(float)-good_q).reshape(-1,2).mean(1);rng=np.random.default_rng(SEED)
    boot=np.array([delta[rng.integers(len(delta),size=len(delta))].mean() for _ in range(2000)])
    interval=np.quantile(boot,[.025,.975]).tolist()
    return {'raw_panel':'entity_final','readout':'linear','paired_root_mean_exact_set_gain':float(delta.mean()),'paired_root_bootstrap95':interval,
      'earned':bool(delta.mean()>=.03 and interval[0]>0),'scope':'partial raw-access advantage, not precise legal-set qualification',
      'decision_provenance':'follow-up trigger recorded after raw audit; user explicitly requested one adapter upon material raw improvement. Original v01 .25 gate is preserved as a strong-fidelity reference, not falsely declared passed.'}

@torch.no_grad()
def infer_adapter(net,d,norm):
    net.eval();parts=[]
    for at in range(0,len(d['mask']),32):
        rows=np.arange(at,min(at+32,len(d['mask'])));parts.append(net(input_batch(d,rows,*norm)).squeeze(-1).numpy())
    return np.concatenate(parts)

def specification(t):
    return {'trigger':t,'question':'Can one compact raw-to-candidate access adapter preserve the partial legality signal lost through T0?',
      'architecture':'one scalar Linear([normalized raw entity_final5394; normalized frozen T0 e64]) -> legality logit; append this one learned coordinate to e without changing its original64 coordinates. Existing heads consume their original slices, unchanged.',
      'trainable_parameters':5459,'runtime_semantics':'estimate.candidate_legal; MODEL_ESTIMATE; not oracle truth or deterministic simulator legality',
      'training':'TRAIN only20fixedepochs; same seed/root-paired16roots batches/AdamW .001 wd.0001/rootmean TRAIN-prevalence-balanced BCE; no additional margin or loss search',
      'threshold':'TRAIN-only exact-set grid identical to raw panel; DEV never selects weights or threshold',
      'selection':'one finalepoch; no new panel/family comparison; no subsequent rescue if weak',
      'source_sha256':sha(Path(__file__)),'raw_manifest_sha256':sha(OUT/'MANIFEST.json'),'protected_contact':False}

def main():
    torch.set_num_threads(4);train=load('TRAIN');dev=load('DEV')
    if '--replay' in sys.argv:
        spec=read(ADAPT/'SPEC.json')
        if sha(Path(__file__))!=spec['source_sha256'] or sha(OUT/'MANIFEST.json')!=spec['raw_manifest_sha256']:raise ValueError('Adapter identity')
        a=torch.load(ADAPT/'adapter.pt',weights_only=True,map_location='cpu');net=torch.nn.Linear(5458,1);net.load_state_dict(a['state']);norm=[a[k].numpy() for k in ['raw_mean','raw_std','e_mean','e_std']];r=read(ADAPT/'RESULT.json')
        for split,d in [('TRAIN',train),('DEV',dev)]:
            z=infer_adapter(net,d,norm)
            if np.max(np.abs(z-np.load(ADAPT/(split+'-logits.npy'))))>1e-5:raise ValueError('Adapter forward replay')
            p=c6.sigmoid(z)
            if split=='TRAIN' and c6.threshold(p,d)!=r['threshold_TRAIN']:raise ValueError('Threshold replay')
            if split=='DEV' and record(d,p>=r['threshold_TRAIN'],p)!=r['DEV']:raise ValueError('Adapter metric replay')
        write(ADAPT/'REPLAY.json',{'status':'PASS','fresh_process':True,'original_e64_preserved':True,'protected_evaluation_opened':False});return
    t=trigger(dev)
    if not t['earned']:print('NO_MATERIAL_RAW_ACCESS_TRIGGER',t,flush=True);return
    ADAPT.mkdir(parents=True,exist_ok=True)
    if (ADAPT/'adapter.pt').exists():raise ValueError('Completed adapter identity already exists')
    write(ADAPT/'SPEC.json',specification(t));a=torch.load(OUT/'heads/entity_final-linear/head.pt',weights_only=True,map_location='cpu')
    e=np.array(train['e'][train['mask']],dtype=np.float64);mean=e.mean(0).astype(np.float32);std=np.maximum(e.std(0),1e-4).astype(np.float32);del e
    norm=[a['mean'].numpy(),a['std'].numpy(),mean,std];torch.manual_seed(SEED);net=torch.nn.Linear(5458,1);opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.0001)
    pi=float(train['y'][train['mask']].mean());curves=[];start=time.perf_counter()
    for epoch in range(20):
        order=np.arange(len(train['mask'])//2);np.random.default_rng(SEED+epoch).shuffle(order);total=0.;count=0
        for at in range(0,len(order),16):
            rows=np.stack((2*order[at:at+16],2*order[at:at+16]+1),-1).ravel();x=input_batch(train,rows,*norm)
            y=torch.from_numpy(train['y'][rows]);mask=torch.from_numpy(train['mask'][rows]);z=net(x).squeeze(-1)
            loss=((torch.nn.functional.binary_cross_entropy_with_logits(z,y,reduction='none')*.5*(y/pi+(1-y)/(1-pi))*mask).sum(1)/mask.sum(1)).mean()
            if not torch.isfinite(loss):raise ValueError('Invalid adapter loss')
            opt.zero_grad(set_to_none=True);loss.backward();opt.step();total+=float(loss.detach())*len(rows);count+=len(rows)
        curves.append(total/count)
        if epoch%5==0:print('ACCESS_ADAPTER',epoch+1,'seconds',round(time.perf_counter()-start,1),flush=True)
    seconds=time.perf_counter()-start
    torch.save({'state':net.state_dict(),**{k:torch.from_numpy(v) for k,v in zip(['raw_mean','raw_std','e_mean','e_std'],norm)}},ADAPT/'adapter.pt')
    zz=infer_adapter(net,train,norm);np.save(ADAPT/'TRAIN-logits.npy',zz);threshold=c6.threshold(c6.sigmoid(zz),train)
    zz=infer_adapter(net,dev,norm);np.save(ADAPT/'DEV-logits.npy',zz);prob=c6.sigmoid(zz)
    x=input_batch(dev,np.arange(32),*norm)
    with torch.no_grad():
        for _ in range(3):net(x)
        start=time.perf_counter()
        for _ in range(10):net(x)
    latency=(time.perf_counter()-start)/10
    r={'trigger':t,'threshold_TRAIN':threshold,'DEV':record(dev,prob>=threshold,prob),'curves':curves,'training_seconds':seconds,'trainable_parameters':5459,'batch32_CPU_head_latency_seconds':latency,'candidate_state_contract':'[original e64; raw-access legality logit1]; original coordinates and completed heads unchanged','protected_evaluation_opened':False}
    write(ADAPT/'RESULT.json',r);write(ADAPT/'MANIFEST.json',{'files':{p.name:sha(p) for p in ADAPT.iterdir() if p.is_file()}})
    subprocess.run([sys.executable,'-B',str(Path(__file__)),'--replay'],check=True)
    write(ADAPT/'FINAL-STATUS.json',{'status':'SEALED_AND_FRESH_PROCESS_REPLAYED','manifest_sha256':sha(ADAPT/'MANIFEST.json'),'replay_sha256':sha(ADAPT/'REPLAY.json'),'disposition':'ACCESS_PATH_REPAIR_TESTED_PARTIAL','production_promotion':False})
    print('ACCESS_ADAPTER_SEALED',flush=True)
if __name__=='__main__':main()
