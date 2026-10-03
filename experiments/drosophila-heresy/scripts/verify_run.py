"""Post-run engineering audit; replayed observations never increase sample size."""
import hashlib
import json
import pathlib
import subprocess
import sys
import copy

ROOT = pathlib.Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def strip_timing(bundle):
    result = copy.deepcopy(bundle)
    result.pop('setup_and_execution_seconds')
    for arm in result['results']:
        arm['outcome'].pop('seconds')
    return result


def verify(run):
    seal = json.loads((run / 'seal.json').read_text())
    completion = json.loads((run / 'completion.json').read_text())
    assert digest(run / 'seal.json') == completion['seal_sha256']
    for name, expected in seal['fingerprints'].items():
        assert digest(run / 'sealed' / name) == expected, name
    for name, expected in completion['output_hashes'].items():
        assert digest(run / name) == expected, name
    output = ROOT / 'artifacts' / 'verification' / run.name
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads((run / 'sealed' / 'config.json').read_text())
    config['seeds'] = config['seeds'][:1]
    config['suites'] = config['suites'][:1]
    config['settings'] = config['settings'][:1]
    config['threads'] = 1
    config_path = output / 'replay-config.json'
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    binary = ROOT / 'target' / 'release' / 'drosophila-heresy.exe'
    assert digest(binary) == seal['fingerprints']['drosophila-heresy.exe']
    subprocess.run([str(binary), 'run', str(config_path), str(run / 'sealed' / 'artifacts' / 'anatomy'), str(output)], check=True)
    name = f"{config['suites'][0]['name']}-{config['settings'][0]['name']}.jsonl"
    expected = json.loads((run / name).read_text().splitlines()[0])
    actual = json.loads((output / name).read_text().splitlines()[0])
    assert strip_timing(expected) == strip_timing(actual), 'real-slice replay differs'
    receipt = dict(status='VERIFIED', frozen_files_checked=len(seal['fingerprints']),
                   output_files_checked=len(completion['output_hashes']), seal_sha256=digest(run / 'seal.json'),
                   real_slice_replayed_arms=6, bit_identical_non_timing_results=True,
                   scientific_sample_size_increased=False,
                   output_hashes={p.name: digest(p) for p in output.iterdir() if p.is_file()})
    (output / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    verify(pathlib.Path(sys.argv[1]))
