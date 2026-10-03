import hashlib
import json
import pathlib
import shutil
import subprocess
import collections

BASE = pathlib.Path(__file__).parent
DEST = BASE / 'checkout'
ROOT = pathlib.Path(r'C:\code land\clean-rust')
ACTIVE = ('experiments/s15-lexi-phase6g-', 'experiments/s15-frizz-phase6f-',
          'experiments/s15-frizz-phase6g-', 'experiments/loopus-',
          'experiments/s15-lepori-qwen-', 'experiments/s15-claudia-phase7')
SOURCE = {'.rs', '.py', '.ts', '.tsx', '.js', '.mjs', '.cjs', '.html', '.css',
          '.scss', '.toml', '.lock', '.md', '.yaml', '.yml', '.ps1', '.sh',
          '.bat', '.cmd', '.mq5', '.mqh', '.cpp', '.h', '.c', '.wgsl', '.svg',
          '.sql', '.svelte', '.vue', '.txt', '.json', '.csv', '.tsv'}
IGNORE_PARTS = {'target', 'node_modules', '__pycache__', '.venv', 'venv',
                'cache', 'caches', 'checkpoints', 'weights', 'models',
                'runtime-deps', 'site-packages', 'dist', 'vendor'}

def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True).stdout

def decision(row):
    name = row['path']; p = pathlib.PurePosixPath(name)
    parts = {x.lower() for x in p.parts}
    if name.startswith(ACTIVE): return 'active-agent'
    if row['class'] in {'cache', 'runtime-or-secret', 'protected-evidence'}:
        return row['class']
    if row['symlink']: return 'link-preserved'
    if parts & IGNORE_PARTS: return 'generated-or-dependency'
    if any(x in name.lower() for x in ('-operational/', '.kammi-dev/', 'admin.secret', 'signing.secret')):
        return 'runtime-or-secret'
    if p.suffix.lower() not in SOURCE and p.name not in {'Dockerfile', '.gitignore', '.editorconfig', 'LICENSE', 'Makefile'}:
        return 'local-payload'
    cap = 256 * 1024 if p.suffix.lower() in {'.json', '.csv', '.tsv'} else 2 * 1024 * 1024
    if row['bytes'] > cap: return 'large-local-artifact'
    if any(x in parts for x in ('worlds', 'test_inputs', 'test-truth', 'truth')):
        return 'dataset-preserved'
    if any(x.startswith(('.codex', '.pydeps', '.cargo-target')) for x in parts):
        return 'cache'
    return 'capture'

def main():
    inventories = json.loads((BASE / 'worktrees.json').read_text())
    receipts = []; excluded = []; conflicts = []
    for idx, info in enumerate(inventories):
        source = pathlib.Path(info['worktree'])
        rows = json.loads((BASE / info['inventory']).read_text())
        for row in rows:
            why = decision(row)
            receipt = {'worktree': str(source), 'head': info['HEAD'], **row}
            if why != 'capture':
                excluded.append({**receipt, 'reason': why}); continue
            src = source / row['path']; dst = DEST / row['path']
            if not src.is_file():
                if idx == 0 and 'D' in row['status'] and dst.is_file():
                    dst.unlink(); receipts.append({**receipt, 'operation': 'tracked-deletion'})
                continue
            before = src.stat(); data = src.read_bytes(); after = src.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                excluded.append({**receipt, 'reason': 'changed-during-read'}); continue
            sha = hashlib.sha256(data).hexdigest()
            # Older worktree deltas never overwrite the main source snapshot.
            if idx and dst.exists():
                if dst.read_bytes() == data: continue
                archive = pathlib.Path('docs/blackrootWorks-2026-10-03/worktree-variants') / f'wt-{idx:02d}' / row['path']
                dst = DEST / archive
                conflicts.append({'original': row['path'], 'archive': str(archive).replace('\\', '/'), 'worktree': str(source)})
            dst.parent.mkdir(parents=True, exist_ok=True); dst.write_bytes(data)
            receipts.append({**receipt, 'sha256': sha, 'destination': dst.relative_to(DEST).as_posix()})
    report = DEST / 'docs/blackrootWorks-2026-10-03'
    report.mkdir(parents=True, exist_ok=True)
    for name, value in [('captured.json', receipts), ('local-and-active.json', excluded), ('conflicts.json', conflicts)]:
        (report / name).write_text(json.dumps(value, indent=2), encoding='utf8')
    shutil.copyfile(__file__, report / 'capture.py')
    (BASE / 'capture-result.json').write_text(json.dumps({'captured': len(receipts), 'excluded': len(excluded), 'conflicts': len(conflicts)}))
    print(json.dumps({'captured': len(receipts), 'excluded': len(excluded), 'conflicts': len(conflicts),
                      'reasons': dict(collections.Counter(x['reason'] for x in excluded))}))

if __name__ == '__main__': main()
