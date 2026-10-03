"""Post-run replay and observer-off comparison; no added scientific replicates."""
import copy
import json
import pathlib
import subprocess
import sys
from seal_run import ROOT, digest, verify_parent


def normalized(record, remove_observer=False):
    b=copy.deepcopy(record); b.pop('setup_and_execution_seconds')
    for r in b['results']:
        r['result']['outcome'].pop('seconds')
        if remove_observer:
            r['result'].pop('diagnostics');r['result'].pop('observer_array_bytes')
    return b


run=pathlib.Path(sys.argv[1]).resolve()
seal=json.loads((run/'seal.json').read_text());completion=json.loads((run/'completion.json').read_text())
assert digest(run/'seal.json')==completion['seal_sha256']
for name,h in seal['fingerprints'].items():assert digest(run/'sealed'/name)==h,name
for name,h in completion['output_hashes'].items():assert digest(run/name)==h,name
assert verify_parent()==seal['parent_dh01']
out=ROOT/'artifacts/verification'/run.name;out.mkdir(parents=True,exist_ok=False)
config=json.loads((run/'sealed/config.json').read_text())
config['seeds']=config['seeds'][:1];config['taus']=config['taus'][:1];config['sides']=config['sides'][:1];config['threads']=1
binary=ROOT/'target/release/drosophila-heresy-dh02.exe'
assert digest(binary)==seal['fingerprints'][binary.name]
name=f"{config['sides'][0]}-tau{config['taus'][0]:g}.jsonl"
expected=json.loads((run/name).read_text().splitlines()[0])
checks={}
for observe in [True,False]:
    folder=out/('observer_on' if observe else 'observer_off');folder.mkdir()
    config['observe']=observe
    path=folder/'config.json';path.write_text(json.dumps(config,indent=2)+'\n')
    subprocess.run([str(binary),'run',str(path),str(run/'sealed/anatomy'),str(folder)],check=True)
    actual=json.loads((folder/name).read_text().splitlines()[0])
    assert normalized(actual,not observe)==normalized(expected,not observe)
    checks[folder.name]={'all_recorded_non_timing_outputs_equal':True,'raw_sha256':digest(folder/name)}
receipt=dict(status='VERIFIED',checks=checks,real_slice_conditions=3,arms_per_condition=2,
             scientific_sample_size_increased=False,parent_dh01_unchanged=True,
             frozen_files_checked=len(seal['fingerprints']),output_files_checked=len(completion['output_hashes']),
             exact_final_weight_noninterference='verified in synthetic unit tests; final full weights not persisted in scientific outputs')
(out/'verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
