"""Bounded, cancellable, fingerprint-verified display structures. No core IDs change."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import math
import os
import re
from pathlib import Path

PARSER_VERSION = "orientation-preview-v1"
MAX_BYTES = 64 * 1024 * 1024
MAX_ATOMS = 1000
_DASH = re.compile(r"^\s*-{5,}\s*$")
_START = re.compile(r"^\s*(Standard|Input) orientation:\s*$")
# Display-only single-bond distance heuristic; unsupported elements get no inferred bonds.
RADII = {1: .31, 6: .76, 7: .71, 8: .66, 9: .57, 15: 1.07, 16: 1.05, 17: 1.02, 35: 1.20, 53: 1.39}


def parse_orientation(lines, start_line, end_line, cancel=lambda: False):
    """Only complete Angstrom tables inside the exact bound job. Last Standard wins.

    Input is the fallback only when no complete supported Standard exists. Unknown
    units, ghost atoms, nonfinite coordinates and partial tables never form models.
    """
    found = {"Standard": [], "Input": []}
    reason = "no_structure"
    i = max(0, start_line - 1)
    stop = min(len(lines), end_line)
    while i < stop:
        if cancel():
            return {"status": "cancelled"}
        match = _START.match(lines[i])
        if not match:
            i += 1
            continue
        first = i
        kind = match[1]
        i += 1
        header = []
        separators = 0
        while i < stop and i - first <= 9:
            text = lines[i]
            if _DASH.match(text):
                separators += 1
            else:
                header.append(text)
            i += 1
            if separators == 2:
                break
        if separators != 2 or not any("Coordinates" in h for h in header):
            reason = "invalid_orientation"
            continue
        if not any("Coordinates (Angstroms)" in h for h in header):
            reason = "unsupported_units"
            continue
        atoms = []
        valid = True
        complete = False
        while i < stop:
            if cancel():
                return {"status": "cancelled"}
            text = lines[i]
            if _DASH.match(text):
                complete = True
                i += 1
                break
            parts = text.split()
            try:
                if len(parts) != 6:
                    raise ValueError()
                center, number, atomic_type = map(int, parts[:3])
                xyz = [float(v.replace("D", "E").replace("d", "e")) for v in parts[3:]]
                if center != len(atoms) + 1 or not 1 <= number <= 118 or not all(math.isfinite(v) and abs(v) <= 1e6 for v in xyz):
                    raise ValueError()
                atoms.append({"atomic_number": number, "xyz": xyz})
                if len(atoms) > MAX_ATOMS:
                    return {"status": "atom_limit"}
            except (ValueError, OverflowError):
                valid = False
                break
            i += 1
        if complete and valid and atoms:
            found[kind].append({"status": "available", "orientation": kind, "units": "angstrom", "line_start": first + 1,
                                "line_end": i, "atoms": atoms})
        else:
            reason = "invalid_orientation"
            # Revisit an unexpected marker rather than swallowing the next block.
            if i == first:
                i += 1
    candidates = found["Standard"] or found["Input"]
    return candidates[-1] if candidates else {"status": reason}


def infer_bonds(atoms, cancel=lambda: False):
    bonds = []
    for i, a in enumerate(atoms):
        if cancel():
            return None
        for j in range(i):
            b = atoms[j]
            ra, rb = RADII.get(a["atomic_number"]), RADII.get(b["atomic_number"])
            if ra is None or rb is None:
                continue
            distance2 = sum((x-y)**2 for x, y in zip(a["xyz"], b["xyz"]))
            if .16 < distance2 <= (1.20 * (ra + rb))**2:
                bonds.append([j, i])
                if len(bonds) >= 6000:
                    return bonds
    return bonds


class StructurePreviewService:
    def __init__(self):
        self.cache = OrderedDict()

    def read(self, source, job, connection, cancel=lambda: False, *, line=None):
        base = {"source_file_id": source.id, "source_label":source.original_name, "job_id": job.id, "source_sha256": source.sha256,
                "job_ordinal": job.ordinal + 1, "job_start": job.start_line, "job_end": job.end_line,
                "parser_version": PARSER_VERSION, "bond_method": "display_distance_heuristic"}
        if connection is None or connection.state != "available" or not connection.path or not source.sha256:
            return {**base, "status": connection.state if connection else "unverified"}
        try:
            path = Path(connection.path)
            chunks = []
            digest = sha256()
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                if before.st_size > MAX_BYTES:
                    return {**base, "status": "size_limit"}
                count = 0
                while chunk := stream.read(65536):
                    if cancel():
                        return {**base, "status": "cancelled"}
                    count += len(chunk)
                    if count > MAX_BYTES:
                        return {**base, "status": "size_limit"}
                    digest.update(chunk)
                    chunks.append(chunk)
                after = os.fstat(stream.fileno())
            signature = lambda stat: (stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev)
            if digest.hexdigest() != source.sha256 or signature(before) != signature(after) or signature(after) != signature(path.stat()):
                return {**base, "status": "changed"}
            text = b"".join(chunks).decode("utf-8-sig", errors="replace")
            lines = text.splitlines()
            key = (source.sha256, job.id, job.start_line, job.end_line, PARSER_VERSION)
            if key in self.cache:
                result = deepcopy(self.cache[key])
                self.cache.move_to_end(key)
            else:
                result = parse_orientation(lines, job.start_line, job.end_line, cancel)
                if result["status"] == "available":
                    bonds = infer_bonds(result["atoms"], cancel)
                    if bonds is None:
                        return {**base, "status": "cancelled"}
                    result["bonds"] = bonds
                if result["status"] != "cancelled":
                    self.cache[key] = deepcopy(result)
                    while len(self.cache) > 32:
                        self.cache.popitem(last=False)
            result = {**base, **result, "synthetic": "SYNTHETIC" in text[:512].upper()}
            if line is not None:
                if type(line) is not int or not job.start_line <= line <= job.end_line:
                    return {**base, "status": "invalid_line"}
                lo, hi = max(job.start_line, line-12), min(job.end_line, line+12, len(lines))
                result["excerpt"] = {"line": line, "start": lo, "end": hi, "text": "\n".join(f"{n:>7}  {lines[n-1][:2000]}" for n in range(lo, hi+1))}
            return result
        except OSError:
            return {**base, "status": "unreadable"}
