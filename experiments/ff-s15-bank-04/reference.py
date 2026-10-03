"""Independent mechanics + forward shortest paths; imports no construction engine."""
import heapq


def evaluate(values, predicates):
    for index, relation, expected in predicates:
        actual = values[index]
        if relation not in ('eq', 'ne'):
            raise ValueError('UNKNOWN_RELATION')
        if (actual == expected) != (relation == 'eq'):
            return False
    return True


def state_valid(w, values):
    if len(values) != len(w['domains']) or any(value not in domain for value, domain in zip(values, w['domains'])):
        return False
    kind = w.get('validity')
    if kind == 'distinct':
        return len(set(values)) == len(values)
    if kind == 'sudoku4':
        buckets = {}
        for pos, digit in enumerate(values):
            if digit == 0:
                continue
            row, col = divmod(pos, 4)
            for key in (('r', row), ('c', col), ('b', row//2, col//2)):
                seen = buckets.setdefault(key, set())
                if digit in seen:
                    return False
                seen.add(digit)
    return True


def binding(w, operation):
    request = operation.get('binding')
    if request is None:
        return True
    definition = w['api_schema']
    if request.get('method') != definition['method']:
        return False
    args = request.get('arguments', {})
    if len(args) != len(definition['required']):
        return False
    for key, specification in definition['required'].items():
        if key not in args:
            return False
        value = args[key]
        if 'enum' in specification and value not in specification['enum']:
            return False
        if specification.get('type') == 'bool' and value is not True and value is not False:
            return False
    return True


def execute(w, values, operation):
    if not evaluate(values, operation['preconditions']) or not binding(w, operation):
        return None
    assignments = dict(operation['effects'])
    result = [assignments.get(i, value) for i, value in enumerate(values)]
    if 'clock' in w:
        clock = w['clock']
        tick = min(clock['maximum'], result[clock['slot']]+1)
        result[clock['slot']] = tick
        for timed in w['scheduled']:
            if tick >= timed['at'] and evaluate(result, timed['when']):
                updates = dict(timed['effects'])
                result = [updates.get(i, value) for i, value in enumerate(result)]
    return tuple(result) if state_valid(w, result) else None


def graph(w, states):
    result = {}
    unconditional = []
    keyed = {}
    for i, operation in enumerate(w['actions']):
        first = operation['preconditions'][0] if operation['preconditions'] else None
        if first is not None and first[0] == 0 and first[1] == 'eq':
            keyed.setdefault(first[2], []).append(i)
        else:
            unconditional.append(i)
    for state in states:
        out = []
        for i in sorted(unconditional+keyed.get(state[0], [])):
            operation = w['actions'][i]
            successor = execute(w, state, operation)
            if successor is not None:
                out.append((i, successor))
        result[tuple(state)] = out
    return result


def shortest(w, start, mode, compiled=None):
    frontier = [(0, tuple(start))]
    visited = {}
    while frontier:
        cost, values = heapq.heappop(frontier)
        if values in visited:
            continue
        visited[values] = cost
        if evaluate(values, w['goal']):
            return cost
        if len(visited) > 4096:
            raise ValueError('REFERENCE_STATE_CAP')
        available = compiled[values] if compiled is not None else [(i, execute(w, values, a)) for i, a in enumerate(w['actions'])]
        for i, result in available:
            operation = w['actions'][i]
            if mode == 'policy' and not evaluate(values, operation['permission']):
                continue
            if result is not None and result not in visited:
                delta = 1 if mode == 'steps' else operation['environment_cost']
                if mode == 'policy':
                    delta += operation['policy_cost']
                heapq.heappush(frontier, (cost+delta, result))
    return None
