"""Real Gaussian16 log checks against manually inspected reference values."""
import hashlib
import json
from pathlib import Path

import pytest

from gaussianreadpro.core.models import EnergyKind, ImportState, Termination
from gaussianreadpro.core.parser import parse_log, select_job

REFERENCE = Path(__file__).parent / "fixtures" / "reference"
REFERENCE_OUTPUTS = ("dvb_gopt.out", "dvb_ir.out", "dvb_sp.out")
if not all((REFERENCE / name).is_file() for name in REFERENCE_OUTPUTS):
    pytest.skip(
        "Real Gaussian output fixtures are not distributed; provide licensed local copies to run these checks.",
        allow_module_level=True,
    )
MANIFEST = json.loads((REFERENCE / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=lambda case: case["path"])
def test_real_log_values_lines_and_metadata(case):
    path = REFERENCE / case["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == case["sha256"]
    result = parse_log(path)
    assert result.source.sha256 == case["sha256"]
    assert result.source.import_state == ImportState.READY
    assert len(result.source.jobs) == 1
    job = result.source.jobs[0]
    assert (job.start_line, job.end_line, job.termination.value) == (
        case["start_line"], case["end_line"], case["termination"])
    assert set(job.energies) == set(case["energies"])
    for kind, expected in case["energies"].items():
        value = job.energies[EnergyKind(kind)]
        assert value.value_hartree == float(expected["value"])
        assert value.raw_text == expected["value"]
        assert value.source_line == expected["line"]
        # Independent source-line check guards the oracle as well as the parser.
        assert expected["value"] in path.read_text().splitlines()[expected["line"] - 1]
    for key, expected in case["metadata"].items():
        assert getattr(job.metadata, key) == expected
        assert job.metadata.source_lines[key] == case["metadata_lines"][key]


def test_two_real_runs_concatenated_keep_sources_and_metadata_separate(tmp_path):
    path = tmp_path / "derived-concatenation.log"
    path.write_bytes((REFERENCE / "dvb_ir.out").read_bytes() + (REFERENCE / "dvb_sp.out").read_bytes())
    source = parse_log(path).source
    assert len(source.jobs) == 2
    assert all(j.termination == Termination.NORMAL for j in source.jobs)
    assert source.jobs[1].start_line == 2678
    assert source.jobs[1].end_line == 8407
    assert source.jobs[0].metadata.temperature_kelvin == 298.15
    assert source.jobs[1].metadata.temperature_kelvin is None
    last_scf = select_job(source, EnergyKind.SCF)
    assert last_scf.job.ordinal == 1 and last_scf.energy.source_line == 6534
    last_gibbs = select_job(source, EnergyKind.GIBBS_TOTAL)
    assert last_gibbs.job.ordinal == 0 and last_gibbs.energy.source_line == 2061
    bound = select_job(source, EnergyKind.GIBBS_TOTAL, job_id=last_scf.job.id)
    assert not bound.available and bound.job.id == last_scf.job.id
