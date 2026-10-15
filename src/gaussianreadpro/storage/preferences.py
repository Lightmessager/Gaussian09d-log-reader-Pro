"""Local Qt preferences, kept separate from portable scientific projects."""
from pathlib import Path

from .codec import StorageError, dumps, loads

DEFAULTS = {"language": "system", "theme": "system", "recent_projects": [],
            "window_geometry": None, "default_export_directory": "",
            "visual_effects": "standard", "reduce_motion": False}
LEGACY_V1_KEYS = set(DEFAULTS) - {"visual_effects", "reduce_motion"}


class LocalPreferences:
    def __init__(self, path=None):
        # Core/storage imports remain usable without Qt; only this adapter requires it.
        from PySide6.QtCore import QSettings
        self._qt = QSettings
        self.settings = (QSettings(str(Path(path).resolve()), QSettings.Format.IniFormat) if path
                         else QSettings("GaussianReadPro", "GaussianReadPro"))
        self.settings.setAtomicSyncRequired(True)

    def load(self):
        text = self.settings.value("preferences_v1")
        if text is None:
            return dict(DEFAULTS, recent_projects=[])
        values = loads(text)
        # Only the complete historical v1 shape may omit these new local options.
        # Loading is read-only: persist the migration only on a successful save.
        if type(values) is dict and set(values) == LEGACY_V1_KEYS:
            values = dict(values, visual_effects="standard", reduce_motion=False)
        self._validate(values)
        return values

    def _validate(self, values):
        if (type(values) is not dict or set(values) != set(DEFAULTS)
                or values["language"] not in ("system", "zh_CN", "en")
                or values["theme"] not in ("system", "light", "dark")
                or type(values["visual_effects"]) is not str
                or values["visual_effects"] not in ("standard", "reduced")
                or type(values["reduce_motion"]) is not bool
                or type(values["recent_projects"]) is not list
                or len(values["recent_projects"]) > 20
                or any(type(p) is not str for p in values["recent_projects"])
                or values["window_geometry"] is not None and type(values["window_geometry"]) is not str
                or type(values["default_export_directory"]) is not str):
            raise StorageError("invalid_preferences")

    def save(self, **changes):
        values = self.load()
        values.update(changes)
        self._validate(values)
        self.settings.setValue("preferences_v1", dumps(values))
        self.settings.sync()
        if self.settings.status() != self._qt.Status.NoError:
            raise StorageError("preferences_save_failed", str(self.settings.status()))
        return values

    def remember_project(self, path):
        path = str(Path(path).resolve())
        recent = [path] + [p for p in self.load()["recent_projects"] if p != path]
        return self.save(recent_projects=recent[:20])

    @property
    def last_project(self):
        recent = self.load()["recent_projects"]
        return Path(recent[0]) if recent else None


def default_recovery_directory():
    from PySide6.QtCore import QStandardPaths
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "recovery"
