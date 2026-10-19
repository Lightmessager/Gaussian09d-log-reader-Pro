"""Post-import summary and explicit source/job candidate selection dialogs."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
    QHeaderView, QLabel, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core.reaction_network import parse_molecular_formula
from .workflow_state import derive_import_summary, derive_job_candidates


_ENERGY_LABELS = {
    "scf": "SCF",
    "gibbs_correction": "Gibbs 热校正",
    "gibbs_total": "Gibbs 总量",
}


class JobCandidateDialog(QDialog):
    """A UUID-addressed candidate table; selecting jobs never creates edges."""
    def __init__(self, project, *, source_ids=None, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("从已导入作业创建物质卡")
        self.resize(1000, 580)
        layout = QVBoxLayout(self)
        note = QLabel("逐项勾选明确的来源文件和 Gaussian 作业，并填写物质名。名称相同也会保留为不同候选；所选作业只加入物质卡草稿，不会自动建立阶段或反应边。")
        note.setWordWrap(True)
        layout.addWidget(note)
        all_rows = derive_job_candidates(project)
        if source_ids is not None:
            allowed = set(source_ids)
            all_rows = tuple(row for row in all_rows if row.source_file_id in allowed)
        self.rows = all_rows
        self.table = QTableWidget(len(self.rows), 6)
        self.table.setHorizontalHeaderLabels(["选择", "来源 / source UUID", "作业 / job UUID", "终止", "可用能量", "物质名 / 分子式"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.name_edits = {}
        self.formula_edits = {}
        for index, row in enumerate(self.rows):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | (
                Qt.ItemFlag.ItemIsUserCheckable if row.available_energy_kinds else Qt.ItemFlag.NoItemFlags))
            check.setCheckState(Qt.CheckState.Unchecked)
            if not row.available_energy_kinds:
                check.setToolTip("该作业没有可用能量，不能作为有绑定的物质卡。")
            self.table.setItem(index, 0, check)
            source_item = QTableWidgetItem(
                f"{row.source_label}\n{row.source_path}\n{row.source_file_id}")
            source_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            source_item.setToolTip(f"文件路径：{row.source_path}\n来源 UUID：{row.source_file_id}")
            self.table.setItem(index, 1, source_item)
            job_item = QTableWidgetItem(f"Job {row.job_ordinal + 1}\n{row.job_id}")
            job_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(index, 2, job_item)
            termination = QTableWidgetItem(row.termination)
            termination.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(index, 3, termination)
            energy_text = "、".join(_ENERGY_LABELS.get(kind, kind) for kind in row.available_energy_kinds) or "无可用能量"
            energies = QTableWidgetItem(energy_text)
            energies.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(index, 4, energies)
            from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit
            editor = QWidget()
            editor_layout = QHBoxLayout(editor)
            editor_layout.setContentsMargins(0, 0, 0, 0)
            name = QLineEdit(f"{row.source_label} · J{row.job_ordinal + 1}")
            name.setPlaceholderText("物质名")
            formula = QLineEdit()
            formula.setPlaceholderText("分子式（可选）")
            editor_layout.addWidget(name, 2)
            editor_layout.addWidget(formula, 1)
            self.table.setCellWidget(index, 5, editor)
            self.name_edits[index] = name
            self.formula_edits[index] = formula
            self.table.setRowHeight(index, 76)
        layout.addWidget(self.table, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                        QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("加入搭建器草稿")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.accepted.connect(self._accept_selection)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.table.itemChanged.connect(self._selection_changed)
        self._selected = []

    def _selection_changed(self, *_):
        selected = [row for row in range(self.table.rowCount())
                    if self.table.item(row, 0).checkState() == Qt.CheckState.Checked]
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(selected))

    def _accept_selection(self):
        from .reaction_builder_state import propose_imported_job_cards
        candidates = []
        for index, row in enumerate(self.rows):
            if self.table.item(index, 0).checkState() != Qt.CheckState.Checked:
                continue
            name = self.name_edits[index].text().strip()
            formula = self.formula_edits[index].text().strip()
            if not name:
                QMessageBox.warning(self, "需要物质名", f"请为 Job {row.job_ordinal + 1} 填写物质名。")
                return
            if formula:
                try:
                    parse_molecular_formula(formula)
                except ValueError as error:
                    QMessageBox.warning(self, "分子式无效", str(error))
                    return
            candidates.append({"source_file_id": row.source_file_id, "job_id": row.job_id,
                               "name": name, "formula": formula})
        try:
            # Validate UUID ownership before the selection leaves this dialog.
            propose_imported_job_cards(self.project, {"species": [], "edges": [], "path_reactions": []}, candidates)
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "作业候选无效", str(error))
            return
        self._selected = candidates
        self.accept()

    @property
    def selected_candidates(self):
        return [dict(item) for item in self._selected]


class ImportSummaryDialog(QDialog):
    """Summarize the project import and route to an explicit job table."""
    def __init__(self, project, *, added_source_ids=None, parent=None):
        super().__init__(parent)
        self.project = project
        self.selected_candidates = []
        self.setWindowTitle("导入摘要")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        total = derive_import_summary(project)
        added = derive_import_summary(project, source_ids=added_source_ids) if added_source_ids is not None else total
        newly_added = max(0, len(set(added_source_ids or ())))
        lines = [f"本次新增来源文件：{newly_added} 个",
                 f"项目来源文件：{total.source_count} 个 · Gaussian 作业：{total.job_count} 个"]
        for kind, label in (("scf", "SCF"), ("gibbs_correction", "Gibbs 热校正"),
                            ("gibbs_total", "Gibbs 总量")):
            if added_source_ids is None:
                lines.append(f"{label} 可用：项目 {total.available(kind)} / {total.job_count} 个作业")
            else:
                lines.append(f"{label} 可用：项目 {total.available(kind)} / {total.job_count}；"
                             f"本次新增 {added.available(kind)} / {added.job_count} 个作业")
        if added_source_ids is not None and added_source_ids and added.job_count:
            lines.append(f"本次新增作业：{added.job_count} 个")
        summary = QLabel("\n".join(lines))
        summary.setWordWrap(True)
        layout.addWidget(summary)
        note = QLabel("已有计算节点已保留。选择作业只会提出物质卡草稿，不会把文件顺序或同名项目自动视为反应路径。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.candidates_button = self.buttons.addButton("打开作业候选表…",
            QDialogButtonBox.ButtonRole.ActionRole)
        self.candidates_button.clicked.connect(self._open_candidates)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _open_candidates(self):
        dialog = JobCandidateDialog(self.project, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_candidates:
            self.selected_candidates = dialog.selected_candidates
            self.accept()
