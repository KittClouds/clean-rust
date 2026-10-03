"""Post-seal descriptive metadata amendment: BA undefined for one-class strata."""
import copy,sys
from common import *

def corrected():
    value=copy.deepcopy(read(OUT/'ACTION-SUPPORTS.json'));count=0
    def walk(obj):
        nonlocal count
        if isinstance(obj,dict):
            if all(k in obj for k in ('BA','valid_candidates','legal_candidates')):
                if obj['legal_candidates'] in (0,obj['valid_candidates']):
                    obj['BA']=None;obj['BA_status']='UNDEFINED_SINGLE_CLASS';count+=1
            for item in obj.values():walk(item)
        elif isinstance(obj,list):
            for item in obj:walk(item)
    walk(value)
    value['BA_convention']='two-class balanced accuracy is undefined where positive or negative support is zero'
    return value,count

def main(verify=False):
    lock();value,count=corrected()
    if verify:
        if value!=read(OUT/'ACTION-SUPPORTS-v02.json'):raise ValueError('typed BA repair replay')
        seal=read(OUT/'METADATA-AMENDMENT-v02-SEALED.json')
        for n,h in seal['artifacts'].items():
            if sha(OUT/n)!=h:raise ValueError('metadata amendment drift')
        if sha(__file__)!=seal['source_sha256']:raise ValueError('repair source drift')
        receipt(OUT/'metadata-v02-replay.json',{'status':'PASS','corrected_single_class_cells':count,
            'parent_seal_unchanged':sha(OUT/'PHASE6E-SEALED.json')==seal['parent_seal_sha256']});return
    receipt(OUT/'ACTION-SUPPORTS-v02.json',value)
    receipt(OUT/'ENGINEERING-METADATA-v02.json',{'reason':'typed single-class BA must be undefined, not inherited zero-specificity arithmetic',
        'corrected_cells':count,'original_receipts_preserved':True,'fits_or_primary_results_changed':False,
        'exact_sets_ranking_disposition_unchanged':True,'protected_evaluation_opened':False})
    with (OUT/'REPORT-ADDENDUM-v02.md').open('x',encoding='utf-8') as f:
        f.write('# Descriptive metric amendment\n\nUse ACTION-SUPPORTS-v02.json for typed support summaries. Balanced accuracy is undefined when a type stratum contains only legal or only illegal candidates; those cells are now null, with UNDEFINED_SINGLE_CLASS status. Original receipts remain preserved. All two-class primary metrics, exact sets, ranking, training, replay, and final disposition are unchanged.\n')
    names=('ACTION-SUPPORTS-v02.json','ENGINEERING-METADATA-v02.json','REPORT-ADDENDUM-v02.md')
    receipt(OUT/'METADATA-AMENDMENT-v02-SEALED.json',{'status':'SEALED','parent_seal_sha256':sha(OUT/'PHASE6E-SEALED.json'),
        'artifacts':{n:sha(OUT/n) for n in names},'source_sha256':sha(__file__),'protected_evaluation_opened':False})
if __name__=='__main__':main('--verify' in sys.argv)
