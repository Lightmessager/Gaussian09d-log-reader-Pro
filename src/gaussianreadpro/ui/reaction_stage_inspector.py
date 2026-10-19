"""Focused details panel for the currently selected stage or connection."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget)

from .i18n import source_text, translate


_ROLE_LABELS = {
    "reactant": "反应物",
    "intermediate": "中间体",
    "transition_state": "过渡态",
    "product": "产物",
    "unspecified": "待选角色",
}


class ReactionStageInspector(QWidget):
    """Displays details from a draft snapshot and emits commands for edits."""

    commandRequested = Signal(dict)

    def __init__(self, parent=None, *, language="zh_CN"):
        super().__init__(parent)
        self.language = language
        self._snapshot = None
        self._selected_id = None
        self._selected_kind = "stage"
        self._loading = False
        self._change_notice_source = ""
        self.title = QLabel(self._text("选中项详情"))
        self.title.setObjectName("section")
        self.change_notice = QLabel()
        self.change_notice.setWordWrap(True)
        self.change_notice.hide()
        self.stage_name = QLineEdit()
        self.stage_role = QComboBox()
        for role, label in _ROLE_LABELS.items():
            self.stage_role.addItem(self._text(label), role)
        self.missing_transition = QCheckBox(self._text("NOT FOUND · 无能量值"))
        self.review_state = QLabel()
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMinimumHeight(150)
        self.summary.setTextInteractionFlags(self.summary.textInteractionFlags())
        form = QFormLayout()
        form.addRow(self._text("阶段标签"), self.stage_name)
        form.addRow(self._text("阶段角色"), self.stage_role)
        form.addRow(self._text("过渡态缺值"), self.missing_transition)
        form.addRow(self._text("科学核对"), self.review_state)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.change_notice)
        layout.addLayout(form)
        layout.addWidget(self.summary, 1)
        self.stage_name.editingFinished.connect(self._stage_name_edited)
        self.stage_role.currentIndexChanged.connect(self._stage_role_edited)
        self.missing_transition.toggled.connect(self._missing_edited)
        self._set_editing_enabled(False)

    def _text(self, text):
        return translate(text, self.language)

    def set_change_notice(self, text):
        self._change_notice_source = source_text(text or "", self.language)
        self.change_notice.setText(text or "")
        self.change_notice.setVisible(bool(text))

    def set_language(self, language):
        if language == self.language:
            return
        self.language = language
        self.title.setText(self._text("选中项详情"))
        self.missing_transition.setText(self._text("NOT FOUND · 无能量值"))
        for index, (role, label) in enumerate(_ROLE_LABELS.items()):
            self.stage_role.setItemText(index, self._text(label))
        self.change_notice.setText(self._text(self._change_notice_source)
                                   if self._change_notice_source else "")
        snapshot, selected_id, kind = self._snapshot, self._selected_id, self._selected_kind
        edited_name = self.stage_name.text()
        if snapshot is not None:
            self.set_draft(snapshot, selected_id, kind)
            if selected_id is not None and kind == "stage" and edited_name:
                self.stage_name.setText(edited_name)

    def _set_editing_enabled(self, enabled):
        self.stage_name.setEnabled(enabled and self._selected_kind == "stage")
        self.stage_role.setEnabled(enabled and self._selected_kind == "stage")
        self.missing_transition.setEnabled(
            enabled and self._selected_kind == "stage" and self.stage_role.currentData() == "transition_state")

    def set_draft(self, snapshot, selected_id=None, kind="stage"):
        self._snapshot = snapshot
        self._selected_id = selected_id
        self._selected_kind = kind
        network = snapshot.get("network", {}) if snapshot else {}
        path_id = snapshot.get("path_id") if snapshot else None
        recipe = next((item for item in network.get("path_reactions", [])
                       if item.get("path_id") == path_id), None)
        species = {item["id"]: item for item in network.get("species", [])}
        self._loading = True
        self.stage_name.blockSignals(True)
        self.stage_role.blockSignals(True)
        self.missing_transition.blockSignals(True)
        try:
            if selected_id is None or recipe is None:
                self.title.setText(self._text("选中项详情"))
                self.stage_name.clear()
                self.stage_role.setCurrentIndex(0)
                self.missing_transition.setChecked(False)
                self.review_state.setText(self._text("请选择阶段或连接查看详情"))
                self.summary.setPlainText(self._text("画布位置、阶段顺序与能量坐标分别处理。"))
                self._set_editing_enabled(False)
                return
            if kind == "connection":
                self._show_connection(recipe, selected_id, species)
                self._set_editing_enabled(False)
                return
            stage = next((item for item in recipe.get("stages", []) if item["id"] == selected_id), None)
            if stage is None:
                self.review_state.setText(self._text("所选阶段已不存在"))
                self.summary.clear()
                self._set_editing_enabled(False)
                return
            self.title.setText(f"{self._text('阶段详情')} · {stage['label']}")
            self.stage_name.setText(stage["label"])
            self.stage_role.setCurrentIndex(max(0, self.stage_role.findData(stage["role"])))
            self.missing_transition.setChecked(bool(stage.get("missing")))
            self.review_state.setText(
                self._text("已核对") if stage.get("normalization_confirmed") else self._text("待核对阶段组成与统一零点可比性"))
            self.summary.setPlainText(self._stage_summary(recipe, stage, species))
            self._set_editing_enabled(True)
        finally:
            self.stage_name.blockSignals(False)
            self.stage_role.blockSignals(False)
            self.missing_transition.blockSignals(False)
            self._loading = False

    def _stage_summary(self, recipe, stage, species):
        lines = [f"{self._text('物质组成')}："]
        components = stage.get("species", [])
        if components:
            lines.extend(f"  {item['coefficient']:g} × {species.get(item['species_id'], {}).get('name', '?')}"
                         for item in components)
        else:
            lines.append(f"  {self._text('尚未添加物质组成')}")
        lines.append(f"\n{self._text('用于计算的能量项')}：")
        terms = stage.get("terms", [])
        if stage.get("missing"):
            lines.append(f"  {self._text('NOT FOUND · 无能量值')}")
        elif not terms:
            lines.append(f"  {self._text('尚未配置能量项')}")
        else:
            for term in terms:
                card = species.get(term["species_id"], {})
                lines.append(f"  {term['coefficient']:g} × {card.get('name', '?')} · "
                             f"{term['energy_kind']} · {term['system_mode']} · "
                             f"{term['source_file_id'][:8]}/{term['job_id'][:8]}")
                lines.append(f"    {self._text('原因')}：{term['reason']}")
        zero = recipe.get("zero_point", {})
        if zero.get("kind") in {"stage", "reactant"}:
            zero_stage = next((item for item in recipe["stages"] if item["id"] == zero.get("stage_id")), None)
            zero_label = zero_stage["label"] if zero_stage else self._text("尚未指定")
            lines.append(f"\n{self._text('统一零点')}：{zero_label}")
        elif zero.get("kind") == "custom_expression":
            lines.append(f"\n{self._text('统一零点')}：{zero.get('expression', '')}")
        elif zero.get("kind") == "manual":
            lines.append(f"\n{self._text('统一零点')}：{zero.get('value')} {zero.get('unit')}")
        lines.append(f"\n{self._text('阶段位置仅影响画布布局，不改变反应拓扑或能量。')}")
        return "\n".join(lines)

    def _show_connection(self, recipe, connection_id, species):
        edge = next((item for item in recipe.get("connections", []) if item["id"] == connection_id), None)
        self.stage_name.clear()
        self.stage_role.setCurrentIndex(0)
        self.missing_transition.setChecked(False)
        if edge is None:
            self.title.setText(self._text("连接详情"))
            self.review_state.setText(self._text("所选连接已不存在"))
            self.summary.clear()
            return
        stage_names = {item["id"]: item["label"] for item in recipe.get("stages", [])}
        self.title.setText(f"{self._text('连接详情')} · {stage_names.get(edge['source_stage_id'], '?')} → "
                           f"{stage_names.get(edge['target_stage_id'], '?')}")
        self.review_state.setText(self._text("已逐边核对") if edge.get("confirmed") else self._text("待逐边核对"))
        lines = [f"{self._text('反应物侧')}："]
        lines.extend(f"  {part['coefficient']:g} × {species.get(part['species_id'], {}).get('name', '?')}"
                     for part in edge.get("reactants", []))
        lines.append(f"\n{self._text('产物侧')}：")
        lines.extend(f"  {part['coefficient']:g} × {species.get(part['species_id'], {}).get('name', '?')}"
                     for part in edge.get("products", []))
        if edge.get("terms"):
            lines.append(f"\n{self._text('边能量项')}：")
            lines.extend(f"  {term['coefficient']:g} × {species.get(term['species_id'], {}).get('name', '?')} · "
                         f"{term['energy_kind']} · {term['source_file_id'][:8]}/{term['job_id'][:8]}"
                         for term in edge["terms"])
        lines.append(f"\n{self._text('核对说明')}：{edge.get('note') or self._text('尚未填写')}")
        self.summary.setPlainText("\n".join(lines))

    def _stage_name_edited(self):
        if self._loading or self._selected_kind != "stage" or self._selected_id is None:
            return
        value = self.stage_name.text().strip()
        if value:
            self.commandRequested.emit({"type": "update_stage", "stage_id": self._selected_id,
                                        "fields": {"label": value}})

    def _stage_role_edited(self, *_):
        if self._loading or self._selected_kind != "stage" or self._selected_id is None:
            return
        role = self.stage_role.currentData()
        if role:
            self.commandRequested.emit({"type": "update_stage", "stage_id": self._selected_id,
                                        "fields": {"role": role}})
        self._set_editing_enabled(True)

    def _missing_edited(self, value):
        if self._loading or self._selected_kind != "stage" or self._selected_id is None:
            return
        self.commandRequested.emit({"type": "update_stage", "stage_id": self._selected_id,
                                    "fields": {"missing": bool(value)}})
