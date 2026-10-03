"""Create-only scientific report and artifact inventory; fresh verifier separate."""
from common import *

def seal():
    lock();v=read(OUT/'results.json');replay=read(OUT/'fresh-process-replay.json')
    if replay['status']!='PASS':raise ValueError('replay missing')
    lines=['# Phase 6F — legality observability and identifiability',
           '',v['decision']['disposition'],'',
           'No models trained, no bank rows modified, protected evaluation unopened.',
           'Canonical legality is positive/negative simulator preconditions, not permission.',
           '', '| Population | Roots | Candidates | Directly witnessed ambiguous roots | Strict fully certified roots |',
           '|---|---:|---:|---:|---:|']
    for split,d in v['splits'].items():
        s=d['supports'];lines.append(f"| {split} | {s['canonical_roots']} | {s['canonical_candidates']} | {d['verified_ambiguous_roots']} ({d['verified_ambiguous_fraction']:.2%}) | {d['strict_certified_roots']} |")
    lines += ['', '## Interpretation', '',
        'Byte-identical permitted-interface counterfactuals are direct non-identifiability witnesses within the pinned semantic/world domain. Each preserves conditional EXECUTE and is checked in both renderer families. They are private diagnostic alternatives, not newly sealed corpus rows, and do not establish their probability under the original seed generator.',
        'The empirical bank ceilings and balanced counterfactual audit ceilings are reported separately. A 100% empirical ceiling in a unique-world sample does not establish observability. Conversely, the fraction with a witness is not an original-bank Bayesian accuracy ceiling.',
        'Partition roots as VERIFIED_AMBIGUOUS, OBSERVABLE_RULE_CERTIFIED, and UNRESOLVED_NOT_CERTIFIED. Absence of a witness does not certify the third group. No Qwen capacity ceiling is inferred.',
        '', '## Oracle and source tracing', '',
        'The strict three-valued oracle uses active direct records plus pinned functional location/attribute semantics. Reports remain claims, never certainty. Missing predicates remain unknown; absent negative predicates are not silently false. The separately reported closed-graph oracle adds a recipe-level assumption only when the full population census finds no hidden graph facts or unrendered slot markers. That is an assumption-qualified reference, not additional text given to Qwen.',
        'Semantic signatures retain full observable root context and candidate coordinates; entity names/bindings, direct records, report claims, emitted gates/policies/costs/query questions, goal prose/mentions, and public requests are traced to actual renderer consumption. Private relation registry IDs are excluded; emitted relation phrases and goal prose remain lexical where inversion is ambiguous. Semantic renderer differences are not automatically leaks or impossibility proofs. Exact interface witnesses retain raw full text, binding/goal information and deterministic type/argument coordinates.',
        '', '## Detailed recorder', '']
    for split,d in v['splits'].items():
        o=d['oracle']['strict'];lines += [f'### {split}', '',
            f"Strict candidate coverage: {o['coverage']:.2%}; certain-legal precision: {o['certain_legal_precision']}; certain-illegal precision: {o['certain_illegal_precision']}.",
            f"Empirical exact-input full-set ceiling: {d['exact_input_root_ceiling']['empirical_exact_set_ceiling']:.6f}; gold-type-conditioned same-type ceiling: {d['exact_same_type_ceiling_gold_type_conditioned']['empirical_exact_set_ceiling']:.6f}.",
            f"Counterfactual augmented-sample full-set ceiling (NOT original bank): {d['augmented_counterfactual_exact_ceiling_NOT_original_bank']['empirical_exact_set_ceiling']:.6f}; equal-root balanced-pair bound: {d['equal_root_balanced_pair_audit_ceiling_NOT_original_bank']:.6f}.",
            f"Hidden predicates producing witnesses: {canonical(d['witness_hidden_predicates'])}; selected labels flipped: {d['selected_candidates_flipped_by_witness']}.",
            f"Renderer recorder: {canonical(d['renderer'])}; failed paired proofs: {d['paired_witness_failures']}.",
            f"Closed-graph qualification valid: {d['recipe_closed_graph_assumption_valid_on_population']}; qualified root count: {d['recipe_certified_roots']}.", '']
    lines += ['Unknown-clause attribution (both renderings; clauses, not mutually exclusive candidate counts):', '',
        '```json',json.dumps(v['attribution_unknown_clauses'],indent=2,sort_keys=True),'```','',
        '## Verification and limitations','',
        'Seven unit/positive-control tests include direct truth, unresolved absence, functional-slot contradiction, inactive schedules, candidate/root modal ceilings, real TRAIN renderer replay, and a canonical hidden-only legality flip. Full fresh-process replay reconstructs every clause, signature, collision class, oracle status, partition and witness and compares canonical content.',
        'This is a conservative bounded witness search, not exhaustive possible-world enumeration. Full-world signatures avoid falsely attributing omitted root context to the model. Root ceilings use whole legal vectors rather than multiplying candidate-level ceilings. Same-type ceilings condition on gold action type as a diagnostic only. No learned oracle or optional neural fit was performed.',
        'All machine-readable denominators, source/input pins and output hashes accompany this report. Existing bridge/E, consequence, legality and LoRA artifacts remain unchanged.', '']
    with (OUT/'REPORT.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines))
    files={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    receipt(OUT/'PHASE6F-SEALED.json',{'status':'SEALED','disposition':v['decision']['disposition'],
        'artifacts':files,'training':False,'protected_evaluation_opened':False,'upstream_inputs_verified':True})
    print('PHASE6F SEALED',flush=True)

if __name__=='__main__':seal()
