"""Post-run read-only identity/target replay and descriptive endpoint strata.

These extra strata are analysis, not checkpoint selection or survival thresholds.
Never trains any model. Writes a new create-only verification receipt.
"""
import importlib.util
import json

import torch

from common import OUT, REPO, BANK, HERE, receipt, sha
from dataset import load, read_jsonl, action_key
from train import init_model, evaluate, metric, PRIMARY, PRESERVE
from diagnostics_world import representations, readout, score
from global_probes import states


def replay_labels(d):
    ids = [d['row_ids'][int(i)] for i in d['canonical']]
    worlds = read_jsonl(BANK/'worlds'/f'{d["split"]}.jsonl',set(ids))
    path = REPO/'experiments/ff-s15-bank-01/src/simulator.py'
    spec = importlib.util.spec_from_file_location('post_run_sim',path)
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    outside, absent = 0, 0
    for i,wid in enumerate(ids):
        w = worlds[wid]
        st,actions,goal = w['initial_state'],w['available_actions'],w['goal']
        gs = sim.goal_satisfied(st,goal)
        missing = len(w.get('missing_information') or [])
        values = {'solvable':float(sim.shortest_plan(st,actions,goal,max_depth=5) is not None and not gs),
            'goal_satisfied':float(gs),'missing_information_present':float(missing>0),
            'contradiction_present':float(bool(w.get('contradictions'))),
            'number_or_structure_of_missing_requirements':float(missing)}
        for n,v in values.items():
            if float(d['g'][n][i,0])!=v:
                raise RuntimeError(f'global label replay mismatch {wid} {n}')
        legal = {action_key(x) for x in sim.legal_actions(st,actions)}
        for j,a in enumerate(actions):
            ok = action_key(a) in legal
            targets = {PRESERVE:float(ok),'candidate_applicable':float(ok),
                'candidate_has_unmet_requirements':float(not ok),
                PRIMARY:float(sim.goal_satisfied(sim.apply_action(st,a) if ok else st,goal))}
            for n,v in targets.items():
                if float(d['c'][n][i,j])!=v:
                    raise RuntimeError(f'candidate label replay mismatch {wid} {n} {j}')
        sel = w.get('selected_action')
        keys = [action_key(a) for a in actions]
        key = action_key(sel) if sel else None
        expected = keys.index(key) if key in keys else -1
        outside += int(sel is not None and key not in keys)
        absent += int(sel is None)
        if int(d['action'][i])!=expected:
            raise RuntimeError('action label replay mismatch')
    return {'canonical_worlds':len(ids),'all_available_labels':'EXACT',
            'selected_action_absent':absent,'selected_action_outside_candidate_set':outside,
            'simulator_sha256':sha(path)}


