"""Machine-readable test cases, subtests and immutable source/runtime binding."""
import json
import sys
import time
import unittest
from pathlib import Path

from ledgerd.identity import canonical
from ledgerd.release import HERE, runtime_identity, source_manifest


class ReceiptResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases, self.subcases = [], []
    def startTest(self, test):
        self.started = time.perf_counter()
        super().startTest(test)
    def stopTest(self, test):
        failed = any(t is test for t, _ in self.failures + self.errors)
        failed |= any(t.id().startswith(test.id()) and status != "PASS" for t, status in self.subcases)
        self.cases.append({"test": test.id(), "status": "FAIL" if failed else "PASS",
                           "preserved_fixture": str(getattr(test, "fixture_root", "")),
                           "elapsed_ms": (time.perf_counter() - self.started) * 1000})
        super().stopTest(test)
    def addSubTest(self, test, subtest, err):
        self.subcases.append((subtest, "PASS" if err is None else "FAIL"))
        super().addSubTest(test, subtest, err)


def run(output):
    _, source = source_manifest()
    _, runtime = runtime_identity()
    suite = unittest.defaultTestLoader.discover(str(HERE / "tests"))
    result = unittest.TextTestRunner(verbosity=2, resultclass=ReceiptResult).run(suite)
    _, after = source_manifest()
    report = {"schema": "KAMMI_QUALIFIED_TESTS_V1", "status": "PASS" if result.wasSuccessful() and source == after else "FAIL",
              "source_root": source, "runtime_identity": runtime, "source_unchanged": source == after,
              "test_count": result.testsRun, "cases": result.cases,
              "subtests": [{"test": t.id(), "status": status} for t, status in result.subcases],
              "failures": [{"test": t.id(), "trace": trace} for t, trace in result.failures + result.errors]}
    output.write_bytes(canonical(report))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    run(Path(sys.argv[1]))
