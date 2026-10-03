"""Presentation of frozen DH02 results using Matplotlib; no new inference."""
import hashlib
import json
import pathlib
import sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'.plot-deps'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


run=pathlib.Path(sys.argv[1]).resolve()
completion=json.loads((run/'completion.json').read_text())
assert digest(run/'summary.json')==completion['output_hashes']['summary.json']
s=json.loads((run/'summary.json').read_text());m=s['means']['R']['E']
out=ROOT/'artifacts/figures'/run.name;out.mkdir(parents=True,exist_ok=True)
conditions=['immediate','quiet','distractor'];labels=['Immediate','Quiet delay','Distractor delay']
colors=['#227b71','#7977a0','#ce713f']
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,(a,b)=plt.subplots(1,2,figsize=(12.5,4.8),gridspec_kw={'width_ratios':[1,1.5]})
fig.subplots_adjust(left=0.07,right=0.98,bottom=0.23,top=0.73,wspace=0.28)
fig.suptitle('DH-02: distractors outperformed quiet delay, but both stayed below chance',x=0.04,ha='left',y=0.97,fontsize=15)
fig.text(0.04,0.86,'Identical acquired states | 24 fresh seed bundles | two eligibility settings | right soma slice',fontsize=10,color='#555555')
values=[100*m[c]['probe_reversal'] for c in conditions]
a.bar(labels,values,color=colors,width=0.65)
for i,v in enumerate(values):a.text(i,v+2,f'{v:.2f}%',ha='center')
a.axhline(50,color='#777777',linestyle='--',linewidth=1)
a.set_ylim(0,85);a.set_ylabel('Final reversal-probe accuracy (%)');a.set_title('Uniform local learning',loc='left',fontsize=12)
for c,label,color in zip(conditions,labels,colors):
    b.plot([32+64*i for i in range(8)],[100*v for v in m[c]['curve']],'-o',markersize=3,color=color,label=label)
b.axvline(256,color='#777777',linestyle='--',linewidth=1);b.axhline(50,color='#999999',linestyle=':',linewidth=1)
b.set_ylim(15,85);b.set_xlim(0,512);b.set_xlabel('Training trial (64-trial means)');b.set_ylabel('Online accuracy (%)')
b.set_title('Common acquisition, then assigned reversal condition',loc='left',fontsize=12)
b.legend(loc='upper right',frameon=False,fontsize=8)
effect=s['primary'];fig.text(0.04,0.115,f"Primary quiet-minus-distractor effect: {100*effect['mean']:+.2f} percentage points; 95% paired interval [{100*effect['ci95'][0]:+.2f}, {100*effect['ci95'][1]:+.2f}].",fontsize=11)
fig.text(0.04,0.045,'Single specimen and synthetic dynamics. The effect does not establish which internal mechanism caused it.',fontsize=9,color='#555555')
for ext in ['png','svg']:fig.savefig(out/f'dh02-results.{ext}',dpi=160,facecolor='white')
plt.close(fig)
receipt=dict(summary_sha256=digest(run/'summary.json'),statistics_recomputed=False,matplotlib_version=matplotlib.__version__,
             output_hashes={p.name:digest(p) for p in out.iterdir() if p.suffix in ['.png','.svg']})
(out/'plot-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(out/'dh02-results.png')
