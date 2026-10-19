"""Rendering contract built exclusively from current, revision-matched results."""
from dataclasses import dataclass
from collections.abc import Mapping
import json
import math
import re

from .expressions import render_expression
from .models import snapshot_to_dict
from .units import from_hartree

UNITS = {"hartree": "Eh", "kcal_mol": "kcal/mol", "kj_mol": "kJ/mol"}


@dataclass(frozen=True)
class PlotPoint:
    entry_id: str
    node_id: str
    label: str
    role: str
    x: int
    energy_hartree: float | None
    absolute_hartree: float | None
    relative_hartree: float | None
    reference_hartree: float | None
    values: tuple
    expression: str
    dependencies: tuple
    reference_dependencies: tuple
    diagnostics: tuple[str, ...]
    valid: bool
    starred_species: tuple[str, ...] = ()
    predecessor_entry_id: str | None = None
    missing_transition_state: bool = False
    predecessor_entry_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlotPath:
    id: str
    label: str
    kind: str
    mode: str
    unit: str
    color: str
    visible: bool
    reference: str
    reference_signature: str
    points: tuple[PlotPoint, ...]
    diagnostics: tuple[str, ...]
    reference_origin: str = "expression"


@dataclass(frozen=True)
class PlotSpec:
    project_id: str
    revision: int
    constants_version: str
    paths: tuple[PlotPath, ...]
    sources: tuple = ()
    protocol_version: int = 2
    jobs: tuple = ()


def _signature(expression):
    if expression is None:
        return ""
    def clean(value):
        if isinstance(value, Mapping):
            return {k: clean(v) for k, v in value.items() if k != "span"}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value
    return json.dumps([clean(expression.ast), expression.purpose.value, expression.combination_mode.value,
                       expression.draft_text, snapshot_to_dict(expression.draft_error)], sort_keys=True, ensure_ascii=False)


def build_plot_spec(project, results):
    results = {r.path_id: r for r in results}
    nodes = {n.id: n for n in project.nodes}
    try:
        from .reaction_network import read_reaction_network
        network = read_reaction_network(project)
        starred = {item["id"]: item["name"] for item in network["species"] if item["starred"]}
        reference_origins = {item["path_id"]: item["zero_point"]["kind"]
                             for item in network["path_reactions"] if not item["historical"]}
        predecessor_entries = {}
        missing_entries = set()
        for reaction in network["path_reactions"]:
            if reaction["historical"]:
                continue
            stage_entries = {stage["id"]: stage["entry_id"] for stage in reaction["stages"]}
            predecessor_entries.update({stage["entry_id"]: tuple(stage_entries[parent]
                for parent in stage["predecessor_stage_ids"] if parent in stage_entries)
                for stage in reaction["stages"] if stage["entry_id"]})
            missing_entries.update(stage["entry_id"] for stage in reaction["stages"]
                                   if stage.get("missing") and stage["entry_id"])
        star_links = {link["node_id"]: tuple(starred[identifier] for identifier in link["species_ids"]
            if identifier in starred) for link in network["node_links"] if not link["historical"]}
    except ValueError:
        star_links = {}
        reference_origins = {}
        predecessor_entries = {}
        missing_entries = set()
    paths = []
    for path in project.paths:
        result = results.get(path.id)
        if result and (result.project_id != project.id or result.revision != project.revision):
            raise ValueError("PlotSpec requires current project/revision results")
        by_entry = {r.entry_id: r for r in result.nodes} if result else {}
        points = []
        for entry in path.entries:
            node, value = nodes[entry.node_id], by_entry.get(entry.id)
            valid = bool(value and value.valid and value.display_value is not None)
            if value and value.revision != project.revision:
                raise ValueError("PlotSpec rejects stale node results")
            energy = (value.absolute_hartree if path.calculation_mode == "absolute" else value.relative_hartree) if valid else None
            conversions = []
            if energy is not None:
                for unit in UNITS:
                    try:
                        converted = from_hartree(energy, unit)
                    except (ValueError, OverflowError):
                        converted = None
                    conversions.append((unit, converted))
            points.append(PlotPoint(entry.id, node.id, node.label, node.role.value, entry.position, energy,
                value.absolute_hartree if value else None, value.relative_hartree if value else None,
                value.reference_hartree if value else None,
                tuple(conversions),
                node.expression.draft_text if node.expression.draft_text is not None else render_expression(node.expression, project.alias_bindings),
                tuple(value.dependencies) if value else (), tuple(value.reference_dependencies) if value else (),
                tuple(d.code for d in value.diagnostics) if value else ("awaiting_current_result",), valid,
                star_links.get(node.id, ()),
                (predecessor_entries.get(entry.id) or (None,))[0], entry.id in missing_entries,
                predecessor_entries.get(entry.id, ())))
        color = path.color if re.fullmatch(r"#[0-9a-fA-F]{6}", path.color or "") else "#5367b8"
        paths.append(PlotPath(path.id, path.label, path.energy_kind.value, path.calculation_mode.value,
            path.unit.value, color, path.visible,
            (path.reference_expression.draft_text if path.reference_expression.draft_text is not None else
             render_expression(path.reference_expression, project.alias_bindings)) if path.reference_expression else "",
            _signature(path.reference_expression), tuple(points), tuple(d.code for d in result.diagnostics) if result else (),
            reference_origins.get(path.id, "expression")))
    sources = tuple((s.id, s.original_name, s.original_path, s.sha256, s.parser_version) for s in project.source_files)
    jobs = tuple((job.id, source.id, job.ordinal + 1) for source in project.source_files for job in source.jobs)
    return PlotSpec(project.id, project.revision, project.unit_constants_version, tuple(paths), sources, jobs=jobs)


