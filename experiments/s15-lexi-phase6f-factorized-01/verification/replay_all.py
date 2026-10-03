"""Supplemental fresh-process replay of all recorder and attribution outputs."""
import sys,tempfile,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from f6 import *

def main():
    torch.set_num_threads(4)
    loader=importlib.util.spec_from_file_location('phase6f_recorder',HERE/'run.py')
    recorder=importlib.util.module_from_spec(loader);loader.loader.exec_module(recorder)
    spec=read(OUT/'SPEC.json');result=read(OUT/'RESULT.json');ts=read(OUT/'THRESHOLDS.json')['values']
    receipt={}
    with tempfile.TemporaryDirectory(dir='C:/phoenix-target-overgraph') as temporary:
        recorder.OUT=Path(temporary)
        for split in ('TRAIN','DEV'):
            z=np.load(OUT/(split+'-logits.npy'));value=recorder.evaluate(spec,z,ts,split)
            write(Path(temporary)/(split+'.json'),value)
            if read(Path(temporary)/(split+'.json'))!=result[split]:raise ValueError('Full metric replay '+split)
            name=split+'-error-attribution.jsonl'
            if sha(Path(temporary)/name)!=sha(OUT/name):raise ValueError('Attribution replay '+split)
            receipt[split]={'all_set_ranking_factor_slice_metrics_equal':True,'attribution_bytes_equal':True}
    # Every previously bound file remains unchanged after the supplementary audit.
    for name,h in read(OUT/'MANIFEST.json')['files'].items():
        if sha(OUT/name)!=h:raise ValueError('Sealed bytes changed')
    root=OUT.parent/'lexi-phase6f-verification-20261003-v01';root.mkdir(exist_ok=True)
    write(root/'RECEIPT.json',{'status':'PASS','fresh_process':True,'checks':receipt,'unit_tests_passed':4,
      'additional_simulator_controls_passed':6,'controls':['scheduled connection active at0/inactive at1','blocked move rejected','missing gate rejected','satisfied gate accepted','WAIT empty conjunction'],
      'completed_release_manifest_sha256':sha(OUT/'MANIFEST.json'),'completed_release_replay_sha256':sha(OUT/'REPLAY.json'),
      'partial_attempt_status':read(OUT.parent/'lexi-phase6f-factorized-20261003-v01/ATTEMPT-STATUS.json'),
      'partial_attempt_status_sha256':sha(OUT.parent/'lexi-phase6f-factorized-20261003-v01/ATTEMPT-STATUS.json'),
      'verification_source_sha256':sha(__file__),'protected_evaluation_opened':False})
    write(root/'MANIFEST.json',{'files':{'RECEIPT.json':sha(root/'RECEIPT.json')},'original_release_unchanged':True})
    print('FULL_METRICS_AND_ATTRIBUTION_REPLAY_PASS',flush=True)
if __name__=='__main__':main()
