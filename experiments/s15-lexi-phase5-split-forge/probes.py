"""Fixed shallow accessibility panel. TRAIN fit, DEV scoring, no selection."""
from report import *

def probe(pop,dev,identity,kind,channel,nonlinear):
    folder=OUT/'states'/identity;candidate=kind=='e'
    tx=np.load(folder/('TRAIN-'+kind+'.npy'),mmap_mode='r');dx=np.load(folder/('DEV-'+kind+'.npy'),mmap_mode='r')
    ykey='cy' if candidate else 'gy';mkey='ca' if candidate else 'ga'
    # Statistics use TRAIN valid coordinates only, in streaming chunks.
    total=np.zeros(64,np.float64);squares=total.copy();n=0
    for i in range(0,pop.n,64):
        valid=pop.arrays[mkey][i:i+64,...,channel];x=np.asarray(tx[i:i+64])[valid].astype(np.float64)
        total+=x.sum(0);squares+=(x*x).sum(0);n+=len(x)
    mean=total/n;std=np.sqrt(np.maximum(squares/n-mean*mean,1e-8))
    labels=pop.arrays[ykey][...,channel][pop.arrays[mkey][...,channel]];pi=float(labels.mean())
    torch.manual_seed(20261002)
    head=torch.nn.Sequential(torch.nn.Linear(64,64),torch.nn.GELU(),torch.nn.Linear(64,1)) if nonlinear else torch.nn.Linear(64,1)
    head.cuda();optimizer=torch.optim.AdamW(head.parameters(),lr=.001,weight_decay=.0001)
    mean=torch.tensor(mean,dtype=torch.float32,device='cuda');std=torch.tensor(std,dtype=torch.float32,device='cuda')
    for epoch in range(4):
        for batch in pop.batches(True,epoch):
            ids=batch['ids'];x=torch.tensor(np.array(tx[ids]),device='cuda');valid=batch[mkey][...,channel]
            logits=head((x-mean)/std).squeeze(-1)
            value=balanced(logits,batch[ykey][...,channel],valid,pi)
            optimizer.zero_grad(set_to_none=True);value.backward();optimizer.step()
    preds=[];truth=[];renderers=[]
    with torch.no_grad():
        for i in range(0,dev.n,64):
            x=torch.tensor(np.array(dx[i:i+64]),device='cuda');valid=dev.arrays[mkey][i:i+64,...,channel]
            p=(head((x-mean)/std).squeeze(-1).cpu().numpy()>=0)
            preds.extend(p[valid].tolist());truth.extend(dev.arrays[ykey][i:i+64,...,channel][valid].tolist())
    family='tiny_MLP' if nonlinear else 'linear';target=('candidate_legal','candidate_satisfies_goal')[channel] if candidate else ('solvable','goal_satisfied','missing_information_present')[channel]
    dest=OUT/'probes';dest.mkdir(exist_ok=True);path=dest/(identity+'-'+target+'-'+family+'.pt')
    torch.save({'head':head.state_dict(),'TRAIN_mean':mean.cpu(),'TRAIN_std':std.cpu(),'pi':pi},path)
    return {'identity':identity,'target':target,'family':family,'DEV':binary(truth,preds),'TRAIN_prevalence':pi,
      'TRAIN_only_fit':True,'artifact_sha256':sha(path),'trainable_parameters':sum(p.numel() for p in head.parameters())}

def panel(train,dev):
    result=[]
    for identity in ['INIT','BRIDGE']:
        for kind,channels in [('s',[1,2]),('e',[0,1])]:
            for channel in channels:
                for nonlinear in [False,True]:
                    row=probe(train,dev,identity,kind,channel,nonlinear);result.append(row);print('PROBE',json.dumps(row),flush=True)
    write(OUT/'ACCESSIBILITY.json',result)

