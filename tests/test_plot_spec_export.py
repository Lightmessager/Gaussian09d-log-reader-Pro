"""S7 shared scientific values, event boundaries, portable exports and recovery."""
from dataclasses import replace
import csv
import hashlib
import json

import pytest

from gaussianreadpro.core import Project, calculate_path
from gaussianreadpro.core.models import new_id
from gaussianreadpro.core.expressions import compile_expression, edit_expression
from gaussianreadpro.core.plot_spec import build_plot_spec, clean_view_state, compare_points, plot_payload, visual_curve_runs
from gaussianreadpro.services.session import import_into
from gaussianreadpro.services.plot_export import export_plot_bundle, assert_current_payload
from gaussianreadpro.storage import ProjectRepository, StorageError
from test_workbench import app, workbench, settle, write_logs


def example(tmp_path):
    project, _ = import_into(Project(new_id()), write_logs(tmp_path / "logs"), lambda: False, lambda *_: None)
    path = replace(project.paths[0], reference_expression=project.nodes[0].expression)
    nodes = tuple(replace(n, role="transition_state") if i == 1 else n for i, n in enumerate(project.nodes))
    project = replace(project, paths=(path,), nodes=nodes)
    spec = build_plot_spec(project, [calculate_path(project, path.id)])
    return project, spec, plot_payload(spec, path.id, language="en")


def test_plot_spec_keeps_core_values_identity_order_and_sources(tmp_path):
    project, spec, payload = example(tmp_path)
    assert [p["value"] for p in payload["paths"][0]["points"]] == pytest.approx([0,15.0602273775,-5.0200757925,-15.6877368516])
    assert [p["entry_id"] for p in payload["paths"][0]["points"]] == [e.id for e in project.paths[0].entries]
    assert payload["paths"][0]["points"][1]["dependencies"][0]["source_line"] == 4
    assert payload["sources"][0][3] == project.source_files[0].sha256
    assert payload["barrier"] is None


def test_display_curve_preserves_nodes_bounds_and_missing_value_gaps():
    runs = visual_curve_runs([(0, 0), (1, 15), None, (3, -5), (4, -16)])
    assert len(runs) == 2
    assert runs[0][0] == [0, 0] and runs[0][-1] == [1, 15]
    assert runs[1][0] == [3, -5] and runs[1][-1] == [4, -16]
    assert all(0 <= value <= 15 and 0 <= step <= 1 for step, value in runs[0])
    assert all(-16 <= value <= -5 and 3 <= step <= 4 for step, value in runs[1])
    assert len(runs[0]) > 2


