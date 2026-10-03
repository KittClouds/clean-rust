"""Typed projections. Canonical hidden truth never becomes observer evidence."""
from common import rng, digest
import engine as sim


def status(values):
    return 'CERTAIN_LEGAL' if all(values) else 'CERTAIN_ILLEGAL' if not any(values) else 'UNRESOLVED'


def clause_status(states, clause):
    values = [sim.test(s, clause) for s in states]
    return 'SATISFIED' if all(values) else 'VIOLATED' if not any(values) else 'UNKNOWN'


def best(w, s, offered, policy_distance):
    if sim.goal(w, s):
        return [], 'ALREADY_GOAL'
    q = []
    for i in offered:
        a = w['actions'][i]
        t = sim.step(w, s, a)
        if t is not None and sim.permitted(s, a) and t in policy_distance:
            q.append((a['environment_cost']+a['policy_cost']+policy_distance[t], a['id']))
    if not q:
        return [], 'NO_OFFERED_GOAL_REACHING_ACTION'
    minimum = min(v for v, _ in q)
    return sorted(k for v, k in q if v == minimum), None


def family(w, split, index):
    states, edges = sim.catalogue(w, [w['initial']])
    r = rng('pair', w['lane'], split, index)
    pairs = []
    state_set = set(states)
    # Compute each action-status bitset once; sibling comparisons are XORs.
    # This removes a domain-size multiplier from candidate-pair construction.
    signatures = {}
    for state in states:
        legal_bits = permission_bits = 0
        for i, a in enumerate(w['actions']):
            if sim.legal(w, state, a):
                legal_bits |= 1 << i
            if sim.permitted(state, a):
                permission_bits |= 1 << i
        signatures[state] = legal_bits, permission_bits
    for s in states:
        for hidden in range(len(s)):
            for value in w['domains'][hidden]:
                t = list(s)
                t[hidden] = value
                t = tuple(t)
                if t <= s or t not in state_set:
                    continue
                changed = (signatures[s][0] ^ signatures[t][0]) | (signatures[s][1] ^ signatures[t][1])
                if changed:
                    pairs.append((s, t, hidden, changed))
    if not pairs:
        raise ValueError('NO_CAUSAL_TRUTH_PAIR')
    unfinished = [p for p in pairs if not sim.goal(w, p[0]) and not sim.goal(w, p[1])]
    s, t, hidden, changed = r.choice(unfinished or pairs)
    witness = [i for i in range(len(w['actions'])) if changed & (1 << i)]
    # Witness guarantees observable uncertainty; other offered actions are sampled
    # without reference to chooser/model outcomes. Order was frozen by producer.
    selected = {r.choice(witness)}
    selected.update(i for i, a in enumerate(w['actions']) if a['type'] == 'WAIT')
    # Dense local pressure: reserve executable alternatives on both siblings;
    # avoid drowning Sokoban's four local moves in hundreds of remote operators.
    for state in (s, t):
        candidates = [i for i, a in enumerate(w['actions']) if a['type'] != 'WAIT' and sim.step(w, state, a) is not None]
        selected.update(r.sample(candidates, min(2, len(candidates))))
    remaining = [i for i in range(len(w['actions'])) if i not in selected]
    # Near misses share supported clauses with the live alternatives.
    r.shuffle(remaining)
    remaining.sort(key=lambda i: max(sum(sim.test(state, c) for c in w['actions'][i]['preconditions'])/
                                     max(1, len(w['actions'][i]['preconditions'])) for state in (s, t)), reverse=True)
    selected.update(remaining[:max(0, 8-len(selected))])
    offered = [i for i in range(len(w['actions'])) if i in selected]
    starts = sim.completions(w, s, hidden)+sim.completions(w, t, hidden)
    states, edges = sim.catalogue(w, starts)
    ds = {mode: sim.distances(w, states, edges, mode) for mode in ('steps', 'environment', 'policy')}
    return {'states': [s, t], 'hidden': hidden, 'offered': offered,
            'reachable_count': len(states), 'distances': ds, 'edges': edges}


