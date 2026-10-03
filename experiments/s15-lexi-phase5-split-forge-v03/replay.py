"""Independent post-run identity replay; no protected population access."""
from lexi_contract import *
from report import Population,metrics

def main():
    verify();release=read(OUT/'RELEASE.json')
    for n,h in release['files'].items():
        if sha(OUT/n)!=h:raise ValueError('Artifact replay mismatch '+n)
    bridge=torch.load(OUT/'models'/'BRIDGE'/'best.pt',map_location='cpu',weights_only=True)
    for arm in ['A_DETERMINISTIC','B_STOCHASTIC']:
        state=torch.load(OUT/'models'/arm/'best.pt',map_location='cpu',weights_only=True)
        for k,v in bridge.items():
            if not torch.equal(v,state['seed.'+k]):raise ValueError('Frozen bridge changed '+arm+'/'+k)
    pop=Population('DEV',device='cpu');metric_checks=0
    reports=[('INIT',read(OUT/'INIT-REPORT.json')),('BRIDGE',read(OUT/'BRIDGE-REPORT.json')),('A_DETERMINISTIC',read(OUT/'A-REPORT.json'))]
    b=read(OUT/'B-REPORT.json');reports.extend(('B_STOCHASTIC',r) for r in [b['operational']]+b['diagnostic_seeds'])
    for identity,report in reports:
        for depth,expected in report['depths'].items():
            saved=np.load(OUT/'predictions'/identity/(str(report['seed'])+'-T'+depth+'.npz'))
            observed=metrics(pop,*[saved[k] for k in ['g','c','action','s','e_stats']])
            if observed!=expected:raise ValueError('Metric replay mismatch '+identity+'/'+depth)
            metric_checks+=1
    write(OUT/'SEAL-REPLAY.json',{'status':'PASS','independent_process':True,'files_checked':len(release['files']),
      'frozen_bridge_parity':True,'metric_depth_reports_replayed':metric_checks,'protected_files_opened':0,'release_sha256':sha(OUT/'RELEASE.json')})
    print('INDEPENDENT SEAL REPLAY PASS',flush=True)

if __name__=='__main__':main()