def test_decorative_curve_does_not_add_selectable_or_exported_scientific_points(tmp_path):
    project, spec, payload = example(tmp_path)
    path = payload["paths"][0]
    assert len(path["points"]) == len(project.paths[0].entries) == 4
    assert len(path["curve_runs"][0]) > len(path["points"])
    assert [p["value"] for p in path["points"]] == [dict(p.values)[payload["unit"]] for p in spec.paths[0].points]
    folder = export_plot_bundle(payload, tmp_path / "decorative", "html")
    with (folder / "data.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4 and [row["Entry ID"] for row in rows] == [p["entry_id"] for p in path["points"]]


def test_plot_spec_rejects_stale_path_and_node_revisions(tmp_path):
    project, _, _ = example(tmp_path)
    result = calculate_path(project, project.paths[0].id)
    with pytest.raises(ValueError, match="revision"):
        build_plot_spec(replace(project, revision=project.revision+1), [result])
    with pytest.raises(ValueError, match="stale node"):
        build_plot_spec(project, [replace(result, nodes=(replace(result.nodes[0], revision=99), *result.nodes[1:]))])


def test_invalid_draft_retains_gap_and_never_exports_last_value(tmp_path):
    project, _, _ = example(tmp_path)
    node = project.nodes[1]
    draft = edit_expression(node.expression, "@{TS1} + (", project.alias_bindings)
    project = replace(project, nodes=(project.nodes[0],replace(node,expression=draft),*project.nodes[2:]))
    spec = build_plot_spec(project, [calculate_path(project, project.paths[0].id)])
    payload = plot_payload(spec, project.paths[0].id, language="en")
    point = payload["paths"][0]["points"][1]
    assert not point["valid"] and point["value"] is None
    result = export_plot_bundle(payload, tmp_path / "partial", "html")
    with (result / "data.csv").open(encoding="utf-8-sig",newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[1]["Value"] == "" and rows[1]["Valid"] == "False"
    assert "@{TS1} + (" in rows[1]["Expression"]
    reference = edit_expression(project.paths[0].reference_expression, "@{R} + (", project.alias_bindings)
    project = replace(project, paths=(replace(project.paths[0], reference_expression=reference),))
    spec = build_plot_spec(project, [calculate_path(project, project.paths[0].id)])
    payload = plot_payload(spec, project.paths[0].id)
    assert payload["paths"][0]["reference"] == "@{R} + ("
    assert all(p["value"] is None for p in payload["paths"][0]["points"])


def test_comparison_normalizes_units_and_warns_for_distinct_references(tmp_path):
    project, _, _ = example(tmp_path)
    first = project.paths[0]
    second = replace(first,id=new_id(),label="different units",unit="kj_mol",entries=tuple(replace(e,id=new_id()) for e in first.entries))
    project = replace(project,paths=(first,second))
    spec = build_plot_spec(project,[calculate_path(project,p.id) for p in project.paths])
    payload = plot_payload(spec,first.id,compare=True)
    assert not payload["warnings"]
    assert payload["paths"][0]["points"][1]["value"] == payload["paths"][1]["points"][1]["value"]
    for index in range(4):
        assert abs(payload["paths"][0]["points"][index]["label_offset"][1] - payload["paths"][1]["points"][index]["label_offset"][1]) >= 44
    second = replace(second,reference_expression=project.nodes[2].expression)
    project = replace(project,paths=(first,second))
    spec = build_plot_spec(project,[calculate_path(project,p.id) for p in project.paths])
    assert plot_payload(spec,first.id,compare=True)["warnings"]
    assert compare_points(spec,[(first.id,first.entries[0].id),(second.id,second.entries[1].id)],"kcal_mol") is None


def test_chart_visual_style_tracks_glass_theme_and_keeps_paper_export_neutral():
    from gaussianreadpro.ui.profile_view import _visual_style
    light, dark = _visual_style(False), _visual_style(True)
    assert light["background"] != dark["background"]
    assert light["foreground"] != dark["foreground"]
    assert light["paper_background"] == dark["paper_background"] == "#FFFFFF"
    assert light["paper_selection"] == light["focus"] != light["paper_background"]
    assert light["focus"] == "#F4A06A" and dark["focus"] == "#EEA06F"


def test_barrier_requires_explicit_ts_and_predecessor_and_mark(tmp_path):
    project, spec, _ = example(tmp_path)
    path = project.paths[0]
    pair = compare_points(spec,[(path.id,path.entries[0].id),(path.id,path.entries[1].id)],"kcal_mol")
    assert pair["barrier_eligible"] and pair["value"] == pytest.approx(15.0602273775)
    state = {"barrier":{k:pair[k] for k in ("path_id","from_entry","to_entry")}}
    marked = plot_payload(spec,path.id,state=state)
    assert marked["barrier"]["value"] == pair["value"]
    assert marked["barrier_label"] == "ΔG‡"
    assert {"path", "node", "source", "job", "line"} <= marked["text"].keys()
    assert "Path" in plot_payload(spec,path.id,state=state,language="en")["text"]["path"]
    assert not compare_points(spec,[(path.id,path.entries[2].id),(path.id,path.entries[1].id)],"kcal_mol")["barrier_eligible"]


def test_barrier_notation_follows_energy_kind_and_direct_mode(tmp_path):
    from dataclasses import replace
    project, spec, _ = example(tmp_path)
    path = spec.paths[0]
    for kind, label in (("scf", "ΔE‡"), ("gibbs_total", "ΔG‡"), ("gibbs_correction", "ΔGcorr‡")):
        typed = replace(spec, paths=(replace(path, kind=kind),))
        assert plot_payload(typed, path.id)["barrier_label"] == label
    direct = replace(spec, paths=(replace(path, mode="direct_difference"),))
    assert plot_payload(direct, path.id, language="en")["barrier_label"] == "ΔG‡ direct"


def test_view_state_allowlist_rejects_nonfinite_and_scientific_edits(tmp_path):
    project, spec, _ = example(tmp_path)
    entry = project.paths[0].entries[0].id
    state = clean_view_state({"mode":"3d","energy":1234,"revision":100,"label_offsets":{entry:[20,-40],"unknown":[1,1]},
        "hidden_paths":[project.paths[0].id,"unknown"],"viewports":{"a":{"x_range":[float("nan"),4],"y_range":[False,2],
            "camera":{"eye":{"x":1.5,"y":1.5,"z":1.2},"evil":"code"}}}},spec)
    assert "energy" not in state and "revision" not in state
    assert state["label_offsets"] == {entry:[20,-40]}
    assert state["viewports"]["a"] == {"camera":{"eye":{"x":1.5,"y":1.5,"z":1.2}}}


@pytest.mark.parametrize("format",["png","svg","pdf","html"])
def test_plot_export_bundle_formats_have_audit_and_checksums(tmp_path,format):
    project,spec,payload=example(tmp_path)
    folder=export_plot_bundle(payload,tmp_path/format,format)
    primary=folder/("profile."+format)
    assert primary.stat().st_size>500
    manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    for name, info in manifest["files"].items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==info["sha256"]
    assert json.loads((folder/"plot.json").read_text(encoding="utf-8"))["paths"]==payload["paths"]
    assert (folder/"sources.csv").read_text(encoding="utf-8-sig").startswith("Path ID")
    if format=="png":
        from PIL import Image
        with Image.open(primary) as im: assert im.width>=1600
    if format=="pdf": assert primary.read_bytes().startswith(b"%PDF")
    if format=="html":
        text=primary.read_text(encoding="utf-8")
        assert 'src="assets/plotly.min.js"' in text and "cdn.plot.ly" not in text


def test_export_escapes_user_html_and_csv_formulas(tmp_path):
    project,_,_=example(tmp_path)
    malicious='</script><img src=x onerror="alert(1)">'
    project=replace(project,nodes=(replace(project.nodes[0],label=malicious),replace(project.nodes[1],label="=1+1"),*project.nodes[2:]))
    spec=build_plot_spec(project,[calculate_path(project,project.paths[0].id)])
    payload=plot_payload(spec,project.paths[0].id,language="en")
    folder=export_plot_bundle(payload,tmp_path/"safe","html")
    text=(folder/"profile.html").read_text(encoding="utf-8")
    assert malicious not in text and "\\u003c/script" in text
    with (folder/"data.csv").open(encoding="utf-8-sig",newline="") as stream: rows=list(csv.DictReader(stream))
    assert rows[1]["Label"]=="'=1+1"
    assert json.loads((folder/"plot.json").read_text(encoding="utf-8"))["paths"][0]["points"][1]["label"]=="=1+1"


def test_export_failure_is_atomic_and_existing_output_untouched(tmp_path,monkeypatch):
    from gaussianreadpro.services import plot_export
    _,_,payload=example(tmp_path)
    monkeypatch.setattr(plot_export,"draw_2d",lambda *args: (_ for _ in ()).throw(OSError("injected export failure")))
    with pytest.raises(OSError): export_plot_bundle(payload,tmp_path/"failed","png")
    assert not (tmp_path/"failed").exists() and not list(tmp_path.glob(".grpr-export-*"))
    existing=tmp_path/"existing"; existing.mkdir(); (existing/"keep").write_text("untouched")
    with pytest.raises(StorageError,match="destination_exists"): export_plot_bundle(payload,existing,"html")
    assert (existing/"keep").read_text()=="untouched"


def test_static_renderer_ignores_ambient_python_and_matplotlib_configuration(tmp_path, monkeypatch):
    from gaussianreadpro.services.plot_export import draw_2d
    _, _, payload = example(tmp_path)
    pollution = tmp_path / "external-python"
    pollution.mkdir()
    marker = pollution / "startup-ran"
    (pollution / "sitecustomize.py").write_text(
        "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n", encoding="utf-8")
    (pollution / "matplotlib.py").write_text("raise RuntimeError('external matplotlib shadow')\n", encoding="utf-8")
    rc = pollution / "matplotlibrc"
    rc.write_text("figure.facecolor: red\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(pollution))
    monkeypatch.setenv("MPLBACKEND", "invalid-external-backend")
    monkeypatch.setenv("MATPLOTLIBRC", str(rc))
    destination = tmp_path / "isolated.png"
    result = draw_2d(payload, destination)
    assert result["python_isolated"] and result["backend"].lower() == "agg"
    assert destination.is_file() and not marker.exists()
    from PIL import Image
    with Image.open(destination) as image:
        assert image.convert("RGB").getpixel((0, 0)) == (255, 255, 255)
    assert not list(tmp_path.glob(".grpr-*.render.json*"))


def test_native_renderer_failure_is_reported_without_retry_or_leftover_request(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from gaussianreadpro.services import plot_export
    _, _, payload = example(tmp_path)
    calls = []
    def crash(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return SimpleNamespace(returncode=3221225477, stderr=b"native startup failure")
    monkeypatch.setattr(plot_export.subprocess, "run", crash)
    with pytest.raises(StorageError, match="3221225477"):
        plot_export.draw_2d(payload, tmp_path / "failed.png")
    assert len(calls) == 1 and "-I" in calls[0][0]
    assert not (tmp_path / "failed.png").exists()
    assert not list(tmp_path.glob(".grpr-*.render.json*"))


def test_three_dimensional_export_never_claims_vector(tmp_path):
    project,spec,_=example(tmp_path)
    payload=plot_payload(spec,project.paths[0].id,state={"mode":"3d"})
    with pytest.raises(StorageError,match="vector"): export_plot_bundle(payload,tmp_path/"vector","svg")
    with pytest.raises(StorageError,match="capture_required"): export_plot_bundle(payload,tmp_path/"capture","png")
    assert not (tmp_path/"vector").exists() and not (tmp_path/"capture").exists()


def test_single_path_3d_payload_explains_category_depth(tmp_path):
    project, spec, _ = example(tmp_path)
    payload = plot_payload(spec, project.paths[0].id, state={"mode": "3d"}, language="en")
    assert any("depth encodes path category" in warning for warning in payload["warnings"])


def test_chart_events_are_guarded_and_plot_state_survives_save(app,workbench,tmp_path):
    window,controller=workbench
    controller.import_files(write_logs(tmp_path/"logs")); settle(app,controller)
    controller.reference_node(controller.project.nodes[0].id); settle(app,controller)
    panel=window.profile
    payload=panel.last_payload
    path=controller.selected_path
    event={"type":"view_state","project_id":controller.project.id,"revision":controller.project.revision,
           "render_id":payload["render_id"],"viewport":{"x_range":[-.6,3.6],"y_range":[-20,25]},"energy":900}
    panel.handle_event(json.dumps({**event,"revision":-1}))
    assert not controller._plot_dirty
    panel.handle_event(json.dumps(event))
    assert controller._plot_dirty
    destination=tmp_path/"view.grproj"
    controller.save(destination); settle(app,controller)
    with ProjectRepository(destination,read_only=True) as repository:
        assert repository.load().plot_state==controller.project.plot_state
    assert "energy" not in controller.project.plot_state
    assert controller.project.plot_state["viewports"][payload["context"]+"/2d"]["x_range"]==(-.6,3.6)


def test_chart_path_visibility_menu_is_bilingual_and_view_only(app, workbench, tmp_path):
    window, controller = workbench
    controller.import_files(write_logs(tmp_path / "logs")); settle(app, controller)
    controller.reference_node(controller.project.nodes[0].id); settle(app, controller)
    assert controller.edit_path("copy", label="Path B"); settle(app, controller)
    panel = window.profile
    path_ids = [path.id for path in controller.project.paths]
    assert set(panel._path_actions) == set(path_ids)
    assert panel.paths_button.isEnabled()
    nodes_before = controller.project.nodes
    paths_before = controller.project.paths
    values_before = [value.display_value for result in controller.results for value in result.nodes]

    # Toggling a path enables comparison and persists only a white-listed view option.
    hidden_id = path_ids[-1]
    panel._path_actions[hidden_id].trigger()
    settle(app, controller)
    assert controller.plot_state["compare"] is True
    assert controller.plot_state["hidden_paths"] == [hidden_id]
    assert controller.project.nodes == nodes_before and controller.project.paths == paths_before
    assert [value.display_value for result in controller.results for value in result.nodes] == values_before
    rendered = {path["id"]: path for path in panel.last_payload["paths"]}
    assert set(rendered) == set(path_ids) and not rendered[hidden_id]["visible"]

    panel.set_language("en")
    assert panel.paths_button.accessibleName().startswith("Path visibility")
    panel.set_language("zh_CN")
    assert panel.paths_button.accessibleName().startswith("路径显隐")
    panel.resize(700, 360); app.processEvents()
    assert panel.toolbar_panel.property("compact") is True
    assert not panel.paths_button.isHidden()


def test_export_rechecks_current_sources_before_writing(app,workbench,tmp_path):
    window,controller=workbench
    paths=write_logs(tmp_path/"logs")
    controller.import_files(paths); settle(app,controller)
    controller.reference_node(controller.project.nodes[0].id); settle(app,controller)
    paths[1].write_text("changed since chart was rendered")
    errors=[]
    controller.failed.connect(lambda code,detail:errors.append(code))
    assert window.profile.export_to(tmp_path/"outdated","png")
    settle(app,controller)
    assert errors==["plot_sources_changed"]
    assert not (tmp_path/"outdated").exists()


def test_independent_chart_theme_survives_native_fallback(app, workbench, tmp_path):
    window, controller = workbench
    controller.import_files(write_logs(tmp_path / "logs")); settle(app, controller)
    controller.reference_node(controller.project.nodes[0].id); settle(app, controller)
    window.theme_combo.setCurrentIndex(window.theme_combo.findData("light"))
    panel = window.profile
    original_colors = [path.color for path in controller.project.paths]
    panel.theme_combo.setCurrentIndex(panel.theme_combo.findData("dark"))
    assert panel.last_payload["dark"] and panel.native.dark
    panel.fallback("Test renderer failure")
    assert panel.stack.currentWidget() is panel.native
    assert panel.native.dark and app.property("glassTheme") == "light"
    panel.theme_combo.setCurrentIndex(panel.theme_combo.findData("light"))
    assert not panel.last_payload["dark"] and not panel.native.dark
    assert [path.color for path in controller.project.paths] == original_colors


def test_capture_timeout_restores_live_language_and_layout(app, workbench, tmp_path):
    from gaussianreadpro.ui.profile_view import PlotBridge
    window, controller = workbench
    controller.import_files(write_logs(tmp_path / "logs")); settle(app, controller)
    controller.reference_node(controller.project.nodes[0].id); settle(app, controller)
    panel = window.profile
    panel.save_state(mode="3d")
    panel.refresh()
    panel.bridge = PlotBridge(panel)
    panel.ready = True
    assert panel.export_to(tmp_path / "capture", "png", language="en")
    assert panel.last_payload["image_capture"] and panel.last_payload["language"] == "en"
    panel.abort_capture("Test capture timeout")
    assert panel._capture is None and not panel.capture_timer.isActive()
    assert not panel.last_payload.get("image_capture")
    assert panel.last_payload["language"] == panel.language == "zh_CN"
    assert panel.warning.text() == "Test capture timeout"
    panel.ready = False