def project(w, fam, state, partial):
    hidden = fam['hidden'] if partial else None
    visible = {str(i): v for i, v in enumerate(state) if i != hidden}
    possible = sim.completions(w, state, hidden) if partial else [tuple(state)]
    offered = fam['offered']
    input_frame = {k: v for k, v in w.items() if k not in ('initial',)}
    input_frame['observation'] = visible
    input_frame['complete_slots'] = sorted(visible, key=int)
    input_frame['offered_actions'] = [w['actions'][i]['id'] for i in offered]
    # Domain/schema geometry is public; hidden actual slot value is absent.
    grounded = []
    diagnostic = []
    opt_sets = [set(best(w, s, offered, fam['distances']['policy'])[0]) for s in possible]
    common_opt = set.intersection(*opt_sets)
    uncertain_decision = any(v != opt_sets[0] for v in opt_sets[1:])
    for i in offered:
        a = w['actions'][i]
        legals = [sim.step(w, s, a) is not None for s in possible]
        permissions = [sim.permitted(s, a) for s in possible]
        grounded.append({'candidate_id': a['id'],
                         'clauses': [clause_status(possible, c) for c in a['preconditions']],
                         'permission_clauses': [clause_status(possible, c) for c in a['permission']],
                         'binding_valid': sim.binding_valid(w, a), 'legality': status(legals),
                         'permission': status(permissions)})
        nxt = sim.step(w, state, a)
        operator = a['effects'] if nxt is not None else []
        actual = [[j, nxt[j]] for j, value in enumerate(state) if nxt is not None and nxt[j] != value]
        distance = fam['distances']['steps'].get(tuple(state))
        next_distance = fam['distances']['steps'].get(nxt)
        clock_slots = {w['clock']['slot']} if 'clock' in w else set()
        scheduled_slots = {e[0] for event in w.get('scheduled', []) for e in event['effects']}
        diagnostic.append({'candidate_id': a['id'], 'legal': nxt is not None,
                           'permitted': sim.permitted(state, a),
                           'next_state': list(nxt) if nxt is not None else None,
                           'operator_assignments': operator, 'actual_effects': actual,
                           'scheduled_effects': [e for e in actual if e[0] in scheduled_slots],
                           'clock_effects': [e for e in actual if e[0] in clock_slots],
                           'goal_delta': None if nxt is None else
                           sum(sim.test(nxt, c) for c in w['goal'])-sum(sim.test(state, c) for c in w['goal']),
                           'distance': distance, 'next_distance': next_distance,
                           'distance_status': 'REACHABLE' if distance is not None else 'UNREACHABLE',
                           'next_distance_status': 'INAPPLICABLE' if nxt is None else 'UNREACHABLE' if next_distance is None else 'REACHABLE',
                           'distance_delta': distance-next_distance if distance is not None and next_distance is not None else None,
                           'environment_cost_to_goal': fam['distances']['environment'].get(nxt),
                           'policy_cost_to_goal': fam['distances']['policy'].get(nxt),
                           'environment_step_cost': a['environment_cost'], 'policy_step_cost': a['policy_cost']})
    canonical_opt, canonical_reason = best(w, tuple(state), offered, fam['distances']['policy'])
    if common_opt:
        decision = {'mode': 'ACT', 'optimal_actions': sorted(common_opt),
                    'selected_action': next(iter(common_opt)) if len(common_opt) == 1 else None,
                    'reason': 'ROBUST_OPTIMAL_OVER_OBSERVABLE_COMPLETIONS', 'requested_slot': None}
    elif partial and uncertain_decision:
        decision = {'mode': 'ASK', 'optimal_actions': [], 'selected_action': None,
                    'reason': 'DECISION_RELEVANT_MISSING_SLOT', 'requested_slot': hidden}
    else:
        decision = {'mode': 'ABSTAIN', 'optimal_actions': [], 'selected_action': None,
                    'reason': 'OBSERVABLY_NO_OFFERED_COMPLETION' if partial else canonical_reason,
                    'requested_slot': None}
    return input_frame, {'grounded_observation': [{'slot': i, 'name': name,
                          'status': 'OBSERVED' if str(i) in visible else 'UNKNOWN',
                          'value': visible.get(str(i))} for i, name in enumerate(w['slots'])],
                         'goal_clauses': [clause_status(possible, c) for c in w['goal']],
                         'grounding': grounded, 'decision': decision,
                         'canonical_consequences': diagnostic, 'canonical_optimal_actions': canonical_opt,
                         'supervision_masks': {'grounding': True, 'observable_decision': True,
                                               'canonical_consequences': not partial,
                                               'canonical_optimal_actions': not partial}}


def render(frame, style):
    from common import encode
    if style == 0:
        return encode(frame).decode()
    # A reversible typed record stream; values never lose arguments or state.
    return '\n'.join(k+'\t'+encode(v).decode() for k, v in sorted(frame.items()))


def parse(text, style):
    import json
    if style == 0:
        return json.loads(text)
    return {k: json.loads(v) for k, v in (line.split('\t', 1) for line in text.splitlines())}
