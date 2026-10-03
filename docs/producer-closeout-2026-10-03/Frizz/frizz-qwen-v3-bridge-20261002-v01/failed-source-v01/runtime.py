"""Own bridge artifact identity and create-only receipts."""
import json
from pathlib import Path
from audit_release import sha

HERE = Path(__file__).resolve().parent
OUT = Path('C:/phoenix-target-overgraph/frizz-qwen-v3-bridge-20261002-v01')
MODEL = Path('D:/codex-runs/s15-lepori-qwen-0.8b-base-v01/models/Qwen3.5-0.8B-Base')
REVISION = 'dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68'
SURFACES = ['lt@24', 'mf@24', 'ms@24', 'mf@18', 'mf@12', 'mf@6']


def receipt(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def verify_handoff():
    from audit_release import ROOT
    corrected = ROOT / 'PHASE5-HANDOFF-v02.json'
    handoff = json.loads(corrected.read_text())
    binding = json.loads((HERE / 'release-binding-v01.json').read_text())
    if handoff['correction']['accepted_frizz_binding_sha256'] != sha(HERE / 'release-binding-v01.json'):
        raise ValueError('accepted downstream binding mismatch')
    for split in ('TRAIN', 'DEV'):
        for kind, key in (('public', 'input'), ('data', 'supervision')):
            expected = binding['splits'][split][kind]
            if handoff['splits'][split][key + '_files'] != expected['files']:
                raise ValueError('corrected handoff file map mismatch')
            if handoff['splits'][split][key + '_identity'] != expected['identity']:
                raise ValueError('corrected handoff identity mismatch')
    return handoff, sha(corrected)
