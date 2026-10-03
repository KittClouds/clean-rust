"""Inference-only estimate envelopes; no oracle fields in exported payload."""
from d6 import *
import subprocess
ADAPT=OUT.parent/'lexi-phase6d-access-adapter-20261002-v02'
EXPORT=OUT.parent/'lexi-phase6d-access-export-20261002-v03'

def rows():
    d=load('DEV');a=read(ADAPT/'RESULT.json');score=c6.sigmoid(np.load(OUT/'heads/entity_final-tiny_MLP/DEV-logits.npy'))
    artifact=sha(ADAPT/'adapter.pt')
    for i,meta in enumerate(d['meta']):
        live=np.flatnonzero(d['mask'][i]);ids=meta['action_ids']
        if len(live)!=len(ids) or not np.array_equal(live,np.arange(len(ids))):raise ValueError('Canonical candidate envelope order')
        yield {'world_id':meta['id'],'provenance_class':'MODEL_ESTIMATE','runtime_availability':'AVAILABLE',
          'estimator_artifact_sha256':artifact,'threshold_TRAIN':a['threshold_TRAIN'],
          'candidates':[{'candidate_id':ids[j],'estimate.candidate_legal':{'sigmoid_score':float(score[i,j]),'legal_estimate':bool(score[i,j]>=a['threshold_TRAIN'])}} for j in live]}

def main():
    if '--replay' in sys.argv:
        receipt=read(EXPORT/'RECEIPT.json')
        if sha(ADAPT/'MANIFEST.json')!=receipt['adapter_manifest_sha256'] or sha(EXPORT/'DEV-estimates.jsonl')!=receipt['file_sha256']:raise ValueError('Envelope identity')
        expected=list(rows());actual=[json.loads(l) for l in (EXPORT/'DEV-estimates.jsonl').open(encoding='utf-8')]
        if actual!=expected:raise ValueError('Envelope replay')
        write(EXPORT/'REPLAY.json',{'status':'PASS','rows':len(expected),'candidate_estimates':sum(len(r['candidates']) for r in expected),'oracle_fields_exported':0,'protected_evaluation_opened':False});return
    if read(ADAPT/'FINAL-STATUS.json')['status']!='SEALED_AND_FRESH_PROCESS_REPLAYED':raise ValueError('Unsealed estimator')
    EXPORT.mkdir(parents=True,exist_ok=True);n=0;count=0
    with (EXPORT/'DEV-estimates.jsonl').open('x',encoding='utf-8') as f:
        for row in rows():f.write(json.dumps(row,sort_keys=True)+'\n');n+=1;count+=len(row['candidates'])
    write(EXPORT/'RECEIPT.json',{'source_sha256':sha(Path(__file__)),'adapter_manifest_sha256':sha(ADAPT/'MANIFEST.json'),
      'file_sha256':sha(EXPORT/'DEV-estimates.jsonl'),'rows':n,'eligible_roots':n//2,'candidate_estimates':count,
      'scope':'DEV eligible panel only, internal engineering OOS readout predictions; no external qualification or runtime policy promotion',
      'score_semantics':'sigmoid of balanced-BCE readout; not a calibrated factual probability',
      'oracle_fields_exported':0,'protected_evaluation_opened':False})
    subprocess.run([sys.executable,'-B',str(Path(__file__)),'--replay'],check=True)
    write(EXPORT/'FINAL-STATUS.json',{'status':'SEALED_AND_FRESH_PROCESS_REPLAYED','receipt_sha256':sha(EXPORT/'RECEIPT.json'),'replay_sha256':sha(EXPORT/'REPLAY.json')})
    print('ESTIMATE_ENVELOPES_SEALED',flush=True)
if __name__=='__main__':main()