def clean_view_state(raw, spec):
    """Allowlisted JSON from UI/JS; never persist arbitrary relayout keys."""
    if not isinstance(raw, Mapping):
        return {}
    paths = {p.id for p in spec.paths}
    entries = {v.entry_id for p in spec.paths for v in p.points}
    def numeric(v, limit=1e12):
        return type(v) in (float, int) and math.isfinite(v) and abs(v) <= limit
    def viewport(value):
        result = {}
        if not isinstance(value, Mapping):
            return result
        for key in ("x_range", "y_range"):
            pair = value.get(key)
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(numeric(v) for v in pair) and pair[0] < pair[1]:
                result[key] = list(pair)
        camera = value.get("camera")
        if isinstance(camera, Mapping):
            camera = {key: {axis: float(val[axis]) for axis in ("x", "y", "z")} for key, val in camera.items()
                      if key in ("eye", "center", "up") and isinstance(val, Mapping)
                      and all(numeric(val.get(axis), 100) for axis in ("x", "y", "z"))}
            if camera:
                result["camera"] = camera
        three = value.get("three_v1")
        if isinstance(three, Mapping) and type(three.get("version")) is int and three["version"] == 1 and three.get("projection") == "orthographic":
            vectors = [three.get(key) for key in ("position", "target", "up")]
            if all(isinstance(v, (list, tuple)) and len(v) == 3 and all(numeric(x, 1000) for x in v) for v in vectors) and numeric(three.get("zoom"), 12) and .15 <= three["zoom"] <= 12:
                position, target, up = vectors
                direction = [a - b for a, b in zip(position, target)]
                distance = math.sqrt(sum(x*x for x in direction))
                up_length = math.sqrt(sum(x*x for x in up))
                cross = [direction[1]*up[2]-direction[2]*up[1], direction[2]*up[0]-direction[0]*up[2], direction[0]*up[1]-direction[1]*up[0]]
                if distance >= .01 and up_length >= .01 and math.sqrt(sum(x*x for x in cross)) / distance / up_length >= .001:
                    result["three_v1"] = {"version": 1, "projection": "orthographic", "position": list(position), "target": list(target), "up": list(up), "zoom": three["zoom"]}
                    if three.get("migrated_from") == "plotly-v1":
                        result["three_v1"]["migrated_from"] = "plotly-v1"
        return result
    result = {}
    if raw.get("mode") in ("2d", "3d"):
        result["mode"] = raw["mode"]
    if type(raw.get("compare")) is bool:
        result["compare"] = raw["compare"]
    for key in ("details_visible", "details_drawer_open"):
        if type(raw.get(key)) is bool:
            result[key] = raw[key]
    identities = {(p.id, n.entry_id) for p in spec.paths for n in p.points}
    if isinstance(raw.get("selected_points"), (list, tuple)):
        result["selected_points"] = [list(pair) for pair in raw["selected_points"][-2:]
            if isinstance(pair, (list, tuple)) and len(pair) == 2
            and all(isinstance(x, str) for x in pair) and tuple(pair) in identities]
    if raw.get("theme") in ("auto", "light", "dark"):
        result["theme"] = raw["theme"]
    if isinstance(raw.get("hidden_paths"), (tuple, list)):
        result["hidden_paths"] = [p for p in raw["hidden_paths"] if isinstance(p, str) and p in paths][:len(paths)]
    offsets = raw.get("label_offsets")
    if isinstance(offsets, Mapping):
        result["label_offsets"] = {key: list(pair) for key, pair in offsets.items() if key in entries
            and isinstance(pair, (tuple, list)) and len(pair) == 2 and all(numeric(v, 500) for v in pair)}
    views = raw.get("viewports")
    if isinstance(views, Mapping):
        result["viewports"] = {key: viewport(val) for key, val in list(views.items())[:100]
                               if isinstance(key, str) and len(key) < 300}
    if isinstance(raw.get("step_pairs"), (list, tuple)):
        identities = {(p.id, n.entry_id) for p in spec.paths for n in p.points}
        pairs, used = [], set()
        for group in raw["step_pairs"][:1000]:
            if not isinstance(group, (list, tuple)) or not 2 <= len(group) <= len(paths):
                continue
            if not all(isinstance(k, (list, tuple)) and len(k) == 2 and all(isinstance(x,str) for x in k) for k in group):
                continue
            keys = [tuple(k) for k in group]
            if len({k[0] for k in keys}) == len(keys) and all(k in identities and k not in used for k in keys):
                pairs.append([list(k) for k in keys])
                used.update(keys)
        result["step_pairs"] = pairs
    barrier = raw.get("barrier")
    if "barrier" in raw and barrier is None:
        result["barrier"] = None
    if isinstance(barrier, Mapping) and barrier.get("path_id") in paths:
        if all(barrier.get(key) in entries for key in ("from_entry", "to_entry")):
            result["barrier"] = {key: barrier[key] for key in ("path_id", "from_entry", "to_entry")}
            offset = barrier.get("offset")
            if isinstance(offset, (list, tuple)) and len(offset) == 2 and all(numeric(v, 500) for v in offset):
                result["barrier"]["offset"] = list(offset)
    return result


