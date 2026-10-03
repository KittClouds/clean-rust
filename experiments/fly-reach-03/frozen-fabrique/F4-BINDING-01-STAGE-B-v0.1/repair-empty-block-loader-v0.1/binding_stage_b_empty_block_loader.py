"""Versioned empty-block correction for the pre-inference Stage B loader stop.

The frozen base loader incorrectly required every planned block to have at
least one U* row. This replacement keeps the original parser and validation,
but permits an expected task block to have zero sampled rows. It still rejects
any row whose block is outside the frozen domain.
"""
from __future__ import annotations

import mmap
import struct

import numpy as np


def load_predictors_allow_empty(data_module, path, expected_blocks=None):
    expected = tuple(data_module.BLOCK_IDS if expected_blocks is None else expected_blocks)
    count = data_module._header(path, data_module.INPUT_MAGIC, data_module.INPUT_WIDTH)
    if count <= 0:
        raise RuntimeError("Stage B predictor panel is empty")
    with path.open("rb") as stream:
        mapping = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            key_matrix = np.ndarray((count, 18), dtype="u1", buffer=mapping, offset=data_module.HEADER_WIDTH, strides=(data_module.INPUT_WIDTH, 1)).copy()
            base = np.ndarray((count, 66), dtype="<f4", buffer=mapping, offset=data_module.HEADER_WIDTH + 18, strides=(data_module.INPUT_WIDTH, 4)).copy()
            tuple_dtype = np.dtype([
                ("incidence", "u1"), ("role", "i1"), ("incidence_role", "i1"),
                ("delta", "<f4"), ("incidence_delta", "<f4"), ("role_delta", "<f4"),
            ], align=False)
            packed = np.ndarray((count, 4), dtype=tuple_dtype, buffer=mapping, offset=data_module.HEADER_WIDTH + 18 + 66 * 4, strides=(data_module.INPUT_WIDTH, 15)).copy()
        finally:
            mapping.close()
    keys = tuple(bytes(row) for row in key_matrix)
    if len(set(keys)) != count:
        raise RuntimeError("duplicate Stage B row keys")
    tuples = np.empty((count, 4, 6), dtype=np.float32)
    tuples[:, :, 0] = packed["incidence"].astype(np.float32)
    tuples[:, :, 1] = packed["role"].astype(np.float32)
    tuples[:, :, 2] = packed["incidence_role"].astype(np.float32)
    tuples[:, :, 3] = packed["delta"]
    tuples[:, :, 4] = packed["incidence_delta"]
    tuples[:, :, 5] = packed["role_delta"]
    substrates = key_matrix[:, 0].astype(np.uint8)
    sides = key_matrix[:, 1].astype(np.uint8)
    blocks = np.fromiter((struct.unpack_from("<Q", key, 2)[0] for key in keys), dtype=np.uint64, count=count)
    observed = set(map(int, blocks))
    if not observed.issubset(set(map(int, expected))):
        raise RuntimeError("Stage B predictor contains a block outside the frozen domain")
    if (substrates > 8).any() or (sides > 1).any():
        raise RuntimeError("Stage B predictor substrate/side domain mismatch")
    if not np.isfinite(base).all() or not np.isfinite(tuples).all():
        raise RuntimeError("nonfinite Stage B predictor feature")
    return data_module.PredictorPanel(keys, blocks, substrates, sides, base, tuples)
