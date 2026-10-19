"""Repeatable S8 core performance sample; writes no user project or preference."""

from dataclasses import replace
import json
import os
import platform
from pathlib import Path
import sys
from time import perf_counter
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gaussianreadpro.core import EnergyKind, calculate_path, parse_log
from gaussianreadpro.core.models import PathEntry, Project, ReactionPath, new_id
from gaussianreadpro.core.plot_spec import build_plot_spec, plot_payload
from gaussianreadpro.storage.sources import inspect_sources


def measured(call):
    start = perf_counter()
    result = call()
    return result, round((perf_counter() - start) * 1000, 3)


def main():
    fixtures = ROOT / "tests/fixtures/reference"
    names = ("dvb_sp.out", "dvb_gopt.out", "dvb_ir.out")
    paths = [fixtures / name for name in names]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Required local licensed fixtures missing: {missing}")

    tracemalloc.start()
    parsed = []
    parse_ms = []
    for path in paths:
        result, elapsed = measured(lambda path=path: parse_log(path))
        parsed.append(result.source)
        parse_ms.append(elapsed)
    _, parse_peak = tracemalloc.get_traced_memory()
    total_bytes = sum(path.stat().st_size for path in paths)

    source = parsed[-1]
    # The real frequency job has the one SCF/Gibbs pair needed for this scale probe.
    from gaussianreadpro.core import EnergyRef, compile_expression
    from gaussianreadpro.core.models import KindPolicy, ProfileNode
    ref = EnergyRef(source.id, source.jobs[0].id, KindPolicy.FIXED, EnergyKind.GIBBS_TOTAL)
    expression = compile_expression("@{real}", {"real": ref}).expression
    nodes = tuple(ProfileNode(new_id(), f"real fixture point {i}", expression) for i in range(100))
    entries = tuple(PathEntry(new_id(), node.id, i) for i, node in enumerate(nodes))
    path = ReactionPath(new_id(), "100 point scale probe", entries,
                        reference_expression=expression)
    project = Project(new_id(), source_files=tuple(parsed), nodes=nodes, paths=(path,))
    connections, fingerprint_ms = measured(lambda: inspect_sources(project, fixtures))
    if not all(item.state == "available" for item in connections):
        raise RuntimeError("Real fixture fingerprint check failed")
    result, calculate_ms = measured(lambda: calculate_path(project, path.id))
    if not result.valid or len(result.nodes) != 100:
        raise RuntimeError("100 point result invalid")
    spec, plot_spec_ms = measured(lambda: build_plot_spec(project, (result,)))
    payload, payload_ms = measured(lambda: plot_payload(spec, path.id))
    if len(payload["paths"][0]["points"]) != 100:
        raise RuntimeError("Plot payload lost scientific points")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # A display-only scale probe: these rows are synthetic and intentionally
    # contain no energy or source connection, so they cannot enter a calculation.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QTableView
    from gaussianreadpro.core.models import ImportState, SourceFile
    from gaussianreadpro.ui.tables import SourceProxy, SourceTable
    app = QApplication.instance() or QApplication([])
    table_project = Project(new_id(), source_files=tuple(
        SourceFile(new_id(), f"SYNTHETIC_{i:04d}.log", f"SYNTHETIC_{i:04d}.log",
                   str(fixtures / f"SYNTHETIC_{i:04d}.log"), 0, 0,
                   import_state=ImportState.READY)
        for i in range(1000)))
    model, proxy, table = SourceTable(), SourceProxy(), QTableView()
    model.update(table_project, (), EnergyKind.SCF)
    proxy.setSourceModel(model)
    table.setModel(proxy)
    table.resize(1000, 700)
    table.show()
    app.processEvents()
    _, filter_ms = measured(lambda: (proxy.setFilterFixedString("SYNTHETIC_0999"), app.processEvents(), proxy.rowCount()))
    if proxy.rowCount() != 1:
        raise RuntimeError("1000 row filter returned wrong count")
    _, scroll_ms = measured(lambda: (proxy.setFilterFixedString(""), table.scrollToBottom(), app.processEvents()))
    if proxy.rowCount() != 1000:
        raise RuntimeError("1000 row table did not restore all rows")
    table.close()

    report = {
        "stage": "S8", "fixture_provenance": "cclib Gaussian16 fixed commit; see tests/fixtures/reference/README.md",
        "platform": platform.platform(), "python": sys.version.split()[0],
        "real_input_bytes": total_bytes, "parse_ms_by_file": dict(zip(names, parse_ms)),
        "parse_total_ms": round(sum(parse_ms), 3),
        "parse_mib_per_second": round(total_bytes / (1024 * 1024) / (sum(parse_ms) / 1000), 3),
        "python_tracemalloc_parse_peak_bytes": parse_peak,
        "fingerprint_three_sources_ms": fingerprint_ms,
        "calculate_100_nodes_ms": calculate_ms,
        "plot_spec_100_nodes_ms": plot_spec_ms,
        "payload_100_nodes_ms": payload_ms,
        "python_tracemalloc_total_peak_bytes": peak,
        "synthetic_source_table_rows": 1000,
        "offscreen_qt_filter_1000_rows_ms": filter_ms,
        "offscreen_qt_scroll_1000_rows_ms": scroll_ms,
        "limits": "One sample on this host; Python heap only. Qt table uses synthetic display-only rows and offscreen platform. Excludes native repaint, WebEngine, GPU, export rendering and other platforms.",
    }
    destination = ROOT / "artifacts/s8/core-performance.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
