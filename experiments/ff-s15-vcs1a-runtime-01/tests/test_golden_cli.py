import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests import helpers as T
from vcs import __main__ as cli, authority as A, canon

G = T.FIX / "golden"
sc = T.schema()
SCHEMA = str(T.FIX / "fixture_schema.json")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class Golden(unittest.TestCase):
    def test_every_golden_receipt_replays_byte_identically(self):
        auth = A.verify_authority(canon.loads_strict((G / "authority.json").read_bytes()), sc)
        names = sorted(p.name[: -len(".receipt.json")] for p in G.glob("*.receipt.json"))
        self.assertEqual(names, ["ask", "decline", "escalate_default", "execute", "noop", "unknown_missing"])
        kinds = set()
        for n in names:
            env = canon.loads_strict((G / f"{n}.envelope.json").read_bytes())
            ctx = canon.loads_strict((G / f"{n}.context.json").read_bytes())
            stored = canon.loads_strict((G / f"{n}.receipt.json").read_bytes())
            fresh = A.decide(auth, env, ctx)
            self.assertEqual(canon.canonical(fresh), canon.canonical(stored), n)
            self.assertTrue(A.replay(stored, auth, env, ctx))
            kinds.add(stored["decision"]["disposition"]["type"])
        self.assertEqual(kinds, {"EXECUTE", "NOOP", "ASK", "DECLINE_UNAVAILABLE", "ESCALATE"})

    def test_authority_source_compiles_to_the_stored_authority(self):
        src = canon.loads_strict((G / "authority_src.json").read_bytes())
        self.assertEqual(canon.canonical(A.load_authority(src, sc).spec), canon.canonical(canon.loads_strict((G / "authority.json").read_bytes())))


class Cli(unittest.TestCase):
    def test_decide_and_replay_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "r.json"
            base = ["--schema", SCHEMA, "--authority", str(G / "authority.json"), "--envelope", str(G / "ask.envelope.json"), "--context", str(G / "ask.context.json")]
            code, _, _ = run(["decide", *base, "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.read_text()), json.loads((G / "ask.receipt.json").read_text()))
            code, text, _ = run(["replay", *base, "--receipt", str(out)])
            self.assertEqual((code, text.strip()), (0, "replay: byte-identical"))
            code, text, _ = run(["replay", "--schema", SCHEMA, "--authority", str(G / "authority.json"), "--envelope", str(G / "execute.envelope.json"),
                                 "--context", str(G / "execute.context.json"), "--receipt", str(out)])
            self.assertEqual(code, 1)

    def test_schema_mismatch_is_an_error_not_a_disposition(self):
        with tempfile.TemporaryDirectory() as td:
            d = json.loads((T.FIX / "fixture_schema.json").read_text())
            d["schema_version"] = "7"
            p = Path(td) / "s.json"
            p.write_text(json.dumps(d))
            code, _, err = run(["decide", "--schema", str(p), "--authority", str(G / "authority.json"), "--envelope", str(G / "ask.envelope.json")])
            self.assertEqual(code, 1)
            self.assertIn("error", err)

    def test_frozen_schema_is_refused_without_a_preregistration(self):
        with tempfile.TemporaryDirectory() as td:
            d = json.loads((T.FIX / "fixture_schema.json").read_text())
            d["status"], d["owner"] = "FROZEN", "an external owner"
            for c in d["coordinates"]:
                c["derivation_audit"] = {"target_derived": False, "downstream_of_target": False, "shared_generator": False}
            p = Path(td) / "s.json"
            p.write_text(json.dumps(d))
            cases = Path(td) / "c.jsonl"
            cases.write_text("")
            auth = Path(td) / "a.json"
            code, _, _ = run(["compile", "--schema", str(p), "--authority", str(G / "authority_src.json"), "--out", str(auth)])
            self.assertEqual(code, 0)
            code, _, err = run(["evaluate", "--schema", str(p), "--authority", str(auth), "--scalar", str(G / "authority.json"), "--cases", f"TRAIN={cases}"])
            self.assertEqual(code, 2)
            self.assertIn("preregistration", err)

    def test_evaluate_on_fixture_marks_no_evidence(self):
        sweep_src = {"score": {"context": "score"}, "at_or_above": {"type": "EXECUTE", "action": "act_a"}, "below": {"type": "ASK", "requirement": "q"}}
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "scalar.json"
            sp.write_text(json.dumps(sweep_src))
            cp = Path(td) / "cases.jsonl"
            cp.write_text("\n".join(json.dumps(c) for c in T.band_cases(sc, 60, seed=2)) + "\n")
            out = Path(td) / "o.json"
            code, _, err = run(["evaluate", "--schema", SCHEMA, "--authority", str(G / "authority.json"), "--scalar", str(sp), "--cases", f"DEV={cp}", "--resamples", "20", "--out", str(out)])
            self.assertEqual(code, 0, err)
            rep = json.loads(out.read_text())
            self.assertEqual(rep["evidence"]["grade"], "NONE (fixture schema)")
            self.assertIn("DEV", rep["splits"])


class Hygiene(unittest.TestCase):
    def test_no_results_directory_and_fixtures_only_under_tests(self):
        root = Path(T.ROOT)
        self.assertFalse((root / "results").exists(), "VCS-1a produces no results; synthetic fixtures live under tests/fixtures")
        self.assertFalse(list(root.glob("vcs/**/*.json")))

    def test_standard_library_only(self):
        import re
        import sys
        allowed = set(sys.stdlib_module_names) | {"vcs", "tests"}
        for p in list((Path(T.ROOT) / "vcs").glob("*.py")) + list((Path(T.ROOT) / "tests").glob("*.py")):
            for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z_0-9]*)", p.read_text(encoding="utf-8"), re.M):
                self.assertIn(m.group(1), allowed, f"{p.name} imports {m.group(1)}")


if __name__ == "__main__":
    unittest.main()
