"""Append reproducible semantic transcripts to the audit package, no new score."""
from common import *
from observation import semantic,exact_interface,replay_public
lock();counts={};h=hashlib.sha256()
with gzip.open(OUT/'observable-signatures.jsonl.gz','xt',encoding='utf-8') as f:
    for split in ('TRAIN','DEV'):
        counts[split]=0
        for p,r in population(split):
            replay_public(p,r);sem=semantic(p,r)
            value={'split':split,'root':r['META']['canonical_id'],'renderer':p['renderer_family'],
                'slot':r['META']['renderer_slot'],'semantic':sem,'semantic_sha256':digest(sem),
                'exact_interface_sha256':digest(exact_interface(p))}
            line=canonical(value)+'\n';f.write(line);h.update(line.encode());counts[split]+=1
if counts!={'TRAIN':2666,'DEV':666}:raise ValueError('observable transcript support mismatch')
receipt(OUT/'observable-transcript-receipt.json',{'status':'PASS','rows':counts,
    'semantic_content_sha256':h.hexdigest(),'source_sha256':sha(Path(__file__)),
    'renderer_public_reconstruction':'exact','no_new_scoring_or_training':True,'protected_evaluation_opened':False})
print('OBSERVABLE TRANSCRIPTS EXPORTED',counts,flush=True)
