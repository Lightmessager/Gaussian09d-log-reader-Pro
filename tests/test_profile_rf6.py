"""RF6 persistence boundaries and portable Three export contracts."""
from dataclasses import replace
import io
import json

import pytest
from PIL import Image

from gaussianreadpro.core.plot_spec import clean_view_state, plot_payload
from gaussianreadpro.core.plot_spec import build_plot_spec
from gaussianreadpro.core import calculate_path
from gaussianreadpro.core.models import new_id
from gaussianreadpro.services.plot_export import export_plot_bundle, assert_current_payload
from gaussianreadpro.storage import ProjectRepository, StorageError
from test_plot_spec_export import example
from test_workbench import app, workbench


def test_rf6_state_roundtrip_keeps_independent_views_and_selection(tmp_path):
    project, spec, payload = example(tmp_path)
    path = project.paths[0]
    camera = {"version": 1, "projection": "orthographic", "position": [7, -9, 6],
              "target": [0, 0, 0], "up": [0, 0, 1], "zoom": 1.7}
    state = clean_view_state({"mode": "3d", "compare": True, "hidden_paths": [path.id],
        "details_visible": False, "details_drawer_open": True,
        "selected_points": [[path.id, path.entries[1].id]],
        "viewports": {payload["context"] + "/2d": {"x_range": [-1, 5], "y_range": [-20, 30]},
                      payload["context"] + "/3d": {"three_v1": camera}}}, spec)
    destination = tmp_path / "state.grproj"
    with ProjectRepository(destination, create=True) as repo:
        repo.save(replace(project, plot_state=state))
    before = destination.read_bytes()
    with ProjectRepository(destination, read_only=True) as repo:
        restored = repo.load()
    assert clean_view_state(restored.plot_state, spec) == state
    assert destination.read_bytes() == before
    assert plot_payload(spec, path.id, state=restored.plot_state)["viewport"]["three_v1"] == camera
    rejected = clean_view_state({"details_visible": 1, "details_drawer_open": "yes",
        "selected_points": [["unknown", path.entries[0].id], [path.id, "unknown"]]}, spec)
    assert rejected == {"selected_points": []}


def test_offline_html_carries_three_runtime_licenses_and_no_qt_dependency(tmp_path):
    _, _, payload = example(tmp_path)
    payload["view"] = "3d"
    folder = export_plot_bundle(payload, tmp_path / "offline", "html")
    document = (folder / "profile.html").read_text(encoding="utf-8")
    bootstrap = (folder / "assets/standalone.js").read_text(encoding="utf-8")
    assert "qwebchannel.js" not in document
    assert 'src="assets/standalone.js"' in document and "data:" in document
    assert "data:text/javascript;base64," in bootstrap and "GRPR_MODULES" in bootstrap
    assert (folder / "assets/vendor/THREE-LICENSE.txt").is_file()
    assert (folder / "assets/vendor/three.module.min.js").is_file()
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["renderer"] == "Three.js r170"
    assert "assets/vendor/THREE-LICENSE.txt" in manifest["files"]


def test_offline_reveal_paths_are_audited_and_rechecked_even_in_single_view(tmp_path):
    import csv
    project, _, _ = example(tmp_path)
    first = project.paths[0]
    second = replace(first, id=new_id(), label="Other path", entries=tuple(replace(e, id=new_id()) for e in first.entries))
    project = replace(project, paths=(first, second))
    spec = build_plot_spec(project, [calculate_path(project, p.id) for p in project.paths])
    payload = plot_payload(spec, first.id, compare=False, language="en")
    payload["offline_paths"] = plot_payload(spec, first.id, compare=True, language="en")["paths"]
    folder = export_plot_bundle(payload, tmp_path / "single-with-comparison", "html")
    with (folder / "data.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 8 and {r["Path ID"] for r in rows} == {first.id, second.id}
    changed = replace(spec.paths[1], points=(replace(spec.paths[1].points[0], valid=False), *spec.paths[1].points[1:]))
    with pytest.raises(StorageError, match="plot_sources_changed"):
        assert_current_payload(payload, replace(spec, paths=(spec.paths[0], changed)))


def test_three_png_manifest_names_actual_renderer_and_rejects_wrong_size(tmp_path):
    _, _, payload = example(tmp_path)
    payload["view"] = "3d"
    def png(size):
        stream = io.BytesIO()
        Image.new("RGB", size, "#0D0C19").save(stream, "PNG")
        return stream.getvalue()
    folder = export_plot_bundle(payload, tmp_path / "chart", "png", raster=png((1600, 1000)))
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["raster_source"] == "Three.js ProfileRenderer.capture"
    assert manifest["export_scope"] == "chart"
    with pytest.raises(StorageError, match="invalid_plot_raster"):
        export_plot_bundle(payload, tmp_path / "bad", "png", raster=png((800, 600)))
    assert not (tmp_path / "bad").exists()
    payload["export_scope"] = "workbench"
    folder = export_plot_bundle(payload, tmp_path / "workbench", "png", raster=png((1200, 700)))
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["raster_source"] == "QtWebEngine QWidget.grab"
    assert manifest["size"] == [1200, 700]


def test_readonly_panel_details_and_selection_are_temporary(workbench, tmp_path):
    window, controller = workbench
    project, spec, _ = example(tmp_path / "readonly-source")
    path = project.paths[0]
    selected = [[path.id, path.entries[1].id]]
    state = {"mode": "3d", "details_visible": False, "selected_points": selected}
    controller.project = replace(project, plot_state=state)
    controller.plot_state = state.copy()
    controller.plot_spec = spec
    controller.read_only = True
    panel = window.profile
    panel.set_spec(spec, path.id)
    assert [list(pair) for pair in panel._selection] == selected
    panel.save_state(details_visible=True, selected_points=[])
    assert panel.state["details_visible"] is True and panel.state["selected_points"] == []
    assert controller.plot_state == state and controller.project.plot_state["details_visible"] is False
