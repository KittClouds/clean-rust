"""Observable-only token and binding census before choosing extraction batching."""
import json
import time
from collections import Counter
from pathlib import Path

from transformers import AutoTokenizer
from adapter import rows
from audit_release import ROOT, sha

HERE = Path(__file__).resolve().parent
MODEL = Path('D:/codex-runs/s15-lepori-qwen-0.8b-base-v01/models/Qwen3.5-0.8B-Base')


def main():
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    binding = json.loads((HERE / 'release-binding-v01.json').read_text())
    report = {'status': 'OBSERVABLE_PREFLIGHT_PASS', 'splits': {},
              'model_tokenizer_sha256': sha(MODEL / 'tokenizer.json'),
              'evaluation_opened': False}
    start = time.perf_counter()
    for split in ('TRAIN', 'DEV'):
        lens, missing, argnames = [], Counter(), Counter()
        max_args = 0
        for path in binding['splits'][split]['public']['files']:
            for row in rows(ROOT / path):
                lens.append(len(tokenizer(row['input_text'], add_special_tokens=True)['input_ids']))
                for b in row['bindings']:
                    missing['bindings'] += 1
                    missing['absent_names'] += b['name'] not in row['input_text']
                for a in row['actions']:
                    max_args = max(max_args, len(a['args']))
                    argnames.update(a['args'].keys())
        lens.sort()
        report['splits'][split] = {'rows': len(lens), 'min_tokens': lens[0],
            'median_tokens': lens[len(lens)//2], 'p99_tokens': lens[int(len(lens)*.99)],
            'max_tokens': lens[-1], 'rows_over_512': sum(x > 512 for x in lens),
            'max_arguments': max_args, 'argument_roles': sorted(argnames), **missing}
    report['seconds'] = time.perf_counter() - start
    out = HERE / 'observable-preflight-v01.json'
    with out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