def main():
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    lock = json.loads((OUT/'training-lock.json').read_text())
    prepare = json.loads((OUT/'prepare-lock.json').read_text())
    for category in ('source_files',):
        for path,expected in lock[category].items():
            if sha(path)!=expected:
                raise RuntimeError(f'training source changed: {path}')
    continuation = json.loads((OUT/'continuation-lock.json').read_text())
    for path,expected in continuation['source_files'].items():
        if sha(path)!=expected:
            raise RuntimeError(f'continuation source changed: {path}')
    for category in ('model_files','bank_files'):
        for path,expected in prepare[category].items():
            if sha(path)!=expected:
                raise RuntimeError(f'preparation input changed: {path}')
    label_receipt = OUT/'canonical-label-replay.json'
    if label_receipt.exists():
        labels = json.loads(label_receipt.read_text())
        simulator = REPO/'experiments/ff-s15-bank-01/src/simulator.py'
        if any(v['simulator_sha256']!=sha(simulator) for v in labels.values()):
            raise RuntimeError('canonical label replay source changed')
    else:
        cpu = {s:load(s,'cpu') for s in ('TRAIN','DEV')}
        labels = {s:replay_labels(d) for s,d in cpu.items()}
        del cpu
        receipt(label_receipt,labels)
    tr,dv = load('TRAIN'),load('DEV')
    for d in (tr,dv):
        d['canonical_lookup'] = {d['row_ids'][int(i)]:j for j,i in enumerate(d['canonical'])}
    init = torch.load(OUT/'initialization.pt',weights_only=True)
    reports = {}
    frozen_candidate,frozen_global = {},{}
    for arm in ('phase1','phase1b'):
        rec = json.loads((OUT/arm/'receipt.json').read_text())
        start = json.loads((OUT/arm/'run-start.json').read_text())
        if start['initialization_sha256']!=sha(OUT/'initialization.pt'):
            raise RuntimeError('initialization receipt mismatch')
        path = OUT/arm/f'epoch-{rec["best_epoch"]}.pt'
        if sha(path)!=rec['checkpoint_sha256']:
            raise RuntimeError('selected checkpoint seal mismatch')
        state = torch.load(path,weights_only=True)
        if arm=='phase1b':
            for n,p in state.items():
                if n.startswith('heads.') and not any(n.startswith(f'heads.c.{t}.')
                                                      for t in (PRIMARY,PRESERVE)):
                    if not torch.equal(p,init[n]):
                        raise RuntimeError(f'isolated forbidden head changed {n}')
        model = init_model(tr)
        model.load_state_dict(state)
        ev,g,c,a = evaluate(model,dv,lock['prevalences'],arm=='phase1b',outputs=True)
        if ev!=rec['trained']:
            raise RuntimeError(f'final evaluation replay mismatch {arm}')
        if arm=='phase1':
            frozen_candidate['trained'] = representations(model,dv)
            frozen_global['trained'] = states(model,dv)
        mask = dv['H']['cand_mask'][dv['canonical']]
        not_already = dv['g']['goal_satisfied'][:,0]<.5
        legal = dv['c'][PRESERVE]>.5
        move = torch.tensor([[j<len(actions) and actions[j]['type']=='MOVE' for j in range(28)]
                             for actions in dv['actions']],device='cuda')
        strata = {}
        for name,m in (('all_valid',mask),('initial_goal_not_satisfied',mask&not_already[:,None]),
                       ('legal_MOVE_initial_goal_not_satisfied',mask&legal&move&not_already[:,None])):
            if m.any():
                strata[name] = metric(c[PRIMARY][m],dv['c'][PRIMARY][m],lock['prevalences'][PRIMARY])
        endpoint = None
        if arm=='phase1':
            valid = dv['action']>=0
            nonempty = dv['optimal'].any(1)
            defined = valid&nonempty
            pred = a.argmax(1)
            hit = dv['optimal'].gather(1,pred[:,None]).flatten()
            cardinality = mask[valid].sum(1).float()
            endpoint = {'optimal_set_hit_when_gold_set_nonempty':float(hit[defined].float().mean()),
                'optimal_set_hit_count':int(hit[defined].sum()),
                'exact_logged_action_accuracy_same_nonempty_gold_subset':
                    float((pred[defined]==dv['action'][defined]).float().mean()),
                'exact_logged_action_hit_count_same_nonempty_gold_subset':
                    int((pred[defined]==dv['action'][defined]).sum()),
                'exact_logged_action_hit_count_all_eligible':int((pred[valid]==dv['action'][valid]).sum()),
                'exact_logged_action_eligible_rows':int(valid.sum()),
                'defined_optimal_set_endpoint_rows':int(defined.sum()),
                'empty_gold_optimal_set_endpoint_rows':int((valid&~nonempty).sum()),
                'uniform_random_candidate_expected_accuracy':float((1/cardinality).mean()),
                'historical_inverse_mean_cardinality':float(1/cardinality.mean()),
                'these_descriptive_strata_used_for_selection':False}
        reports[arm]={'selected_epoch':rec['best_epoch'],'evaluation_replay':'EXACT',
            'goal_relative_strata':strata,'endpoint_denominator_audit':endpoint,
            'forbidden_heads_unchanged':True if arm=='phase1b' else None}
        del model,state,g,c,a
    probes = json.loads((OUT/'recoverability-world-v02/receipt.json').read_text())
    if not probes['instrument_valid']:
        raise RuntimeError('recoverability positive controls not valid')
    model = init_model(tr)
    model.load_state_dict(init)
    frozen_candidate['init'] = representations(model,dv)
    frozen_global['init'] = states(model,dv)
    m = dv['H']['cand_mask'][dv['canonical']]
    for name,rec in probes['arms'].items():
        role,rep,kind,target,epochs = name.split('-')
        X = frozen_candidate[role][rep]
        net = readout(X.shape[-1],kind=='mlp','cuda')
        for suffix,metric_key,sha_key in (('final','final_epoch','final_readout_sha256'),
                ('best-train','best_train_loss_secondary','best_train_readout_sha256')):
            path = OUT/'recoverability-world-v02'/f'{name}-{suffix}.pt'
            if sha(path)!=rec[sha_key]:
                raise RuntimeError('candidate readout seal mismatch')
            net.load_state_dict(torch.load(path,weights_only=True))
            if score(net,X,dv['c'][target],m,lock['prevalences'][target])!=rec[metric_key]:
                raise RuntimeError('candidate readout scoring replay mismatch')
    global_folder = OUT/'global-init-probes-v01'
    globals_ = json.loads((global_folder/'receipt.json').read_text())
    gp = json.loads((global_folder/'protocol.json').read_text())
    for path,h in gp['source_files'].items():
        if sha(path)!=h:
            raise RuntimeError('global diagnostic source seal mismatch')
    gm = torch.ones((len(dv['canonical']),1),dtype=torch.bool,device='cuda')
    for name,rec in globals_['arms'].items():
        role,target,kind = name.split('-')
        X = frozen_global[role]
        net = readout(X.shape[-1],kind=='mlp','cuda')
        for suffix,metric_key,sha_key in (('final','final_epoch','final_readout_sha256'),
                ('best-train','best_train_loss_secondary','best_train_readout_sha256')):
            path = global_folder/f'{name}-{suffix}.pt'
            if sha(path)!=rec[sha_key]:
                raise RuntimeError('global readout seal mismatch')
            net.load_state_dict(torch.load(path,weights_only=True))
            if score(net,X,dv['g'][target],gm,lock['prevalences'][target])!=rec[metric_key]:
                raise RuntimeError('global readout scoring replay mismatch')
    receipt(OUT/'trial-verification.json',{'status':'PASS','sources_and_inputs_unchanged':True,
        'label_replay':labels,'label_replay_receipt_sha256':sha(label_receipt),
        'arms':reports,'shared_initialization':'EXACT',
        'candidate_readout_replays':len(probes['arms']),'global_readout_replays':len(globals_['arms']),
        'final_and_best_train_readout_scores':'EXACT',
        'graft_training_runs':2,'protected_test_opened':False,
        'analysis_source_sha256':sha(HERE/'audit_trial.py'),
        'claim_scope':'repaired Qwen acquisition; NOT substrate-only superiority over historical MiniCPM'})
    print(json.dumps(reports,indent=2))


if __name__=='__main__':
    main()
