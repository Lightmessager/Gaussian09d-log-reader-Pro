"""Atomic, offline plot bundles. Every renderer consumes the same PlotSpec payload."""
import base64
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from time import perf_counter
import subprocess
import sys

from ..storage import StorageError

RESOURCES = Path(__file__).resolve().parents[1] / "resources" / "plot"


def assert_current_payload(payload, spec):
    if payload["project_id"] != spec.project_id or payload["revision"] != spec.revision:
        raise StorageError("stale_plot_export")
    paths = {p.id: p for p in spec.paths}
    for path in payload["paths"]:
        current = paths.get(path["id"])
        if current is None or current.reference_signature != path["reference_signature"]:
            raise StorageError("plot_sources_changed")
        points = {p.entry_id: p for p in current.points}
        for point in path["points"]:
            value = points.get(point["entry_id"])
            if value is None or value.valid != point["valid"] or dict(value.values).get(payload["unit"]) != point["value"]:
                raise StorageError("plot_sources_changed")


def _safe_cell(value):
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def _tables(payload, folder):
    en = payload["language"] == "en"
    headers = (["Path", "Path ID", "Entry ID", "Node ID", "Step", "Label", "Valid", "Value", "Unit", "Absolute / Eh", "Reference / Eh", "Difference / Eh", "Expression", "Reference expression", "Diagnostics"] if en else
               ["路径", "路径ID", "条目ID", "节点ID", "步骤", "标签", "有效", "当前数值", "单位", "体系能量/Eh", "参考能量/Eh", "能量差/Eh", "表达式", "参考表达式", "诊断"])
    rows, provenance = [], []
    source_paths = {s[0]: s[2] for s in payload["sources"]}
    for path in payload["paths"]:
        for point in path["points"]:
            rows.append([_safe_cell(path["label"]), path["id"], point["entry_id"], point["node_id"], point["x"] + 1,
                _safe_cell(point["label"]), point["valid"], point["value"] if point["valid"] else "", payload["unit_label"],
                point["absolute_hartree"], point["reference_hartree"], point["relative_hartree"], _safe_cell(point["expression"]),
                _safe_cell(path["reference"]), "; ".join([*point["diagnostics"], *path["diagnostics"]])])
            for role, dependencies in (("node", point["dependencies"]), ("reference", point["reference_dependencies"])):
                for dep in dependencies:
                    provenance.append([path["id"], point["entry_id"], role, dep["source_file_id"], _safe_cell(dep["source_label"]),
                        _safe_cell(source_paths.get(dep["source_file_id"], "")), dep["job_id"], dep["kind"], dep["source_line"],
                        dep["value_hartree"], dep["source_sha256"], json.dumps(dep["metadata"], ensure_ascii=False)])
    audit_headers = (["Path ID", "Entry ID", "Dependency", "Source ID", "Source label", "Source path", "Job ID", "Energy kind", "Source line", "Hartree", "SHA256", "Metadata"] if en else
                     ["路径ID", "条目ID", "依赖类别", "来源ID", "来源标签", "来源路径", "作业ID", "能量类型", "来源行号", "Hartree", "SHA256", "元数据"])
    for name, heading, data in (("data.csv", headers, rows), ("sources.csv", audit_headers, provenance)):
        with (folder / name).open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream, delimiter=",")
            writer.writerow(heading)
            writer.writerows(data)
    return headers, rows, audit_headers, provenance


