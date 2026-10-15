"""Behavior checks against independent manual oracles and adversarial inputs."""
import hashlib
import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import UUID

import pytest

from gaussianreadpro.core.models import (EnergyKind, ImportState, SCFConvergence,
                                        Termination, snapshot_to_dict)
from gaussianreadpro.core.parser import parse_log, select_job

FIXTURES = Path(__file__).parent / "fixtures"
ORACLE = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
SOURCE_ID = "53e06f66-b08d-498b-8476-aae6485a0823"


def codes(items):
    return {d.code for d in items}


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda case: case["path"])
def test_manual_job_and_line_oracle(case):
    path = FIXTURES / case["path"]
    result = parse_log(path, SOURCE_ID)
    assert result.source.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.bytes_read == path.stat().st_size
    assert len(result.source.jobs) == len(case["jobs"])
    for actual, expected in zip(result.source.jobs, case["jobs"]):
        assert (actual.start_line, actual.end_line, actual.termination.value) == (
            expected["start_line"], expected["end_line"], expected["termination"])
        assert set(actual.energies) == set(expected["energies"])
        for kind, value in expected["energies"].items():
            energy = actual.energies[EnergyKind(kind)]
            assert energy.value_hartree == pytest.approx(float(value["value"]), abs=1e-12)
            assert energy.source_line == value["line"]
            assert energy.job_id == actual.id
    for kind, expected_index in case["default_job"].items():
        selection = select_job(result.source, kind)
        assert selection.available == (expected_index is not None)
        assert (selection.job.ordinal if selection.job else None) == expected_index
        if expected_index is not None:
            assert set(case.get("warnings", [])) <= codes(selection.diagnostics)


def test_single_point_is_ready_and_missing_gibbs_does_not_change_state():
    source = parse_log(FIXTURES / "logs/single_point.log").source
    assert source.import_state == ImportState.READY
    scf = select_job(source, EnergyKind.SCF)
    gibbs = select_job(source, EnergyKind.GIBBS_TOTAL, job_id=scf.job.id)
    assert scf.available and not gibbs.available
    assert gibbs.job.id == scf.job.id
    assert "missing_energy" in codes(gibbs.diagnostics)
    assert source.jobs[0].scf_convergence == SCFConvergence.CONVERGED


def test_explicit_binding_cannot_borrow_previous_jobs_gibbs():
    source = parse_log(FIXTURES / "logs/multi_job.log").source
    selected = select_job(source, EnergyKind.SCF)
    missing = select_job(source, EnergyKind.GIBBS_TOTAL, job_id=selected.job.id)
    assert not missing.available
    assert missing.job.ordinal == 1
    assert "missing_energy" in codes(missing.diagnostics)
    assert select_job(source, EnergyKind.GIBBS_TOTAL).job.ordinal == 0
    unknown = select_job(source, EnergyKind.SCF, job_id="fb847fd4-96cc-45fc-88a4-3c303a7db3ff")
    assert not unknown.available and "job_not_found" in codes(unknown.diagnostics)


def test_failed_and_incomplete_jobs_require_explicit_selection():
    source = parse_log(FIXTURES / "logs/last_job_failed.log").source
    assert source.import_state == ImportState.PARTIAL
    automatic = select_job(source, "scf")
    manual = select_job(source, "scf", job_id=source.jobs[1].id)
    assert automatic.energy.value_hartree == -75
    assert manual.energy.value_hartree == -76
    assert "job_error_termination" in codes(manual.diagnostics)
    truncated = parse_log(FIXTURES / "logs/truncated.log").source
    assert not select_job(truncated, "scf").available
    assert select_job(truncated, "scf", job_id=truncated.jobs[0].id).available


def test_same_names_and_reparse_have_correct_stable_identity(tmp_path):
    a = parse_log(FIXTURES / "logs/目录 A/species.log", SOURCE_ID).source
    b = parse_log(FIXTURES / "logs/目录 B/species.log").source
    assert a.display_name == b.display_name == "species"
    assert a.id != b.id and a.jobs[0].id != b.jobs[0].id
    again = parse_log(FIXTURES / "logs/目录 A/species.log", SOURCE_ID).source
    assert a.jobs[0].id == again.jobs[0].id
    assert str(UUID(a.id)) == a.id
    target = tmp_path / "copy.log"
    target.write_bytes((FIXTURES / "logs/目录 A/species.log").read_bytes())
    identical = parse_log(target, SOURCE_ID).source
    assert identical.jobs[0].id == a.jobs[0].id
    target.write_bytes(target.read_bytes().replace(b"-10.000000000", b"-12.000000000"))
    changed = parse_log(target, SOURCE_ID).source
    assert changed.jobs[0].id != a.jobs[0].id


