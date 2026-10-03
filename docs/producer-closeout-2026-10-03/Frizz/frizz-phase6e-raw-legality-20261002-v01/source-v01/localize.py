import numpy as np
from common import *
from panel import VIEWS,FAMILIES
def main():
    lock();r=read(OUT/'raw-results.json');baseline=read(D6/'results.json')['results']['trained']['primary']['full_legal_sets']
    qualified=[];rules={}
    for name,v in r.items():
        g=v['trained']['primary']['full'];s=v['trained']['primary']['same_type']
        gain=paired_interval(np.array(baseline['root_exact'],float),np.array(g['root_exact'],float))
        ok=(g['full_exact_set_recovery']>=.50 and s['full_exact_set_recovery']>=.75 and g['root_mean_Jaccard']>=.80
            and g['precision']>=.95 and g['recall']>=.90 and g['selected_retention']>=.95 and gain['delta']>=.10 and gain['ci95'][0]>0)
        rules[name]={'precise_grounding_qualified':ok,'exact_gain_vs_gate':gain}
        if ok and not name.startswith('E_e'):qualified.append(name)
    if qualified:
        priority=[v+'-'+f for v in VIEWS for f in FAMILIES]
        qualified.sort(key=lambda n:(-r[n]['trained']['primary']['full']['full_exact_set_recovery'],
            -r[n]['trained']['primary']['full']['precision'],priority.index(n)))
    receipt(OUT/'RAW-LOCALIZATION.json',{'rules':rules,'adapter_earned':bool(qualified),
        'adapter_arm':qualified[0] if qualified else None,'micro_LoRA_earned':not bool(qualified),
        'interpretation':'bounded qualified frozen panel fails precise grounding at fixed dose' if not qualified else 'raw local precise grounding survives',
        'protected_evaluation_opened':False})
if __name__=='__main__':main()