def compare_points(spec, keys, unit):
    if len(keys) != 2:
        return None
    selected = []
    for path_id, entry_id in keys:
        path = next((p for p in spec.paths if p.id == path_id), None)
        point = next((p for p in path.points if p.entry_id == entry_id), None) if path else None
        if point is None or not point.valid:
            return None
        selected.append((path, point))
    (a, first), (b, second) = selected
    if a.kind != b.kind or a.mode != b.mode:
        return None
    if a.id != b.id and (a.mode == "direct_difference" or a.reference_signature != b.reference_signature):
        return None
    try:
        difference = from_hartree(second.energy_hartree - first.energy_hartree, unit)
    except (ValueError, OverflowError):
        return None
    return {"value": difference,
            "first": first.label, "second": second.label,
            "barrier_eligible": a.id == b.id and second.role == "transition_state" and
                (first.entry_id in second.predecessor_entry_ids if second.predecessor_entry_ids
                 else second.predecessor_entry_id == first.entry_id if second.predecessor_entry_id
                 else second.x == first.x + 1),
            "path_id": a.id, "from_entry": first.entry_id, "to_entry": second.entry_id}


def visual_curve_runs(points, samples=24, edges=None):
    """Display-only, non-overshooting connections. Never used for values, hover or barriers."""
    if edges is not None:
        by_id = {point[0]: (point[1], point[2]) for point in points if point is not None}
        runs = []
        for source, target in edges:
            if source in by_id and target in by_id:
                runs.extend(visual_curve_runs([by_id[source], by_id[target]], samples))
        return runs
    runs, run, previous = [], [], None
    for point in points:
        if point is None:
            if run:
                runs.append(run)
            run, previous = [], None
            continue
        x, value = point
        if previous is None:
            run.append([x, value])
        else:
            for index in range(1, samples + 1):
                t = index / samples
                blend = t*t*(3-2*t)
                run.append([(1-t)*previous[0]+t*x, (1-blend)*previous[1]+blend*value])
        previous = point
    if run:
        runs.append(run)
    return runs