def write_log(tmp_path, content, *, crlf=False):
    path = tmp_path / "中文 path-file.LOG"
    data = content.replace("\n", "\r\n") if crlf else content
    path.write_bytes(data.encode("utf-8"))
    return path


@pytest.mark.parametrize("crlf", [False, True])
def test_runtime_link1_boundary_does_not_split_internal_links(tmp_path, crlf):
    path = write_log(tmp_path, "Entering Gaussian System\n"
                     "Entering Link 1 = /g16/l1.exe\n"
                     " #p b3lyp/sto-3g opt\n"
                     "SCF Done: E(RB3LYP) = -1.0 A.U.\n"
                     "Entering Link 1 = /g16/l1.exe\n"
                     "SCF Done: E(RB3LYP) = -2.0 A.U.\n"
                     "Normal termination of Gaussian 16\n"
                     "Link1:  Proceeding to internal job step number  2.\n"
                     "Entering Link 1 = /g16/l1.exe\n"
                     " #p b3lyp/sto-3g freq\n"
                     "SCF Done: E(RB3LYP) = -3.0 A.U.\n"
                     "Thermal correction to Gibbs Free Energy= .01\n"
                     "Sum of electronic and thermal Free Energies= -2.99\n"
                     "Normal termination of Gaussian 16\n", crlf=crlf)
    jobs = parse_log(path).source.jobs
    assert len(jobs) == 2
    assert (jobs[0].start_line, jobs[0].end_line) == (1, 7)
    assert (jobs[1].start_line, jobs[1].end_line) == (8, 14)
    assert jobs[0].energies[EnergyKind.SCF].source_line == 6
    assert jobs[0].energies[EnergyKind.SCF].value_hartree == -2
    assert EnergyKind.GIBBS_TOTAL not in jobs[0].energies
    assert jobs[1].energies[EnergyKind.GIBBS_TOTAL].value_hartree == -2.99


def test_link1_without_terminal_record_closes_previous_as_incomplete(tmp_path):
    path = write_log(tmp_path, "Entering Gaussian System\nSCF Done: E(RHF) = -1\n"
                     "Link1: Proceeding to internal job step number 2.\nSCF Done: E(RHF) = -2\n"
                     "Normal termination of Gaussian 16\n")
    jobs = parse_log(path).source.jobs
    assert jobs[0].termination == Termination.INCOMPLETE
    assert jobs[0].end_line == 2 and jobs[1].start_line == 3
    assert len(jobs) == 2


@pytest.mark.parametrize("token,expected", [("+1.5E-2", .015), ("-.125d+2", -12.5),
                                           (".5", .5), ("-2.", -2)])
def test_all_supported_numeric_forms(tmp_path, token, expected):
    path = write_log(tmp_path, f"Entering Gaussian System\nSCF Done: E(RHF) = {token} A.U.\n"
                     "Normal termination of Gaussian 16\n")
    energy = parse_log(path).source.jobs[0].energies[EnergyKind.SCF]
    assert energy.value_hartree == expected
    assert energy.raw_text == token


@pytest.mark.parametrize("token", ["NaN", "Infinity", "1e999", "-1D+02oops", "True", ""])
def test_malformed_or_nonfinite_values_are_not_silently_truncated(tmp_path, token):
    path = write_log(tmp_path, f"Entering Gaussian System\nSCF Done: E(RHF) = {token}\n"
                     "Normal termination of Gaussian 16\n")
    source = parse_log(path).source
    assert source.jobs[0].energies == {}
    assert codes(source.jobs[0].diagnostics) & {"invalid_energy_number", "non_finite_energy"}
    assert not select_job(source, "scf").available
    json.dumps(snapshot_to_dict(source), allow_nan=False)


def test_convergence_is_evidence_not_guessed_from_missing_energy(tmp_path):
    path = write_log(tmp_path, "Entering Gaussian System\nConvergence failure -- run terminated.\n"
                     "Error termination via Lnk1e\n")
    source = parse_log(path).source
    assert source.jobs[0].scf_convergence == SCFConvergence.FAILED
    unknown = parse_log(FIXTURES / "logs/unrecognized.log").source
    assert unknown.jobs[0].scf_convergence == SCFConvergence.UNKNOWN
    other_failure = parse_log(FIXTURES / "logs/last_job_failed.log").source.jobs[1]
    assert other_failure.scf_convergence == SCFConvergence.CONVERGED


