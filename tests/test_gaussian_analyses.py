from pathlib import Path
import os
from types import SimpleNamespace

import pytest

from gaussianreadpro.core.parser import parse_log
from gaussianreadpro.services.gaussian_analyses import (
    find_analysis_sections,
    parse_thermochemistry,
    parse_vibrations,
    parse_irc,
    read_verified_job,
)


def test_vibrations_preserve_modes_imaginary_sign_intensity_and_line():
    lines = ["header", " Frequencies --- -125.5  42.0", " IR Intensities --- 3.25 0.00"]
    result = parse_vibrations(lines, 1, 3)
    assert result["status"] == "available"
    assert result["mode_count"] == 2
    assert result["imaginary_count"] == 1
    assert result["modes"] == [
        {"mode": 1, "frequency_cm1": -125.5, "imaginary": True,
         "ir_intensity_km_mol": 3.25, "source_line": 2},
        {"mode": 2, "frequency_cm1": 42.0, "imaginary": False,
         "ir_intensity_km_mol": 0.0, "source_line": 2},
    ]


def test_thermochemistry_keeps_correction_distinct_from_total():
    lines = [" SCF Done: E(RB3LYP) = -382.308266602 A.U.",
             " Temperature 298.15 Kelvin. Pressure 1.00 Atm.",
             " Thermal correction to Gibbs Free Energy= 0.143352",
             " Sum of electronic and thermal Free Energies= -382.164915"]
    result = parse_thermochemistry(lines, 1, 4)
    values = {item["term"]: item for item in result["values"]}
    assert values["gibbs_correction_hartree"]["value"] == pytest.approx(.143352)
    assert values["gibbs_total_hartree"]["value"] == pytest.approx(-382.164915)
    assert values["gibbs_total_hartree"]["source_line"] == 4
    assert values["scf_electronic_hartree"]["value"] == pytest.approx(-382.308266602)
    assert {item["term"] for item in result["conditions"]} == {"temperature_kelvin", "pressure_atm"}


def test_nbo_and_irc_absence_is_not_reported_as_parse_failure():
    lines = ["SCF Done: E(RB3LYP) = -1.0 A.U."]
    assert find_analysis_sections(lines, 1, 1, "nbo")["status"] == "no_data"
    assert find_analysis_sections(lines, 1, 1, "irc")["status"] == "no_data"


def test_gaussian_nbo_31_reads_npa_and_e2_tables_with_source_lines():
    # Compact rows follow the real Gaussian 16 NBO 3.1 sample layout from cclib-data.
    lines = ["******************************Gaussian NBO Version 3.1******************************",
             "Summary of Natural Population Analysis:",
             "      O    1   -0.37667      2.00000     6.37667    0.00000     8.37667",
             "   * Total *   -0.00000      2.00000     8.00000    0.00000    10.00000",
             "Second Order Perturbation Theory Analysis of Fock Matrix in NBO Basis",
             "   1. BD ( 1) O 1 - H 2        /  7. BD*( 1) O 1 - H 3            1.46    1.42    0.041",
             "Natural Bond Orbitals (Summary):"]
    result = find_analysis_sections(lines, 1, len(lines), "nbo")
    assert result["status"] == "available"
    assert result["version"] == "3.1"
    assert result["row_count"] == 2
    npa, e2 = result["sections"]
    assert npa["rows"][0]["charge"] == pytest.approx(-.37667)
    assert npa["rows"][0]["source_line"] == 3
    assert e2["rows"][0]["e2_kcal_mol"] == pytest.approx(1.46)
    assert e2["rows"][0]["source_line"] == 6


def test_nbo_unknown_version_is_explicitly_unsupported():
    result = find_analysis_sections(["Gaussian NBO Version 7.0"], 1, 1, "nbo")
    assert result["status"] == "unsupported_format"
    assert result["reason"] == "unsupported_nbo_version"


def _compact_irc():
    # Contract excerpt transcribed from Gaussian16 HCN-ts-irc.log. Four point
    # records are shortened, while the real marker/table grammar is retained.
    lines = ["IRC-IRC-IRC-IRC-IRC", "Point Number:   0          Path Number:   1"]
    for branch, path, step, coord, hydrogen in [
        ("FORWARD", 1, 1, .08084, -.639646),
        ("FORWARD", 1, 2, .16169, -.618646),
        ("REVERSE", 2, 1, .08085, -.680903),
        ("REVERSE", 2, 2, .16170, -.701073),
    ]:
        lines += [f"Point Number  {step} in {branch} path direction.",
                  f"Point Number:   {step}          Path Number:   {path}",
                  "                    CURRENT STRUCTURE",
                  "                Cartesian Coordinates (Ang):",
                  "  ---------------------------------------------------------------------",
                  "  Center     Atomic                     Coordinates (Angstroms)",
                  "  Number     Number                        X           Y           Z",
                  "  ---------------------------------------------------------------------",
                  "       1          6                    0.443500   -0.461873    0.000000",
                  "       2          7                   -0.334023    0.463858    0.000000",
                  f"       3          1                   {hydrogen:.6f}   -0.945571    0.000000",
                  "  ---------------------------------------------------------------------",
                  f"   NET REACTION COORDINATE UP TO THIS POINT =    {coord:.5f}"]
    lines += ["Energies reported relative to the TS energy of         -93.114020",
              "    Summary of reaction path following",
              "                        Energy    RxCoord",
              "   1                   -0.00072  -0.16170",
              "   2                   -0.00017  -0.08085",
              "   3                    0.00000   0.00000",
              "   4                   -0.00018   0.08084",
              "   5                   -0.00072   0.16169",
              "  ---------------------------------------------------------------------"]
    return lines


