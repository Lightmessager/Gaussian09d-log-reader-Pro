"""Protect independent benchmark inputs, not legacy implementation behavior."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("baseline", ROOT / "tools" / "check_baseline.py")
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


def test_manual_oracle_sources_and_calculation():
    baseline.validate_oracle(baseline.load_oracle())


def test_wrong_source_line_is_detected():
    oracle = baseline.load_oracle()
    oracle["cases"][0]["jobs"][0]["energies"]["scf"]["line"] = 4
    with pytest.raises(AssertionError):
        baseline.validate_oracle(oracle)


def test_incorrect_reference_or_unit_is_detected():
    oracle = baseline.load_oracle()
    oracle["calculation"]["reference_hartree"] = "-149.0"
    with pytest.raises(AssertionError):
        baseline.validate_oracle(oracle)


def test_same_names_are_distinct_fixtures():
    oracle = baseline.load_oracle()
    copies = [case for case in oracle["cases"] if case["path"].endswith("species.log")]
    assert len(copies) == 2
    assert copies[0]["path"] != copies[1]["path"]
    assert copies[0]["jobs"][0]["energies"]["scf"]["value"] != copies[1]["jobs"][0]["energies"]["scf"]["value"]
