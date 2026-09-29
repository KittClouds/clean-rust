"""The C0 gate: same inputs and same contracts give a byte-identical decision and receipt.

Checked in-process, across interpreter processes with different hash seeds, working directories and
flags, across file formatting and key order, and against the committed golden receipts.
"""
from __future__ import annotations

import ast
import hashlib
import json
import random
import sys
import unittest

from . import support
from .support import CASES, FIX, ROOT, Records, case_inputs, expected_bytes, python, shuffled
from s15 import canon, model, runtime


class GoldenTests(support.Base):
    def test_every_case_reproduces_its_golden_receipt_byte_for_byte(self):
        world = support.fixture_world()
        self.assertEqual(len(CASES), 14)
        for name in CASES:
            with self.subTest(name):
                observation, vector = case_inputs(name)
                _, data = runtime.run(world, observation, vector)
                self.assertEqual(data, expected_bytes(name))

    def test_golden_manifest_matches_the_stored_receipts(self):
        lines = (FIX / "GOLDEN.sha256").read_text(encoding="ascii").splitlines()
        self.assertEqual(lines, [f"{hashlib.sha256(expected_bytes(n)).hexdigest()}  {n}/expected-receipt.json" for n in CASES])

    def test_receipts_are_canonical_bytes(self):
        for name in CASES:
            data = expected_bytes(name)
            self.assertEqual(canon.canonical_bytes(canon.loads_strict(data)), data, name)

    def test_repeated_runs_are_identical(self):
        world = support.fixture_world()
        observation, vector = case_inputs("c12-medium-risk-edit")
        first = runtime.run(world, observation, vector)[1]
        for _ in range(25):
            self.assertEqual(runtime.run(world, observation, vector)[1], first)

    def test_run_does_not_change_its_inputs(self):
        world = support.fixture_world()
        for name in CASES:
            observation, vector = case_inputs(name)
            before = (canon.canonical_bytes(observation), canon.canonical_bytes(vector))
            runtime.run(world, observation, vector)
            self.assertEqual((canon.canonical_bytes(observation), canon.canonical_bytes(vector)), before, name)

    def test_replay_confirms_and_detects(self):
        world = support.fixture_world()
        observation, vector = case_inputs("c04-disagreement")
        self.assertEqual(runtime.replay(world, observation, vector, expected_bytes("c04-disagreement")), (True, "byte-identical"))
        ok, message = runtime.replay(world, observation, vector, expected_bytes("c05-high-risk"))
        self.assertFalse(ok)
        self.assertIn("differs", message)

    def test_a_different_input_gives_a_different_receipt(self):
        world = support.fixture_world()
        seen = {runtime.run(world, *case_inputs(name))[1] for name in CASES}
        self.assertEqual(len(seen), len(CASES))


class FormattingIndependenceTests(support.Base):
    def test_key_order_whitespace_and_line_endings_do_not_matter(self):
        for seed, newline in ((1, "\r\n"), (2, "\n"), (3, "\r\n")):
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                directory = self.tmp()

                def encode(record):
                    return (json.dumps(shuffled(record, rng), indent=rng.choice([None, 1, 2, 4]), separators=None if seed != 2 else (", ", ": ")).replace("\n", newline) + newline).encode("ascii")

                policy, contracts, bundles = Records().write(directory, encode=encode)
                world = model.load_world(policy, contracts, bundles)
                for name in CASES:
                    observation, vector = case_inputs(name)
                    text = lambda r: (json.dumps(shuffled(r, rng), indent=2) + newline).encode("ascii")  # noqa: E731
                    observation = canon.loads_strict(text(observation))
                    vector = canon.loads_strict(text(vector))
                    self.assertEqual(runtime.run(world, observation, vector)[1], expected_bytes(name), name)


