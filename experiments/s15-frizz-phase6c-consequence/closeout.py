"""Fixed response-vector disposition, readable report and immutable lane seal."""
from common import *


def table(head,rows):
    return '\n'.join(['| '+' | '.join(head)+' |','| '+' | '.join(['---']*len(head))+' |']+
        ['| '+' | '.join(map(str,row))+' |' for row in rows])+'\n'


def fmt(v):return 'NA' if v is None else f'{v:.4f}'


def main(replay=False):
    lock()
    if replay:
        sealed=read(OUT/'PHASE6C-SEALED.json')
        for name,digest in sealed['artifacts'].items():
            if sha(OUT/name)!=digest:raise ValueError('seal artifact drift '+name)
        receipt(OUT/'seal-replay.json',{'status':'PASS','artifact_count':len(sealed['artifacts']),
            'seal_sha256':sha(OUT/'PHASE6C-SEALED.json'),'evaluation_opened':False});return
    for stage in ('canonical-replay','input-replay','model-replay','controls','training-complete'):
        if read(OUT/f'{stage}.json')['status']!='PASS':raise ValueError('unfinished '+stage)
    result=read(OUT/'results.json');census=read(OUT/'support-census.json');train=read(OUT/'training-complete.json')
    decision=result['decision'];a=result['results']['init']['primary'];b=result['results']['trained']['primary']
    report=['# Frizz Phase 6C — transition-consequence acquisition','',
        'Status: completed, exact fresh-process replay verified; protected evaluation unopened.','',
        '## Outcome','',decision['disposition'], '',
        table(['Response coordinate','Initialization','Epoch8','Gate'],[
            ['Legal-category macro recall',fmt(a['factor']['legal_macro_recall']),fmt(b['factor']['legal_macro_recall']),decision['factor_qualified']],
            ['Certified conditional MAE',fmt(a['factor']['certified_conditional_distance_MAE']),fmt(b['factor']['certified_conditional_distance_MAE']),decision['factor_qualified']],
            ['Conditional same-type legal ordering',fmt(a['conditional_distance_order']['root_mean_order_accuracy']),fmt(b['conditional_distance_order']['root_mean_order_accuracy']),decision['ordering_qualified']],
            ['Same-type selected top1',fmt(a['ranking']['same_type']['selected']['top1']),fmt(b['ranking']['same_type']['selected']['top1']),decision['ranking_qualified']]]),
        'This is direct planner-supervision acquisition, not a frozen accessibility probe. A positive result would not show the consequence signal was accessible before this training. A negative bounds this one construction and cannot establish a Qwen information ceiling. F remains parked; no new comparator, recurrence, LoRA or adaptation follows.','',
        '## Frozen lineage and ABI','',
        '- Qwen/Qwen3.5-0.8B-Base revision dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68, frozen BF16 qualified substrate. Existing bridge/E checkpoints and goal heads unchanged.',
        '- BANK-v3-core release 84f0a7e13032e8cdfcecc862217bb33ca23568fade64fafeef410327eb996f12, synthetic-only; conflict diagnostic-only; protected EVAL untouched.',
        '- Same Phase6B endpoint-eligible population: 1,333 TRAIN /333 DEV canonical roots, both renderings grouped. All candidate types and exhaustive menus retained. This does not establish acquisition on the non-EXECUTE part of BANK-v3-core.',
        '- ABI: observable type9, four qualified positional arguments1024 with typed roles/presence, two existing observable goal-role vectors1024 and ambiguity flags, six TRAIN-normalized global surfaces1024, frozen E c256/e32/s64. No gold feature, selected ID, latent binding repair, new token extraction or candidate cap.',
        '- Paired frozen E states replayed on CPU from the same checkpoint; primary alignment against the historical FP16 caches and prospective .02 tolerance appear in support-census.json. Both renderings use a matched CPU path. Sidecar arithmetic is FP32; Qwen and E are not trainable.',
        '- Baseline positional vectors already carry schema order. The sidecar makes consequence structure trainable; it does not claim E was previously devoid of roles.','',
        '## Canonical targets and support','',
        'Canonical legal apply at tick1 followed by pinned search(depth8,states40,000). Codes0..8=certified SOLVED remaining distance;9=UNSAT_EXHAUSTED;10=CAP/STATE_LIMIT UNKNOWN;11=ILLEGAL. All categories remain explicit. Fresh simulator replay verifies every retained TRAIN/DEV candidate; immutable input/source hashes are in SPECIFICATION.json.','',
        table(['Code','TRAIN candidates','TRAIN roots','DEV candidates','DEV roots','DEV supported≥200'],[
            [str(k),census['TRAIN']['support'][str(k)]['canonical_candidates'],census['TRAIN']['support'][str(k)]['roots'],
             census['DEV']['support'][str(k)]['canonical_candidates'],census['DEV']['support'][str(k)]['roots'],census['DEV']['support'][str(k)]['root_supported']]
             for k in range(12)]),
        'Candidates above are canonical, not doubled renderings. Per-class claims below200 DEV roots are descriptive. This census includes every candidate type; its denominators differ from Phase6B selected-type factor probes. Ordering population and rendered counts remain explicit in support-census.json.','',
        '## One estimator and fixed training','',
        f"{train['parameters']} trainable sidecar parameters; shared entity1024→32/world1024→16 projections, argument×goal product,823→128→64 GELU MLP, separate four-way status head and monotone eight-cutpoint ordinal distance. No setwise interaction.",
        '- Eight fixed epochs, seed0,16 paired canonical-root batches, AdamW .001/.01, clipping1. No interim DEV scoring or endpoint selection. TRAIN-only inverse-square-root status weights and threshold prevalence balancing; solved ordinal BCE +.25 SmoothL1/8 +.25 same-type certified ordering +.05 paired value consistency.',
        '- Ordering examples use any unequal certified same-type candidate consequences, never selected identity; fixed maximum64 TRAIN pairs/root. DEV ordering enumerates all such pairs.',
        '- Inference value = p_solved E[d]+9p_exhausted+10p_unknown+11p_illegal. Special-state penalties are a declared ranking convention, not true ordinal distances or proofs about unknown continuations. Status probabilities and conditional distance remain separately recorded.',
        '- All target weighting, architecture, dose, rendering, ranking and survival rules were frozen before new DEV contact. Initialization and epoch8 are the only scored checkpoints.','',
        '## Consequence factor panel','',
        table(['Phenotype/render','Legal accuracy','Legal macro recall','Certified MAE','Ordinal absolute error','Legal candidates'],[
            [state+'/'+render,fmt(p['factor']['legal_distance_accuracy']),fmt(p['factor']['legal_macro_recall']),
             fmt(p['factor']['certified_conditional_distance_MAE']),fmt(p['factor']['certified_ordinal_absolute_error']),p['factor']['legal_candidates']]
             for state in ('init','trained') for render,p in result['results'][state].items() if render in ('primary','paired')]),
        'Full category recalls and root/class supports: results.json → results → phenotype → render → factor. Illegal/exhausted/unknown are not silently relabeled as solved. Conditional distance metrics do not excuse incorrect status predictions.','',
        '## Legal-vs-legal consequence ordering','',
        table(['Phenotype/render','Conditional ordering root mean','Value ordering root mean','Pairs','Roots','Supported≥200'],[
            [state+'/'+render,fmt(p['conditional_distance_order']['root_mean_order_accuracy']),fmt(p['induced_cost_order']['root_mean_order_accuracy']),
             p['conditional_distance_order']['pairs'],p['conditional_distance_order']['roots'],p['conditional_distance_order']['root_supported']]
            for state in ('init','trained') for render,p in result['results'][state].items() if render in ('primary','paired')]),
        'Own-init paired-root conditional ordering gain: '+str(decision['conditional_order_gain_vs_init'])+'. Selected-type ordering is separately retained. If this support is below200, interpretation remains a pilot rather than a reliability-level consequence-ordering claim. Improvement due only to illegality filtering cannot pass the ordering gate.','',
        '## Ranking induced by consequence value','',
        table(['Source/universe','Selected top1','MRR','Top3','Top5','Best optimal mean rank','Roots'],[
            [state+'/'+render+'/'+universe,fmt(m['selected']['top1']),fmt(m['selected']['MRR']),fmt(m['selected']['top3']),fmt(m['selected']['top5']),fmt(m['optimal']['mean_rank']),m['selected']['roots']]
            for state in ('init','trained') for render in ('primary','paired')
            for universe,m in result['results'][state][render]['ranking'].items()]),
        'Gold-legal restrictions are diagnostic truth-assisted slices, not inference inputs. Same-type restriction uses the logged action type for localization; full-set ranking is unrestricted. Stable canonical menu order breaks numeric ties. Logged selection and best optimal-set membership retain separate supports and exclusion counts.','',
        table(['Frozen/reference universe','Selected top1','MRR','Top3','Top5','Roots'],[
            [family+'/'+universe,fmt(m['selected']['top1']),fmt(m['selected']['MRR']),fmt(m['selected']['top3']),fmt(m['selected']['top5']),m['selected']['roots']]
             for family,panels in result['frozen_independent_scorers'].items() for universe,m in panels.items()]+
            [['gold-distance/'+universe,fmt(m['selected']['top1']),fmt(m['selected']['MRR']),fmt(m['selected']['top3']),fmt(m['selected']['top5']),m['selected']['roots']]
             for universe,m in result['gold_distance_oracle'].items()]),
        'Primary same-type top1 gain versus prospectively fixed frozen E-linear reference: '+str(decision['same_type_top1_gain_vs_fixed_linear'])+'. The frozen linear and TinyMLP references remain distinct. This is a distillation trial against historical scalar references, not a controlled claim isolating every architecture/backend difference. Gold remaining-distance oracle requires expensive canonical planning. No selected target enters training.','',
        'The original oracle additionally restricts to canonical permission-qualified candidates. Pure-distance unrestricted gold variants are also shown: distance supervision alone does not encode policy permission, and ties/permission may limit logged-action ranking. The permission field is used for these oracle reports only, never in the estimator or its losses.','',
        'Candidate-count full/same-type ranking and denominator slices, renderer factor/ranking panels, and pair disagreement are fully retained in results.json. Only MOVE was reliability-supported in the frozen selected-action panel; other action claims are not promoted.','',
        '## Preservation','',
        'Qwen/E/goal checkpoints and existing full-bank production logits are byte-invariant before/after. The independent consequence optimizer contains no E or Qwen parameter. Goal BA, TRAIN-defined hard binding/globalization cells and renderer panels are repeated as unchanged metrics in results.json → preservation (3,000 DEV roots, both views). This is isolation/hash preservation, not a new goal-access training measurement.',
        '- Sidecar candidate permutation equivariance passed for initialization and epoch8; candidate IDs are join-only.',
        '- Estimator paired-render top1/value disagreement is reported for both initialization and trained outputs. Goal renderer behavior is untouched, not optimized by the new task.',
        '- Known-solvable ordinal-gradient and full-status decoder controls passed. Input/cache, canonical targets, initialization/epoch8 outputs, metrics, dispositions and frozen-input identities have fresh-process verification.','',
        '## Final disposition','',str(decision),'',
        'Factor acquisition, operational ranking acquisition, and legality-only filtering are kept distinct. No aggregate composite score. No automatic F, comparator, recurrence, LoRA or hidden-state search after failure.','',
        '## Costs and artifacts','',
        f"TRAIN fit {train['training_seconds']:.2f}s, {train['steps']} optimizer steps, {train['parameters']} sidecar parameters, CPU FP32/four threads. Preparation/evaluation timing receipts record frozen-feature replay and per-row/candidate throughput; timings are on a shared host, not isolated microbenchmarks. No Qwen extraction or GPU reset occurred.",
        'Checkpoint, target census, ABI, TRAIN weighting, journal, fixed output, preservation and replay hashes are bound by PHASE6C-SEALED.json. Source-v01 and its preparation failure remain preserved; source-v02 corrects only the comparison of unused padding and the historical permission-qualified oracle reference, without increasing tolerances or changing the estimator. Existing lineage and failed Phase6B engineering attempts remain untouched. Protected evaluation unopened.','']
    (OUT/'REPORT.md').write_text('\n'.join(report),encoding='utf-8')
    artifacts={str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in sorted(OUT.rglob('*'))
        if p.is_file() and p.name not in ('PHASE6C-SEALED.json','seal-replay.json','finish.stdout.log','finish.stderr.log','pipeline-complete.json')}
    receipt(OUT/'PHASE6C-SEALED.json',{'status':'SEALED','artifacts':artifacts,'disposition':decision['disposition'],
        'Qwen_revision':'dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68','BANK_release':'84f0a7e13032e8cdfcecc862217bb33ca23568fade64fafeef410327eb996f12',
        'E_checkpoint_sha256':sha(P5/'E/run/epoch-8.pt'),'consequence_checkpoint_sha256':sha(OUT/'epoch-8.pt'),
        'F':'PARKED','protected_evaluation_opened':False,'automatic_escalation':False})


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args();main(a.replay)
