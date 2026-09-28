from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

for _key in (
    "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_MAXIMUM_THREADS",
):
    os.environ[_key] = "1"

import numpy as np

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
for _path in (STUDY / "f4-invariant-01-impl-v2", STUDY / "f4-presentation-02-v2", BRANCH):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from cphi_model import deserialize_tensors
from presentation03_model import UNSHARED_TENSOR_NAMES, UNSHARED_TENSOR_SHAPES
from prepare_initializers import expand_shared_phi, read_d_bundle, serialize_unshared, sha_file


class InitializerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = BRANCH / "implementation-artifacts"
        cls.manifest = json.loads((cls.root / "INITIALIZER-MANIFEST.json").read_text(encoding="utf-8"))
        cls.cells = {
            (int(row["fold_index"]), int(row["replicate_index"]), row["arm"]): row
            for row in cls.manifest["cells"]
        }

    def _values(self, fold: int, replicate: int, arm: str) -> list[np.ndarray]:
        row = self.cells[(fold, replicate, arm)]
        path = self.root / row["relative_path"]
        raw = path.read_bytes()
        self.assertEqual(len(raw), row["file_bytes"])
        self.assertEqual(__import__("hashlib").sha256(raw).hexdigest(), row["file_sha256"])
        if arm == "D":
            return read_d_bundle(path)
        if arm in ("Cphi", "Cphi_shuffled"):
            return deserialize_tensors(raw)
        return self._decode_unshared(raw)

    @staticmethod
    def _decode_unshared(raw: bytes) -> list[np.ndarray]:
        import struct

        if not raw.startswith(b"F4PRES03UNSHARED\0"):
            raise AssertionError("unshared initializer magic mismatch")
        offset = len(b"F4PRES03UNSHARED\0")
        arrays = []
        for name, shape in zip(UNSHARED_TENSOR_NAMES, UNSHARED_TENSOR_SHAPES, strict=True):
            token = name.encode("ascii") + b"\0"
            if raw[offset:offset + len(token)] != token:
                raise AssertionError(f"unshared initializer tensor name mismatch: {name}")
            offset += len(token)
            ndim = struct.unpack_from("<I", raw, offset)[0]
            offset += 4
            dimensions = struct.unpack_from("<" + "I" * ndim, raw, offset)
            offset += ndim * 4
            if tuple(dimensions) != shape:
                raise AssertionError(f"unshared initializer tensor shape mismatch: {name}")
            count = int(np.prod(shape))
            arrays.append(np.frombuffer(raw, dtype="<f4", count=count, offset=offset).reshape(shape).copy())
            offset += count * 4
        if offset != len(raw):
            raise AssertionError("unshared initializer has trailing bytes")
        return arrays

    def test_initializer_manifest_covers_all_task_free_cells(self) -> None:
        self.assertEqual(self.manifest["initializer_cell_count"], 144)
        self.assertIs(self.manifest["task_ids_or_seeds_used"], False)
        self.assertEqual(len(self.cells), 12 * 3 * 4)
        self.assertEqual({row["parameter_count"] for row in self.manifest["cells"] if row["arm"] == "D"}, {19969})
        self.assertEqual({row["parameter_count"] for row in self.manifest["cells"] if row["arm"] == "Cphi"}, {19936})
        self.assertEqual({row["parameter_count"] for row in self.manifest["cells"] if row["arm"] == "Cphi_unshared"}, {20272})

    def test_cphi_shuffled_and_unshared_initializers_share_frozen_parent(self) -> None:
        for fold in range(12):
            for replicate in range(3):
                cphi = self._values(fold, replicate, "Cphi")
                shuffled = self._values(fold, replicate, "Cphi_shuffled")
                unshared = self._values(fold, replicate, "Cphi_unshared")
                self.assertEqual(serialize_unshared(unshared), (self.root / self.cells[(fold, replicate, "Cphi_unshared")]["relative_path"]).read_bytes())
                self.assertTrue(np.array_equal(cphi[0], shuffled[0]))
                self.assertTrue(np.array_equal(cphi[-1], shuffled[-1]))
                self.assertTrue(np.array_equal(unshared[0], np.broadcast_to(cphi[0], (4, 6, 16))))
                self.assertTrue(np.array_equal(unshared[1], np.broadcast_to(cphi[1], (4, 16))))

    def test_every_initializer_is_a_deterministic_copy_or_expansion(self) -> None:
        from prepare_initializers import REPO

        for row in self.manifest["cells"]:
            output_path = self.root / row["relative_path"]
            source_path = REPO / row["source_path"]
            source_raw = source_path.read_bytes()
            output_raw = output_path.read_bytes()
            self.assertEqual(sha_file(source_path), row["source_file_sha256"])
            if row["arm"] in ("D", "Cphi", "Cphi_shuffled"):
                self.assertEqual(output_raw, source_raw, row["fit_key"])
                self.assertEqual(output_raw, source_path.read_bytes(), row["fit_key"])
            else:
                source_values = deserialize_tensors(source_raw)
                regenerated_a = serialize_unshared(expand_shared_phi(source_values))
                regenerated_b = serialize_unshared(expand_shared_phi(source_values))
                self.assertEqual(regenerated_a, regenerated_b, row["fit_key"])
                self.assertEqual(output_raw, regenerated_a, row["fit_key"])


if __name__ == "__main__":
    unittest.main()