def plot_payload(spec, active_path_id, *, compare=False, state=None, language="zh_CN", dark=False, selected=()):
    """Shared coordinates, annotation offsets and labels for every rendering backend."""
    state = clean_view_state(state or {}, spec)
    active = next((p for p in spec.paths if p.id == active_path_id), None)
    if active is None:
        active = spec.paths[0] if spec.paths else None
    en = language == "en"
    mode = active.mode if active else "relative"
    kind = active.kind if active else "gibbs_total"
    unit = active.unit if active else "kcal_mol"
    names = {"scf": ("SCF 电子能", "SCF electronic energy"), "gibbs_total": ("Gibbs 自由能", "Gibbs free energy"),
             "gibbs_correction": ("Gibbs 热校正", "Gibbs thermal correction")}
    prefix = ("绝对" if not en else "Absolute ") if mode == "absolute" else ("直接差值 · " if not en else "Direct difference · ") if mode == "direct_difference" else ("相对" if not en else "Relative ")
    energy_label = prefix + names[kind][int(en)]
    if kind == "gibbs_correction" and mode != "absolute":
        energy_label += " difference" if en else "差"
    chosen = [p for p in spec.paths if active and (p.id == active.id or compare and p.kind == kind and p.mode == mode)]
    warnings = []
    if compare and active and any(p.kind != kind or p.mode != mode for p in spec.paths):
        warnings.append("Different energy types or modes are excluded." if en else "已排除能量类型或计算模式不同的路径。")
    if compare and active and any(p.id != active.id and (mode == "direct_difference" or p.reference_signature != active.reference_signature) for p in chosen):
        warnings.append("References differ; each path uses its own zero. Cross-path differences are disabled." if en else "参考体系不同：各路径使用自己的零点，已禁用跨路径能量差。")
    hidden = set(state.get("hidden_paths", []))
    levels = [value for p in chosen if p.visible and p.id not in hidden for point in p.points if point.valid
              if (value := dict(point.values).get(unit)) is not None]
    span = max(levels) - min(levels) if levels else 1.
    span = max(span, .002 if unit == "hartree" else .5)
    paths, occupied = [], []
    for category, path in enumerate(chosen):
        points = []
        for point in path.points:
            value = dict(point.values).get(unit) if point.valid else None
            offset = [0., -32.]
            if value is not None and path.visible and path.id not in hidden:
                for x, y, dy in occupied:
                    if abs(point.x - x) < .45 and abs(value - y) / span < .12 and abs(offset[1] - dy) < 44:
                        # Put matching labels on opposite sides of nearby points.
                        # Moving both annotations upward made their text boxes collide
                        # when two paths had a small but nonzero energy difference.
                        offset[1] = 68.0 if dy < 0 else -68.0
            offset = state.get("label_offsets", {}).get(point.entry_id, offset)
            if value is not None and path.visible and path.id not in hidden:
                occupied.append((point.x, value, offset[1]))
            data = snapshot_to_dict(point)
            data.update(value=value, label_offset=offset, selected=(path.id, point.entry_id) in selected)
            compact = value is not None and (abs(value) > 1e6 or 0 < abs(value) < (1e-6 if unit == "hartree" else 1e-3))
            data["value_label"] = format(value, "+.6g" if compact else "+.6f" if unit == "hartree" else "+.3f") if value is not None else "—"
            data["label_short"] = point.label if len(point.label) <= 70 else point.label[:67] + "…"
            if point.valid and value is None:
                data["valid"] = False
                data["diagnostics"].append("unit_conversion_unavailable")
            points.append(data)
        paths.append({"id": path.id, "label": path.label, "color": path.color, "category": category,
                      "visible": path.visible and path.id not in hidden, "reference": path.reference,
                      "reference_origin": path.reference_origin,
                      "reference_signature": path.reference_signature,
                      "diagnostics": list(path.diagnostics), "points": points,
                      "curve_runs": (visual_curve_runs(
                          [(p["entry_id"], p["x"], p["value"]) if p["valid"] and p["value"] is not None else None for p in points],
                          edges=[(parent, point["entry_id"]) for point in points
                                 for parent in point.get("predecessor_entry_ids", [])])
                          if any(point.get("predecessor_entry_ids") for point in points) else
                          visual_curve_runs([(p["x"], p["value"]) if p["valid"] and p["value"] is not None else None for p in points]))})
    if state.get("mode") == "3d" and sum(bool(path["visible"]) for path in paths) <= 1:
        warnings.append("3D depth encodes path category; comparison is more informative." if en else
                        "三维深度轴表示路径类别；比较多条路径时更有帮助。")
    context = f"{spec.project_id}/{active.id if active else 'empty'}/{unit}/{kind}/{mode}"
    barrier = state.get("barrier", {})
    marker = None
    if barrier:
        pair = compare_points(spec, [(barrier["path_id"], barrier["from_entry"]), (barrier["path_id"], barrier["to_entry"])], unit)
        if pair and pair["barrier_eligible"]:
            marker = {**pair, "label_offset": list(barrier.get("offset", [72, 36]))}
    barrier_label = {"scf": "ΔE‡", "gibbs_total": "ΔG‡", "gibbs_correction": "ΔGcorr‡"}[kind]
    if mode == "direct_difference":
        barrier_label += " direct" if en else "（直接差值）"
    actual_theme = state.get("theme", "auto")
    dark = actual_theme == "dark" or actual_theme == "auto" and dark
    steps = sorted({point.x for path in chosen for point in path.points})
    default_range = [min(levels) - span*.15, max(levels) + span*.30] if levels else [-1., 1.]
    return {"protocol_version": 2, "project_id": spec.project_id, "revision": spec.revision,
        "constants_version": spec.constants_version, "active_path_id": active.id if active else None,
        "view": state.get("mode", "2d"), "unit": unit, "unit_label": UNITS[unit], "energy_label": energy_label,
        "mode": mode, "kind": kind, "language": language, "dark": bool(dark), "context": context,
        "viewport": state.get("viewports", {}).get(context + "/" + state.get("mode", "2d"), {}),
        "viewports": state.get("viewports", {}),
        "details_visible": state.get("details_visible", True),
        "details_drawer_open": state.get("details_drawer_open", False),
        "warnings": warnings, "paths": paths, "barrier": marker, "sources": list(spec.sources), "jobs": list(spec.jobs),
        "renderer_capabilities": ["three_v1", "plotly-v1"],
        "barrier_label": barrier_label,
        "ticks": steps, "tick_labels": [str(v+1) for v in steps],
        "default_y_range": default_range,
        "default_camera": {"eye": {"x": -1.1, "y": -1.9, "z": 1.05}, "center": {"x": 0, "y": 0, "z": 0}, "up": {"x": 0, "y": 0, "z": 1}},
        "text": {"step": "Reaction step" if en else "反应步骤", "category": "Path category" if en else "路径类别",
                 "guide": "Curves and ribbons are visual guides; values are at nodes" if en else "曲线与光带仅作视觉引导，数值以节点为准",
                 "reference": "Reference" if en else "参考体系", "absolute": "System energy / Eh" if en else "体系能量 / Eh",
                 "relative": "Energy difference / Eh" if en else "能量差 / Eh", "expression": "Expression" if en else "表达式",
                 "path": "Path" if en else "路径", "node": "Node" if en else "节点",
                 "source": "Source" if en else "来源", "job": "Job" if en else "作业",
                 "line": "Line" if en else "行",
                 "zero_plane": "Zero-energy reference plane" if en else "零能量参考平面",
                 "empty": "No valid current values. Check references, drafts and sources." if en else "无当前有效结果，请检查参考、草稿与来源。",
                 "webgl": "WebGL unavailable; showing 2D." if en else "WebGL 不可用，已切换到二维。"}}
