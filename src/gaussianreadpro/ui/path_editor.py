"""Create a real path with explicit shared-node selection and a custom colour."""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

from .i18n import translate


class NewPathDialog(QDialog):
    def __init__(self, project, active_path=None, *, language="zh_CN", parent=None):
        super().__init__(parent)
        t = lambda text: translate(text, language)
        self.setWindowTitle(t("新增反应路径"))
        self.resize(530, 570)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        existing = {p.label for p in project.paths}
        i = len(project.paths) + 1
        while "Path " + str(i) in existing:
            i += 1
        self.name_edit = QLineEdit("Path " + str(i))
        self.name_edit.setObjectName("newPathName")
        self.name_edit.setMaxLength(256)
        form.addRow(t("路径名称"), self.name_edit)
        palette = ("#AD83FF", "#FFA96C", "#52CDB8", "#68ACFF", "#F27DA9", "#DBC564")
        used = {p.color.lower() for p in project.paths}
        default = next((c for c in palette if c.lower() not in used), palette[len(project.paths) % len(palette)])
        self.color_edit = QLineEdit(default)
        self.color_edit.setObjectName("newPathColor")
        self.color_edit.setMaxLength(7)
        self.color_button = QPushButton(t("选择颜色…"))
        row = QHBoxLayout()
        row.addWidget(self.color_edit); row.addWidget(self.color_button)
        form.addRow(t("路径颜色"), row)
        self.color_button.clicked.connect(self.choose_color)
        hint = QLabel(t("勾选已有节点加入新路径，可拖动调整顺序。共享节点的表达式修改会影响引用它的路径；不勾选则创建空路径，随后从“路径节点与编辑”新增节点。"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.nodes = QListWidget()
        self.nodes.setObjectName("newPathNodes")
        self.nodes.setAccessibleName(t("选择路径节点并调整顺序"))
        self.nodes.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        labels = {n.id: n for n in project.nodes}
        order = list(dict.fromkeys([e.node_id for e in active_path.entries] if active_path else []))
        order += [n.id for n in project.nodes if n.id not in order]
        for node_id in order:
            n = labels[node_id]
            item = QListWidgetItem(n.label + " · " + n.id[:8], self.nodes)
            item.setData(Qt.ItemDataRole.UserRole, n.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
        layout.addWidget(self.nodes, 1)
        reference = QLabel(t("新路径继承当前路径的能量类型、单位和参考体系；高光与面积阴影使用相同算法。"))
        reference.setWordWrap(True); layout.addWidget(reference)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("创建并比较"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("取消"))
        self.buttons.accepted.connect(self.accept); self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.name_edit.textChanged.connect(self.validate)
        self.color_edit.textChanged.connect(self.validate)
        self.validate()

    def validate(self):
        valid = bool(re.fullmatch(r"#[0-9a-fA-F]{6}", self.color_edit.text()))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.name_edit.text().strip()) and valid)
        if valid:
            self.color_button.setStyleSheet("border: 3px solid " + self.color_edit.text() + ";")

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.color_edit.text()), self)
        if color.isValid():
            self.color_edit.setText(color.name())

    def values(self):
        return {"label": self.name_edit.text().strip(), "color": self.color_edit.text().lower(),
            "node_ids": [self.nodes.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.nodes.count())
                         if self.nodes.item(i).checkState() == Qt.CheckState.Checked]}
