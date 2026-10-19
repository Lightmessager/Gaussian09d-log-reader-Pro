"""Bounded, provenance retaining analysis of Gaussian output sections.

This module intentionally parses only stable, line oriented Gaussian sections.
It does not calculate thermochemistry or infer normal-mode vectors. Callers must
first fingerprint-verify the source and pass one job range.
"""
from __future__ import annotations

import math
import hashlib
import re
import os
from pathlib import Path

MAX_SOURCE_BYTES = 64 * 1024 * 1024


def read_verified_job(source, connection, job, cancel=lambda: False) -> dict:
    """Read a source only when its complete-file fingerprint still matches."""
    base = {"source_file_id": source.id, "source_sha256": source.sha256,
            "job_id": job.id, "job_ordinal": job.ordinal + 1,
            "job_start": job.start_line, "job_end": job.end_line}
    if connection is None or connection.state != "available" or not connection.path or not source.sha256:
        return {**base, "status": "source_unavailable"}
    try:
        path = Path(connection.path)
        digest = hashlib.sha256()
        chunks = []
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if before.st_size > MAX_SOURCE_BYTES:
                return {**base, "status": "size_limit"}
            size = 0
            while chunk := handle.read(65536):
                if cancel():
                    return {**base, "status": "cancelled"}
                size += len(chunk)
                if size > MAX_SOURCE_BYTES:
                    return {**base, "status": "size_limit"}
                digest.update(chunk)
                chunks.append(chunk)
            after = os.fstat(handle.fileno())
        signature = lambda item: (item.st_size, item.st_mtime_ns, item.st_ino, item.st_dev)
        if (digest.hexdigest() != source.sha256 or signature(before) != signature(after)
                or signature(after) != signature(path.stat())):
            return {**base, "status": "source_changed"}
        text = b"".join(chunks).decode("utf-8-sig", errors="replace")
        lines = text.splitlines()
        if job.end_line > len(lines):
            return {**base, "status": "job_range_invalid"}
        return {**base, "status": "available", "lines": lines}
    except OSError:
        return {**base, "status": "source_unreadable"}


