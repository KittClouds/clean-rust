"""Reuse the once-fitted raw MLP as the single candidate access adapter."""
from d6 import *
import subprocess,shutil
ADAPT=OUT.parent/'lexi-phase6d-access-adapter-20261002-v02'

@torch.no_grad()
def adapted(net,d,mean,std):
    states=[];scores=[]
    for at in range(0,len(d['mask']),32):
        rows=np.arange(at,min(at+32,len(d['mask'])));x=batch(d,rows,'entity_final',mean,std)
        local=net[1](net[0](x));z=net[2](local).squeeze(-1)
        joined=np.concatenate((np.array(d['e'][rows]),local.numpy()),-1)
        joined[~d['mask'][rows]]=0
        states.append(joined);scores.append(z.numpy())
    return np.concatenate(states),np.concatenate(scores)

def check():
    spec=read(ADAPT/'SPEC.json');r=read(ADAPT/'RESULT.json')
    if sha(Path(__file__))!=spec['source_sha256']:raise ValueError('Adapter source changed')
    for path,h in spec['parents'].items():
        if sha(path)!=h:raise ValueError('Adapter parent changed')
    for name,h in read(ADAPT/'MANIFEST.json')['files'].items():
        if sha(ADAPT/name)!=h:raise ValueError('Packaged artifact changed')
    a=torch.load(ADAPT/'adapter.pt',weights_only=True,map_location='cpu');net=network(a['width'],a['family']);net.load_state_dict(a['state'])
    for split in ('TRAIN','DEV'):
        d=load(split);state,z=adapted(net,d,a['mean'].numpy(),a['std'].numpy())
        if not np.array_equal(state,np.load(ADAPT/(split+'-candidate-state.npy'))):raise ValueError('Adapter state replay')
        if np.max(np.abs(z-np.load(OUT/'heads/entity_final-tiny_MLP'/(split+'-logits.npy'))))>1e-5:raise ValueError('Raw readout prediction parity')
        if not np.array_equal(state[:,:,:64][d['mask']],d['e'][d['mask']]):raise ValueError('Original candidate state changed')
        if split=='DEV':
            p=c6.sigmoid(z)
            if record(d,p>=r['threshold_TRAIN'],p)!=r['DEV']:raise ValueError('Adapter metrics')
        elif c6.threshold(c6.sigmoid(z),d)!=r['threshold_TRAIN']:raise ValueError('TRAIN threshold')
    write(ADAPT/'REPLAY.json',{'status':'PASS','fresh_process':True,'all_original_valid_e64_coordinates_preserved':True,'raw_legality_readout_parity':True,'TRAIN_threshold_and_DEV_metrics_replayed':True,'protected_evaluation_opened':False})

def main():
    torch.set_num_threads(4)
    if '--replay' in sys.argv:return check()
    folder=OUT/'heads/entity_final-tiny_MLP';r=read(folder/'RESULT.json');a=torch.load(folder/'head.pt',weights_only=True,map_location='cpu')
    if a['family']!='tiny_MLP' or a['width']!=5394:raise ValueError('Earned raw interface')
    ADAPT.mkdir(parents=True,exist_ok=True)
    if (ADAPT/'FINAL-STATUS.json').exists():raise ValueError('Already sealed')
    spec={'architecture':'[original frozen T0 e64; raw entity/world Linear64-GELU latent64] -> augmented candidate state128. Existing heads consume original64 unchanged; appended64 has the once-fitted raw legality scalar readout.',
      'runtime_output':'estimate.candidate_legal probability and TRAIN-frozen boolean; provenance MODEL_ESTIMATE, not ORACLE_TRUTH',
      'input_firewall':'existing raw panel public text/bindings/action type+ordinal; frozen T0 e. No truth inputs.',
      'training':'reuse exact raw entity tiny-MLP artifact already fit once on TRAIN for20epochs. No second fit of the same construction and no new optimizer, objective or family.',
      'decision':'user-authorized raw-access adapter after material exact-set improvement; engineering DEV evidence, not fresh external qualification. Original .25 fidelity reference stays NOT MET.',
      'prepared_scalar_followup':'access_adapter.py was prepared but NOT RUN; superseded by reusing the better once-trained local projection. No claimed additional acquisition from packaging.',
      'parents':{str(folder/n):sha(folder/n) for n in ['head.pt','RESULT.json','TRAIN-logits.npy','DEV-logits.npy']},'source_sha256':sha(Path(__file__)),'protected_evaluation_opened':False}
    write(ADAPT/'SPEC.json',spec);shutil.copyfile(folder/'head.pt',ADAPT/'adapter.pt')
    net=network(a['width'],a['family']);net.load_state_dict(a['state']);start=time.perf_counter()
    for split in ('TRAIN','DEV'):
        d=load(split);state,z=adapted(net,d,a['mean'].numpy(),a['std'].numpy());np.save(ADAPT/(split+'-candidate-state.npy'),state)
        if not np.array_equal(state[:,:,:64][d['mask']],d['e'][d['mask']]):raise ValueError('Original state mutation')
        if np.max(np.abs(z-np.load(folder/(split+'-logits.npy'))))>1e-5:raise ValueError('Prediction parity')
    result={'DEV':r['DEV'],'threshold_TRAIN':r['threshold_TRAIN'],'trainable_parameters_in_inherited_adapter':r['parameters'],
      'TRAIN_fit_seconds_once':r['train_seconds'],'additional_training_seconds':0.,'packaging_seconds':time.perf_counter()-start,
      'batch32_CPU_head_latency_seconds':r['batch32_CPU_head_latency_seconds'],'candidate_state_dimensions':128,'original_dimensions_preserved':64,'protected_evaluation_opened':False,'production_promotion':False}
    write(ADAPT/'RESULT.json',result)
    write(ADAPT/'MANIFEST.json',{'files':{p.name:sha(p) for p in ADAPT.iterdir() if p.is_file() and p.name not in ['MANIFEST.json','REPLAY.json','FINAL-STATUS.json']}})
    subprocess.run([sys.executable,'-B',str(Path(__file__)),'--replay'],check=True)
    write(ADAPT/'FINAL-STATUS.json',{'status':'SEALED_AND_FRESH_PROCESS_REPLAYED','manifest_sha256':sha(ADAPT/'MANIFEST.json'),'replay_sha256':sha(ADAPT/'REPLAY.json'),'disposition':'ACCESS_PATH_REPAIR_PARTIAL','production_promotion':False})
    print('ACCESS_ADAPTER_PACKAGED_AND_REPLAYED',flush=True)
if __name__=='__main__':main()
