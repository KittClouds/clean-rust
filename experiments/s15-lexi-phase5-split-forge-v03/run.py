"""Single NVMe pipeline: qualify/freeze, extract, bridge, matched computation."""
import traceback
from probes import *
from comparison import compare

def main():
    verify();configure()
    from extract import main as extract
    extract()
    train=Population('TRAIN');dev=Population('DEV');pi=prevalence(train)
    model=new_bridge().cuda();reference=reference_and_normalizer(model,train)
    init=OUT/'INIT.pt'
    if not init.exists():torch.save(model.state_dict(),init);np.save(OUT/'variance-reference.npy',reference.cpu().numpy());write(OUT/'TRAIN-PREVALENCE.json',pi)
    else:
        model.load_state_dict(torch.load(init,weights_only=True));reference=torch.tensor(np.load(OUT/'variance-reference.npy'),device='cuda')
    if not (OUT/'INIT-REPORT.json').exists():
        evaluate(model,train,'INIT',save_states=True);write(OUT/'INIT-REPORT.json',evaluate(model,dev,'INIT',save_states=True))
    bridge=train_arm(model,'BRIDGE',train,dev,pi,reference)
    if not (OUT/'BRIDGE-REPORT.json').exists():
        evaluate(bridge,train,'BRIDGE',save_states=True);write(OUT/'BRIDGE-REPORT.json',evaluate(bridge,dev,'BRIDGE',save_states=True))
        write(OUT/'BRIDGE-ABLATIONS.json',ablations(bridge,dev))
    torch.manual_seed(20261002);A=RecurrentCausalGraft(copy.deepcopy(bridge)).cuda()
    B=StochasticCausalGraft(copy.deepcopy(bridge)).cuda();match_mean_initialization(B,A)
    # Training A does not mutate B's initial mean parameters or inherited bridge.
    A=train_arm(A,'A_DETERMINISTIC',train,dev,pi,reference)
    if not (OUT/'A-REPORT.json').exists():
        evaluate(A,train,'A_DETERMINISTIC',save_states=True)
        ar=evaluate(A,dev,'A_DETERMINISTIC',save_states=True);ar['latency']=timing(A,dev);write(OUT/'A-REPORT.json',ar)
        write(OUT/'A-ABLATIONS.json',ablations(A,dev))
    B=train_arm(B,'B_STOCHASTIC',train,dev,pi,reference)
    if not (OUT/'B-REPORT.json').exists():
        evaluate(B,train,'B_STOCHASTIC',save_states=True)
        reports=[evaluate(B,dev,'B_STOCHASTIC',seed,save_states=(seed==20261002)) for seed in [20261002,20261003,20261004]]
        reports[0]['latency']=timing(B,dev)
        gs=np.stack([np.load(OUT/'states'/'B_STOCHASTIC'/(str(seed)+'-global-state.npy')) for seed in [20261002,20261003,20261004]])
        cs=np.stack([np.load(OUT/'states'/'B_STOCHASTIC'/(str(seed)+'-candidate-logits.npy')) for seed in [20261002,20261003,20261004]])
        write(OUT/'B-REPORT.json',{'operational':reports[0],'diagnostic_seeds':reports[1:],
          'trajectory_variance':{'exact_action_accuracy':float(np.var([r['depths']['4']['action']['exact_logged_accuracy'] for r in reports])),
            'global_state_mean_coordinate_variance':float(gs.var(0).mean()),'valid_candidate_logit_variance':float(cs.var(0)[dev.arrays['mask']].mean()),
            'scope':'three independent one-trajectory evaluations; no ensemble, no best-seed selection'}})
        write(OUT/'B-ABLATIONS.json',ablations(B,dev))
    if not (OUT/'ACCESSIBILITY.json').exists():panel(train,dev)
    a=read(OUT/'A-REPORT.json');b=read(OUT/'B-REPORT.json')['operational'];base=read(OUT/'BRIDGE-REPORT.json')
    comparison=compare(dev,a,read(OUT/'B-REPORT.json'),base)
    tables=[]
    for name,report,depth in [('BRIDGE',base,'0'),('A deterministic',a,'4'),('B single trajectory',b,'4')]:
        r=report['depths'][depth];act=r['action'];can=r['candidate']
        tables.append(f"| {name} | {act['exact_logged_accuracy']:.4f} | {act['optimal_set_hit']:.4f} | {can['candidate_legal']['balanced_accuracy']:.4f} | {can['candidate_satisfies_goal']['balanced_accuracy']:.4f} |")
    write(OUT/'PRESERVATION.json',{target:{'B_minus_A_balanced_accuracy':b['depths']['4']['candidate'][target]['balanced_accuracy']-a['depths']['4']['candidate'][target]['balanced_accuracy']} for target in ['candidate_legal','candidate_satisfies_goal']})
    (OUT/'REPORT.md').write_text('# Lexi Phase 5 — Split Forge\n\nSynthetic-only BANK-v3 core. TRAIN/DEV engineering run; protected evaluation unopened.\n\n'
      '| Arm | Exact action | Optimal-set hit (selected-eligible) | Candidate legal BA | Candidate goal BA |\n|---|---:|---:|---:|---:|\n'+'\n'.join(tables)+
      '\n\nOnly MOVE meets the 200-root DEV action-type support floor. Other action types are support-only.\n\n'+json.dumps(comparison,indent=2)+'\n',encoding='utf-8')
    files={str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in OUT.rglob('*') if p.is_file() and p.suffix not in ('.tmp','.log') and p.name not in ['RELEASE.json','SEAL-REPLAY.json']}
    write(OUT/'RELEASE.json',{'status':'COMPLETE','files':files,'comparison':comparison,'source_contract_sha256':sha(OUT/'PHASE5-SPEC.json')})
    import subprocess
    subprocess.run([sys.executable,'-B',str(SOURCE/'replay.py')],check=True,cwd=SOURCE)
    print('PHASE5 COMPLETE',json.dumps(comparison),flush=True)

if __name__=='__main__':
    try:main()
    except Exception:
        (OUT/'FAILURE.txt').write_text(traceback.format_exc());raise
