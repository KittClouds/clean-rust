"""Seven finite executable archetypes. Public benchmark rows are never imported."""
from common import rng, digest


def action(name, clauses=(), effects=(), permission=(), cost=1, binding=None):
    return {'id': name, 'type': name.split(':')[0],
            'preconditions': [list(c) for c in clauses],
            'permission': [list(c) for c in permission],
            'effects': [list(e) for e in effects], 'environment_cost': cost,
            'policy_cost': 1, 'binding': binding}


def clause(slot, value, op='eq'):
    return slot, op, value


def world(lane, names, domains, state, goal, actions, **extra):
    return {'lane': lane, 'slots': names, 'domains': domains, 'initial': state,
            'goal': [list(c) for c in goal], 'actions': actions, **extra}


def planning(r, transfer):
    # Transport with conjunctive prerequisites and separate access permission.
    names = ['location', 'key', 'door_open', 'parcel_held', 'delivered', 'permit']
    n = 4 if transfer else 3
    acts = [action('TAKE_KEY', [clause(0, 0)], [(1, 1)]),
            action('OPEN', [clause(1, 1)], [(2, 1)]),
            action('TAKE_PARCEL', [clause(0, 0)], [(3, 1)]),
            action('REQUEST_PERMIT', effects=[(5, 1)])]
    for a in range(n):
        for b in range(n):
            if abs(a-b) == 1:
                acts.append(action(f'MOVE:{a}:{b}', [clause(0, a), clause(2, 1)],
                                   [(0, b)], [clause(5, 1)], r.randint(1, 4)))
    acts.append(action('DELIVER', [clause(0, n-1), clause(3, 1)], [(4, 1), (3, 0)]))
    return world('planning', names, [list(range(n))]+[[0, 1]]*5,
                 [0, 0, 0, 0, 0, r.randrange(2)], [clause(4, 1)], acts)