def test_irc_branches_summary_and_selected_point_geometry():
    lines = _compact_irc()
    result = parse_irc(lines, 1, len(lines))
    assert result["status"] == "available"
    assert result["point_count"] == 4
    assert result["branches"] == ["forward", "reverse"]
    assert result["ts_energy_hartree"] == pytest.approx(-93.114020)
    assert [(p["branch"], p["step"]) for p in result["points"]] == [
        ("reverse", 2), ("reverse", 1), ("transition_state", 0),
        ("forward", 1), ("forward", 2)]
    assert result["points"][3]["structure"]["atoms"][2]["xyz"][0] == pytest.approx(-.639646)
    assert result["points"][1]["structure"]["atoms"][2]["xyz"][0] == pytest.approx(-.680903)
    assert result["points"][2]["structure"] is None


def test_irc_mismatch_and_incomplete_output_do_not_show_guessed_points():
    lines = _compact_irc()
    bad = [line.replace("0.08084", "0.99999") if "NET REACTION" in line else line for line in lines]
    assert parse_irc(bad, 1, len(bad))["status"] == "parse_error"
    assert parse_irc(lines[:25], 1, 25)["status"] == "unsupported_format"


def test_irc_single_explicit_branch_remains_single_branch():
    lines = _compact_irc()
    reverse_begin = next(i for i, line in enumerate(lines) if "REVERSE path direction" in line)
    summary_begin = next(i for i, line in enumerate(lines) if "Energies reported relative" in line)
    one_branch = lines[:reverse_begin] + lines[summary_begin:summary_begin + 3] + lines[-4:]
    result = parse_irc(one_branch, 1, len(one_branch))
    assert result["status"] == "available"
    assert result["branches"] == ["forward"]
    assert [(point["branch"], point["step"]) for point in result["points"]] == [
        ("transition_state", 0), ("forward", 1), ("forward", 2)]


def test_full_gaussian_irc_reference_if_supplied():
    path = os.environ.get("GAUSSIAN_IRC_REFERENCE")
    if not path:
        pytest.skip("Set GAUSSIAN_IRC_REFERENCE to a local Gaussian IRC output")
    parsed = parse_log(Path(path))
    assert len(parsed.source.jobs) == 1
    job = parsed.source.jobs[0]
    verified = read_verified_job(parsed.source, SimpleNamespace(state="available", path=path), job)
    assert verified["status"] == "available"
    result = parse_irc(verified["lines"], job.start_line, job.end_line)
    assert result["status"] == "available"
    assert result["point_count"] == 20
    assert result["branches"] == ["forward", "reverse"]
    assert all(p["structure"] and len(p["structure"]["atoms"]) == 3
               for p in result["points"] if p["step"] > 0)
    changed = SimpleNamespace(id=parsed.source.id, sha256="0" * 64)
    assert read_verified_job(changed, SimpleNamespace(state="available", path=path), job)["status"] == "source_changed"
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.analysis_pages import AnalysisPage

    app = QApplication.instance() or QApplication([])
    page = AnalysisPage("IRC 分析", SimpleNamespace(project=None))
    page.show_result({**result, "module": "irc", "job_ordinal": 1,
                      "job_start": job.start_line, "job_end": job.end_line})
    assert page.table.rowCount() == 21
    page.table.selectRow(0)
    reverse_xyz = page.structure_canvas.atoms[2]["xyz"]
    page.table.selectRow(20)
    forward_xyz = page.structure_canvas.atoms[2]["xyz"]
    assert reverse_xyz != forward_xyz
    assert page.table.item(0, 0).text() == "reverse"
    assert page.table.item(20, 0).text() == "forward"
    page.close()


def test_irc_page_selection_uses_the_matching_point_structure():
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.analysis_pages import AnalysisPage

    app = QApplication.instance() or QApplication([])

    class Controller:
        project = None

    lines = _compact_irc()
    result = parse_irc(lines, 1, len(lines))
    page = AnalysisPage("IRC 分析", Controller())
    page.show_result({**result, "module": "irc", "job_ordinal": 1,
                      "job_start": 1, "job_end": len(lines)})
    assert page.table.rowCount() == 5
    page.table.selectRow(3)
    assert page.structure_canvas.atoms[2]["xyz"][0] == pytest.approx(-.639646)
    page.table.selectRow(1)
    assert page.structure_canvas.atoms[2]["xyz"][0] == pytest.approx(-.680903)
    page.table.selectRow(2)
    assert page.structure_canvas.isHidden()
    page.close()


def test_real_gaussian16_frequency_and_thermochemistry_oracle():
    sample = Path(__file__).parent / "fixtures" / "reference" / "dvb_ir.out"
    if not sample.exists():
        pytest.skip("Local licensed Gaussian reference sample is not installed")
    parsed = parse_log(sample)
    job = parsed.source.jobs[-1]
    lines = sample.read_text(encoding="utf-8", errors="replace").splitlines()
    vibration = parse_vibrations(lines, job.start_line, job.end_line)
    thermo = parse_thermochemistry(lines, job.start_line, job.end_line)
    assert vibration["status"] == "available"
    assert vibration["mode_count"] == 54  # one harmonic table, not its repeated mode-vector listing
    assert vibration["modes"][0]["frequency_cm1"] == pytest.approx(53.1981)
    assert vibration["modes"][0]["source_line"] == 777
    assert vibration["imaginary_count"] == 0
    values = {item["term"]: item for item in thermo["values"]}
    assert values["gibbs_correction_hartree"]["value"] == pytest.approx(.143352)
    assert values["gibbs_total_hartree"]["value"] == pytest.approx(-382.164915)
    assert values["gibbs_total_hartree"]["source_line"] == 2061
