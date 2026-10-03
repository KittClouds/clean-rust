"""Freeze executable/source before qualification; never starts measured science."""
from pathlib import Path
import datetime
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parent

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def verify(run):
    seal=json.loads((run/'seal.json').read_text())
    done=json.loads((run/'completion.json').read_text())
    assert digest(run/'seal.json')==done['seal_sha256']
    for name,h in seal['fingerprints'].items():
        assert digest(run/'sealed'/name)==h
    for name,h in done['output_hashes'].items():
        assert digest(run/name)==h
    return done['seal_sha256']

if __name__=='__main__':
    parent=BASE/'dh06/artifacts/runs/20260915T201008Z'
    parent_hash=verify(parent)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=ROOT/'artifacts'/stamp
    frozen=out/'frozen'
    frozen.mkdir(parents=True,exist_ok=False)
    files=list((ROOT/'src').rglob('*.rs'))+list((ROOT/'scripts').glob('*.py'))
    files += [ROOT/p for p in ['Cargo.toml','Cargo.lock','PLAN.md']]
    fingerprints={}
    for src in files:
        rel=src.relative_to(ROOT)
        dest=frozen/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dest)
        fingerprints[str(rel)]=digest(dest)
    binary=ROOT/'target/release/q07-bounded-null-v1.exe'
    assert str(binary.resolve()).lower().startswith('d:\\drosophila-heresy\\q07-bounded-null-v1-target\\')
    shutil.copy2(binary,frozen/binary.name)
    fingerprints[binary.name]=digest(frozen/binary.name)
    blocked={str(p.relative_to(BASE/'dh07')):digest(p) for p in (BASE/'dh07').rglob('*')
             if p.is_file() and 'target' not in p.parts}
    receipt=dict(protocol='Q07-BoundedNull-v1',kind='qualification_and_posthoc_audit_only',
                 before_execution=True,created_utc=stamp,python=sys.version,
                 interpreter=sys.executable,interpreter_sha256=digest(Path(sys.executable)),
                 parent_dh06_sha256=parent_hash,blocked_dh07_fingerprints=blocked,
                 fingerprints=fingerprints,measured_seeds_forbidden=list(range(7000,7032)),
                 anatomy=str(parent/'sealed/anatomy'))
    (out/'qualification-seal.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(out)
