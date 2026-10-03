"""Check generated operators against physical/type rules, beyond DSL replay."""


def qualify(w):
    assert len({a['id'] for a in w['actions']}) == len(w['actions']), 'DUPLICATE_ACTION_ID'
    for a in w['actions']:
        assert a['environment_cost'] > 0 and a['policy_cost'] > 0, 'NONPOSITIVE_COST'
        # A Sudoku peer can have a fixed domain {2} yet be compared to digit 3;
        # that signed predicate is well typed and constantly true, not malformed.
        value_universe = {value for domain in w['domains'] for value in domain}
        assert all(0 <= c[0] < len(w['slots']) and c[1] in ('eq', 'ne') and
                   c[2] in value_universe for c in a['preconditions']+a['permission']), 'CLAUSE_DOMAIN'
        assert all(value in w['domains'][i] for i, value in a['effects']), 'EFFECT_DOMAIN'
        assert len({i for i, _ in a['effects']}) == len(a['effects']), 'CONFLICTING_ASSIGNMENTS'
    if w['lane'] == 'sokoban':
        side = w['geometry']['side']
        walls = set(w['geometry']['walls'])
        expected = set()
        for src in w['domains'][0]:
            x, y = src % side, src//side
            for direction, dx, dy in [('N', 0, -1), ('S', 0, 1), ('E', 1, 0), ('W', -1, 0)]:
                nx, ny = x+dx, y+dy
                if not (0 <= nx < side and 0 <= ny < side) or ny*side+nx in walls:
                    continue
                dst = ny*side+nx
                expected.add(('MOVE:'+direction+':'+str(src), ((0, 'eq', src), (1, 'ne', dst)), ((0, dst),)))
                bx, by = nx+dx, ny+dy
                if 0 <= bx < side and 0 <= by < side and by*side+bx not in walls:
                    expected.add(('PUSH:'+direction+':'+str(src), ((0, 'eq', src), (1, 'eq', dst)), ((0, dst), (1, by*side+bx))))
        actual = {(a['id'], tuple(map(tuple, a['preconditions'])), tuple(map(tuple, a['effects'])))
                  for a in w['actions'] if a['type'] != 'WAIT'}
        assert actual == expected, 'SOKOBAN_PHYSICAL_OPERATOR_SET'
    if w['lane'] == 'sudoku':
        for a in w['actions']:
            if a['type'] == 'WAIT':
                continue
            _, position, digit = a['id'].split(':')
            position, digit = int(position), int(digit)
            row, col = divmod(position, 4)
            expected = {(position, 'eq', 0)}
            for other in range(16):
                r, c = divmod(other, 4)
                if other != position and (r == row or c == col or (r//2, c//2) == (row//2, col//2)):
                    expected.add((other, 'ne', digit))
            assert set(map(tuple, a['preconditions'])) == expected, 'SUDOKU_PEER_GUARDS'
            assert a['effects'] == [[position, digit]], 'SUDOKU_FILL_EFFECT'
    if w['lane'] == 'graph':
        assert {tuple(e) for e in w['graph_edges']} == {
            (a['preconditions'][0][2], a['effects'][0][1]) for a in w['actions'] if a['type'] != 'WAIT'}, 'GRAPH_EDGE_BINDING'
    if w['lane'] == 'api_binding':
        assert w['api_schema']['additional_properties'] is False, 'API_UNKNOWN_ARGUMENT_POLICY'