def test_metadata_routes_wrap_and_missing_fields_stay_none(tmp_path):
    path = write_log(tmp_path, "\ufeffEntering Gaussian System\n"
                     " #p B3LYP/6-31G(d) opt freq\n"
                     " scrf=(smd,solvent=water)\n"
                     " ----------------------\n"
                     "Charge = -1 Multiplicity = 2\n"
                     "Standard basis: 6-31G(d) (5D, 7F)\n"
                     "SCF Done: E(UB3LYP) = -100\n"
                     "Temperature 298.150 Kelvin. Pressure 1.00000 Atm.\n"
                     "Normal termination of Gaussian 16\n")
    meta = parse_log(path).source.jobs[0].metadata
    assert meta.method == "B3LYP" and meta.basis_set == "6-31G(d)"
    assert meta.solvent == "water" and meta.scf_method_label == "UB3LYP"
    assert meta.charge == -1 and meta.multiplicity == 2
    assert meta.temperature_kelvin == 298.15 and meta.pressure_atm == 1
    assert meta.source_lines["method"] == 2 and meta.source_lines["temperature_kelvin"] == 8
    missing = parse_log(FIXTURES / "logs/single_point.log").source.jobs[0].metadata
    assert missing.temperature_kelvin is None and missing.solvent is None


def test_snapshots_are_immutable_and_json_compatible():
    result = parse_log(FIXTURES / "logs/normal_opt_freq.log")
    with pytest.raises(FrozenInstanceError):
        result.source.display_name = "changed"
    with pytest.raises(TypeError):
        result.source.jobs[0].energies[EnergyKind.SCF] = None
    with pytest.raises(TypeError):
        result.source.jobs[0].metadata.source_lines["method"] = 0
    encoded = json.dumps(snapshot_to_dict(result), allow_nan=False)
    assert json.loads(encoded)["source"]["jobs"][0]["energies"]["scf"]["source_line"] == 5


def test_missing_empty_and_unreadable_are_distinct(tmp_path, monkeypatch):
    missing = parse_log(tmp_path / "no file.log")
    assert missing.source.import_state == ImportState.MISSING
    assert "file_not_found" in codes(missing.diagnostics)
    assert missing.source.size_bytes is None and missing.source.sha256 is None
    empty = tmp_path / "empty.log"
    empty.touch()
    result = parse_log(empty)
    assert result.source.jobs == () and result.source.import_state == ImportState.FAILED
    assert "empty_file" in codes(result.diagnostics)
    def denied(*args, **kwargs):
        raise PermissionError(13, "Denied by test")
    monkeypatch.setattr(Path, "open", denied)
    unreadable = parse_log(empty)
    assert "file_permission_denied" in codes(unreadable.diagnostics)
    assert unreadable.source.jobs == ()


def test_cancellation_is_checked_before_open_and_during_long_line(tmp_path):
    immediate = parse_log(tmp_path / "not-required.log", cancel=lambda: True)
    assert immediate.source.import_state == ImportState.CANCELLED
    assert immediate.bytes_read == 0 and immediate.source.sha256 is None
    path = tmp_path / "long.log"
    path.write_bytes(b"Entering Gaussian System\nSCF Done: E(RHF) = -1\n" + b"x" * 200000)
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        return calls >= 7
    result = parse_log(path, cancel=cancel, read_chunk_bytes=4096)
    assert result.source.import_state == ImportState.CANCELLED
    assert result.bytes_read < path.stat().st_size
    assert result.source.sha256 is None
    assert result.source.jobs[0].termination == Termination.INCOMPLETE
    assert not select_job(result.source, "scf").available


def test_overlong_and_bad_encoding_are_diagnosed_with_correct_lines(tmp_path):
    path = tmp_path / "oversized.log"
    path.write_bytes(b"Entering Gaussian System\n" + b"x" * 100000 + b"\n"
                     b"SCF Done: E(RHF) = -1\n\xff comment\nNormal termination of Gaussian 16\n")
    result = parse_log(path, max_line_bytes=1024, read_chunk_bytes=257)
    assert result.lines_read == 5 and result.bytes_read == path.stat().st_size
    assert result.source.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    job = result.source.jobs[0]
    assert job.energies[EnergyKind.SCF].source_line == 3
    assert {d.source_line for d in job.diagnostics if d.code == "line_too_long"} == {2}
    assert {d.source_line for d in job.diagnostics if d.code == "decode_replacement"} == {4}


def test_source_changed_while_reading_is_stale(tmp_path):
    path = write_log(tmp_path, "Entering Gaussian System\nSCF Done: E(RHF) = -1\n"
                     "Normal termination of Gaussian 16\n")
    original_mtime = path.stat().st_mtime_ns
    calls = 0
    def change_during_read():
        nonlocal calls
        calls += 1
        if calls == 4:
            os.utime(path, ns=(original_mtime, original_mtime + 1_000_000_000))
        return False
    result = parse_log(path, cancel=change_during_read)
    assert result.source.import_state == ImportState.STALE
    assert result.source.sha256 is None
    assert "source_changed_during_read" in codes(result.diagnostics)
    assert not select_job(result.source, "scf").available


