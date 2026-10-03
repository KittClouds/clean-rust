"""Final acceptance and small repo locator; validates completed seals only."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'core-v04'))
from common import *

def main():
    spec=verify_spec();seal=read(OUTPUT/'BANK-V3-CORE-SEALED.json')
    for field,name in [('manifest_sha256','RELEASE-MANIFEST.json'),('replay_sha256','INDEPENDENT-REPLAY.json'),
                       ('handoff_sha256','PHASE5-HANDOFF.json'),('report_sha256','REPORT.md')]:
        if seal[field]!=sha(OUTPUT/name):raise ValueError('Final seal hash mismatch '+name)
    body={k:v for k,v in seal.items() if k!='release_identity'}
    if seal['release_identity']!=sha256_hex(body):raise ValueError('Release identity mismatch')
    manifest=read(OUTPUT/'RELEASE-MANIFEST.json')
    for name,h in manifest['files'].items():
        if sha(OUTPUT/name)!=h:raise ValueError('Final manifest payload mismatch '+name)
    repair=read(OUTPUT/'BOUNDARY-REPAIR-v1.json')
    for m in repair['moves']:
        if (OUTPUT/m['old']).exists() or sha(OUTPUT/m['new'])!=m['sha256']:raise ValueError('Derived truth boundary mismatch')
    census=read(OUTPUT/'CENSUS.json');cue=read(OUTPUT/'CUE-RECHECK.json');replay=read(OUTPUT/'INDEPENDENT-REPLAY.json')
    if cue['status']!='PASS' or replay['status']!='PASS':raise ValueError('Upstream gate failure')
    vocab=['MOVE','TAKE','DROP','ACTIVATE','DEACTIVATE','OPEN','CLOSE','WAIT','TRANSFER']
    supports={s:{a:census['targets'][s]['first_action_type'].get(a,0) for a in vocab} for s in BUDGET}
    record={'status':'PASS','release_identity':seal['release_identity'],'final_seal_sha256':sha(OUTPUT/'BANK-V3-CORE-SEALED.json'),
       'gate_coverage_rows':sum(replay['rows'].values()),'gate_coverage_roots':sum(replay['roots'].values()),
       'gates':{g:'PASS' for g in ['G14_CORE','SEMANTIC_DERIVATION','REFSIM_TRANSITION_PARITY','ALL_AXIS_ANNOTATIONS',
          'EXHAUSTIVE_CANDIDATE_IDENTITY','SELECTED_AND_OPTIMAL_ACTION_ABI','FULL_ROOT_SEED_REPLAY',
          'ROOT_AND_CONTEXT_LEAKAGE','OBSERVABLE_INPUT_FIREWALL','PROTECTED_DERIVED_TRUTH_BOUNDARY',
          'G19_DECLARED_CUE_INSTRUMENT','BOOKKEEPING_REVERSE_REPLAY_AND_COUNT_DECOUPLING']},
       'action_type_canonical_root_support':supports,
       'support_denominator':{s:sum(supports[s].values()) for s in BUDGET},
       'statistical_floor':200,'model_learnability_measured':False,
       'TRANSFER_WAIT':'support only, no claims','acceptance_script_sha256':sha(__file__)}
    write(OUTPUT/'RELEASE-ACCEPTANCE.json',record)
    pointer={'schema':'BANK-v3-core-release-locator-v04','status':'SEALED_INDEPENDENTLY_REPLAYED',
      'actual_path':str(OUTPUT),'release_identity':seal['release_identity'],
      'manifest_sha256':seal['manifest_sha256'],'acceptance_sha256':sha(OUTPUT/'RELEASE-ACCEPTANCE.json'),
      'handoff':str(OUTPUT/'PHASE5-HANDOFF.json'),'report':str(OUTPUT/'REPORT.md'),
      'prospective_amendment':'core-v04/CONSTITUTION.md','core_provenance':'SYNTHETIC_ONLY',
      'human_extension':'PENDING_PERMISSION_AND_RECONSTRUCTION; prior requirements unchanged',
      'model_contact':'TRAIN_DEV_ONLY; public evaluation inputs only, no protected truth grant',
      'model_learnability_measured':False}
    write(SOURCE.parent/'bank-v3-core-release-v04.json',pointer)
    md=['# BANK-v3-core — current release locator','',f'Release: `{seal["release_identity"]}`',
      f'Actual NVMe path: `{OUTPUT}`','',
      'Use PHASE5-HANDOFF.json at that path. The historical scaffold is unchanged; the prospective core/human amendment is core-v04/CONSTITUTION.md.',
      '24,000 TRAIN, 6,000 DEV, 6,000 public evaluation rows, grouped into 12,000 / 3,000 / 3,000 canonical roots.',
      '171 exhaustive candidates maximum; never reuse the v1 cap of 28.',
      'BANK-v1: historical regression only. BANK-v2: pinned semantic ancestor, no row imports.',
      'Phase 5 begins with each lane\'s v3 bridge baseline; no neural learnability was measured by this build.','',
      '| Action type | TRAIN roots | DEV roots | DEV support |','|---|---:|---:|---|']
    for a in vocab:
        n=supports['DEV'][a];status='SUPPORT_ONLY' if a in ('WAIT','TRANSFER') else 'UNDERPOWERED' if n<200 else 'SUPPORTED_COUNT'
        md.append(f'| {a} | {supports["TRAIN"][a]} | {n} | {status} |')
    md += ['','These are selected EXECUTE action-type denominators, not named-candidate accuracy or model capability.',
       'Conflict stays diagnostic-only. Requestability/missing-cardinality require within-stratum reporting.',
       'Repaired renderer checks are bounded B4/phrase measurements. Full B3 DEV direction remains unknown.',
       'No human-grounded or scientific generalization claim. Protected truth remained construction/replay-only.']
    p=SOURCE.parent/'BANK-V3-CORE-RELEASE-v04.md'
    with p.open('x',encoding='utf-8') as f:f.write('\n'.join(md)+'\n')
    print(canonical_json({'status':'RELEASE_ACCEPTED','identity':seal['release_identity'],'support':supports['DEV']}))

if __name__=='__main__':main()
