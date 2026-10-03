"""Full independent semantic qualification, including epistemic completions."""
import reference as ref
from common import digest
from archetype_checks import qualify


def check(condition, name):
    if not condition:
        raise AssertionError(name)


def status(values):
    if len(set(values)) == 2:
        return 'UNRESOLVED'
    return 'CERTAIN_LEGAL' if values[0] else 'CERTAIN_ILLEGAL'


def audit_family(w, fam, roots):
    qualify(w)
    compiled = ref.graph(w, fam['edges'])
    check(compiled == fam['edges'], 'INDEPENDENT_TRANSITIONS')
    check(all(t in compiled for row in compiled.values() for _, t in row), 'STATE_CLOSURE')
    cache = {}
    def distance(state, mode):
        if state is None:
            return None
        key = (tuple(state), mode)
        if key not in cache:
            cache[key] = ref.shortest(w, state, mode, compiled)
        actual = cache[key]
        check(actual == fam['distances'][mode].get(tuple(state)), 'FORWARD_REVERSE_DISTANCE')
        return actual
    for state in fam['states']:
        for mode in ('steps', 'environment', 'policy'):
            distance(state, mode)
    for frame, target in roots:
        observed = frame['observation']
        omitted = [i for i in range(len(w['slots'])) if str(i) not in observed]
        check(len(omitted) <= 1, 'OBSERVATION_SHAPE')
        base = [observed.get(str(i), 0) for i in range(len(w['slots']))]
        if omitted:
            j = omitted[0]
            possible = []
            for value in w['domains'][j]:
                candidate = list(base)
                candidate[j] = value
                if ref.state_valid(w, candidate):
                    possible.append(tuple(candidate))
        else:
            possible = [tuple(base)]
        check(bool(possible), 'NONEMPTY_COMPLETIONS')
        for i, ground in enumerate(target['grounded_observation']):
            check(ground == {'slot': i, 'name': w['slots'][i],
                            'status': 'OBSERVED' if str(i) in observed else 'UNKNOWN',
                            'value': observed.get(str(i))}, 'GROUNDED_OBSERVATION')
        expected_goal = []
        for c in w['goal']:
            flags = [ref.evaluate(s, [c]) for s in possible]
            expected_goal.append('UNKNOWN' if len(set(flags)) == 2 else 'SATISFIED' if flags[0] else 'VIOLATED')
        check(target['goal_clauses'] == expected_goal, 'OBSERVABLE_GOAL_CLAUSES')
        by_id = {a['id']: a for a in w['actions']}
        optimal_sets = []
        for state in possible:
            scored = []
            if not ref.evaluate(state, w['goal']):
                for identity in frame['offered_actions']:
                    a = by_id[identity]
                    successor = ref.execute(w, state, a)
                    if successor is not None and ref.evaluate(state, a['permission']):
                        cost = distance(successor, 'policy')
                        if cost is not None:
                            scored.append((cost+a['environment_cost']+a['policy_cost'], identity))
            optimum = min((c for c, _ in scored), default=None)
            optimal_sets.append({identity for c, identity in scored if c == optimum})
            reverse_scores = []
            if not ref.evaluate(state, w['goal']):
                for identity in reversed(frame['offered_actions']):
                    a = by_id[identity]
                    nxt = ref.execute(w, state, a)
                    if nxt is not None and ref.evaluate(state, a['permission']):
                        cost = distance(nxt, 'policy')
                        if cost is not None:
                            reverse_scores.append((cost+a['environment_cost']+a['policy_cost'], identity))
            reverse_min = min((c for c, _ in reverse_scores), default=None)
            check({k for c, k in reverse_scores if c == reverse_min} == optimal_sets[-1], 'PERMUTATION_EQUIVARIANCE')
        intersection = set.intersection(*optimal_sets)
        expected_mode = 'ACT' if intersection else 'ASK' if any(s != optimal_sets[0] for s in optimal_sets[1:]) else 'ABSTAIN'
        check(target['decision']['mode'] == expected_mode, 'OBSERVABLE_DECISION')
        check(set(target['decision']['optimal_actions']) == intersection, 'ALL_OPTIMAL_ACTIONS')
        chosen = target['decision']['selected_action']
        check(chosen == next(iter(intersection)) if len(intersection) == 1 else chosen is None, 'SINGLETON_ONLY')
        check(target['decision']['requested_slot'] == (omitted[0] if expected_mode == 'ASK' else None), 'CAUSAL_ASK_SLOT')
        for row in target['grounding']:
            a = by_id[row['candidate_id']]
            check(row['legality'] == status([ref.execute(w, s, a) is not None for s in possible]), 'LEGality_COMPLETIONS')
            check(row['permission'] == status([ref.evaluate(s, a['permission']) for s in possible]), 'PERMISSION_COMPLETIONS')
            check(row['binding_valid'] == ref.binding(w, a), 'TYPED_BINDING')
            for name, predicates in [('clauses', a['preconditions']), ('permission_clauses', a['permission'])]:
                expected = []
                for c in predicates:
                    flags = [ref.evaluate(s, [c]) for s in possible]
                    expected.append('UNKNOWN' if len(set(flags)) == 2 else 'SATISFIED' if flags[0] else 'VIOLATED')
                check(row[name] == expected, 'DENSE_CLAUSE_TARGET')
        canonical = target['_construction_state']
        check(ref.state_valid(w, canonical), 'VALID_LATENT_STATE')
        canonical_index = possible.index(tuple(canonical))
        check(set(target['canonical_optimal_actions']) == optimal_sets[canonical_index], 'CANONICAL_ALL_OPTIMAL_ACTIONS')
        for row in target['canonical_consequences']:
            a = by_id[row['candidate_id']]
            nxt = ref.execute(w, canonical, a)
            check(row['next_state'] == (list(nxt) if nxt is not None else None), 'SUCCESSOR')
            check(row['legal'] == (nxt is not None), 'LEGAL')
            check(row['permitted'] == ref.evaluate(canonical, a['permission']), 'PERMISSION')
            actual = [[i, value] for i, value in enumerate(nxt or ()) if value != canonical[i]]
            check(row['actual_effects'] == actual, 'ACTUAL_EFFECTS')
            check(row['operator_assignments'] == (a['effects'] if nxt is not None else []), 'OPERATOR_EFFECTS')
            timed_slots = {i for e in w.get('scheduled', []) for i, _ in e['effects']}
            check(row['scheduled_effects'] == [e for e in actual if e[0] in timed_slots], 'TIMED_EFFECTS')
            tick_slots = {w['clock']['slot']} if 'clock' in w else set()
            check(row['clock_effects'] == [e for e in actual if e[0] in tick_slots], 'CLOCK_EFFECTS')
            d, nd = distance(canonical, 'steps'), distance(nxt, 'steps')
            check((row['distance'], row['next_distance']) == (d, nd), 'DISTANCE')
            check(row['distance_status'] == ('UNREACHABLE' if d is None else 'REACHABLE'), 'UNREACHABLE_NOT_ZERO')
            check(row['next_distance_status'] == ('INAPPLICABLE' if nxt is None else 'UNREACHABLE' if nd is None else 'REACHABLE'), 'NEXT_REACHABILITY')
            check(row['distance_delta'] == (d-nd if d is not None and nd is not None else None), 'DISTANCE_DELTA')
            progress = None if nxt is None else sum(ref.evaluate(nxt, [c]) for c in w['goal'])-sum(ref.evaluate(canonical, [c]) for c in w['goal'])
            check(row['goal_delta'] == progress, 'GOAL_DELTA')
            check(row['environment_cost_to_goal'] == distance(nxt, 'environment'), 'ENVIRONMENT_COST')
            check(row['policy_cost_to_goal'] == distance(nxt, 'policy'), 'POLICY_COST')
            check(row['environment_step_cost'] == a['environment_cost'] and row['policy_step_cost'] == a['policy_cost'], 'STEP_COST')
        check(target['supervision_masks']['canonical_consequences'] == (not omitted), 'MASK_HIDDEN_CONSEQUENCES')
        check(target['supervision_masks']['canonical_optimal_actions'] == (not omitted), 'MASK_HIDDEN_CHOICE')
    # Same observation, different latent truth; all observable targets must agree.
    check(roots[1][0] == roots[3][0], 'HIDDEN_PAIR_FRAME_IDENTICAL')
    for field in ('grounded_observation', 'goal_clauses', 'grounding', 'decision', 'supervision_masks'):
        check(roots[1][1][field] == roots[3][1][field], 'HIDDEN_PAIR_OBSERVABLE_TARGET_IDENTICAL')
    return {'states': len(compiled), 'transitions': sum(map(len, compiled.values())),
            'forward_distance_queries': len(cache), 'roots': len(roots)}
