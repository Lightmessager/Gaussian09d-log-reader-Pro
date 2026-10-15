"""Record independent-oracle checks and bounded-memory streaming measurements."""
import hashlib
import json
import platform
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gaussianreadpro.core.models import EnergyKind, ImportState
from gaussianreadpro.core.parser import PARSER_VERSION, parse_log, select_job
from gaussianreadpro.core.units import CONSTANTS_VERSION, HARTREE_TO_KCAL, HARTREE_TO_KJ


def main():
    out = ROOT / "artifacts" / "s1"
    out.mkdir(parents=True, exist_ok=True)
    synthetic = json.loads((ROOT / "tests/fixtures/expected.json").read_text(encoding="utf-8"))
    real = json.loads((ROOT / "tests/fixtures/reference/expected.json").read_text(encoding="utf-8"))
    results = []
    for folder, cases in [(ROOT / "tests/fixtures", synthetic["cases"]),
                          (ROOT / "tests/fixtures/reference", real["cases"])]:
        for case in cases:
            start = time.perf_counter()
            result = parse_log(folder / case["path"])
            expected_jobs = case.get("jobs") or [case]
            assert len(result.source.jobs) == len(expected_jobs)
            for actual, expected in zip(result.source.jobs, expected_jobs):
                assert (actual.start_line, actual.end_line, actual.termination.value) == (
                    expected["start_line"], expected["end_line"], expected["termination"])
                for kind, value in expected["energies"].items():
                    energy = actual.energies[EnergyKind(kind)]
                    assert energy.value_hartree == float(value["value"])
                    assert energy.source_line == value["line"]
            results.append({"path": str((folder / case["path"]).relative_to(ROOT)),
                            "state": result.source.import_state.value, "job_count": len(result.source.jobs),
                            "lines": result.lines_read, "bytes": result.bytes_read,
                            "sha256": result.source.sha256, "elapsed_ms": (time.perf_counter() - start) * 1000})
    measurements = []
    for mib in (2, 16):
        path = out / f"streaming-{mib}MiB.log"
        with path.open("wb") as handle:
            handle.write(b"Entering Gaussian System\nSCF Done: E(RHF) = -1.0 A.U.\n")
            row = b" synthetic filler " + b"x" * (1024 - len(b" synthetic filler ") - 1) + b"\n"
            for _ in range(mib * 1024):
                handle.write(row)
            handle.write(b"Normal termination of Gaussian 16\n")
        tracemalloc.start()
        start = time.perf_counter()
        result = parse_log(path)
        elapsed = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert result.source.import_state == ImportState.READY
        assert select_job(result.source, "scf").energy.value_hartree == -1
        assert result.bytes_read == path.stat().st_size
        assert peak < 4 * 1024 * 1024, "Input is not being read with bounded Python memory"
        measurements.append({"input_bytes": path.stat().st_size, "python_peak_bytes": peak,
                             "elapsed_seconds": elapsed})
    report = {"stage": "S1", "passed": True, "host": platform.platform(), "python": platform.python_version(),
              "parser_version": PARSER_VERSION, "unit_constants_version": CONSTANTS_VERSION,
              "hartree_to_kcal": HARTREE_TO_KCAL, "hartree_to_kj": HARTREE_TO_KJ,
              "cases": results, "streaming": measurements,
              "original_sha256": hashlib.sha256((ROOT / "Gaussian_LogReaderPro.py").read_bytes()).hexdigest(),
              "scope": "SCF/Gibbs; real G16 single-point/optimization/frequency; synthetic Link1/error paths"}
    (out / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"passed": True, "case_count": len(results), "streaming": measurements,
                      "report": str(out / "validation.json")}, indent=2))


if __name__ == "__main__":
    main()