_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?\Z")
_FREQUENCIES = re.compile(r"^\s*Frequencies\s*-{3,}\s*(.*?)\s*$", re.I)
_IR = re.compile(r"^\s*IR\s+Inten(?:sities)?\s*-{2,}\s*(.*?)\s*$", re.I)
_THERMO = (
    ("gibbs_correction_hartree", re.compile(r"Thermal correction to Gibbs Free Energy\s*=\s*(\S+)", re.I)),
    ("gibbs_total_hartree", re.compile(r"Sum of electronic and thermal Free Energies\s*=\s*(\S+)", re.I)),
    ("enthalpy_total_hartree", re.compile(r"Sum of electronic and thermal Enthalpies\s*=\s*(\S+)", re.I)),
    ("electronic_zero_point_hartree", re.compile(r"Sum of electronic and zero-point Energies\s*=\s*(\S+)", re.I)),
    ("electronic_thermal_hartree", re.compile(r"Sum of electronic and thermal Energies\s*=\s*(\S+)", re.I)),
)
_SCF = re.compile(r"SCF Done:\s*E\(([^)]+)\)\s*=\s*(\S+)", re.I)
_NBO_VERSION = re.compile(r"Gaussian NBO Version\s+(\d+(?:\.\d+)?)", re.I)
_NPA_ROW = re.compile(r"^\s*([A-Z][a-z]?)\s+(\d+)\s+([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s*$")
_NBO_E2_ROW = re.compile(r"^\s*\d+\.\s+(.+?)\s*/\s*(\d+\.\s+.+?)\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$")
_NBO_HEADERS = ("Natural Bond Orbital", "Natural Population Analysis", "Second Order Perturbation Theory")
_IRC_HEADERS = ("# of points along the path", "Reaction path following", "IRC-IRC-", "Point Number")
_IRC_POINT = re.compile(r"^\s*Point Number:\s*(\d+)\s+Path Number:\s*(\d+)\s*$", re.I)
_IRC_DIRECTION = re.compile(r"Point Number\s+\d+\s+in\s+(FORWARD|REVERSE)\s+path direction", re.I)
_IRC_TS_ENERGY = re.compile(r"Energies reported relative to the TS energy of\s+(\S+)", re.I)
_IRC_COORDINATE = re.compile(r"NET REACTION COORDINATE UP TO THIS POINT\s*=\s*(\S+)", re.I)
_IRC_SUMMARY_ROW = re.compile(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s*$")
_IRC_ATOM = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")


def _numbers(payload: str) -> list[float] | None:
    result = []
    for raw in payload.split():
        if not _NUMBER.fullmatch(raw):
            return None
        value = float(raw.replace("D", "E").replace("d", "e"))
        if not math.isfinite(value):
            return None
        result.append(value)
    return result or None


def _line_rows(lines: list[str], start_line: int, end_line: int):
    # Input lines are a zero based whole-file list; job ranges are one based/inclusive.
    return ((number, lines[number - 1]) for number in range(max(1, start_line), min(end_line, len(lines)) + 1))


def parse_vibrations(lines: list[str], start_line: int, end_line: int) -> dict:
    """Read Gaussian harmonic frequency and IR intensity rows within one job."""
    modes = []
    pending = None
    for line_no, text in _line_rows(lines, start_line, end_line):
        frequency_match = _FREQUENCIES.match(text)
        if frequency_match:
            values = _numbers(frequency_match.group(1))
            if values is None or len(values) > 8:
                return {"status": "parse_error", "reason": "invalid_frequency_row", "line": line_no, "modes": []}
            pending = [{"frequency": value, "intensity": None, "line": line_no} for value in values]
            modes.extend(pending)
            continue
        ir_match = _IR.match(text)
        if ir_match and pending is not None:
            values = _numbers(ir_match.group(1))
            if values is None or len(values) != len(pending):
                return {"status": "parse_error", "reason": "invalid_ir_intensity_row", "line": line_no, "modes": []}
            for index, value in enumerate(values):
                pending[index]["intensity"] = value
            pending = None
    rows = [{"mode": index, "frequency_cm1": item["frequency"], "imaginary": item["frequency"] < 0,
             "ir_intensity_km_mol": item["intensity"], "source_line": item["line"]}
            for index, item in enumerate(modes, 1)]
    if not rows:
        return {"status": "no_data", "reason": "no_harmonic_frequencies", "modes": []}
    return {"status": "available", "modes": rows, "mode_count": len(rows),
            "imaginary_count": sum(row["imaginary"] for row in rows), "units": "cm^-1"}


def parse_thermochemistry(lines: list[str], start_line: int, end_line: int) -> dict:
    """Return explicit Gaussian thermochemistry terms; never derive missing totals."""
    values = {}
    conditions = {}
    temperature = re.compile(r"Temperature\s+(\S+)\s+Kelvin\.\s+Pressure\s+(\S+)\s+Atm\.", re.I)
    charge = re.compile(r"Charge\s*=\s*([+-]?\d+)\s+Multiplicity\s*=\s*(\d+)", re.I)
    for line_no, text in _line_rows(lines, start_line, end_line):
        match = _SCF.search(text)
        if match:
            number = _numbers(match.group(2))
            if number is None or len(number) != 1:
                return {"status": "parse_error", "reason": "invalid_scf_number", "line": line_no, "values": []}
            values["scf_electronic_hartree"] = {"value": number[0], "unit": "hartree",
                                                "raw": match.group(2), "method": match.group(1),
                                                "source_line": line_no}
        for key, pattern in _THERMO:
            match = pattern.search(text)
            if match:
                value = _numbers(match.group(1))
                if value is None or len(value) != 1:
                    return {"status": "parse_error", "reason": "invalid_thermochemistry_number", "line": line_no, "values": []}
                values[key] = {"value": value[0], "unit": "hartree", "raw": match.group(1), "source_line": line_no}
        match = temperature.search(text)
        if match:
            parsed = [_numbers(raw) for raw in match.groups()]
            if any(value is None or len(value) != 1 or value[0] <= 0 for value in parsed):
                return {"status": "parse_error", "reason": "invalid_conditions", "line": line_no, "values": []}
            conditions["temperature_kelvin"] = {"value": parsed[0][0], "unit": "K", "source_line": line_no}
            conditions["pressure_atm"] = {"value": parsed[1][0], "unit": "atm", "source_line": line_no}
        match = charge.search(text)
        if match:
            conditions["charge"] = {"value": int(match.group(1)), "unit": "e", "source_line": line_no}
            conditions["multiplicity"] = {"value": int(match.group(2)), "unit": "", "source_line": line_no}
    if not values and not conditions:
        return {"status": "no_data", "reason": "no_supported_thermochemistry", "values": [], "conditions": []}
    return {"status": "available", "values": [{"term": key, **value} for key, value in values.items()],
            "conditions": [{"term": key, **value} for key, value in conditions.items()]}


def find_analysis_sections(lines: list[str], start_line: int, end_line: int, module: str) -> dict:
    """Dispatch source-bound NBO and IRC readers."""
    if module == "nbo":
        return parse_nbo(lines, start_line, end_line)
    elif module == "irc":
        return parse_irc(lines, start_line, end_line)
    else:
        raise ValueError("module must be nbo or irc")


def _irc_number(raw: str) -> float | None:
    values = _numbers(raw)
    return values[0] if values is not None and len(values) == 1 else None


def _irc_structure(lines: list[str], marker_line: int, stop_line: int) -> dict | None:
    """Read the CURRENT STRUCTURE block attached to a completed IRC point."""
    limit = min(stop_line, marker_line + 1020)
    for number in range(marker_line + 1, min(marker_line + 12, limit + 1)):
        if lines[number - 1].strip() != "CURRENT STRUCTURE":
            continue
        first = next((n for n in range(number + 1, min(number + 10, limit + 1))
                      if re.fullmatch(r"\s*-{5,}\s*", lines[n - 1])), None)
        if first is None:
            return None
        second = next((n for n in range(first + 1, min(first + 7, limit + 1))
                       if re.fullmatch(r"\s*-{5,}\s*", lines[n - 1])), None)
        if second is None:
            return None
        atoms = []
        for atom_line in range(second + 1, min(second + 1002, limit + 1)):
            raw = lines[atom_line - 1]
            if re.fullmatch(r"\s*-{5,}\s*", raw):
                return {"status": "available", "orientation": "IRC current structure",
                        "units": "angstrom", "line_start": number, "line_end": atom_line,
                        "atoms": atoms} if atoms else None
            match = _IRC_ATOM.match(raw)
            if not match or int(match[1]) != len(atoms) + 1 or not 1 <= int(match[2]) <= 118:
                return None
            xyz = [_irc_number(value) for value in match.groups()[2:]]
            if any(value is None or abs(value) > 1e6 for value in xyz):
                return None
            atoms.append({"atomic_number": int(match[2]), "xyz": xyz})
        return None
    return None


def parse_irc(lines: list[str], start_line: int, end_line: int) -> dict:
    """Read Gaussian IRC summary rows and match them to explicit branch points.

    Summary energies are relative to the stated TS energy in hartree. A point is
    associated with geometry only from its own CURRENT STRUCTURE block. The
    summary coordinate must agree with that point's reported net coordinate.
    """
    rows = list(_line_rows(lines, start_line, end_line))
    headers = [{"line": n, "text": value.strip()[:300]} for n, value in rows
               if any(header.casefold() in value.casefold() for header in _IRC_HEADERS)]
    if not headers:
        return {"status": "no_data", "reason": "no_irc_section", "points": []}
    direction = None
    path_directions = {}
    points = {}
    ts_energy = None
    summary_line = None
    for n, value in rows:
        match = _IRC_DIRECTION.search(value)
        if match:
            direction = match[1].lower()
        match = _IRC_POINT.match(value)
        if match:
            step, path = map(int, match.groups())
            if step > 0:
                if direction is None:
                    return {"status": "unsupported_format", "reason": "irc_branch_direction_missing", "sections": headers}
                if path in path_directions and path_directions[path] != direction:
                    return {"status": "parse_error", "reason": "irc_conflicting_path_direction", "line": n, "points": []}
                path_directions[path] = direction
                points[(path, step)] = {"branch": direction, "path_number": path,
                                        "step": step, "source_line": n}
        match = _IRC_COORDINATE.search(value)
        if match and points:
            coordinate = _irc_number(match[1])
            if coordinate is None:
                return {"status": "parse_error", "reason": "irc_invalid_coordinate", "line": n, "points": []}
            points[next(reversed(points))]["net_coordinate"] = coordinate
        match = _IRC_TS_ENERGY.search(value)
        if match:
            ts_energy = _irc_number(match[1])
            if ts_energy is None:
                return {"status": "parse_error", "reason": "irc_invalid_ts_energy", "line": n, "points": []}
        if "Summary of reaction path following" in value:
            summary_line = n
    if summary_line is None or ts_energy is None or not path_directions:
        return {"status": "unsupported_format", "reason": "irc_complete_summary_missing", "sections": headers}
    point_markers = sorted((item["source_line"], key) for key, item in points.items())
    for index, (marker, key) in enumerate(point_markers):
        stop = point_markers[index + 1][0] - 1 if index + 1 < len(point_markers) else summary_line - 1
        # A branch transition can precede the next point marker; the structure is
        # required immediately after this marker and never borrowed from another.
        structure = _irc_structure(lines, marker, min(stop, end_line))
        if structure:
            from .structure_preview import infer_bonds
            structure["bonds"] = infer_bonds(structure["atoms"]) if len(structure["atoms"]) <= 200 else []
        points[key]["structure"] = structure
    summary = []
    in_table = False
    for n in range(summary_line + 1, min(end_line, len(lines)) + 1):
        value = lines[n - 1]
        if not in_table:
            if re.search(r"\bEnergy\s+Rx\.?\s*Coord\b", value, re.I):
                in_table = True
            continue
        match = _IRC_SUMMARY_ROW.match(value)
        if match:
            sequence = int(match[1])
            energy, coordinate = (_irc_number(raw) for raw in match.groups()[1:])
            if energy is None or coordinate is None:
                return {"status": "parse_error", "reason": "irc_invalid_summary_row", "line": n, "points": []}
            summary.append((sequence, energy, coordinate, n))
        elif summary:
            break
    if not summary or len(summary) != len(points) + 1:
        return {"status": "parse_error", "reason": "irc_summary_point_count_mismatch", "points": []}
    result = []
    used = set()
    ordered = {
        "reverse": sorted(((key, item) for key, item in points.items() if item["branch"] == "reverse"),
                          key=lambda entry: entry[1]["step"], reverse=True),
        "forward": sorted(((key, item) for key, item in points.items() if item["branch"] == "forward"),
                          key=lambda entry: entry[1]["step"]),
    }
    for sequence, energy, coordinate, line in summary:
        if abs(coordinate) <= 5e-5:
            if abs(energy) > 5e-5:
                return {"status": "parse_error", "reason": "irc_ts_row_invalid", "line": line, "points": []}
            result.append({"branch": "transition_state", "path_number": 0, "step": 0,
                           "relative_energy_hartree": energy, "reaction_coordinate": coordinate,
                           "summary_line": line, "source_line": summary_line, "structure": None})
            continue
        branch = "forward" if coordinate > 0 else "reverse"
        if not ordered[branch]:
            return {"status": "parse_error", "reason": "irc_summary_point_unmatched", "line": line, "points": []}
        key, item = ordered[branch].pop(0)
        if "net_coordinate" not in item or abs(abs(coordinate) - item["net_coordinate"]) > 5e-4:
            return {"status": "parse_error", "reason": "irc_summary_point_unmatched", "line": line, "points": []}
        used.add(key)
        result.append({**item, "relative_energy_hartree": energy,
                       "reaction_coordinate": coordinate, "summary_line": line})
    if len(used) != len(points) or sum(item["step"] == 0 for item in result) != 1:
        return {"status": "parse_error", "reason": "irc_summary_point_unmatched", "points": []}
    return {"status": "available", "points": result, "point_count": len(points),
            "branches": sorted(set(path_directions.values())), "ts_energy_hartree": ts_energy,
            "summary_line": summary_line, "energy_unit": "hartree", "coordinate_unit": "sqrt(amu)*bohr"}


def parse_nbo(lines: list[str], start_line: int, end_line: int) -> dict:
    """Parse the Gaussian NBO 3.1 NPA summary and second-order E(2) table."""
    version = None
    in_npa = False
    in_e2 = False
    npa_rows, e2_rows = [], []
    section_lines = []
    for line_no, text in _line_rows(lines, start_line, end_line):
        version_match = _NBO_VERSION.search(text)
        if version_match:
            version = version_match.group(1)
            section_lines.append({"line": line_no, "text": text.strip()[:300]})
        if "Summary of Natural Population Analysis:" in text:
            in_npa = True
        elif "Second Order Perturbation Theory Analysis of Fock Matrix in NBO Basis" in text:
            in_e2 = True
            in_npa = False
            section_lines.append({"line": line_no, "text": text.strip()[:300]})
        elif "Natural Bond Orbitals (Summary)" in text:
            in_e2 = False
        if in_npa:
            match = _NPA_ROW.match(text)
            if match:
                symbol, atom, *raw_values = match.groups()
                npa_rows.append({"atom": int(atom), "element": symbol,
                                 "charge": float(raw_values[0]), "core": float(raw_values[1]),
                                 "valence": float(raw_values[2]), "rydberg": float(raw_values[3]),
                                 "total": float(raw_values[4]), "source_line": line_no})
            if "* Total *" in text:
                in_npa = False
        if in_e2:
            match = _NBO_E2_ROW.match(text)
            if match:
                donor, acceptor, e2, gap, coupling = match.groups()
                nbo_values = [float(value) for value in (e2, gap, coupling)]
                if all(math.isfinite(value) for value in nbo_values):
                    e2_rows.append({"donor": donor.strip(), "acceptor": acceptor.strip(),
                                    "e2_kcal_mol": nbo_values[0], "energy_gap_hartree": nbo_values[1],
                                    "fock_coupling_hartree": nbo_values[2], "source_line": line_no})
    if version is None and not section_lines and not npa_rows and not e2_rows:
        return {"status": "no_data", "reason": "no_nbo_section", "sections": []}
    if version != "3.1":
        return {"status": "unsupported_format", "reason": "unsupported_nbo_version",
                "version": version, "sections": section_lines}
    if not npa_rows and not e2_rows:
        return {"status": "parse_error", "reason": "nbo_3_1_sections_without_supported_rows",
                "version": version, "sections": section_lines}
    sections = []
    if npa_rows:
        sections.append({"name": "Natural Population Analysis", "columns":
                         ["atom", "element", "charge", "core", "valence", "rydberg", "total", "source_line"],
                         "rows": npa_rows})
    if e2_rows:
        sections.append({"name": "Second Order Perturbation E(2)", "columns":
                         ["donor", "acceptor", "e2_kcal_mol", "energy_gap_hartree",
                          "fock_coupling_hartree", "source_line"], "rows": e2_rows})
    return {"status": "available", "version": version, "sections": sections,
            "row_count": len(npa_rows) + len(e2_rows)}