def test_missing_start_marker_is_exposed(tmp_path):
    path = write_log(tmp_path, "Preamble\nSCF Done: E(RHF) = -1\nNormal termination of Gaussian 16")
    job = parse_log(path).source.jobs[0]
    assert (job.start_line, job.end_line) == (2, 3)
    assert "missing_job_start_marker" in codes(job.diagnostics)


def test_diagnostic_growth_is_bounded(tmp_path):
    path = write_log(tmp_path, "Entering Gaussian System\n" + "SCF Done: E(RHF) = NaN\n" * 500
                     + "Normal termination of Gaussian 16\n")
    job = parse_log(path).source.jobs[0]
    assert len(job.diagnostics) <= 64
    assert "diagnostics_truncated" in codes(job.diagnostics)


def test_huge_integer_metadata_and_route_cannot_crash_or_expand_without_limit(tmp_path):
    path = write_log(tmp_path, "Entering Gaussian System\n#p " + "x" * 50000 + "\n"
                     + "Charge = " + "9" * 5000 + " Multiplicity = 1\n"
                     + "SCF Done: E(RHF) = -1\nNormal termination of Gaussian 16\n")
    job = parse_log(path).source.jobs[0]
    assert job.energies[EnergyKind.SCF].value_hartree == -1
    assert job.metadata.charge is None
    assert len(job.metadata.route) <= 8192
    assert {"route_too_long", "invalid_charge_or_multiplicity"} <= codes(job.diagnostics)


def test_iop_slash_is_not_guessed_as_method_basis(tmp_path):
    path = write_log(tmp_path, "Entering Gaussian System\n#p guess=read iop(3/33=1)\n"
                     "SCF Done: E(RHF) = -1\nNormal termination of Gaussian 16\n")
    meta = parse_log(path).source.jobs[0].metadata
    assert meta.method is None and meta.basis_set is None


def test_append_new_job_preserves_completed_old_job_id(tmp_path):
    path = write_log(tmp_path, "Entering Gaussian System\nSCF Done: E(RHF) = -1\n"
                     "Normal termination of Gaussian 16\n")
    original = parse_log(path, SOURCE_ID).source
    with path.open("ab") as handle:
        handle.write(b"Entering Gaussian System\nSCF Done: E(RHF) = -2\nNormal termination of Gaussian 16\n")
    appended = parse_log(path, SOURCE_ID).source
    assert len(appended.jobs) == 2
    assert appended.jobs[0].id == original.jobs[0].id
    assert appended.sha256 != original.sha256


def test_callback_programming_error_is_not_reported_as_file_error(tmp_path):
    def broken_callback():
        raise RuntimeError("Caller failure")
    with pytest.raises(RuntimeError):
        parse_log(tmp_path / "file.log", cancel=broken_callback)


def test_io_failure_mid_stream_keeps_evidence_but_blocks_computation(tmp_path, monkeypatch):
    path = write_log(tmp_path, "Entering Gaussian System\nSCF Done: E(RHF) = -1\n"
                     "Normal termination of Gaussian 16\n")
    original_open = Path.open
    class FailingReader:
        def __init__(self, handle):
            self.handle = handle
            self.read_count = 0
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.handle.close()
        def fileno(self):
            return self.handle.fileno()
        def readline(self, limit):
            self.read_count += 1
            if self.read_count == 3:
                raise OSError(5, "Simulated I/O failure")
            return self.handle.readline(limit)
    monkeypatch.setattr(Path, "open", lambda self, *args, **kwargs:
                        FailingReader(original_open(self, *args, **kwargs)))
    result = parse_log(path)
    assert result.source.import_state == ImportState.FAILED
    assert "file_read_error" in codes(result.diagnostics)
    assert result.source.sha256 is None
    assert result.source.jobs[0].energies[EnergyKind.SCF].value_hartree == -1
    assert result.source.jobs[0].termination == Termination.INCOMPLETE
    assert not select_job(result.source, "scf").available


def test_last_valid_value_keeps_its_own_line_when_later_value_is_invalid(tmp_path):
    path = write_log(tmp_path, "Entering Gaussian System\nSCF Done: E(RHF) = -1.25\n"
                     "SCF Done: E(RHF) = -1.5D+00oops\nNormal termination of Gaussian 16\n")
    source = parse_log(path).source
    assert source.import_state == ImportState.PARTIAL
    selected = select_job(source, "scf")
    assert selected.energy.value_hartree == -1.25
    assert selected.energy.source_line == 2
    assert "invalid_energy_number" in codes(selected.diagnostics)