def draw_2d(payload, destination):
    """Start a headless helper before any PySide import hooks can affect Matplotlib."""
    destination = Path(destination).resolve()
    request = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".render.json", prefix=".grpr-", dir=destination.parent,
                                         encoding="utf-8", delete=False) as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            request = Path(stream.name)
        if getattr(sys, "frozen", False):
            arguments = [sys.executable]
        else:
            # Ignore ambient PYTHONPATH/user startup hooks, then add only our trusted package root.
            # Passing the root as data also supports source checkouts without an editable install.
            bootstrap = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
                         "from gaussianreadpro.__main__ import main; raise SystemExit(main())")
            arguments = [sys.executable, "-I", "-X", "faulthandler", "-c", bootstrap,
                         str(Path(__file__).resolve().parents[2])]
        arguments += ["--render-static", str(request), str(destination)]
        environment = os.environ.copy()
        environment["MPLBACKEND"] = "Agg"
        environment["MPLCONFIGDIR"] = str(Path(tempfile.gettempdir()) / "GaussianReadPro-matplotlib")
        environment.pop("MATPLOTLIBRC", None)
        process = subprocess.run(arguments, capture_output=True, timeout=120,
            env=environment, cwd=request.parent,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        result_path = Path(str(request) + ".result.json")
        if process.returncode or not result_path.is_file():
            detail = process.stderr.decode("utf-8", errors="replace")[-2000:]
            raise StorageError("static_plot_export_failed", f"exit_code={process.returncode}; {detail}")
        return json.loads(result_path.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired as error:
        raise StorageError("static_plot_export_timeout") from error
    finally:
        if request:
            request.unlink(missing_ok=True)
            Path(str(request) + ".result.json").unlink(missing_ok=True)


def _draw_2d_in_process(payload, destination):
    started = perf_counter()
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "GaussianReadPro-matplotlib"))
    import matplotlib
    matplotlib.use("Agg", force=True)
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib import font_manager
    names = {font.name for font in font_manager.fontManager.ttflist}
    cjk = next((name for name in ("Microsoft YaHei", "Noto Sans CJK SC", "PingFang SC", "SimHei") if name in names), None)
    fonts = [cjk, "DejaVu Sans"] if cjk else ["DejaVu Sans"]
    with matplotlib.rc_context({"font.family": fonts, "axes.unicode_minus": False, "pdf.fonttype": 42, "svg.fonttype": "path", "text.parse_math": False}):
        fig = Figure(figsize=(11, 6.5), dpi=160, facecolor="white")
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        ax.set_facecolor("white")
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color("#c2d0c8")
        ax.grid(axis="y", color="#e8efeb", linewidth=.6)
        count = sum(len(p["points"]) for p in payload["paths"])
        for path in payload["paths"]:
            if not path["visible"]:
                continue
            for run in path.get("curve_runs", []):
                x_values, y_values = zip(*run)
                for width, alpha in ((7, .06), (4, .12), (1.8, 1)):
                    ax.plot(x_values, y_values, color=path["color"], linewidth=width, alpha=alpha,
                            solid_capstyle="round", zorder=2)
            for point in path["points"]:
                if not point["valid"] or point["value"] is None:
                    continue
                x, value = point["x"], point["value"]
                focus = payload.get("visual_style", {}).get("paper_selection", "#F4A06A")
                if point["selected"]:
                    ax.scatter([x], [value], s=400, c=focus, alpha=.10, edgecolors="none", zorder=3)
                    ax.scatter([x], [value], s=165, facecolors="none", edgecolors=focus, linewidths=1.5, zorder=3)
                ax.plot([x], [value], marker="o", linestyle="none",
                        color=focus if point["selected"] else path["color"], markersize=8 if point["selected"] else 6,
                        markeredgecolor=payload.get("visual_style", {}).get("paper_selection", "#7450AF") if point["selected"] else "white",
                        markeredgewidth=1.2 if point["selected"] else .7, zorder=4)
                if count <= 40 or point["selected"] or point["role"] == "transition_state":
                    dx, dy = point["label_offset"]
                    ax.annotate(f"{point['label_short']}\n{point['value_label']}", (x, value), xytext=(dx*.75, -dy*.75),
                        textcoords="offset points", ha="center", va="bottom", fontsize=9,
                        arrowprops={"arrowstyle": "-", "color": "#b8c9c0", "linewidth": .45})
            ax.plot([], [], color=path["color"], label=f"{path['label']} · {payload['text']['reference']}: {path['reference'] or '—'}")
        if payload["mode"] != "absolute":
            ax.axhline(0, color="#a8bdb0", linewidth=.7, zorder=0)
        ax.set_xlabel(payload["text"]["step"])
        ax.set_ylabel(payload["energy_label"] + " / " + payload["unit_label"])
        ax.set_xticks(payload["ticks"])
        ax.set_xticklabels(payload["tick_labels"])
        ax.margins(x=.1, y=.24)
        viewport = payload["viewport"]
        if "x_range" in viewport:
            ax.set_xlim(viewport["x_range"])
        if "y_range" in viewport:
            ax.set_ylim(viewport["y_range"])
        else:
            ax.set_ylim(payload["default_y_range"])
        for path in payload["paths"]:
            if path["visible"]:
                for point in path["points"]:
                    if point["selected"] and point["valid"] and point["value"] is not None:
                        ax.vlines(point["x"], ax.get_ylim()[0], point["value"],
                                  color=payload.get("visual_style", {}).get("paper_selection", "#F4A06A"),
                                  linewidth=.8, linestyles=":", zorder=0)
        ax.legend(loc="upper left", bbox_to_anchor=(0, -0.15), frameon=False, fontsize=8)
        ax.set_title(payload["energy_label"], loc="left", fontsize=15, pad=22)
        note = " · ".join([payload["text"]["guide"], *payload["warnings"]])
        fig.text(.09, .98, note, fontsize=8, va="top", wrap=True, color="#667d6d")
        marker = payload.get("barrier")
        if marker:
            path = next((p for p in payload["paths"] if p["id"] == marker["path_id"] and p["visible"]), None)
            point = next((p for p in path["points"] if p["entry_id"] == marker["to_entry"]), None) if path else None
            if point:
                dx, dy = marker["label_offset"]
                ax.annotate(f"{payload['barrier_label']} = {marker['value']:+.6g} {payload['unit_label']}", (point["x"], point["value"]),
                            xytext=(dx*.75, -dy*.75), textcoords="offset points", arrowprops={"arrowstyle": "->"}, fontsize=9)
        fig.subplots_adjust(left=.12, right=.96, top=.85, bottom=.24)
        fig.savefig(destination, facecolor="white", metadata={"Creator": "GaussianReadPro"} if destination.suffix in (".svg", ".pdf") else None)
    return {"matplotlib": matplotlib.__version__, "cjk_font": cjk, "paper_background": "white",
            "python": sys.version.split()[0], "python_isolated": bool(sys.flags.isolated),
            "backend": matplotlib.get_backend(), "render_seconds": perf_counter()-started}


