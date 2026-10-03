"""Versioned packaging-chronology correction and complete delivery binding."""
from d6 import *
import subprocess
PREV=OUT.parent/'lexi-phase6d-raw-legality-20261002-v02'
FINAL=OUT.parent/'lexi-phase6d-raw-legality-20261002-v03'
ADAPT=OUT.parent/'lexi-phase6d-access-adapter-20261002-v02'
EXPORT=OUT.parent/'lexi-phase6d-access-export-20261002-v03'

def derive():
    links={}
    for root in [OUT,PREV,ADAPT,EXPORT]:
        status=read(root/'FINAL-STATUS.json')
        if 'SEALED' not in status['status']:raise ValueError('Unsealed delivery component')
        links[str(root)]={'status':status,'final_status_sha256':sha(root/'FINAL-STATUS.json')}
        if (root/'MANIFEST.json').exists():
            for name,h in read(root/'MANIFEST.json')['files'].items():
                if sha(root/name)!=h:raise ValueError('Delivery file changed '+name)
        else:
            r=read(root/'RECEIPT.json')
            if sha(root/'DEV-estimates.jsonl')!=r['file_sha256']:raise ValueError('Envelope bytes changed')
    result=read(OUT/'RESULT.json');adapter=read(ADAPT/'RESULT.json')
    return {'disposition':'ACCESS_PATH_REPAIR','scope':'PARTIAL_ONLY_NOT_PRODUCTION_PROMOTED','links':links,
      'adapter_original_training_reused':True,'new_adapter_training_runs':0,'prepared_scalar_adapter_run':False,
      'diagnostic_training_seconds_sum':sum(r['train_seconds'] for r in result['results'].values()),
      'adapter_parameters':adapter['trainable_parameters_in_inherited_adapter'],'adapter_head_batch32_latency_seconds':adapter['batch32_CPU_head_latency_seconds'],
      'adapter_artifact_sha256':sha(ADAPT/'adapter.pt'),'estimate_rows':666,'estimate_candidates':41578,
      'source_sha256':sha(Path(__file__)),'protected_evaluation_opened':False}

def main():
    if '--replay' in sys.argv:
        if derive()!=read(FINAL/'DELIVERY.json'):raise ValueError('Delivery replay')
        write(FINAL/'REPLAY.json',{'status':'PASS','fresh_process':True,'complete_delivery_chain_bound':True});return
    FINAL.mkdir(parents=True,exist_ok=True);v=derive();write(FINAL/'DELIVERY.json',v)
    text=(PREV/'REPORT.md').read_text(encoding='utf-8')
    old='The follow-up trigger and architecture were recorded before adapter training; the original gate was not retroactively declared passed.'
    new='The adapter packaging contract was recorded before export. Its weights reuse the already completed TRAIN-only raw-MLP fit; there was no separate adapter training. The original gate was not retroactively declared passed.'
    if old not in text:raise ValueError('Editorial correction anchor')
    text=text.replace(old,new)
    text+='\nThis v03 delivery corrects the v02 packaging chronology sentence; all prior versions and numerical results are preserved. No additional training or scoring decision was introduced.\n'
    text+=f"\nCost: nine fixed diagnostic fits total {v['diagnostic_training_seconds_sum']:.1f}s; one raw backbone pass about125.6s, peak allocated CUDA1.69GB. Reused adapter: {v['adapter_parameters']:,} parameters, head-only CPU4-thread batch32 latency {v['adapter_head_batch32_latency_seconds']*1000:.2f}ms. Feature extraction/gathering is excluded from that latency; these are shared-host engineering measurements, not isolated serving benchmarks.\n"
    (FINAL/'REPORT.md').write_text(text,encoding='utf-8')
    write(FINAL/'MANIFEST.json',{'files':{n:sha(FINAL/n) for n in ['DELIVERY.json','REPORT.md']},'source_sha256':sha(Path(__file__))})
    subprocess.run([sys.executable,'-B',str(Path(__file__)),'--replay'],check=True)
    write(FINAL/'FINAL-STATUS.json',{'status':'SEALED_AND_FRESH_PROCESS_REPLAYED','disposition':'ACCESS_PATH_REPAIR','scope':'PARTIAL_ONLY_NOT_PRODUCTION_PROMOTED','manifest_sha256':sha(FINAL/'MANIFEST.json'),'replay_sha256':sha(FINAL/'REPLAY.json'),'protected_evaluation_opened':False})
    print('PHASE6D_FINAL_DELIVERY_SEALED',flush=True)
if __name__=='__main__':main()
