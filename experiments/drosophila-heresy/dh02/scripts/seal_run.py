"""Seal DH02, prove DH01 ancestry unchanged, execute, and analyze immutable inputs."""
import ctypes
import datetime
import hashlib
import json
import pathlib
import platform
import shutil
import subprocess
import sys
import time

ROOT=pathlib.Path(__file__).resolve().parents[1]
PARENT=ROOT.parent/'artifacts/runs/20260912T032529Z'


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def verify_parent():
    completion=json.loads((PARENT/'completion.json').read_text())
    seal=json.loads((PARENT/'seal.json').read_text())
    assert digest(PARENT/'seal.json')==completion['seal_sha256']
    for name,h in completion['output_hashes'].items():
        assert digest(PARENT/name)==h, name
    for name,h in seal['fingerprints'].items():
        assert digest(PARENT/'sealed'/name)==h, name
    assert digest(ROOT/'src/baseline.rs')==seal['fingerprints']['src\\simulation.rs']
    return dict(seal_sha256=completion['seal_sha256'],frozen_files=len(seal['fingerprints']),output_files=len(completion['output_hashes']))


class Memory(ctypes.Structure):
    _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(k,ctypes.c_size_t) for k in [
        'PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
        'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]


def run():
    parent=verify_parent()
    config=json.loads((ROOT/'config.json').read_text())
    old=json.loads((PARENT/'sealed/config.json').read_text())
    assert not set(config['seeds']) & set(old['seeds'])
    assert len(config['seeds'])==len(set(config['seeds']))
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=ROOT/'artifacts/runs'/stamp
    out.mkdir(parents=True,exist_ok=False)
    frozen=out/'sealed'; frozen.mkdir()
    files=[ROOT/n for n in ['Cargo.toml','Cargo.lock','config.json','PROTOCOL.md','QUALIFICATION.json']]
    files+=sorted((ROOT/'src').rglob('*.rs'))+sorted((ROOT/'scripts').glob('*.py'))
    files+=sorted((ROOT/'qualification').glob('*.log'))
    fingerprints={}
    for p in files:
        relative=p.relative_to(ROOT); target=frozen/relative; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,target); fingerprints[str(relative)]=digest(target); assert fingerprints[str(relative)]==digest(p)
    anatomy=frozen/'anatomy'; anatomy.mkdir()
    for p in sorted((PARENT/'sealed/artifacts/anatomy').iterdir()):
        if p.is_file():
            shutil.copy2(p,anatomy/p.name); fingerprints[str(pathlib.Path('anatomy')/p.name)]=digest(p)
    binary=ROOT/'target/release/drosophila-heresy-dh02.exe'
    assert str(binary.resolve()).lower().startswith('d:\\drosophila-heresy\\dh02-target\\')
    shutil.copy2(binary,frozen/binary.name); fingerprints[binary.name]=digest(binary)
    seal=dict(protocol='DH-02',created_utc=stamp,before_task_execution=True,fingerprints=fingerprints,
              parent_dh01=parent,shared_immediate_acquisition=True,fresh_seed_bundles=config['seeds'],
              dh02_outcomes_used_for_tuning=0,python=sys.version,platform=platform.platform(),
              binary_executed=str(binary),binary_resolved=str(binary.resolve()),
              compiler=subprocess.check_output(['rustc','--version'],text=True).strip())
    (out/'seal.json').write_text(json.dumps(seal,indent=2)+'\n')
    print('FROZEN_RUN',out,flush=True);print('SEAL_SHA256',digest(out/'seal.json'),flush=True)
    query=ctypes.WinDLL('psapi').GetProcessMemoryInfo
    query.argtypes=[ctypes.c_void_p,ctypes.POINTER(Memory),ctypes.c_ulong];query.restype=ctypes.c_int
    start=time.perf_counter(); peak=0;last=start
    with (out/'stdout.log').open('w') as log:
        process=subprocess.Popen([str(binary),'run',str(frozen/'config.json'),str(anatomy),str(out)],stdout=log,stderr=subprocess.STDOUT)
        while process.poll() is None:
            counters=Memory();counters.cb=ctypes.sizeof(counters)
            if query(ctypes.c_void_p(int(process._handle)),ctypes.byref(counters),counters.cb):
                peak=max(peak,counters.PeakWorkingSetSize)
            time.sleep(0.1)
            if time.perf_counter()-last>=30:
                print('running_seconds',round(time.perf_counter()-start,1),'peak_working_set_bytes',peak,flush=True);last=time.perf_counter()
    resource=dict(exit_code=process.returncode,wall_seconds_including_launch=time.perf_counter()-start,
                  observed_peak_working_set_bytes=peak,method='Windows GetProcessMemoryInfo peak working set sampled every 0.1 s; simulator only')
    (out/'resources.json').write_text(json.dumps(resource,indent=2)+'\n')
    assert process.returncode==0,(out/'stdout.log').read_text()
    for name,h in fingerprints.items():assert digest(frozen/name)==h,name
    assert verify_parent()==parent
    assert digest(binary)==fingerprints[binary.name]
    subprocess.run([sys.executable,str(frozen/'scripts/analyze.py'),str(out)],check=True)
    receipt=dict(seal_sha256=digest(out/'seal.json'),parent_dh01_reverified=True,
                 frozen_inputs_reverified=True,resources=resource,
                 output_hashes={p.name:digest(p) for p in out.iterdir() if p.is_file()})
    (out/'completion.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('COMPLETE',out,flush=True)


if __name__=='__main__':run()