def sokoban(r, transfer):
    side = 5 if transfer else 4
    cells = list(range(side*side))
    walls = sorted(r.sample(cells, 2 if transfer else 1))
    cells = [c for c in cells if c not in walls]
    box = r.choice([c for c in cells if 0 < c//side < side-1 and 0 < c % side < side-1])
    player = r.choice([c for c in cells if c != box])
    goal = r.choice(cells)
    acts = []
    for src in cells:
        for direction, dx, dy in [('N', 0, -1), ('S', 0, 1), ('E', 1, 0), ('W', -1, 0)]:
            x, y = src % side + dx, src//side + dy
            if not (0 <= x < side and 0 <= y < side):
                continue
            dst = y*side+x
            if dst not in cells:
                continue
            acts.append(action(f'MOVE:{direction}:{src}',
                               [clause(0, src), clause(1, dst, 'ne')], [(0, dst)]))
            x, y = x+dx, y+dy
            beyond = y*side+x
            if 0 <= x < side and 0 <= y < side and beyond in cells:
                acts.append(action(f'PUSH:{direction}:{src}',
                                   [clause(0, src), clause(1, dst)], [(0, dst), (1, beyond)]))
    return world('sokoban', ['player', 'crate'], [cells, cells], [player, box],
                 [clause(1, goal)], acts, validity='distinct', geometry={'side': side, 'walls': walls})


def sudoku(r, transfer):
    # Explicitly mini 4x4 Sudoku, never presented as the upstream 9x9 benchmark.
    digits = r.sample([1, 2, 3, 4], 4)
    row_order = r.sample([0, 1], 2)+r.sample([2, 3], 2)
    if r.randrange(2):
        row_order = row_order[2:]+row_order[:2]
    col_order = r.sample([0, 1], 2)+r.sample([2, 3], 2)
    if r.randrange(2):
        col_order = col_order[2:]+col_order[:2]
    state = [digits[(row*2+row//2+col) % 4] for row in row_order for col in col_order]
    holes = sorted(r.sample(range(16), 4 if transfer else 3))
    domains = [[v] for v in state]
    acts = []
    for i in holes:
        state[i] = 0
        domains[i] = [0, 1, 2, 3, 4]
        row, col = divmod(i, 4)
        peers = sorted({j for j in range(16) if j != i and
                        (j//4 == row or j % 4 == col or
                         (j//8 == row//2 and (j % 4)//2 == col//2))})
        for value in range(1, 5):
            acts.append(action(f'FILL:{i}:{value}', [clause(i, 0)]+
                               [clause(p, value, 'ne') for p in peers], [(i, value)]))
    return world('sudoku', [f'cell_{i}' for i in range(16)], domains, state,
                 [clause(i, 0, 'ne') for i in holes], acts, validity='sudoku4')


def household(r, transfer):
    names = ['location', 'held', 'clean', 'warm', 'served', 'tick', 'heater_on']
    n = 4 if transfer else 3
    acts = [action('TAKE', [clause(0, 0)], [(1, 1)]),
            action('WASH', [clause(0, 1), clause(1, 1)], [(2, 1)]),
            action('START_HEATER', [clause(1, 1)], [(6, 1)]),
            action('SERVE', [clause(0, n-1), clause(1, 1), clause(2, 1), clause(3, 1)], [(4, 1)])]
    for a in range(n):
        for b in range(n):
            if abs(a-b) == 1:
                acts.append(action(f'MOVE:{a}:{b}', [clause(0, a)], [(0, b)], cost=r.randint(1, 3)))
    return world('household', names, [list(range(n))]+[[0, 1]]*4+[list(range(3)), [0, 1]],
                 [0, 0, 0, 0, 0, 0, 0], [clause(4, 1)], acts,
                 clock={'slot': 5, 'maximum': 2},
                 scheduled=[{'at': 2, 'when': [list(clause(6, 1))], 'effects': [[3, 1]]}])


def policy_tools(r, transfer):
    names = ['authenticated', 'eligible', 'consent', 'refunded', 'verified']
    acts = [action('LOGIN', effects=[(0, 1)]), action('VERIFY', [clause(0, 1)], [(4, 1)]),
            action('REQUEST_CONSENT', [clause(0, 1)], [(2, 1)]),
            action('REFUND:standard', [clause(0, 1), clause(1, 1), clause(3, 0)], [(3, 1)],
                   [clause(2, 1)]+([clause(4, 1)] if transfer else []), cost=r.randint(1, 4)),
            action('REFUND:reviewed', [clause(0, 1), clause(1, 1), clause(3, 0), clause(4, 1)], [(3, 1)],
                   [clause(2, 1)], cost=r.randint(1, 4)),
            action('REFUND:express', [clause(0, 1), clause(1, 1), clause(3, 0)], [(3, 1)],
                   [clause(2, 1), clause(4, 1)], cost=r.randint(1, 4)),
            action('LOGOUT', effects=[(0, 0)])]
    return world('policy_tools', names, [[0, 1]]*5, [0, r.randrange(2), 0, 0, 0],
                 [clause(3, 1)], acts)


def graph(r, transfer):
    n = 10 if transfer else r.choice([5, 6, 7])
    edges = {(i, (i+1) % n) for i in range(n)}
    edges.update((r.randrange(n), r.randrange(n)) for _ in range(n))
    edges = {(a, b) for a, b in edges if a != b}
    acts = [action(f'EDGE:{a}:{b}', [clause(0, a)], [(0, b)], cost=r.randint(1, 7))
            for a, b in sorted(edges) if a != b]
    return world('graph', ['node'], [list(range(n))], [r.randrange(n)],
                 [clause(0, r.randrange(n))], acts, graph_edges=[list(e) for e in sorted(edges)])


def api_binding(r, transfer):
    kinds = ['basic', 'premium', 'trial'] if transfer else ['basic', 'premium']
    schema = {'method': 'create_record', 'required': {'kind': {'enum': kinds},
               'enabled': {'type': 'bool'}}, 'additional_properties': False}
    bindings = [{'method': 'create_record', 'arguments': {'kind': k, 'enabled': True}} for k in kinds]
    bindings += [{'method': 'create_record', 'arguments': {'kind': kinds[0], 'enabled': 'true'}},
                 {'method': 'create_record', 'arguments': {'kind': 'unknown', 'enabled': True}},
                 {'method': 'delete_record', 'arguments': {'kind': kinds[0], 'enabled': True}},
                 {'method': 'create_record', 'arguments': {'kind': kinds[0], 'enabled': True, 'extra': 1}}]
    acts = [action('AUTH', effects=[(0, 1)]), action('CONSENT', effects=[(2, 1)]),
            action('COMMIT', [clause(1, 1)], [(3, 1)])]
    acts += [action(f'CALL:{i}', [clause(0, 1)], [(1, 1)], [clause(2, 1)],
                    cost=1, binding=b) for i, b in enumerate(bindings)]
    return world('api_binding', ['authenticated', 'created', 'consent', 'committed'],
                 [[0, 1]]*4, [0, 0, 0, 0], [clause(3, 1)], acts, api_schema=schema)


FACTORIES = {f.__name__: f for f in (planning, sokoban, sudoku, household, policy_tools, graph, api_binding)}


def generate(lane, split, index):
    r = rng('world', lane, split, index)
    w = FACTORIES[lane](r, split == 'TRANSFER')
    w['actions'].append(action('WAIT'))
    # Prospectively varied operational costs supply genuine policy pressure.
    # Physical one-step distances remain separate from these weighted costs.
    # Equivalent implementations sometimes retain equal costs (set-valued truth).
    type_cost = {}
    for a in w['actions']:
        if a['type'] not in type_cost:
            type_cost[a['type']] = (r.randint(1, 5), r.randint(1, 5))
        if r.randrange(3) == 0:
            a['environment_cost'], a['policy_cost'] = type_cost[a['type']]
        else:
            a['environment_cost'], a['policy_cost'] = r.randint(1, 5), r.randint(1, 5)
    # Freeze producer order independently of labels; preserve semantic identity.
    r.shuffle(w['actions'])
    return w
