"""Explicit batch selection and worker-calculated preview before application."""
from dataclasses import replace
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox,
    QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout, QHBoxLayout)
from ..core.expressions import AliasIndex
from ..core.models import EnergyRef
from ..core.project_edits import (ProjectChange, add_component_to_nodes, replace_node_references,
                                 set_reference_for_paths)
from .i18n import translate
from .tables import UNIT_LABELS
from .glass_widgets import GlassPanel


def _glass_theme():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    theme = app.property("glassTheme") if app is not None else None
    return theme if theme in {"light", "dark"} else "light"


class BatchDialog(QDialog):
    def __init__(self, controller, node_ids=(), *, paths=False, language="zh_CN", parent=None):
        super().__init__(parent)
        self.setObjectName("batchDialog")
        self.controller, self.paths, self.language = controller, paths, language
        self.change = None
        self.setWindowTitle(self.t("批量编辑预览"))
        self.resize(940, 720)
        self.setMinimumSize(800, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)
        info_panel = GlassPanel("toolbar", theme=_glass_theme())
        info_panel.setObjectName("batchHeading")
        info_layout = QVBoxLayout(info_panel)
        info_layout.setContentsMargins(16, 11, 16, 11)
        info_layout.setSpacing(5)
        heading = QLabel(self.t("批量编辑预览"))
        heading.setObjectName("section")
        info_layout.addWidget(heading)
        info = QLabel(self.t("选择目标，生成计算预览后再应用。共享节点会同时影响引用它的所有路径。"))
        info.setWordWrap(True)
        info.setObjectName("muted")
        info_layout.addWidget(info)
        layout.addWidget(info_panel)
        settings = QHBoxLayout()
        settings.setSpacing(12)
        target_panel = GlassPanel("surface", theme=_glass_theme())
        target_panel.setObjectName("batchTargetPanel")
        target_layout = QVBoxLayout(target_panel)
        target_layout.setContentsMargins(14, 12, 14, 12)
        target_layout.setSpacing(8)
        target_heading = QLabel(self.t("选择目标"))
        target_heading.setObjectName("section")
        target_layout.addWidget(target_heading)
        self.target_summary = QLabel()
        self.target_summary.setObjectName("batchSelectionSummary")
        self.target_summary.setWordWrap(True)
        target_layout.addWidget(self.target_summary)
        self.targets = QListWidget()
        self.targets.setObjectName("batchTargets")
        self.targets.setAccessibleName(self.t("批量编辑目标"))
        self.targets.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        project, path = controller.project, controller.selected_path
        items = project.paths if paths else [next(n for n in project.nodes if n.id == e.node_id) for e in path.entries]
        for value in items:
            item = QListWidgetItem(value.label)
            item.setData(Qt.ItemDataRole.UserRole, value.id)
            item.setToolTip(f"{value.label}\n{value.id}")
            self.targets.addItem(item)
            item.setSelected(value.id in node_ids or paths and value.id == path.id)
        target_layout.addWidget(self.targets, 1)
        settings.addWidget(target_panel, 1)
        operation_panel = GlassPanel("surface", theme=_glass_theme())
        operation_panel.setObjectName("batchOperationPanel")
        operation_layout = QVBoxLayout(operation_panel)
        operation_layout.setContentsMargins(14, 12, 14, 12)
        operation_layout.setSpacing(8)
        operation_heading = QLabel(self.t("操作与参数"))
        operation_heading.setObjectName("section")
        operation_layout.addWidget(operation_heading)
        self.action = QComboBox()
        for text, key in (([("应用当前参考到所选路径", "reference")] if paths else
                           [("添加同一组分", "add"), ("替换精确来源引用", "replace"), ("复制节点表达式模板", "template")])):
            self.action.addItem(self.t(text), key)
        self.action.setAccessibleName(self.t("批量操作"))
        operation_layout.addWidget(QLabel(self.t("批量操作")))
        operation_layout.addWidget(self.action)
        self.first, self.second = QComboBox(), QComboBox()
        self.coefficient = QDoubleSpinBox()
        self.coefficient.setRange(-1000000, 1000000)
        self.coefficient.setDecimals(8)
        self.coefficient.setValue(1)
        aliases = AliasIndex(project.alias_bindings)
        choices = list(project.alias_bindings.values())
        for source in project.source_files:
            for job in source.jobs:
                choices.extend([EnergyRef(source.id, job.id), *[EnergyRef(source.id, job.id, "fixed", kind) for kind in job.energies]])
        for ref in dict.fromkeys(choices):
            source = next((s for s in project.source_files if s.id == ref.source_file_id), None)
            job = next((j for j in source.jobs if j.id == ref.job_id), None) if source else None
            text = f"{source.display_name if source else self.t('来源未连接')} · {ref.source_file_id[:8]} · J{job.ordinal + 1 if job else '?'} · {ref.kind.value if ref.kind else self.t('跟随路径')}"
            for combo in (self.first, self.second):
                combo.addItem(text, ref)
        self.template = QComboBox()
        for node in project.nodes:
            self.template.addItem(node.label, node.id)
        for combo in (self.first, self.second, self.template):
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        for combo in (self.first, self.second, self.template):
            combo.setMinimumContentsLength(16)
            combo.setAccessibleName(self.t("来源或表达式选项"))
        self.first_label = QLabel(self.t("组分 / 替换前来源"))
        self.second_label = QLabel(self.t("替换后来源"))
        self.template_label = QLabel(self.t("表达式模板"))
        self.coefficient_label = QLabel(self.t("系数组分"))
        for text_label, widget in ((self.first_label, self.first), (self.second_label, self.second),
                                   (self.template_label, self.template), (self.coefficient_label, self.coefficient)):
            text_label.setObjectName("muted")
            operation_layout.addWidget(text_label)
            operation_layout.addWidget(widget)
        operation_layout.addStretch(1)
        settings.addWidget(operation_panel, 1)
        layout.addLayout(settings, 1)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setObjectName("batchPreview")
        self.output.setAccessibleName(self.t("计算预览"))
        self.output.setPlaceholderText(self.t("生成预览后会在此显示各路径结果与诊断。"))
        preview_panel = GlassPanel("surface", theme=_glass_theme())
        preview_panel.setObjectName("batchPreviewPanel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(14, 10, 14, 10)
        preview_layout.setSpacing(6)
        preview_heading = QLabel(self.t("计算预览（未应用）"))
        preview_heading.setObjectName("section")
        preview_layout.addWidget(preview_heading)
        preview_layout.addWidget(self.output)
        layout.addWidget(preview_panel, 1)
        actions = QHBoxLayout()
        self.preview_button = QPushButton(self.t("生成预览"))
        self.preview_button.clicked.connect(self.preview)
        self.apply_button = QPushButton(self.t("应用到所选目标"))
        self.apply_button.setEnabled(False)
        self.apply_button.setObjectName("primary")
        self.apply_button.setAccessibleName(self.t("应用到所选目标"))
        self.apply_button.clicked.connect(self.apply)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        controller.previewReady.connect(self.preview_ready)
        controller.busyChanged.connect(self.busy_changed)
        controller.failed.connect(self.failed)
        self.targets.itemSelectionChanged.connect(self.selection_changed)
        self.action.currentIndexChanged.connect(self.inputs_changed)
        for combo in (self.first, self.second, self.template):
            combo.editTextChanged.connect(self.invalidate)
        self.coefficient.valueChanged.connect(self.invalidate)
        self.inputs_changed()
        self.update_target_summary()

    def t(self, text):
        return translate(text, self.language)

    def invalidate(self, *_):
        self.change = None
        self.apply_button.setEnabled(False)

    def selection_changed(self):
        self.update_target_summary()
        self.invalidate()

    def update_target_summary(self):
        selected = len(self.targets.selectedItems()) if hasattr(self, "targets") else 0
        total = self.targets.count() if hasattr(self, "targets") else 0
        self.target_summary.setText(self.t("已选目标") + f" · {selected}/{total}")

    def inputs_changed(self, *_):
        mode = self.action.currentData()
        self.first.setVisible(mode in ("add", "replace"))
        self.first_label.setVisible(mode in ("add", "replace"))
        self.second.setVisible(mode == "replace")
        self.second_label.setVisible(mode == "replace")
        self.template.setVisible(mode == "template")
        self.template_label.setVisible(mode == "template")
        self.coefficient.setVisible(mode == "add")
        self.coefficient_label.setVisible(mode == "add")
        self.invalidate()

    def choice(self, combo):
        if combo.currentIndex() < 0 or combo.currentText() != combo.itemText(combo.currentIndex()):
            raise ValueError(self.t("请从候选列表选择来源物种。"))
        return combo.currentData()

    def preview(self):
        self.invalidate()
        if self.controller.busy:
            return
        project = self.controller._snapshot()
        selected = [item.data(Qt.ItemDataRole.UserRole) for item in self.targets.selectedItems()]
        try:
            if not selected:
                raise ValueError(self.t("请选择至少一个目标。"))
            mode = self.action.currentData()
            if mode == "add":
                change = add_component_to_nodes(project, selected, self.choice(self.first), self.coefficient.value(), project.alias_bindings)
            elif mode == "replace":
                change = replace_node_references(project, selected, {self.choice(self.first): self.choice(self.second)}, project.alias_bindings)
            elif mode == "reference":
                reference = self.controller.selected_path.reference_expression
                change = set_reference_for_paths(project, selected, reference)
            else:
                original = next(n for n in project.nodes if n.id == self.choice(self.template))
                nodes = tuple(replace(n, expression=original.expression) if n.id in selected else n for n in project.nodes)
                affected = tuple(p.id for p in project.paths if any(e.node_id in selected for e in p.entries))
                change = ProjectChange(project.id, project.revision, replace(project, nodes=nodes, revision=project.revision + 1), tuple(selected), affected)
            self._pending_change = change
            self.controller.preview_change(change)
        except (ValueError, TypeError) as error:
            self.output.setPlainText(str(error))

    def preview_ready(self, data):
        change, results = data
        if change is not getattr(self, "_pending_change", None):
            return
        self.change = change
        lines = [self.t("预览尚未应用") + f" · revision {change.base_revision} → {change.project.revision}"]
        for result in results:
            path = next(p for p in change.project.paths if p.id == result.path_id)
            lines.append(f"\n{path.label}")
            for value in result.nodes:
                label = next(n.label for n in change.project.nodes if n.id == value.node_id)
                lines.append(f"{label}: {format(value.display_value, '+.8f') if value.valid else '—'} {UNIT_LABELS[value.unit.value]}")
                lines.extend(d.code for d in value.diagnostics)
            lines.extend(d.code for d in result.diagnostics)
        self.output.setPlainText("\n".join(lines))

    def busy_changed(self, busy, *_):
        self.preview_button.setEnabled(not busy)
        self.apply_button.setEnabled(not busy and self.change is not None)
        self.targets.setEnabled(not busy)
        for widget in (self.action, self.first, self.second, self.template, self.coefficient):
            widget.setEnabled(not busy)

    def failed(self, code, detail):
        self.invalidate()
        self.output.setPlainText(code + "\n" + detail)

    def apply(self):
        try:
            if self.change and self.controller.apply_change(self.change):
                self.accept()
        except ValueError as error:
            self.invalidate()
            self.output.setPlainText(str(error))
