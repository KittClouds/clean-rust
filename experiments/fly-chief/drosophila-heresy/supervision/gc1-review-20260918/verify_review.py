"""Post hoc reviewer verification; no search and no parent writes."""
from pathlib import Path
import hashlib
import json
import math
import struct
import sys

OUT = Path(__file__).resolve().parent
REPO = OUT.parents[3]
EXP = REPO / 'experiments/drosophila-heresy'
sys.dont_write_bytecode = True
sys.path.insert(0, str(EXP / 'q10-rh1-f2-v1/scripts'))
import run_rh1 as R


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def f(raw):
    return struct.unpack('<f', struct.pack('<I', raw))[0]


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def bh(raws):
    return hashlib.sha256(b''.join(struct.pack('<I', b) for b in raws)).hexdigest().upper()


def norm(values):
    return math.sqrt(math.fsum(v*v for v in values))


def replay(rows, raw_weights):
    weights = [f(b) for b in raw_weights]
    result = []
    for row in rows:
        acc = -0.0
        for i in row:
            acc = f(bits(acc + weights[i]))
        result.append(bits(acc))
    return tuple(result)


def order(raw):
    return (0x80000000 - (raw & 0x7fffffff)) if raw & 0x80000000 else raw + 0x80000000


def score(actual, target):
    errors = [f(a)-f(b) for a,b in zip(actual,target)]
    return {'mismatch_count': sum(a!=b for a,b in zip(actual,target)),
            'total_ulp_distance': sum(abs(order(a)-order(b)) for a,b in zip(actual,target)),
            'residual_l2': norm(errors), 'maximum_absolute_residual': max(map(abs,errors), default=0.0)}


def geometry(state, raws):
    delta = [f(b)-base for b,base in zip(raws,state.base_weights)]
    target = [w-base for w,base in zip(state.target_weights,state.base_weights)]
    axis = math.fsum(d*a for d,a in zip(delta,state.axis))
    ta = math.fsum(d*a for d,a in zip(target,state.axis))
    dn, tn = norm(delta), norm(target)
    drives = [math.fsum(delta[i] for i in row) for row in state.rows]
    td = [math.fsum(target[i] for i in row) for row in state.rows]
    ce = norm(a-b for a,b in zip(drives,td))
    return {'axis_absolute_error': abs(axis-ta), 'axis_normalized_error': abs(axis-ta)/max(abs(ta),1e-12),
            'norm_absolute_error': abs(dn-tn), 'norm_normalized_error': abs(dn-tn)/max(tn,1e-12),
            'cue_linear_absolute_error': ce, 'cue_linear_normalized_error': ce/max(norm(td),1e-12),
            'final_axis': axis, 'target_axis': ta, 'final_norm': dn, 'target_norm': tn}


