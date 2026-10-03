"""Bounded full-population surface/counter audit, TRAIN-only fitted cheap LR."""
import sys,re,time
from collections import Counter,defaultdict
import numpy as np
from common import *
sys.path.insert(0,str(REPO/'experiments/ff-s15-v2-eval-00'))
from features import B4_PHRASES,B4_FEATURE_NAMES,b4_features
from cheap_lr import MultinomialLogisticRegression

def macro(y,p,classes):
    return float(np.mean([2*np.sum((y==c)&(p==c))/max(1,np.sum(y==c)+np.sum(p==c)) for c in classes]))

def collect(split):
    rows=[];labels=[];strata=[];signatures=[];known=[]
    for path in sorted((OUTPUT/'data'/split).glob('*.gz')):
        for row in iter_rows(path):
            text=row['OBSERVATION']['rendered_text'].lower()
            features=b4_features(row)
            rows.append(features);labels.append(row['SUPERVISION_ABI']['core_targets'])
            signatures.append(tuple(int(x) for x in features[:12]))
            known.append(tuple(int(p in text) for p in ['you may ask','nobody can tell','reports that','says']))
            strata.append({'renderer':row['OBSERVATION']['renderer_family_id'],
               'hidden_count':len(row['OBSERVATION']['hidden_facts']),
               'requirement_count':row['CAPABILITY_AXES']['globalization'],
               'temporal_phrase':tuple(features[9:12]),'intervened':bool(row['BOOKKEEPING']['hidden_irrelevant_facts'])})
    return np.asarray(rows,np.float64),labels,strata,signatures,known

def main(pilot=False):
    if not pilot:verify_spec()
    t=time.perf_counter();X,yt,st,sg,kn=collect('TRAIN');V,yv,sv,vg,vkn=collect('DEV')
    edges=np.quantile(X[:,-2],np.arange(1,10)/10)
    X[:,-2]=np.searchsorted(edges,X[:,-2]);V[:,-2]=np.searchsorted(edges,V[:,-2])
    for s,v in zip(sv,V[:,-2]):s['length_decile']=int(v)
    mean=X.mean(0);std=X.std(0);std[std<1e-10]=1.;X=(X-mean)/std;V=(V-mean)/std
    results={};fails=[]
    for name in CORE_TARGETS:
        y=np.asarray([str(r[name]) for r in yt]);v=np.asarray([str(r[name]) for r in yv])
        eligible=np.ones(len(y),bool);ev=np.ones(len(v),bool)
        if name=='first_action_type':eligible=y!='NA';ev=v!='NA'
        classes=np.unique(y[eligible]);major=Counter(y[eligible]).most_common(1)[0][0]
        model=MultinomialLogisticRegression(max_iter=200,l2=1.,fit_intercept=True)
        model.fit(X[eligible],y[eligible]);pred=model.predict(V)
        table=defaultdict(Counter)
        for sig,label,ok in zip(sg,y,eligible):
            if ok:table[sig][label]+=1
        guess=np.asarray([table[sig].most_common(1)[0][0] if sig in table else major for sig in vg])
        score=macro(v[ev],pred[ev],classes);sigscore=macro(v[ev],guess[ev],classes)
        result={'B4_macro_f1':score,'complete_phrase_signature_macro_f1':sigscore,
          'majority_macro_f1':macro(v[ev],np.full(ev.sum(),major),classes),'TRAIN_rows_fit':int(eligible.sum()),
          'DEV_rows_scored':int(ev.sum()),'classes':classes.tolist(),'intercept':True,
          'iterations':int(model.n_iter_),'gradient_norm':float(model.grad_norm_),
          'scope':'fixed B4 + exact 12-phrase TRAIN-signature table, not universal cue independence',
          'strata':{}}
        for key in ('renderer','length_decile','hidden_count','requirement_count','temporal_phrase','intervened'):
            values=[canonical_json(s[key]) for s in sv]
            result['strata'][key]={}
            for value in sorted(set(values)):
                m=np.asarray([x==value for x in values])&ev
                result['strata'][key][value]={'n':int(m.sum()),'support':dict(Counter(v[m])),
                  'B4_macro_f1':macro(v[m],pred[m],classes),'status':'UNDERPOWERED' if m.sum()<200 else 'DESCRIPTIVE'}
        if name in ('disposition','reason','first_action_type') and max(score,sigscore)>=.8:
            fails.append(name)
        results[name]=result
        print(name,score,sigscore,flush=True)
        np.savez(OUTPUT/f'cue-{name}.npz',coef=model.coef_,classes=model.classes_,mean=mean,std=std,
                 intercept=model.intercept_,length_edges=edges)
    rec={'status':'PASS' if not fails else 'FAIL','failed_admissible_targets':fails,
      'all_TRAIN_DEV_rows_checked':len(X)+len(V),'known_four_phrase_counts_TRAIN':dict(Counter(map(str,kn))),
      'known_four_phrase_counts_DEV':dict(Counter(map(str,vkn))),
      'conflict_disposition':'DIAGNOSTIC_ONLY; repaired surface independently measured, no promotion',
      'B3_legacy_limit':'100k TRAIN head fit; no guaranteed DEV bias direction; five negative cue findings qualified',
      'results':results,'seconds':time.perf_counter()-t,'TRAIN_only_fit':True}
    rec['engineering_pilot']=pilot
    write(OUTPUT/'CUE-RECHECK.json',rec)
    if fails:raise ValueError('G19 target surface shortcut: '+str(fails))

if __name__=='__main__':main()
