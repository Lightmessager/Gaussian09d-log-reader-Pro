"""Shared QAction catalog for the persistent project/workflow controls."""

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QKeySequence


@dataclass(frozen=True)
class ActionAvailability:
    enabled: bool
    reason: str = ""


_ACTIONS = {
    "new_project": ("新建", QKeySequence.StandardKey.New),
    "open_project": ("打开", QKeySequence.StandardKey.Open),
    "save_project": ("保存项目", QKeySequence.StandardKey.Save),
    "save_as": ("另存为", QKeySequence.StandardKey.SaveAs),
    "edit_reaction_path": ("编辑反应路径", "Ctrl+Shift+E"),
    "new_reaction_path": ("新建反应路径", None),
    "new_reaction_path_advanced": ("高级：从现有节点创建路径…", None),
    "import_logs": ("＋ 导入日志", "Ctrl+I"),
    "show_sources": ("计算日志", None),
    "reconnect_source": ("重新定位失效来源", None),
    "show_path_nodes": ("路径节点", None),
    "calculate": ("重新计算", "F5"),
    "rename_project_file": ("重命名项目文件…", None),
}


class ProjectActions(QObject):
    """Owns shared actions and binds text-bearing buttons to their state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actions = {}
        self._availability = {}
        for key, (text, shortcut) in _ACTIONS.items():
            action = QAction(text, self)
            action.setProperty("i18n_source", text)
            if shortcut is not None:
                sequence = (QKeySequence(shortcut) if isinstance(shortcut, QKeySequence.StandardKey)
                            else QKeySequence(shortcut))
                action.setShortcut(sequence)
                action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self._actions[key] = action
            self._availability[key] = ActionAvailability(True)

    def action(self, key):
        try:
            return self._actions[key]
        except KeyError:
            raise ValueError(f"Unknown project action: {key}") from None

    def availability(self, key):
        try:
            return self._availability[key]
        except KeyError:
            self.action(key)
            raise AssertionError("unreachable")

    def set_availability(self, key, enabled, reason=""):
        action = self.action(key)
        availability = ActionAvailability(bool(enabled), str(reason or ""))
        self._availability[key] = availability
        action.setEnabled(availability.enabled)
        action.setStatusTip(availability.reason)
        action.setToolTip(availability.reason)

    def bind_button(self, key, button):
        action = self.action(key)

        def sync_button():
            button.setText(action.text())
            button.setEnabled(action.isEnabled())
            button.setAccessibleName(action.text())
            button.setToolTip(action.toolTip())

        button.setProperty("sharedProjectAction", key)
        button.clicked.connect(action.trigger)
        action.changed.connect(sync_button)
        sync_button()
        return button
