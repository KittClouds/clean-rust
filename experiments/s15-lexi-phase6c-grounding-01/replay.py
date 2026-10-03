from c6 import *

def main():
    verify();torch.set_num_threads(4);manifest=read(OUT/'MANIFEST.json');checks=0
    for name,digest in manifest['files'].items():
        if sha(OUT/name)!=digest:raise ValueError('Artifact differs '+name)
        checks+=1
    train=load('TRAIN');dev=load('DEV');result=read(OUT/'RESULT.json');rules=[]
    for family in ['linear','tiny_MLP']:
        tr=old_scores(train,family);dv=old_scores(dev,family)
        if not np.array_equal(tr,np.load(OUT/(family+'-TRAIN-logits.npy'))) or not np.array_equal(dv,np.load(OUT/(family+'-DEV-logits.npy'))):raise ValueError('Frozen logits replay differs')
        if record(dev,sigmoid(dv)>=.5,sigmoid(dv))!=result['raw'][family]['DEV']:raise ValueError('Raw DEV metrics differ')
        for rule in calibrate(tr,train):rule['head']=family;rules.append(rule)
    saved=read(OUT/'CALIBRATION-FROZEN.json')
    if rules!=saved['rules']:raise ValueError('TRAIN calibration refit differs')
    chosen=max(range(len(rules)),key=lambda i:(*rules[i]['TRAIN_quality'],-i));rule=rules[chosen]
    if rule!=saved['chosen']:raise ValueError('Calibration choice differs')
    for split,data in [('TRAIN',train),('DEV',dev)]:
        z=np.load(OUT/(rule['head']+'-'+split+'-logits.npy'));p,mask=calibrated(z,data,rule)
        if record(data,mask,p)!=result['calibration'][split]:raise ValueError('Calibrated metric replay differs')
    inference=0
    if result['module']:
        a=torch.load(OUT/'grounder.pt',weights_only=True,map_location='cpu');norm={k:{f:v.numpy() for f,v in values.items()} for k,values in a['norm'].items()}
        expected=normalization(train)
        for key in norm:
            for field in norm[key]:
                if not np.array_equal(norm[key][field],expected[key][field]):raise ValueError('Grounder TRAIN normalization differs')
        net=Grounder();net.load_state_dict(a['model']);net.eval()
        for split,data in [('TRAIN',train),('DEV',dev)]:
            z=infer(net,data,norm);saved_z=np.load(OUT/('grounder-'+split+'-logits.npy'))
            if not np.array_equal(z,saved_z):raise ValueError('Grounder inference replay differs')
            t=result['module']['threshold']
            if split=='TRAIN' and threshold(sigmoid(z),data)!=t:raise ValueError('Grounder TRAIN threshold differs')
            if record(data,sigmoid(z)>=t,sigmoid(z))!=result['module'][split]:raise ValueError('Grounder set/ranking replay differs')
            inference+=1
    write(OUT/'REPLAY.json',{'status':'PASS','hash_checks':checks,'frozen_head_TRAIN_DEV_replays':4,'TRAIN_calibration_recomputed':True,
        'grounder_full_inference_replays':inference,'set_and_ranking_metrics_replayed':True,'protected_files_opened':0})
    print('REPLAY PASS',checks,inference,flush=True)

if __name__=='__main__':main()
