"""Validate manually authored S0 oracles; record legacy differences without importing GUI."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import operator
import re
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
KINDS = ("scf", "gibbs_correction", "gibbs_total")
MARKERS = {
    "scf": "SCF Done:",
    "gibbs_correction": "Thermal correction to Gibbs Free Energy=",
    "gibbs_total": "Sum of electronic and thermal Free Energies=",
}


def load_oracle() -> dict:
    return json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


def validate_oracle(oracle: dict) -> None:
    """Check explicit source lines, boundaries, selection policy and exact arithmetic."""
    assert oracle["format_version"] == 1
    for case in oracle["cases"]:
        lines = (FIXTURES / case["path"]).read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("SYNTHETIC S0 FIXTURE"), case["path"]
        previous_end = 1
        for job in case["jobs"]:
            start, end = job["start_line"], job["end_line"]
            assert previous_end < start <= end <= len(lines), case["path"]
            assert lines[start - 1] == "Entering Gaussian System"
            if job["termination"] == "normal":
                assert "Normal termination" in lines[end - 1]
            elif job["termination"] == "error":
                assert "Error termination" in lines[end - 1]
            else:
                assert not any("termination" in line for line in lines[start - 1:end])
            for kind, expected in job["energies"].items():
                assert start <= expected["line"] <= end
                line = lines[expected["line"] - 1]
                assert MARKERS[kind] in line
                numeric = line.split("=", 1)[1].strip().split()[0]
                actual = Decimal(numeric.replace("D", "E").replace("d", "e"))
                assert actual == Decimal(expected["value"]), (case["path"], kind)
            previous_end = end
        for kind in KINDS:
            eligible = [i for i, j in enumerate(case["jobs"])
                        if j["termination"] == "normal" and kind in j["energies"]]
            assert case["default_job"][kind] == (eligible[-1] if eligible else None)
    calc = oracle["calculation"]
    for node in calc["nodes"]:
        delta = Decimal(node["absolute_hartree"]) - Decimal(calc["reference_hartree"])
        assert delta == Decimal(node["relative_hartree"])
        assert delta * Decimal(calc["unit_factor_kcal"]) == Decimal(node["relative_kcal"])


def legacy_parse_function():
    """Compile only the existing parse_log method with its original body."""
    source = (ROOT / "Gaussian_LogReaderPro.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LogExtractorApp")
    method = next(n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == "parse_log")
    module = ast.Module(body=[method], type_ignores=[])
    namespace = {"re": re}
    exec(compile(ast.fix_missing_locations(module), "legacy_parse_log", "exec"), namespace)
    return namespace["parse_log"]


def make_report() -> dict:
    oracle = load_oracle()
    validate_oracle(oracle)
    parse = legacy_parse_function()
    results = []
    for case in oracle["cases"]:
        actual = dict(zip(KINDS, parse(None, FIXTURES / case["path"])))
        expected = {}
        for kind in KINDS:
            selected = case["default_job"][kind]
            expected[kind] = (float(case["jobs"][selected]["energies"][kind]["value"])
                              if selected is not None else None)
        differences = {kind: {"expected": expected[kind], "legacy": actual[kind]}
                       for kind in KINDS if actual[kind] != expected[kind]}
        latest_sources = {kind: next((i for i in range(len(case["jobs"]) - 1, -1, -1)
                                     if kind in case["jobs"][i]["energies"]), None)
                          for kind in KINDS}
        cross_job = len({v for v in latest_sources.values() if v is not None}) > 1
        results.append({"path": case["path"], "expected": expected, "legacy": actual,
                        "differences": differences, "legacy_cross_job_mixing": cross_job})
    tree = ast.parse((ROOT / "Gaussian_LogReaderPro.py").read_text(encoding="utf-8"))
    evaluator_class = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                           and n.name == "EnergyExpressionEvaluator")
    namespace = {"ast": ast, "operator": operator}
    exec(compile(ast.Module(body=[evaluator_class], type_ignores=[]), "legacy_evaluator", "exec"), namespace)
    evaluator = namespace["EnergyExpressionEvaluator"]({"TS1": -149.976, "R": -150.0})
    expression_results = []
    for expression, expected_value, expected_error in [
        ("TS1 - R", 0.024, False),
        ("R_missing", None, True),
        ("True", None, True),
        ("__import__('os')", None, True),
    ]:
        try:
            value, error = evaluator.evaluate(expression), None
        except Exception as exc:
            value, error = None, type(exc).__name__
        matches = (error is not None if expected_error
                   else error is None and abs(value - expected_value) < 1e-10)
        expression_results.append({"expression": expression, "expected_value": expected_value,
                                   "expected_error": expected_error, "legacy_value": value,
                                   "legacy_error": error, "matches_contract": matches})
    return {"stage": "S0", "oracle_check": "passed", "synthetic_only": True,
            "original_sha256": hashlib.sha256((ROOT / "Gaussian_LogReaderPro.py").read_bytes()).hexdigest(),
            "cases": results,
            "legacy_expression_cases": expression_results,
            "limitations": ["No real Gaussian log compatibility has been verified.",
                            "Legacy parser has no job provenance or termination model.",
                            "The original GUI is not executed by this baseline tool."]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "s0" / "baseline.json")
    args = parser.parse_args()
    report = make_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Oracle: passed; {len(report['cases'])} synthetic cases")
    print(f"Legacy differing cases: {sum(bool(c['differences']) for c in report['cases'])}")
    print(f"Legacy cross-job cases: {sum(c['legacy_cross_job_mixing'] for c in report['cases'])}")
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
