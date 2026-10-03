"""Manifest preparation and post-replay final seal/handoff. Never trains models."""
import sys
from common import *

def prepare():
    spec=verify_spec();cue=read(OUTPUT/'CUE-RECHECK.json');census=read(OUTPUT/'CENSUS.json')
    if cue['status']!='PASS':raise ValueError('Cue recheck failed')
    files={str(p.relative_to(OUTPUT)):sha(p) for p in OUTPUT.rglob('*') if p.is_file()}
    splits={}
    for s in BUDGET:
        prefix='protected/evaluation-truth' if s=='EVAL' else 'data'
        inputs={k:h for k,h in files.items() if k.startswith('public/'+s+'/')}
        truth={k:h for k,h in files.items() if k.startswith(prefix+'/'+s+'/')}
        splits[s]={'canonical_roots':BUDGET[s],'rows':2*BUDGET[s],
                   'input_files':inputs,'supervision_files':truth,
                   'input_identity':sha256_hex(inputs),'supervision_identity':sha256_hex(truth)}
    manifest={'release':'BANK-v3-core','version':'0.4','status':'BUILT_PENDING_INDEPENDENT_REPLAY',
       'actual_path':str(OUTPUT),'provenance_class':'SYNTHETIC_ONLY','external_roots_imported':0,
       'contract_sha256':sha(OUTPUT/'BUILD-CONTRACT.json'),'splits':splits,'files':files,
       'max_canonical_candidates':census['max_candidates'],'candidate_truncation':0,
       'human_extension_status':'PENDING; provenance requirements unchanged'}
    write(OUTPUT/'RELEASE-MANIFEST.json',manifest)

