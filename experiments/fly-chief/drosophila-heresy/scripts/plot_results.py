"""Post-run Matplotlib rendering of already frozen statistics; no new inference."""
import hashlib
import json
import pathlib
import sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.plot-deps'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


run = pathlib.Path(sys.argv[1]).resolve()
summary_path = run / 'summary.json'
completion = json.loads((run / 'completion.json').read_text())
assert digest(summary_path) == completion['output_hashes']['summary.json']
summary = json.loads(summary_path.read_text())
out = ROOT / 'artifacts' / 'figures' / run.name
out.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
fig, (ax, curve) = plt.subplots(1, 2, figsize=(12.8, 4.7), gridspec_kw={'width_ratios': [1.0, 1.2]})
fig.subplots_adjust(left=0.15, right=0.98, bottom=0.21, top=0.73, wspace=0.34)
fig.suptitle('DH-01: no reliable routing advantage in this model', fontsize=17, x=0.04, ha='left', y=0.97)
fig.text(0.04, 0.87, '1,728 arm runs | 24 seed bundles | 4 dynamics settings | 3 suites | one specimen', fontsize=10, color='#555555')
for y, (suite, label) in enumerate([('task_transfer', '32-cue transfer'), ('left_transfer', 'Left soma slice'), ('primary', 'Primary: right slice')]):
    e = summary['effects'][suite]
    point = 100 * e['mean']
    lo, hi = [100 * v for v in e['ci95']]
    ax.errorbar(point, y, xerr=[[point-lo], [hi-point]], fmt='o', capsize=5, color='#176d8a', lw=2)
    ax.text(0.75, y+0.20, f'{point:+.3f} pp', ha='right', fontsize=9)
ax.set_yticks([0, 1, 2], ['32-cue transfer', 'Left soma slice', 'Primary: right slice'])
ax.set_ylim(-0.6, 2.6)
ax.set_xlim(-0.8, 0.8)
ax.axvline(0, color='#777777', linestyle='--', linewidth=1)
ax.set_xlabel('Anatomical minus shuffled routing\n(percentage points; 95% bootstrap interval)')
ax.set_title('Paired routing effect', loc='left', fontsize=12, pad=14)
ax.grid(axis='x', alpha=0.15)
colors = {'A': '#176d8a', 'B': '#cb6537', 'Z': '#666666'}
labels = {'A': 'A: anatomical routing', 'B': 'B: shuffled routing', 'Z': 'Z: no learning'}
for arm in ['A', 'B', 'Z']:
    values = [100*v for v in summary['arm_means']['primary'][arm]['curve']]
    curve.plot([32+64*i for i in range(8)], values, marker='o', markersize=3, color=colors[arm], label=labels[arm])
curve.axhline(50, color='#aaaaaa', linestyle=':', linewidth=1)
curve.axvline(256, color='#999999', linestyle='--', linewidth=1)
curve.text(262, 65, 'Reversal', color='#666666', fontsize=9)
curve.set_ylim(35, 67)
curve.set_xlim(0, 512)
curve.set_xlabel('Training trial (64-trial block means)')
curve.set_ylabel('Online accuracy (%)')
curve.set_title('Learning occurs; reversal recovery is limited', loc='left', fontsize=12, pad=14)
curve.legend(loc='lower left', frameon=False, fontsize=8)
curve.grid(axis='y', alpha=0.15)
fig.text(0.04, 0.025, 'Primary comparison is inferential; transfer intervals are descriptive. Synthetic dynamics and coarse routing; no biological conclusion.', fontsize=9, color='#555555')
for extension in ['png', 'svg']:
    fig.savefig(out / f'routing-effect.{extension}', dpi=160, facecolor='white')
plt.close(fig)
receipt = dict(summary_sha256=digest(summary_path), statistics_recomputed=False,
               matplotlib_version=matplotlib.__version__,
               output_hashes={p.name: digest(p) for p in out.iterdir() if p.suffix in ['.png', '.svg']})
(out / 'plot-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(out / 'routing-effect.png')