class ProcessIndependenceTests(support.Base):
    def test_golden_from_another_directory_under_different_hash_seeds_and_flags(self):
        elsewhere = self.tmp()
        for env, flags in (({"PYTHONHASHSEED": "0"}, ()), ({"PYTHONHASHSEED": "1"}, ()), ({"PYTHONHASHSEED": "4242"}, ("-O",)), ({"PYTHONHASHSEED": "random"}, ("-X", "utf8=0"))):
            with self.subTest(env=env, flags=flags):
                done = python("golden", cwd=elsewhere, env=env, flags=flags)
                self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())
                self.assertEqual(done.stdout.decode().count("identical"), len(CASES))

    def test_run_command_writes_the_golden_bytes(self):
        elsewhere = self.tmp()
        for seed in ("0", "7", "random"):
            for name in ("c02-confident-observer", "c11-incomplete-evidence", "c12-medium-risk-edit"):
                with self.subTest(seed=seed, case=name):
                    out = elsewhere / f"{name}-{seed}.json"
                    done = python("run", "--policy", FIX / "policy.json", "--contracts", FIX / "contracts", "--bundles", FIX / "bundles",
                                  "--observation", FIX / "cases" / name / "observation.json", "--vector", FIX / "cases" / name / "vector.json", "--out", out,
                                  cwd=elsewhere, env={"PYTHONHASHSEED": seed})
                    self.assertEqual(done.returncode, 0, done.stderr.decode())
                    self.assertEqual(out.read_bytes(), expected_bytes(name))

    def test_replay_command(self):
        common = ["--policy", FIX / "policy.json", "--contracts", FIX / "contracts", "--bundles", FIX / "bundles"]
        case = FIX / "cases" / "c06-ask"
        args = ["replay", *common, "--observation", case / "observation.json", "--vector", case / "vector.json"]
        self.assertEqual(python(*args, "--receipt", case / "expected-receipt.json").returncode, 0)
        other = FIX / "cases" / "c07-abstain" / "expected-receipt.json"
        self.assertEqual(python(*args, "--receipt", other).returncode, 1)

    def test_exit_codes(self):
        common = ["--policy", FIX / "policy.json", "--contracts", FIX / "contracts", "--bundles", FIX / "bundles"]
        directory = self.tmp()
        bad = directory / "observation.json"
        bad.write_bytes(b'{"x": 1.5}')
        case = FIX / "cases" / "c06-ask"
        self.assertEqual(python("run", *common, "--observation", bad, "--vector", case / "vector.json").returncode, 2)
        self.assertEqual(python("run", *common, "--observation", directory / "missing.json", "--vector", case / "vector.json").returncode, 2)
        self.assertEqual(python("check", *common).returncode, 0)
        self.assertEqual(python("check", "--policy", directory / "nope.json", "--contracts", FIX / "contracts", "--bundles", FIX / "bundles").returncode, 2)

    def test_golden_reports_a_difference(self):
        # Copy-free check: a stored receipt that no longer matches must fail the comparison, not be silently refreshed.
        world = support.fixture_world()
        observation, vector = case_inputs("c02-confident-observer")
        _, data = runtime.run(world, observation, vector)
        self.assertNotEqual(data, expected_bytes("c03-set-agreement"))


class PurityTests(unittest.TestCase):
    """The runtime is a pure function of files: no clock, randomness, network, processes or third-party code."""

    FORBIDDEN = {"time", "datetime", "random", "secrets", "uuid", "socket", "ssl", "urllib", "http", "subprocess", "threading", "multiprocessing",
                 "asyncio", "ctypes", "platform", "locale", "tempfile", "shutil", "os", "signal", "select", "sched", "zoneinfo", "calendar"}

    def imports(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add((node.module or "").split(".")[0])
        return names

    def test_no_forbidden_or_third_party_imports(self):
        for path in sorted((ROOT / "s15").glob("*.py")):
            names = self.imports(path)
            with self.subTest(path.name):
                self.assertFalse(names & self.FORBIDDEN, names & self.FORBIDDEN)
                self.assertFalse({n for n in names if n and n not in sys.stdlib_module_names}, names)

    def test_no_float_arithmetic_or_environment_access_in_the_runtime_modules(self):
        for name in ("policy.py", "model.py", "runtime.py", "schema.py"):
            tree = ast.parse((ROOT / "s15" / name).read_text(encoding="utf-8"))
            with self.subTest(name):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant):
                        self.assertNotIsInstance(node.value, float)
                    if isinstance(node, ast.Name):
                        self.assertNotIn(node.id, {"float", "environ", "getenv"})
                    if isinstance(node, ast.Attribute):
                        self.assertNotIn(node.attr, {"environ", "getenv", "now", "time", "random"})
                    if name != "model.py" and isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):  # model.py joins paths with `/`
                        self.fail(f"true division at line {node.lineno}")

    def test_canon_has_no_float_literals(self):
        # The quantizer takes model floats but converts them to exact fractions before any arithmetic.
        tree = ast.parse((ROOT / "s15" / "canon.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                self.assertNotIsInstance(node.value, float)

    def test_receipt_carries_no_clock_or_host_information(self):
        text = "".join(expected_bytes(n).decode("ascii") for n in CASES).lower()
        for word in ("utc", "time", "date", "host", "user", "path", "pid", "\\\\", "c:/"):
            self.assertNotIn(f'"{word}', text)
        self.assertNotIn("code land", text)


if __name__ == "__main__":
    unittest.main()
