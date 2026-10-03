"""Fresh process: parent custody, every forward output and metric replay."""
from d6 import *
def main():
    spec=verify();torch.set_num_threads(4)
    for path,digest in spec['parents'].items():
        if sha(path)!=digest:raise ValueError('Frozen input changed '+path)
    for name,digest in read(OUT/'MANIFEST.json')['files'].items():
        if sha(OUT/name)!=digest:raise ValueError('Output changed '+name)
    train=load('TRAIN');dev=load('DEV');r=read(OUT/'RESULT.json');checked={}
    for key,receipt in r['results'].items():
        folder=OUT/'heads'/key;a=torch.load(folder/'head.pt',weights_only=True,map_location='cpu');net=network(a['width'],a['family']);net.load_state_dict(a['state'])
        mean,std=a['mean'].numpy(),a['std'].numpy();maximum=0.
        for split,d in [('TRAIN',train),('DEV',dev)]:
            expected=np.load(folder/(split+'-logits.npy'));actual=infer(net,d,a['panel'],mean,std);delta=float(np.max(np.abs(actual-expected)));maximum=max(maximum,delta)
            if delta>1e-5:raise ValueError('Forward replay failed')
            prob=c6.sigmoid(actual)
            if split=='TRAIN':
                if c6.threshold(prob,d)!=receipt['threshold_TRAIN']:raise ValueError('TRAIN threshold replay')
            else:
                for field,t in [('DEV',receipt['threshold_TRAIN']),('DEV_uncalibrated',.5)]:
                    if json.dumps(record(d,prob>=t,prob),sort_keys=True,default=lambda v:v.item())!=json.dumps(receipt[field],sort_keys=True):raise ValueError('Metric replay '+key)
        checked[key]={'maximum_logit_difference':maximum,'TRAIN_threshold_replayed':True,'DEV_metrics_replayed':True}
    write(OUT/'REPLAY.json',{'status':'PASS','parent_hashes_verified':len(spec['parents']),'heads':checked,'protected_evaluation_opened':False,'fresh_process':True})
if __name__=='__main__':main()
