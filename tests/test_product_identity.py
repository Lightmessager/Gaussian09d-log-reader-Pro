"""Renaming the product must preserve existing local work."""
from pathlib import Path
import tomllib

from gaussianreadpro import APP_NAME, VERSION_LABEL, __version__
from gaussianreadpro.storage.preferences import LocalPreferences, default_recovery_directory
from test_workbench import app, workbench, settle, write_logs


def test_static_helper_failure_returns_diagnostics_without_dialog(tmp_path, monkeypatch):
    import json
    import sys
    from gaussianreadpro.__main__ import main
    from gaussianreadpro.services import static_plot_worker
    request = tmp_path / "request.json"
    monkeypatch.setattr(sys, "argv", ["app", "--render-static", str(request), str(tmp_path / "out.svg")])
    def fail(arguments):
        raise ModuleNotFoundError("injected missing SVG backend")
    monkeypatch.setattr(static_plot_worker, "main", fail)
    assert main() == 1
    assert json.loads(Path(str(request) + ".result.json").read_text())["error"] == "ModuleNotFoundError: injected missing SVG backend"


def test_static_failure_diagnostic_reaches_ui(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import pytest
    from gaussianreadpro.services import plot_export
    from gaussianreadpro.storage import StorageError
    def fail(arguments, **kwargs):
        request = Path(arguments[-2])
        Path(str(request) + ".result.json").write_text(json.dumps({"error": "injected SVG failure"}))
        return SimpleNamespace(returncode=1, stderr=b"")
    monkeypatch.setattr(plot_export.subprocess, "run", fail)
    with pytest.raises(StorageError, match="injected SVG failure"):
        plot_export.draw_2d({}, tmp_path / "out.svg")
    assert not list(tmp_path.glob(".grpr-*"))


def test_identity_agrees_with_distribution_metadata():
    metadata=tomllib.loads((Path(__file__).resolve().parents[1]/"pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert APP_NAME=="GaussianReaderPro" and VERSION_LABEL=="2.0.0" and __version__==metadata["version"]=="2.0.0"
    assert "gaussianreaderpro" in metadata["scripts"]


def test_renamed_application_keeps_existing_preferences_and_recovery(app):
    original=(app.organizationName(),app.applicationName())
    try:
        app.setOrganizationName("GaussianReadPro");app.setApplicationName("GaussianReadPro")
        old=default_recovery_directory()
        app.setOrganizationName(APP_NAME);app.setApplicationName(APP_NAME)
        assert default_recovery_directory()==old
        preferences=LocalPreferences()
        assert preferences.settings.organizationName()=="GaussianReadPro"
        assert preferences.settings.applicationName()=="GaussianReadPro"
    finally:
        app.setOrganizationName(original[0]);app.setApplicationName(original[1])


def test_expression_save_footer_fits_840_with_long_project_path(app,workbench,tmp_path):
    from gaussianreadpro.ui.expression_editor import ExpressionDialog
    from PySide6.QtCore import QPoint
    window,controller=workbench
    controller.import_files(write_logs(tmp_path/"logs"));settle(app,controller)
    editor=ExpressionDialog(controller,node_id=controller.project.nodes[0].id,language="en",parent=window)
    editor.save_status.setText("Saved to: D:/Research projects/"+"long-project-directory/"*5+"reaction.grproj")
    editor.resize(840,680);editor.show();app.processEvents()
    assert editor.width()<=840 and editor.height()<=680
    for button in (editor.save_button,editor.save_close_button,editor.close_button):
        point=button.mapTo(editor,QPoint(0,0))
        assert 0<=point.x() and point.x()+button.width()<=editor.width()
        assert 0<=point.y() and point.y()+button.height()<=editor.height()
    editor._dirty=False;editor.timer.stop();editor.reject()
