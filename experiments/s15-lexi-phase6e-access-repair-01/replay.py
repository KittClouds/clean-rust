"""Fresh-process raw predictions, thresholds, metrics, state and custody."""
from e6 import *
def main():
    spec=verify();torch.set_num_threads(4)
    for path,h in spec['parents'].items():
        if sha(path)!=h:raise ValueError('Parent bytes changed '+path)
    for name,h in read(OUT/'MANIFEST.json')['files'].items():
        if sha(OUT/name)!=h:raise ValueError('Output bytes changed '+name)
    a=torch.load(OUT/'adapter.pt',weights_only=True,map_location='cpu');model=net();model.load_state_dict(a['state']);r=read(OUT/'RESULT.json');checks={}
    for split in ('TRAIN','DEV'):
        d=d6.load(split);z=infer(model,split);expected=np.load(OUT/(split+'-logits.npy'));delta=float(np.max(np.abs(z-expected)))
        if delta>1e-5:raise ValueError('Prediction mismatch')
        p=d6.c6.sigmoid(z)
        if split=='TRAIN' and d6.c6.threshold(p,d)!=r['threshold_TRAIN']:raise ValueError('Threshold mismatch')
        measured=record(d,p>=r['threshold_TRAIN'],p)
        if json.dumps(measured,sort_keys=True,default=lambda v:v.item())!=json.dumps(r[split],sort_keys=True):raise ValueError('Metric mismatch')
        checks[split]={'rows':len(d['mask']),'candidates':int(d['mask'].sum()),'maximum_logit_difference':delta}
    dev=d6.load('DEV');s=np.load(OUT/'DEV-local-state.npy',mmap_mode='r')
    if not np.array_equal(s[:,:,:64][dev['mask']],dev['e'][dev['mask']]):raise ValueError('Original T0 state changed')
    # Independent Python set reconstruction validates exact-set metric.
    pred=d6.c6.sigmoid(np.load(OUT/'DEV-logits.npy'))>=r['threshold_TRAIN'];correct=0
    for i in range(len(pred)):
        gold={j for j in range(171) if dev['mask'][i,j] and dev['y'][i,j]>=.5};guess={j for j in range(171) if dev['mask'][i,j] and pred[i,j]};correct+=gold==guess
    if correct/len(pred)!=r['DEV']['full_legal_set']['exact_set']:raise ValueError('Explicit set mismatch')
    write(OUT/'REPLAY.json',{'status':'PASS','fresh_process':True,'checks':checks,'parent_hashes':len(spec['parents']),'original_candidate_state_preserved':True,'explicit_set_replay':True,'protected_evaluation_opened':False})
if __name__=='__main__':main()