def finalize():
    spec=verify_spec();replay=read(OUTPUT/'INDEPENDENT-REPLAY.json');c=read(OUTPUT/'CENSUS.json')
    m=read(OUTPUT/'RELEASE-MANIFEST.json');mh=sha(OUTPUT/'RELEASE-MANIFEST.json')
    if replay['status']!='PASS' or replay['manifest_sha256']!=mh:raise ValueError('Independent replay not bound')
    for name,h in m['files'].items():
        if sha(OUTPUT/name)!=h:raise ValueError('Post-replay bytes changed '+name)
    handoff={'status':'MODEL_CONTACT_READY_TRAIN_DEV_ONLY','release_manifest_sha256':mh,'path':str(OUTPUT),
       'provenance_class':'SYNTHETIC_ONLY','splits':m['splits'],
       'target_and_curriculum_contract':str(OUTPUT/'BUILD-CONTRACT.json'),
       'observable_inputs':['input_text','goal_mentions','bindings','actions','requests'],
       'join_only_metadata':['world_id','canonical_id','split','renderer_id','renderer_family'],
       'never_input':['WORLD_TRUTH','TARGETS','SUPERVISION_ABI','CAPABILITY_AXES','BOOKKEEPING','META','PROVENANCE'],
       'candidate_vocabulary':['MOVE','TAKE','DROP','ACTIVATE','DEACTIVATE','OPEN','CLOSE','WAIT','TRANSFER'],
       'candidate_contract':{'exhaustive':True,'max_count':c['max_candidates'],'order':spec['candidate_order'],
          'padding':'downstream deterministic padding; masked slots have no loss or metric'},
       'action_endpoint':{'selected':'EXECUTE only; scalar per candidate; ID-index equality required',
         'optimal_set':spec['optimal_set'],'empty_set':spec['empty_set'],
         'action_type':'separate type classification; never equate with named candidate selection'},
       'renderer_families':{'TRAIN_DEV':list(freeze.SEEN_FAMILIES),'PUBLIC_EVAL':list(freeze.HELD_FAMILIES)},
       'target_masks':{'first_action_type':'EXECUTE only, exclude NA from loss/accuracy',
          'requestability':'NA is structural no-missing category; report missing-required-only slice separately',
          'reason':'canonical null is absence-of-reason, never action disposition relabeling',
          'solvable':'exclude nonterminal search status; solvable_available flag',
          'conflict_and_aliases':'diagnostic only, no loss/promotion'},
       'axes':spec['axis_definitions'],'normalization':spec['normalization'],
       'supervision_ABI':spec['supervision_ABI'],'ontology_availability':spec['ontology_availability'],
       'grouping':'all renderings with canonical_id remain together; root namespace determines split',
       'protected_policy':{'model_truth_grant':False,'construction_replay_grant':True,
         'public_evaluation_inputs_only':str(OUTPUT/'public/EVAL'),
         'access_control':'role/contract boundary, not claimed cryptographic or different-user escrow'},
       'unavailable_candidate_targets':['candidate_supported','candidate_has_counterevidence','candidate_requires_missing_information'],
       'scope':'Bank seal certifies construction/instrument; neural learnability unmeasured. BANK-v1 regression only, no substitution.'}
    write(OUTPUT/'PHASE5-HANDOFF.json',handoff)
    cue=read(OUTPUT/'CUE-RECHECK.json')
    lines=['# BANK-v3-core v0.4 — sealed synthetic-only release','',
      f'Actual path: `{OUTPUT}`',f'Release manifest SHA-256: `{mh}`','',
      '18,000 newly generated canonical roots; 36,000 rendered rows. No BANK-v1/v2 rows imported.',
      'TRAIN: 12,000 roots / 24,000 rows. DEV: 3,000 / 6,000. Public evaluation: 3,000 / 6,000.',
      f'Exhaustive candidate maximum: {c["max_candidates"]}. No truncation.',
      '100% root replay, derivation, simulator/refsim action parity, input-boundary and lineage gates passed.',
      'Independent replay is a separate process/verifier path, not a separately authored semantic engine.',
      'Protected new evaluation truth was accessed only for authorized construction and seal replay.',
      'No historical protected truth or neural weights opened. No model learnability measured.','',
      '| Target | B4 macro-F1 | Phrase-signature macro-F1 | Disposition |','|---|---:|---:|---|']
    for name,r in cue['results'].items():
        d='DIAGNOSTIC_ONLY' if name=='conflict' else 'STRATUM_RESTRICTED' if name in ('requestability','missing_cardinality') else 'ADMISSIBLE'
        lines.append(f'| {name} | {r["B4_macro_f1"]:.4f} | {r["complete_phrase_signature_macro_f1"]:.4f} | {d} |')
    lines += ['','Cue results cover the declared B4/phrase instruments, not every cheap lexical learner.',
       'Legacy B3 head subsampling has no guaranteed DEV bias direction. Negative cue findings stay qualified.',
       'B0/replay establishes semantic decidability and instrument correctness, not blanket renderer/learner validity.',
       'first_action_type is a computation-pressure target, not demonstrated learnable headroom or proof of the historical MOVE wall.',
       'Reason has weak lexical recovery; no claim of textual impossibility.',
       'TRANSFER/WAIT: support and denominators only. DEV per-class/slice reliability floor: 200 canonical roots.',
       'CENSUS.json reports actual support; paired rows are not independent worlds.',
       'Bookkeeping hiding preserves core labels and is reverse-replayed; it breaks exact counter identity, not all statistical count association.',
       'BANK-v3-human remains pending permission-cleared roots/reconstruction witnesses; its original requirements remain intact.',
       'Engineering correction during fixtures: shortest-path first actions are ID strings, not Act objects; fixed before corpus freeze.',
       '', 'Model-facing boundary and exact split identities: PHASE5-HANDOFF.json. No model evaluation-truth grant.']
    (OUTPUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    seal={'status':'SEALED_INDEPENDENTLY_REPLAYED','release':'BANK-v3-core','version':'0.4',
      'manifest_sha256':mh,'replay_sha256':sha(OUTPUT/'INDEPENDENT-REPLAY.json'),
      'handoff_sha256':sha(OUTPUT/'PHASE5-HANDOFF.json'),'report_sha256':sha(OUTPUT/'REPORT.md'),
      'provenance_class':'SYNTHETIC_ONLY','model_contact':'TRAIN_DEV_ONLY','human_extension':'PENDING'}
    seal['release_identity']=sha256_hex(seal);write(OUTPUT/'BANK-V3-CORE-SEALED.json',seal)
    print(json.dumps(seal),flush=True)

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare()
    elif sys.argv[1]=='finalize':finalize()
    else:raise ValueError('prepare or finalize required')
