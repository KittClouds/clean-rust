"""Independent binary32 row oracle for engineering receipt audits.

This code uses only Python's standard library. It deliberately rounds after
each addition and preserves duplicate indices and the given row order.
"""
import math
import struct


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def from_bits(value):
    return struct.unpack('<f', struct.pack('<I', value))[0]


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def sequential(row, weights):
    # Rust std::iter::Sum<f32> uses negative zero as the identity.
    accumulator = -0.0
    for coordinate in row:
        accumulator = f32(accumulator + weights[coordinate])
    return accumulator


def readout(rows, weight_bits):
    weights = list(map(from_bits, weight_bits))
    return [bits(sequential(row, weights)) for row in rows]


def metrics(actual_bits, target_bits):
    assert len(actual_bits) == len(target_bits)
    residual = [from_bits(a) - from_bits(t)
                for a, t in zip(actual_bits, target_bits)]
    return {
        'mismatches': sum(a != t for a, t in zip(actual_bits, target_bits)),
        'squared_error': math.fsum(x*x for x in residual),
    }


def supports(rows, coordinates):
    result = [set() for _ in range(coordinates)]
    for row, ids in enumerate(rows):
        for coordinate in ids:
            result[coordinate].add(row)
    return result


def assert_disjoint(selected, coordinate_supports):
    occupied = set()
    for coordinate in selected:
        assert not occupied.intersection(coordinate_supports[coordinate])
        occupied.update(coordinate_supports[coordinate])
    return occupied


def self_test():
    assert bits(sequential([], [])) == 0x80000000
    assert bits(sequential([0], [0.0])) == 0
    assert sequential([0, 1, 2], [16777216.0, 1.0, -16777216.0]) == 0.0
    assert sequential([0, 2, 1], [16777216.0, 1.0, -16777216.0]) == 1.0
    assert sequential([0, 0], [0.5]) == 1.0
    assert metrics([0], [0x80000000]) == {'mismatches': 1, 'squared_error': 0.0}
    print('independent binary32 oracle self-test passed')


if __name__ == '__main__':
    self_test()
