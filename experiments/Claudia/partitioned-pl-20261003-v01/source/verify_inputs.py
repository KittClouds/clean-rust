"""Verify every consumed frozen input against its sealing experiment BEFORE any training.

Consumed: E-trained-{TRAIN,DEV}.pt (trained-E candidate states), {TRAIN,DEV}-targets.pt (selected/optimal
targets), bridge {TRAIN,DEV}-dataset.pt (canonical action type / argument presence / legality label).
Checked against: the Phase6B seal (whole closure + its recorded input hashes), the Phase6A seal-v02
(artifact hashes), per-artifact sidecar receipts, and the BANK-v3-core release identity chain.
Protected / EVAL files are never opened.
"""
from common import *

CONSUMED = {
    'E-trained-TRAIN.pt': P6A / 'E-trained-TRAIN.pt', 'E-trained-DEV.pt': P6A / 'E-trained-DEV.pt',
    'TRAIN-targets.pt': P6A / 'TRAIN-targets.pt', 'DEV-targets.pt': P6A / 'DEV-targets.pt',
    'TRAIN-dataset.pt': BRIDGE / 'TRAIN-dataset.pt', 'DEV-dataset.pt': BRIDGE / 'DEV-dataset.pt',
}


def main():
    result = {'status': 'PENDING', 'protected_or_eval_files_opened': False}
    # 1. Phase6B seal closure
    seal_path = P6B / 'PHASE6B-SEALED.json'
    seal = read(seal_path)
    assert seal['status'] == 'SEALED' and seal['evaluation_opened'] is False
    bad = [k for k, v in seal['artifacts'].items() if sha(P6B / k) != v]
    if bad:
        raise ValueError(f'Phase6B sealed artifacts drifted: {bad[:5]}')
    result['phase6b'] = {'seal_sha256': sha(seal_path), 'artifacts_verified': len(seal['artifacts']),
                         'disposition': seal['disposition'], 'evaluation_opened': seal['evaluation_opened']}
    # 2. Phase6A seal-v02 identity and artifact hashes
    s6a_path = P6A / 'PHASE6A-SEALED-v02.json'
    if sha(s6a_path) != P6A_SEAL_SHA:
        raise ValueError('Phase6A seal-v02 drift')
    s6a = read(s6a_path)['artifact_hashes']
    spec6b = read(P6B / 'SPECIFICATION.json')['inputs']
    consumed = {}
    for name, path in CONSUMED.items():
        digest = sha(path)
        evidence = {}
        key = Path(path).as_posix().lower()
        s6a_n = {Path(k).as_posix().lower(): v for k, v in s6a.items()}
        if key in s6a_n:
            evidence['phase6a_seal_v02'] = s6a_n[key] == digest
        for k, v in spec6b.items():
            if Path(k).as_posix().lower() == key:
                evidence['phase6b_specification_inputs'] = v == digest
        sidecar = path.with_suffix('.json')
        if sidecar.exists() and 'sha256' in read(sidecar):
            evidence['sidecar_receipt'] = read(sidecar)['sha256'] == digest
        if name.endswith('-dataset.pt'):
            frozen = read(P6A / 'SPECIFICATION.json')['frozen_inputs']
            for k, v in frozen.items():
                if Path(k).as_posix().lower() == key:
                    evidence['phase6a_specification_frozen_inputs'] = v == digest
        if not evidence or not all(evidence.values()):
            raise ValueError(f'identity check failed for {name}: {evidence}')
        consumed[name] = {'path': str(path), 'sha256': digest, 'bytes': path.stat().st_size, 'verified_against': evidence}
    result['consumed'] = consumed
    # 3. BANK-v3-core release identity chain (public metadata only)
    sealed = read(BANK / 'BANK-V3-CORE-SEALED.json')
    handoff_path = BANK / 'PHASE5-HANDOFF-v02.json'
    handoff = read(handoff_path)
    if sha(handoff_path) != HANDOFF_SHA:
        raise ValueError('corrected handoff drift')
    if handoff['correction']['original_release_identity'] != RELEASE_IDENTITY or RELEASE_IDENTITY not in json.dumps(sealed):
        raise ValueError('release identity mismatch')
    if handoff['provenance_class'] != 'SYNTHETIC_ONLY':
        raise ValueError('not synthetic-only')
    result['bank_v3_core'] = {'release_identity': RELEASE_IDENTITY, 'corrected_handoff_sha256': HANDOFF_SHA,
                              'release_manifest_sha256': handoff['release_manifest_sha256'],
                              'provenance_class': handoff['provenance_class'],
                              'candidate_contract': handoff['candidate_contract'],
                              'candidate_vocabulary': handoff['candidate_vocabulary'],
                              'protected_files_opened': False}
    result['status'] = 'PASS'
    receipt(OUT / 'INPUT-IDENTITY.json', result)
    print('INPUT_IDENTITY_PASS', {k: v['sha256'][:12] for k, v in consumed.items()}, flush=True)


if __name__ == '__main__':
    main()
