"""Freeze all scientific inputs, run through the C: target junction, then analyze."""
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

ROOT = pathlib.Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class MemoryCounters(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [(name, ctypes.c_size_t) for name in [
        'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage',
        'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage']]


def run():
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = ROOT / 'artifacts' / 'runs' / stamp
    out.mkdir(parents=True, exist_ok=False)
    snapshot = out / 'sealed'
    snapshot.mkdir()
    paths = [ROOT / name for name in ['Cargo.toml', 'Cargo.lock', 'config.json', 'PROTOCOL.md', 'QUALIFICATION.json']]
    paths += sorted((ROOT / 'src').glob('*.rs')) + sorted((ROOT / 'scripts').glob('*.py'))
    paths += sorted((ROOT / 'artifacts' / 'anatomy').glob('*'))
    fingerprints = {}
    for path in paths:
        relative = path.relative_to(ROOT)
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        fingerprints[str(relative)] = digest(target)
        assert digest(path) == fingerprints[str(relative)]
    binary = ROOT / 'target' / 'release' / 'drosophila-heresy.exe'
    assert str(binary.resolve()).lower().startswith('d:\\drosophila-heresy\\target\\'), binary.resolve()
    shutil.copy2(binary, snapshot / 'drosophila-heresy.exe')
    fingerprints['drosophila-heresy.exe'] = digest(binary)
    seal = dict(created_utc=stamp, before_task_execution=True, fingerprints=fingerprints,
                binary_executed=str(binary), binary_resolved=str(binary.resolve()),
                platform=platform.platform(), python=sys.version,
                compiler=subprocess.check_output(['rustc', '--version'], text=True).strip(),
                protocol='DH-01', scientific_outcomes_used_for_tuning=0,
                source_attribution='MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY')
    (out / 'seal.json').write_text(json.dumps(seal, indent=2) + '\n')
    print('FROZEN_RUN', out, flush=True)
    print('SEAL_SHA256', digest(out / 'seal.json'), flush=True)
    query = ctypes.WinDLL('psapi').GetProcessMemoryInfo
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(MemoryCounters), ctypes.c_ulong]
    query.restype = ctypes.c_int
    peak = 0
    start = time.perf_counter()
    with (out / 'stdout.log').open('w') as log:
        process = subprocess.Popen([str(binary), 'run', str(snapshot / 'config.json'),
                                    str(snapshot / 'artifacts' / 'anatomy'), str(out)], stdout=log, stderr=subprocess.STDOUT)
        last = start
        while process.poll() is None:
            counters = MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if query(ctypes.c_void_p(int(process._handle)), ctypes.byref(counters), counters.cb):
                peak = max(peak, counters.PeakWorkingSetSize)
            time.sleep(0.2)
            if time.perf_counter() - last >= 30:
                print('running_seconds', round(time.perf_counter()-start, 1), 'process_peak_working_set_bytes', peak, flush=True)
                last = time.perf_counter()
    resource = dict(exit_code=process.returncode, observed_peak_working_set_bytes=peak,
                    wall_seconds_including_launch=time.perf_counter()-start,
                    memory_method='Windows GetProcessMemoryInfo PeakWorkingSetSize sampled every 0.2 s; simulator process only')
    (out / 'resource-receipt.json').write_text(json.dumps(resource, indent=2) + '\n')
    assert process.returncode == 0, (out / 'stdout.log').read_text()
    for name, expected in fingerprints.items():
        assert digest(snapshot / name) == expected, f'Frozen input changed: {name}'
    assert digest(binary) == fingerprints['drosophila-heresy.exe']
    subprocess.run([sys.executable, str(snapshot / 'scripts' / 'analyze.py'), str(out)], check=True)
    completion = dict(seal_sha256=digest(out / 'seal.json'), resource=resource,
                      output_hashes={p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file()},
                      frozen_inputs_verified_after_run=True)
    (out / 'completion.json').write_text(json.dumps(completion, indent=2) + '\n')
    print('COMPLETE', out, flush=True)


if __name__ == '__main__':
    run()