def _write_html(payload, folder, tables):
    assets = folder / "assets"
    assets.mkdir()
    shutil.copyfile(RESOURCES / "vendor" / "plotly.min.js", assets / "plotly.min.js")
    shutil.copyfile(RESOURCES / "profile.js", assets / "profile.js")
    (assets / "standalone.js").write_text("window.GRPR_STANDALONE=true;\n", encoding="utf-8")
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    def table(headers, rows):
        return "<table><thead><tr>" + "".join("<th>"+html.escape(str(v))+"</th>" for v in headers) + "</tr></thead><tbody>" + "".join(
            "<tr>" + "".join("<td>"+html.escape(str(v) if v is not None else "—")+"</td>" for v in row) + "</tr>" for row in rows) + "</tbody></table>"
    caption = "Data and provenance" if payload["language"] == "en" else "数据与来源"
    document = '''<!doctype html><html><head><meta charset="utf-8"><title>GaussianReadPro</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' 'unsafe-eval'; style-src 'unsafe-inline'; img-src data: blob:; worker-src blob:; connect-src 'none'">
<style>body{margin:0;background:var(--plot-background,#FCFAFF);color:var(--plot-foreground,#292137);font:14px 'Segoe UI','Microsoft YaHei',sans-serif}header{padding:12px;background:var(--plot-surface,#FFFFFF)}button{padding:8px;margin-right:8px;background:var(--plot-surface,#FFFFFF);color:inherit;border:1px solid var(--plot-border,#D8CBE5);border-radius:8px}button:focus-visible{outline:2px solid currentColor;outline-offset:2px}#plot{height:80vh;min-height:400px}#notice{padding:4px 20px;color:var(--plot-warning,#875017)}details{padding:18px;overflow:auto}td,th{border-bottom:1px solid var(--plot-border,#D8CBE5);padding:7px;white-space:pre-wrap;max-width:500px}table{border-collapse:collapse}</style>
<script src="assets/standalone.js"></script><script src="assets/plotly.min.js"></script><script src="assets/profile.js" defer></script></head><body>
<header><b>GaussianReadPro</b> <button id="view-toggle">2D / 3D</button><button id="reset">Reset / 重置</button></header><div id="notice"></div><div id="plot"></div>'''
    document += '<script id="payload" type="application/json">' + raw + "</script>"
    document += "<details><summary>" + caption + "</summary>" + table(tables[0], tables[1]) + table(tables[2], tables[3]) + "</details></body></html>"
    (folder / "profile.html").write_text(document, encoding="utf-8")


def export_plot_bundle(payload, destination, format, *, raster=None):
    if format not in ("png", "svg", "pdf", "html"):
        raise StorageError("unsupported_plot_format")
    if payload["view"] == "3d" and format in ("svg", "pdf"):
        raise StorageError("three_dimensional_vector_unsupported")
    if not any(p["valid"] and p["value"] is not None for path in payload["paths"] if path["visible"] for p in path["points"]):
        raise StorageError("plot_has_no_valid_values")
    destination = Path(destination).resolve()
    if destination.exists():
        raise StorageError("destination_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".grpr-export-", dir=destination.parent))
    published = False
    try:
        tables = _tables(payload, staging)
        (staging / "plot.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        info = {}
        if format == "html":
            _write_html(payload, staging, tables)
        elif payload["view"] == "3d":
            if not raster or len(raster) > 32*1024*1024:
                raise StorageError("three_dimensional_capture_required")
            from PIL import Image
            with Image.open(io.BytesIO(raster)) as im:
                if im.format != "PNG" or im.size != (1600, 1000):
                    raise StorageError("invalid_plot_raster")
                im.verify()
            (staging / "profile.png").write_bytes(raster)
            info = {"raster_source": "Plotly.toImage", "size": [1600, 1000]}
        else:
            info = draw_2d(payload, staging / ("profile." + format))
        files = {path.relative_to(staging).as_posix(): {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
                 for path in staging.rglob("*") if path.is_file()}
        manifest = {"format_version": 1, "primary": "profile."+format, "project_id": payload["project_id"],
                    "revision": payload["revision"], "view": payload["view"], "unit": payload["unit"],
                    "csv_encoding": "utf-8-sig", "csv_delimiter": ",", "text_formula_escape": "apostrophe; exact original in plot.json",
                    "files": files, **info}
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        destination.mkdir(exist_ok=False)
        published = True
        for child in staging.iterdir():
            # Publish with destination permissions, not the private staging directory ACL.
            if child.is_dir():
                shutil.copytree(child, destination / child.name)
            else:
                shutil.copyfile(child, destination / child.name)
        return destination
    except BaseException:
        if published:
            shutil.rmtree(destination)
        raise
    finally:
        shutil.rmtree(staging)