def main():
    input_hashes = {}
    def bind(path):
        input_hashes[str(path.relative_to(REPO))] = sha(path)
    for name in ('q10-gc1-par8-v1','q10-gc1-par8-audit1-v1'):
        root = EXP / name
        c, pre = read(root/'CONTRACT.json'), read(root/'PREEXECUTION.json')
        runner = root/'scripts'/('audit.py' if 'audit1' in name else 'run_gc1.py')
        assert c['plan_sha256'] == sha(root/'PLAN.md') == pre['plan_sha256']
        assert pre['contract_sha256'] == sha(root/'CONTRACT.json')
        assert c['sealed_runner_sha256'] == sha(runner) == pre['runner_sha256']
        for entry in c['parent_bindings']:
            path = REPO/entry['path']
            assert sha(path) == entry['sha256'], entry['label']
            bind(path)
        status = read(root/'qualification/derived/STATUS.json')
        for label, relative in [('execution','execution.json'),('summary','derived/SUMMARY.json'),('result','derived/RESULT.md')]:
            path = root/'qualification'/relative
            assert status[label+'_sha256'] == sha(path)
            bind(path)
        for path in (root/'PLAN.md',root/'CONTRACT.json',root/'PREEXECUTION.json',runner,root/'qualification/derived/STATUS.json'):
            bind(path)
    execution = read(EXP/'q10-gc1-par8-v1/qualification/execution.json')
    receipts = execution['endpoint_set_results']
    keys = {(x['endpoint'],x['set_index']) for x in receipts}
    assert len(keys) == len(receipts) == 14
    runtime_bindings = R.verify_contract()
    for rec in receipts:
        assert rec['nested_runtime_bindings'] == runtime_bindings
    states = {s.key:s for s in R.PF5.load_endpoint_states(R.PF5.load_lineage(R.PF5_ROOT), selected_keys=keys)}
    palettes = {}
    for line in (EXP/'q10-gc0-gp1-par2-v1/qualification/palettes.jsonl').open(encoding='utf-8'):
        group = json.loads(line)
        endpoint, index, gid = group['identity']
        palettes.setdefault((endpoint,index),{})[gid] = group
    thresholds = {'axis_normalized_error':2e-6,'norm_normalized_error':2e-7,'cue_linear_normalized_error':2e-6}
    all_rows = []
    for rec in receipts:
        key = rec['endpoint'],rec['set_index']
        state, groups = states[key],palettes[key]
        base_out = replay(state.rows,state.baseline_weight_bits)
        target_out = replay(state.rows,state.target_weight_bits)
        assert base_out == state.baseline_readout_bits and target_out == state.target_readout_bits
        base_score = score(base_out,target_out)
        detail = {'endpoint':key[0],'set_index':key[1],'baseline':base_score,'group_count':len(groups)}
        for kind in ('best_valid','best_search'):
            item = rec[kind]
            chosen = item['selected_candidates']
            assert len(chosen) == len({c['group_index'] for c in chosen}) == len(groups)
            assert {c['group_index'] for c in chosen} == set(groups)
            mapping = {}
            for choice in chosen:
                group = groups[choice['group_index']]
                candidates = [c for c in group['palette'] if c['candidate_identity']==choice['candidate_identity']]
                assert len(candidates)==1
                cand = candidates[0]
                canon = cand['canonical_mapping']
                assert [p[0] for p in canon] == group['coordinates_canonical']
                assert R.CQ.state_identity(dict(canon)) == cand['candidate_identity']
                assert [[i,k] for i,k,_ in cand['committed_f32_mapping']] == canon
                for i,k,b in cand['committed_f32_mapping']:
                    assert b == state.baseline_weight_bits[i]+k
                    if i in mapping: assert mapping[i]==k
                    mapping[i]=k
                if cand['roles']==['ZERO']: assert all(k==0 for _,k in canon)
            assert item['canonical_mapping'] == [list(p) for p in sorted(mapping.items())]
            raw = list(state.baseline_weight_bits)
            for i,k in mapping.items():
                assert k in (0,-1,1,-2,2,-4,4,-8,8,-16,16)
                assert state.permitted[i] and i in state.interior
                raw[i] += k
                assert 0.0<f(raw[i])<2.0 and raw[i]>=16 and bits(2.0)-raw[i]>=16
            assert all(math.isfinite(f(b)) and 0<=f(b)<=2 for b in raw)
            assert all(raw[i]==b for i,b in enumerate(state.baseline_weight_bits) if i not in mapping)
            assert all((f(b) in (0.0,2.0)) == (f(raw[i]) in (0.0,2.0)) for i,b in enumerate(state.baseline_weight_bits))
            actual = replay(state.rows,raw)
            q, g = score(actual,target_out),geometry(state,raw)
            assert q==item['score'] and g==item['geometry']
            assert bh(raw)==item['weight_state_sha256'] and bh(actual)==item['readout_sha256']
            failures = [k for k,t in thresholds.items() if g[k]>t]
            assert (not failures)==item['final_geometry_pass']
            fixed=sum(a!=t and b==t for a,b,t in zip(base_out,actual,target_out))
            damaged=sum(a==t and b!=t for a,b,t in zip(base_out,actual,target_out))
            distinct = tuple(raw)!=state.target_weight_bits
            assert distinct and tuple(raw)!=state.baseline_weight_bits
            if kind=='best_valid':
                assert not failures and tuple(q.values())<tuple(base_score.values())
                assert rec['independent_audit']['weight_state_sha256']==bh(raw)
            detail[kind]={'score':q,'gate_failures':failures,'gate_ratios':{k:g[k]/t for k,t in thresholds.items()},
                          'distinct_from_target':distinct,'changed_coordinates':sum(a!=b for a,b in zip(raw,state.baseline_weight_bits)),
                          'initial_mismatches_fixed':fixed,'previously_exact_rows_damaged':damaged,
                          'active_groups':item['active_group_count']}
        all_rows.append(detail)
        print('verified',key,flush=True)
    assert sum(r['exact_evaluations'] for r in receipts)==execution['counts']['exact_evaluations']
    for relative,h in input_hashes.items(): assert sha(REPO/relative)==h
    report={'scope':'Post hoc verification of saved candidates; no search or behavioral experiment',
            'independence_limit':'Reuses frozen PF5 state loader and CQ identity routine; own struct-based sequential replay, scoring, prefix reconstruction, and geometry calculation; not a cross-language simulator validation.',
            'input_sha256':input_hashes,'script_sha256':sha(Path(__file__)),
            'runtime_bindings':runtime_bindings,'source_counts':execution['counts'],'endpoint_results':all_rows,
            'checks_passed':True,'parents_unchanged':True}
    def check_keys(value, path='root'):
        if isinstance(value,dict):
            assert all(isinstance(k,str) for k in value), (path,list(value))
            for k,v in value.items(): check_keys(v,path+'.'+k)
        elif isinstance(value,list):
            for i,v in enumerate(value): check_keys(v,path+f'[{i}]')
    check_keys(report)
    (OUT/'evidence.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print('REVIEW_VERIFICATION_PASSED',flush=True)


if __name__=='__main__':
    main()
