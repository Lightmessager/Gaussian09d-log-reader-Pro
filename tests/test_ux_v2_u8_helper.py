from pathlib import Path

from gaussianreadpro.validation_ux_v2_u8 import _save_dialog_target


def test_save_dialog_target_is_scoped_and_restores_original():
    class FileDialog:
        @staticmethod
        def getSaveFileName(*args, **kwargs):
            return ("original.grproj", "Project files (*.grproj)")

    original = FileDialog.getSaveFileName
    target = Path("C:/scratch/U8 Frozen Project.grproj")

    with _save_dialog_target(FileDialog, target):
        assert FileDialog.getSaveFileName(None, "Save project") == (str(target), "")

    assert FileDialog.getSaveFileName is original
    assert FileDialog.getSaveFileName(None, "Save project") == (
        "original.grproj", "Project files (*.grproj)")
