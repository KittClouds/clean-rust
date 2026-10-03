"""Construction oracle: exact finite-state mechanics and reverse distances."""
from collections import deque
import heapq


def test(state, c):
    slot, op, value = c
    return state[slot] == value if op == 'eq' else state[slot] != value


def binding_valid(w, a):
    b = a['binding']
    if b is None:
        return True
    schema = w['api_schema']
    args = b['arguments']
    if b['method'] != schema['method'] or set(args) != set(schema['required']):
        return False
    for key, rule in schema['required'].items():
        if 'enum' in rule and args[key] not in rule['enum']:
            return False
        if rule.get('type') == 'bool' and type(args[key]) is not bool:
            return False
    return True


def valid(w, state):
    if any(v not in d for v, d in zip(state, w['domains'])):
        return False
    if w.get('validity') == 'distinct':
        return state[0] != state[1]
    if w.get('validity') == 'sudoku4':
        groups = [[4*r+c for c in range(4)] for r in range(4)]
        groups += [[4*r+c for r in range(4)] for c in range(4)]
        groups += [[4*r+c for r in range(br, br+2) for c in range(bc, bc+2)]
                   for br in (0, 2) for bc in (0, 2)]
        return all(len([state[i] for i in g if state[i]]) ==
                   len(set(state[i] for i in g if state[i])) for g in groups)
    return True


def legal(w, state, a):
    return binding_valid(w, a) and all(test(state, c) for c in a['preconditions'])


def permitted(state, a):
    return all(test(state, c) for c in a['permission'])


def step(w, state, a):
    if not legal(w, state, a):
        return None
    result = list(state)
    for slot, value in a['effects']:
        result[slot] = value
    clock = w.get('clock')
    if clock:
        result[clock['slot']] = min(result[clock['slot']]+1, clock['maximum'])
        for e in w.get('scheduled', []):
            if result[clock['slot']] >= e['at'] and all(test(result, c) for c in e['when']):
                for slot, value in e['effects']:
                    result[slot] = value
    result = tuple(result)
    return result if valid(w, result) else None


def goal(w, state):
    return all(test(state, c) for c in w['goal'])


def catalogue(w, starts):
    states = set(tuple(s) for s in starts)
    queue = deque(states)
    edges = {}
    by_first = {v: [i for i, a in enumerate(w['actions'])
                    if not a['preconditions'] or a['preconditions'][0][:2] != [0, 'eq']
                    or a['preconditions'][0][2] == v] for v in w['domains'][0]}
    while queue:
        s = queue.popleft()
        row = []
        for i in by_first[s[0]]:
            a = w['actions'][i]
            t = step(w, s, a)
            if t is not None:
                row.append((i, t))
                if t not in states:
                    states.add(t)
                    queue.append(t)
                    if len(states) > 4096:
                        raise ValueError('STATE_CAP_EXCEEDED')
        edges[s] = row
    return sorted(states), edges


def distances(w, states, edges, mode):
    reverse = {s: [] for s in states}
    for s, row in edges.items():
        for i, t in row:
            a = w['actions'][i]
            if mode == 'policy' and not permitted(s, a):
                continue
            weight = 1 if mode == 'steps' else a['environment_cost']
            if mode == 'policy':
                weight += a['policy_cost']
            reverse[t].append((s, weight))
    d = {s: 0 for s in states if goal(w, s)}
    heap = [(0, s) for s in d]
    heapq.heapify(heap)
    while heap:
        cost, t = heapq.heappop(heap)
        if d[t] != cost:
            continue
        for s, weight in reverse[t]:
            c = cost+weight
            if c < d.get(s, float('inf')):
                d[s] = c
                heapq.heappush(heap, (c, s))
    return d


def completions(w, state, hidden):
    out = []
    for value in w['domains'][hidden]:
        s = list(state)
        s[hidden] = value
        if valid(w, s):
            out.append(tuple(s))
    return out
