"""Project-local reaction path builder over the existing expression/calculation core."""
from copy import deepcopy
from dataclasses import replace
from collections.abc import Mapping
import json
import re
from PySide6.QtCore import Qt, QMimeData, Signal
from PySide6.QtGui import QDrag, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QApplication, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem,
    QMenu, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from ..core.calculations import calculate_path
from ..core.expressions import compile_expression, expression_references, render_expression
from ..core.models import (CalculationMode, EnergyKind, ExpressionPurpose, ReactionPath, Unit, new_id)
from ..core.reaction_network import (apply_path_recipe, empty_network, read_reaction_network,
                                     reference_signature, validate_network)
from ..core.parser import select_job
from ..core.units import from_hartree, UNIT_LABELS
from .i18n import diagnostic_text, source_text, translate
from .reaction_builder_state import BuilderDraft, propose_imported_job_cards
from .reaction_canvas import ReactionCanvas, SPECIES_MIME
from .reaction_stage_inspector import ReactionStageInspector


class SpeciesCardList(QListWidget):
    tabForwardPressed = Signal()
    tabBackwardPressed = Signal()

    def focusNextPrevChild(self, next):
        (self.tabForwardPressed if next else self.tabBackwardPressed).emit()
        return True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Tab:
            self.tabForwardPressed.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Backtab:
            self.tabBackwardPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def startDrag(self, supported_actions):
        identifiers = [item.data(Qt.ItemDataRole.UserRole) for item in self.selectedItems()]
        if not identifiers:
            return
        mime = QMimeData()
        mime.setData(SPECIES_MIME, json.dumps(identifiers).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class SnapList(QListWidget):
    def __init__(self, callback):
        super().__init__()
        self._snap_callback = callback
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(SPECIES_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(SPECIES_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(SPECIES_MIME):
            try:
                identifiers = json.loads(bytes(event.mimeData().data(SPECIES_MIME)).decode("utf-8"))
            except (ValueError, UnicodeError):
                event.ignore()
                return
            item = self.itemAt(event.position().toPoint())
            self._snap_callback(identifiers, item.data(Qt.ItemDataRole.UserRole) if item else None)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class StageNavigationList(SnapList):
    """Stage list with explicit keyboard activation and undoable deletion."""

    enterPressed = Signal()
    deletePressed = Signal()
    tabForwardPressed = Signal()
    tabBackwardPressed = Signal()

    def focusNextPrevChild(self, next):
        (self.tabForwardPressed if next else self.tabBackwardPressed).emit()
        return True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Tab:
            self.tabForwardPressed.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Backtab:
            self.tabBackwardPressed.emit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.enterPressed.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            self.deletePressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class LegacyReadOnlyDialog(QDialog):
    def __init__(self, project, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("原路径只读概览")
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        note = QLabel("以下内容来自当前路径的既有节点与表达式。关闭此窗口不会改变项目。")
        note.setWordWrap(True)
        layout.addWidget(note)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        nodes = {node.id: node for node in project.nodes}
        result = next((item for item in getattr(parent.controller, "results", ())
                       if item.project_id == project.id and item.path_id == path.id and
                       item.revision == project.revision), None) if parent else None
        result_by_entry = {item.entry_id: item for item in result.nodes} if result else {}
        lines = []
        for entry in path.entries:
            node = nodes[entry.node_id]
            text = node.expression.draft_text if node.expression.draft_error else render_expression(
                node.expression, project.alias_bindings)
            value = result_by_entry.get(entry.id)
            if value:
                absolute = "缺值" if value.absolute_hartree is None else f"{value.absolute_hartree:.12f} Eh"
                relative = "不可用" if value.relative_hartree is None else f"{value.relative_hartree:+.12f} Eh"
            else:
                absolute, relative = "尚无当前修订结果", "尚无当前修订结果"
            lines.append(f"节点 {node.id}\n路径点 {entry.id}\n{node.label} · {node.role.value}\n"
                         f"原表达式：{text}\n绝对能量：{absolute}\n相对能量：{relative}\n")
        details.setPlainText("\n".join(lines) or "当前路径没有计算节点。")
        layout.addWidget(details, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class LegacyConversionDialog(QDialog):
    """Collect explicit role/composition/reference choices for a legacy draft."""
    def __init__(self, project, path, draft, parent=None, *, target_path=None):
        super().__init__(parent)
        self.project, self.path, self.draft = project, path, draft
        self.target_path = target_path
        self.preview = None
        self.setWindowTitle("转换预览 · 旧路径")
        self.resize(1040, 500)
        layout = QVBoxLayout(self)
        target_note = (f"将新建路径：{target_path.label}。旧路径保持不变。" if target_path else
                       "将在当前路径原位转换。")
        note = QLabel(f"{target_note} 每个旧节点先作为一张独立物质卡和一个阶段提案。导入顺序不会生成反应边；请逐项选择角色并核对单物质组成。")
        note.setWordWrap(True)
        layout.addWidget(note)
        refs = []
        nodes = {node.id: node for node in project.nodes}
        for entry in path.entries:
            refs.extend(expression_references(nodes[entry.node_id].expression))
        policy_summary = "；".join(dict.fromkeys(
            "随路径" if ref.kind_policy.value == "follow_path" else f"固定 {ref.kind.value}"
            for ref in refs))
        self.reference_policy = QCheckBox(
            f"确认引用策略：原引用为 {policy_summary}；新配方将固定为当前路径类型 {path.energy_kind.value}。")
        layout.addWidget(self.reference_policy)
        self.table = QTableWidget(len(path.entries), 7)
        self.table.setHorizontalHeaderLabels(["旧节点 / 原表达式", "来源 / 作业 UUID", "角色", "组成提案", "分子式（可选）", "组成核对", "能量口径"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(True)
        self.role_boxes, self.formula_fields, self.composition_checks = {}, {}, {}
        for row, entry in enumerate(path.entries):
            node = nodes[entry.node_id]
            ref = expression_references(node.expression)[0]
            source = next(source for source in project.source_files if source.id == ref.source_file_id)
            job = next(job for job in source.jobs if job.id == ref.job_id)
            expression = render_expression(node.expression, project.alias_bindings)
            self.table.setItem(row, 0, QTableWidgetItem(f"{node.label}\n{expression}"))
            self.table.setItem(row, 1, QTableWidgetItem(
                f"{source.display_name} · Job {job.ordinal + 1}\n{source.id}\n{job.id}"))
            role = QComboBox()
            role.addItem("请选择角色", None)
            for value, label in (("reactant", "反应物"), ("intermediate", "中间体"),
                                 ("transition_state", "过渡态"), ("product", "产物")):
                role.addItem(label, value)
            role.currentIndexChanged.connect(self._update_acceptance)
            self.table.setCellWidget(row, 2, role)
            self.role_boxes[node.id] = role
            composition_text = QTableWidgetItem(f"1 × {node.label}（独立物质卡）")
            composition_text.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 3, composition_text)
            formula = QLineEdit()
            formula.setPlaceholderText("未知可留空")
            self.table.setCellWidget(row, 4, formula)
            self.formula_fields[node.id] = formula
            composition = QCheckBox("单物质组成已核对")
            composition.toggled.connect(self._update_acceptance)
            self.table.setCellWidget(row, 5, composition)
            self.composition_checks[node.id] = composition
            self.table.setItem(row, 6, QTableWidgetItem(
                f"完整体系 · {path.energy_kind.value}\n来源作业保持为 {source.id[:8]} / {job.id[:8]}"))
            self.table.setRowHeight(row, 82)
        layout.addWidget(self.table, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                        QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("生成转换草稿")
        self.buttons.accepted.connect(self._accept_conversion)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.reference_policy.toggled.connect(self._update_acceptance)
        self._update_acceptance()

    def _update_acceptance(self, *_):
        ready = self.reference_policy.isChecked() and bool(self.role_boxes)
        ready = ready and all(box.currentData() in {"reactant", "intermediate", "transition_state", "product"}
                              for box in self.role_boxes.values())
        ready = ready and all(check.isChecked() for check in self.composition_checks.values())
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ready)

    def _accept_conversion(self):
        roles = {identifier: box.currentData() for identifier, box in self.role_boxes.items()}
        formulas = {identifier: field.text().strip() for identifier, field in self.formula_fields.items()}
        confirmed = {identifier for identifier, check in self.composition_checks.items() if check.isChecked()}
        try:
            self.preview = self.draft.conversion_preview(self.project, roles=roles,
                confirmed_compositions=confirmed, accept_reference_policy=self.reference_policy.isChecked(),
                formulas=formulas, target_path=self.target_path)
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "无法生成转换草稿", str(error))
            return
        self.accept()


class ReactionBuilderDialog(QDialog):
    """Editable draft UI. Only Apply writes one project revision."""
    def __init__(self, controller, path_id=None, *, focus_node_id=None, focus_entry_id=None,
                 create_new_path=False, candidate_cards=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.project = controller.project
        self.language = getattr(parent, "language", "zh_CN")
        self._draft_new_path = None
        self._builder_layouts = {}
        self._selected_stage_id = None
        self._selected_connection_id = None
        self._syncing_stage_selection = False
        self._flow_state = "draft"
        self._pending_token = None
        self._pending_operation = None
        self._pending_preview_mode = None
        self._accepted_preview = None
        self._applying_base_revision = None
        self._apply_save_requested = False
        self._applied_generation = None
        self._applied_project_id = None
        self._applied_revision = None
        self._applied_signature = None
        self._active_path_id = None
        self._identity_policy = "regenerate"
        self._identity_policy_path = None
        self._legacy_conversion_active = False
        self._legacy_conversion_preview = None
        self._allow_close = False
        self._path_change_bypass = False
        self._draft_exit_pending = None
        self._draft_exit_token = None
        self._persisted_draft_generation = None
        self._initial_dirty_signature = None
        self._recovery_load_tokens = {}
        self._recovery_checked_paths = set()
        self._recovery_payloads = {}
        self._recovery_revision_conflict = False
        self.setWindowTitle("反应路径搭建 · 物质关系网")
        self.setMinimumWidth(840)
        self.resize(1180, 760)
        self.network = read_reaction_network(self.project)
        self._base_network = deepcopy(self.network)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        header = QVBoxLayout()
        identity_row = QHBoxLayout()
        identity_row.addWidget(QLabel("整条反应路径 · 组成与能量账本分别编辑"))
        identity_row.addStretch()
        self.path_combo = QComboBox()
        self.path_combo.setMaximumWidth(180)
        for path in self.project.paths:
            self.path_combo.addItem(f"{path.label} · {path.id[:8]}", path.id)
        if path_id is not None:
            selected_path_index = self.path_combo.findData(path_id)
            if selected_path_index >= 0:
                self.path_combo.setCurrentIndex(selected_path_index)
        self.builder_draft = (BuilderDraft.from_project(self.project, self.path_combo.currentData())
                              if self.path_combo.currentData() else None)
        if self.builder_draft is not None:
            self.network = self.builder_draft.network
        identity_row.addWidget(self.path_combo)
        self.path_name = QLineEdit()
        self.path_name.setPlaceholderText("路径名称")
        self.path_name.setMaximumWidth(150)
        identity_row.addWidget(self.path_name)
        self.path_unit = QComboBox()
        self.path_unit.setMaximumWidth(100)
        for unit, title in ((Unit.KCAL_MOL, "kcal/mol"), (Unit.KJ_MOL, "kJ/mol"),
                            (Unit.HARTREE, "Hartree")):
            self.path_unit.addItem(title, unit.value)
        identity_row.addWidget(self.path_unit)
        self.path_color = QLineEdit()
        self.path_color.setPlaceholderText("#RRGGBB")
        self.path_color.setMaximumWidth(85)
        identity_row.addWidget(self.path_color)
        header.addStretch()
        header.addLayout(identity_row)
        options_row = QHBoxLayout()
        self.energy_mode_combo = QComboBox()
        self.energy_mode_combo.setMaximumWidth(220)
        self.energy_mode_combo.addItem("阶段绝对能量账本", "absolute")
        self.energy_mode_combo.addItem("边局部差值递推到统一零点", "edge_recursive")
        options_row.addWidget(self.energy_mode_combo)
        self.new_path_button = QPushButton("新建路径")
        self.new_path_button.setEnabled(not getattr(controller, "read_only", False) and not getattr(controller, "busy", False))
        if getattr(controller, "read_only", False):
            self.new_path_button.setToolTip("当前项目为只读。")
        options_row.addWidget(self.new_path_button)
        self.restore_draft_button = QPushButton(translate("检查恢复草稿…", self.language))
        self.restore_draft_button.setAccessibleName(translate("检查恢复草稿", self.language))
        self.restore_draft_button.setToolTip(translate("检查此项目和路径是否有已保留的未应用草稿。", self.language))
        options_row.addWidget(self.restore_draft_button)
        self.export_draft_button = QPushButton(translate("复制草稿文本…", self.language))
        self.export_draft_button.setAccessibleName(translate("复制未应用草稿文本", self.language))
        self.export_draft_button.setVisible(bool(getattr(controller, "read_only", False)))
        options_row.addWidget(self.export_draft_button)
        options_row.addStretch()
        header.addLayout(options_row)
        root.addLayout(header)

        self.legacy_panel = QWidget()
        legacy_layout = QVBoxLayout(self.legacy_panel)
        legacy_layout.setContentsMargins(0, 6, 0, 6)
        self.legacy_notice = QLabel()
        self.legacy_notice.setWordWrap(True)
        legacy_layout.addWidget(self.legacy_notice)
        self.legacy_nodes = QPlainTextEdit()
        self.legacy_nodes.setReadOnly(True)
        self.legacy_nodes.setMaximumHeight(104)
        legacy_layout.addWidget(self.legacy_nodes)
        legacy_actions = QHBoxLayout()
        self.legacy_convert_button = QPushButton("转换预览…")
        self.legacy_new_path_button = QPushButton("另建可视化路径…")
        self.legacy_jobs_new_path_button = QPushButton("选作业另建路径…")
        self.legacy_continue_button = QPushButton("继续查看原路径")
        self.legacy_expert_button = QPushButton("使用专家表达式…")
        legacy_actions.addWidget(self.legacy_convert_button)
        legacy_actions.addWidget(self.legacy_new_path_button)
        legacy_actions.addWidget(self.legacy_jobs_new_path_button)
        legacy_actions.addWidget(self.legacy_continue_button)
        legacy_actions.addWidget(self.legacy_expert_button)
        legacy_actions.addStretch()
        legacy_layout.addLayout(legacy_actions)
        root.addWidget(self.legacy_panel)

        tabs = QTabWidget()
        self.main_tabs = tabs
        root.addWidget(tabs, 1)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        work = QSplitter(Qt.Orientation.Horizontal)
        editor_layout.addWidget(work, 1)
        library_panel = QWidget()
        library_layout = QVBoxLayout(library_panel)
        library_layout.addWidget(QLabel("物质库 · 同名物质不会自动合并"))
        self.species_list = SpeciesCardList()
        self.species_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.species_list.setDragEnabled(True)
        library_layout.addWidget(self.species_list, 1)
        source_form = QFormLayout()
        self.species_name = QLineEdit()
        self.species_formula = QLineEdit()
        self.species_formula.setPlaceholderText("分子式，如 C6H5NO2；可留空，留空时逐边人工核对")
        self.source_combo = QComboBox()
        self.job_combo = QComboBox()
        self.kind_combo = QComboBox()
        self.binding_combo = QComboBox()
        for kind, label in ((EnergyKind.GIBBS_TOTAL, "Gibbs：同作业 SCF + 热校正"),
                            (EnergyKind.SCF, "SCF Done"),
                            (EnergyKind.GIBBS_CORRECTION, "Gibbs 热校正（单独）")):
            self.kind_combo.addItem(label, kind.value)
        source_form.addRow("物质名", self.species_name)
        source_form.addRow("分子式", self.species_formula)
        source_form.addRow("来源文件", self.source_combo)
        source_form.addRow("Gaussian 作业", self.job_combo)
        source_form.addRow("已选物质的作业绑定", self.binding_combo)
        library_layout.addLayout(source_form)
        add_species = QPushButton("按所选来源/作业新增物质卡")
        add_placeholder = QPushButton("新增无作业物质占位卡")
        add_binding = QPushButton("给选中物质增加来源/作业绑定")
        update_formula = QPushButton("更新所选物质分子式")
        library_layout.addWidget(add_species)
        library_layout.addWidget(add_placeholder)
        library_layout.addWidget(add_binding)
        library_layout.addWidget(update_formula)
        species_actions = QHBoxLayout()
        self.star_button = QPushButton("加星 / 取消星标")
        self.filter_starred = QCheckBox("只看星标")
        species_actions.addWidget(self.star_button)
        species_actions.addWidget(self.filter_starred)
        library_layout.addLayout(species_actions)
        library_scroll = QScrollArea()
        library_scroll.setWidgetResizable(True)
        library_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        library_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        library_scroll.setMinimumWidth(150)
        library_scroll.setWidget(library_panel)
        self.library_panel_scroll = library_scroll
        work.addWidget(library_scroll)

        middle = QWidget()
        middle.setMinimumWidth(300)
        middle_layout = QVBoxLayout(middle)
        middle_layout.addWidget(QLabel("反应阶段 · 布局与能量坐标分开"))
        self.stage_canvas = ReactionCanvas(language=self.language)
        self.stage_list = StageNavigationList(self._snap_to_stage)
        self.stage_list.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.stage_list.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.stage_list.setDropIndicatorShown(True)
        stage_list_panel = QWidget()
        stage_list_layout = QVBoxLayout(stage_list_panel)
        stage_list_layout.addWidget(QLabel("键盘替代列表 · 选择阶段后编辑详情；拖入物质可添加到组成。"))
        stage_list_layout.addWidget(self.stage_list, 1)
        self.stage_views = QTabWidget()
        self.stage_views.addTab(self.stage_canvas, "阶段画布")
        self.stage_views.addTab(stage_list_panel, "阶段列表")
        self.stage_views.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.stage_views.setMinimumWidth(self.stage_canvas.minimumWidth())
        self.advanced_panel = QWidget()
        advanced_outer = QVBoxLayout(self.advanced_panel)
        advanced_scroll = QScrollArea()
        advanced_scroll.setWidgetResizable(True)
        advanced_fields = QWidget()
        self.advanced_fields_layout = QVBoxLayout(advanced_fields)
        advanced_scroll.setWidget(advanced_fields)
        advanced_outer.addWidget(advanced_scroll)
        middle_layout.addWidget(self.stage_views, 1)
        self.composition_list = QListWidget()
        self.composition_list.setMaximumHeight(75)
        self.advanced_fields_layout.addWidget(self.composition_list)
        stage_form = QFormLayout()
        self.equation_label = QLabel("路径反应式待构建")
        self.equation_label.setWordWrap(True)
        stage_form.addRow("整条反应式", self.equation_label)
        self.stage_role = QComboBox()
        for role, name in (("reactant", "反应物"), ("transition_state", "过渡态"),
                           ("intermediate", "中间体"), ("product", "产物")):
            self.stage_role.addItem(name, role)
        self.stage_name = QLineEdit()
        self.missing_transition = QCheckBox("过渡态未找到 · NOT FOUND（无能量值）")
        self.normalization_confirmed = QCheckBox("已核对本阶段组成与统一零点可比")
        self.normalization_note = QLineEdit()
        self.normalization_note.setPlaceholderText("写明补偿物质/计量口径及核对依据")
        self.predecessor_combo = QComboBox()
        self.additional_predecessor_combo = QComboBox()
        self.composition_coefficient = self._coefficient_box()
        self.energy_coefficient = self._coefficient_box()
        self.system_mode = QComboBox()
        self.system_mode.addItem("独立组分", "component")
        self.system_mode.addItem("完整体系作业", "complete_system")
        self.reason = QLineEdit("用户确认的阶段能量组成")
        stage_form.addRow("阶段角色", self.stage_role)
        stage_form.addRow("阶段标签", self.stage_name)
        stage_form.addRow("缺值占位", self.missing_transition)
        stage_form.addRow("组成核对", self.normalization_confirmed)
        stage_form.addRow("核对说明", self.normalization_note)
        stage_form.addRow("局部前驱（势垒参考）", self.predecessor_combo)
        stage_form.addRow("增加合流前驱", self.additional_predecessor_combo)
        stage_form.addRow("反应式计量系数", self.composition_coefficient)
        stage_form.addRow("能量项系数（可正可负）", self.energy_coefficient)
        stage_form.addRow("能量项口径", self.system_mode)
        stage_form.addRow("能量项原因", self.reason)
        self.advanced_fields_layout.addLayout(stage_form)
        connection_form = QFormLayout()
        self.connection_list = QListWidget()
        self.connection_list.setMaximumHeight(78)
        self.connection_confirmed = QCheckBox("已逐边核对组成、补偿项与共同参考")
        self.connection_note = QLineEdit()
        self.connection_note.setPlaceholderText("记录此反应边的核对依据")
        connection_form.addRow("当前阶段入边", self.connection_list)
        connection_form.addRow("逐边确认", self.connection_confirmed)
        connection_form.addRow("边核对说明", self.connection_note)
        self.edge_side_combo = QComboBox()
        self.edge_side_combo.addItem("反应物侧", "reactants")
        self.edge_side_combo.addItem("产物侧", "products")
        self.edge_stoich_list = QListWidget()
        self.edge_stoich_list.setMaximumHeight(74)
        self.add_edge_stoich_button = QPushButton("将选中物质加入所选边的一侧")
        self.update_edge_stoich_button = QPushButton("更新边计量系数")
        self.remove_edge_stoich_button = QPushButton("移除所选边计量项")
        connection_form.addRow("编辑边的计量侧", self.edge_side_combo)
        connection_form.addRow("边级反应式计量", self.edge_stoich_list)
        connection_form.addRow(self.add_edge_stoich_button)
        edge_stoich_actions = QHBoxLayout()
        edge_stoich_actions.addWidget(self.update_edge_stoich_button)
        edge_stoich_actions.addWidget(self.remove_edge_stoich_button)
        connection_form.addRow(edge_stoich_actions)
        self.advanced_fields_layout.addLayout(connection_form)
        stage_actions = QHBoxLayout()
        self.add_stage_button = QPushButton("用选中物质新建阶段")
        self.update_stage_button = QPushButton("更新阶段标签/角色/前驱")
        self.add_predecessor_button = QPushButton("添加另一条前驱边")
        self.confirm_connection_button = QPushButton("确认 / 更新所选反应边")
        self.remove_connection_button = QPushButton("删除所选入边")
        self.add_terms_button = QPushButton("给所选阶段 / 反应边加入能量项")
        self.update_term_button = QPushButton("更新选中能量项")
        self.update_composition_button = QPushButton("更新所选计量")
        self.remove_composition_button = QPushButton("移除所选物质")
        self.remove_term_button = QPushButton("删除选中能量项")
        self.remove_stage_button = QPushButton("删除阶段")
        stage_actions.addWidget(self.add_stage_button)
        stage_actions.addWidget(self.update_stage_button)
        stage_actions.addWidget(self.add_predecessor_button)
        stage_actions.addWidget(self.confirm_connection_button)
        stage_actions.addWidget(self.remove_connection_button)
        stage_actions.addWidget(self.remove_stage_button)
        self.advanced_fields_layout.addLayout(stage_actions)
        composition_actions = QHBoxLayout()
        composition_actions.addWidget(self.update_composition_button)
        composition_actions.addWidget(self.remove_composition_button)
        self.advanced_fields_layout.addLayout(composition_actions)
        self.ledger_list = SnapList(self._snap_to_ledger)
        self.ledger_list.setMaximumHeight(110)
        self.advanced_fields_layout.addWidget(self.ledger_list)
        term_actions = QHBoxLayout()
        term_actions.addWidget(self.add_terms_button)
        term_actions.addWidget(self.update_term_button)
        term_actions.addWidget(self.remove_term_button)
        self.advanced_fields_layout.addLayout(term_actions)
        self.stage_views.addTab(self.advanced_panel, "详细编辑")
        work.addWidget(middle)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.right_tabs = QTabWidget()
        self.stage_inspector = ReactionStageInspector(language=self.language)
        self.right_tabs.addTab(self.stage_inspector, "选中详情")
        preview_page = QWidget()
        preview_layout = QVBoxLayout(preview_page)
        preview_layout.addWidget(QLabel("零点、关系邻居与计算预览"))
        self.zero_combo = QComboBox()
        self.zero_combo.addItem("反应物总能量（默认零点）", ("reactant", ""))
        preview_layout.addWidget(self.zero_combo)
        self.custom_zero = QLineEdit()
        self.custom_zero.setPlaceholderText("自定义参考表达式，例如 @{A} + @{B}")
        preview_layout.addWidget(self.custom_zero)
        self.manual_zero = QDoubleSpinBox()
        self.manual_zero.setRange(-1e9, 1e9)
        self.manual_zero.setDecimals(12)
        self.manual_unit = QComboBox()
        for unit, name in ((Unit.HARTREE, "Hartree"), (Unit.KCAL_MOL, "kcal/mol"), (Unit.KJ_MOL, "kJ/mol")):
            self.manual_unit.addItem(name, unit.value)
        manual_row = QHBoxLayout()
        manual_row.addWidget(self.manual_zero)
        manual_row.addWidget(self.manual_unit)
        preview_layout.addLayout(manual_row)
        preview_layout.addWidget(QLabel("物质直接关系"))
        self.relation_target = QComboBox()
        self.relation_kind = QComboBox()
        self.relation_kind.addItem("前驱", "precursor")
        self.relation_kind.addItem("后继", "successor")
        self.add_edge_button = QPushButton("连接选中物质 → 邻居")
        self.edge_list = QListWidget()
        self.edge_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.remove_edge_button = QPushButton("删除所选关系边")
        self.deploy_edge_button = QPushButton("按所选关系边加入邻居阶段")
        preview_layout.addWidget(self.relation_target)
        preview_layout.addWidget(self.relation_kind)
        preview_layout.addWidget(self.add_edge_button)
        preview_layout.addWidget(self.edge_list, 1)
        preview_layout.addWidget(self.remove_edge_button)
        preview_layout.addWidget(self.deploy_edge_button)
        self.flow_status = QLabel(translate("选择阶段和零点，然后检查能量。", self.language))
        self.flow_status.setWordWrap(True)
        preview_layout.addWidget(self.flow_status)
        self.diagnostics_list = QListWidget()
        self.diagnostics_list.setMaximumHeight(120)
        self.diagnostics_list.itemClicked.connect(self._focus_preview_diagnostic)
        preview_layout.addWidget(self.diagnostics_list)
        self.preview = QLabel(translate("选择阶段、来源作业和零点后预览。", self.language))
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview_layout.addWidget(self.preview, 1)
        self.right_tabs.addTab(preview_page, "零点与预览")
        right_layout.addWidget(self.right_tabs)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setMinimumWidth(220)
        right_scroll.setWidget(right)
        self.right_panel_scroll = right_scroll
        work.addWidget(right_scroll)
        work.setChildrenCollapsible(False)
        work.setSizes([190, 360, 270])
        tabs.addTab(editor, "整条反应式与相对能量")

        evidence = QWidget()
        evidence_layout = QVBoxLayout(evidence)
        self.evidence = QLabel("选中物质卡查看作业编号、终止状态、能量候选和来源行。")
        self.evidence.setWordWrap(True)
        self.evidence.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        evidence_layout.addWidget(self.evidence)
        evidence_layout.addStretch()
        self.evidence_page = evidence
        tabs.addTab(evidence, "来源证据与关系网")

        footer = QHBoxLayout()
        self.undo_button = QPushButton("撤销")
        self.redo_button = QPushButton("重做")
        footer.addWidget(self.undo_button)
        footer.addWidget(self.redo_button)
        self.apply_button = QPushButton(translate("应用并保存", self.language))
        self.apply_menu_button = QToolButton()
        self.apply_menu_button.setText(translate("更多操作", self.language))
        self.apply_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.apply_menu = QMenu(self.apply_menu_button)
        self.apply_only_action = self.apply_menu.addAction(translate("仅应用到当前项目", self.language))
        self.apply_menu.addSeparator()
        self.preview_action = self.apply_menu.addAction(translate("预览计算", self.language))
        self.save_network_action = self.apply_menu.addAction(translate("仅保存物质与关系网…", self.language))
        self.save_file_action = self.apply_menu.addAction(translate("仅保存到项目文件…", self.language))
        self.apply_menu_button.setMenu(self.apply_menu)
        self.preview_button = QPushButton(translate("预览计算", self.language))
        self.save_network_button = QPushButton("仅保存物质与关系网")
        self.save_file_button = QPushButton("保存到项目文件…")
        self.cancel_button = QPushButton("取消")
        footer.addWidget(self.apply_button)
        footer.addWidget(self.apply_menu_button)
        footer.addWidget(self.preview_button)
        footer.addWidget(self.save_network_button)
        footer.addWidget(self.save_file_button)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        root.addLayout(footer)

        self.source_combo.currentIndexChanged.connect(self._update_jobs)
        add_species.clicked.connect(self._add_species)
        add_placeholder.clicked.connect(self._add_placeholder_species)
        add_binding.clicked.connect(self._add_binding)
        update_formula.clicked.connect(self._update_formula)
        self.star_button.clicked.connect(self._toggle_star)
        self.filter_starred.toggled.connect(self._render_species)
        self.species_list.currentItemChanged.connect(self._show_evidence)
        self.species_list.itemSelectionChanged.connect(self._selection_changed)
        self.add_stage_button.clicked.connect(self._add_stage)
        self.update_stage_button.clicked.connect(self._update_stage)
        self.add_predecessor_button.clicked.connect(self._add_stage_predecessor)
        self.confirm_connection_button.clicked.connect(self._confirm_connection)
        self.remove_connection_button.clicked.connect(self._remove_connection)
        self.add_terms_button.clicked.connect(self._add_terms)
        self.update_term_button.clicked.connect(self._update_term)
        self.remove_stage_button.clicked.connect(self._remove_stage)
        self.update_composition_button.clicked.connect(self._update_composition)
        self.remove_composition_button.clicked.connect(self._remove_composition)
        self.remove_term_button.clicked.connect(self._remove_term)
        self.stage_list.currentItemChanged.connect(self._update_zero_points)
        self.stage_list.currentItemChanged.connect(self._render_ledger)
        self.stage_list.currentItemChanged.connect(self._render_composition)
        self.stage_list.currentItemChanged.connect(self._load_stage_fields)
        self.stage_list.currentItemChanged.connect(self._render_connections)
        self.stage_list.currentItemChanged.connect(self._stage_list_selection_changed)
        self.connection_list.currentItemChanged.connect(self._load_connection_fields)
        self.connection_list.currentItemChanged.connect(self._render_ledger)
        self.connection_list.currentItemChanged.connect(self._render_edge_stoich)
        self.connection_list.currentItemChanged.connect(self._inspect_connection)
        self.edge_side_combo.currentIndexChanged.connect(self._render_edge_stoich)
        self.add_edge_stoich_button.clicked.connect(self._add_edge_stoich)
        self.update_edge_stoich_button.clicked.connect(self._update_edge_stoich)
        self.remove_edge_stoich_button.clicked.connect(self._remove_edge_stoich)
        self.stage_canvas.commandRequested.connect(self._execute_draft_command)
        self.stage_canvas.selectionRequested.connect(self._canvas_selection_requested)
        self.stage_canvas.dropRejected.connect(self._error)
        self.stage_list.enterPressed.connect(self._open_stage_details_from_keyboard)
        self.stage_list.deletePressed.connect(self._remove_stage)
        self.species_list.tabForwardPressed.connect(self.stage_list.setFocus)
        self.species_list.tabBackwardPressed.connect(self.cancel_button.setFocus)
        self.stage_list.tabForwardPressed.connect(self._open_stage_details_from_keyboard)
        self.stage_list.tabBackwardPressed.connect(self.species_list.setFocus)
        self.stage_inspector.commandRequested.connect(self._execute_draft_command)
        self.undo_button.clicked.connect(self._undo_builder)
        self.redo_button.clicked.connect(self._redo_builder)
        self.add_edge_button.clicked.connect(self._add_edge)
        self.remove_edge_button.clicked.connect(self._remove_edge)
        self.deploy_edge_button.clicked.connect(self._deploy_edge)
        self.new_path_button.clicked.connect(self._new_path)
        self.restore_draft_button.clicked.connect(self._restore_draft_clicked)
        self.export_draft_button.clicked.connect(self._copy_draft_text)
        self.legacy_convert_button.clicked.connect(self._convert_legacy)
        self.legacy_new_path_button.clicked.connect(self._convert_legacy_to_new_path)
        self.legacy_jobs_new_path_button.clicked.connect(self._propose_new_path_from_jobs)
        self.legacy_continue_button.clicked.connect(self._show_legacy_overview)
        self.legacy_expert_button.clicked.connect(self._open_legacy_expression)
        self.zero_combo.currentIndexChanged.connect(self._zero_mode_changed)
        self.custom_zero.editingFinished.connect(self._set_zero_point_from_controls)
        self.manual_zero.editingFinished.connect(self._set_zero_point_from_controls)
        self.manual_unit.currentIndexChanged.connect(self._set_zero_point_from_controls)
        self.path_combo.currentIndexChanged.connect(self._path_selection_changed)
        self.energy_mode_combo.currentIndexChanged.connect(self._set_energy_mode)
        self.kind_combo.currentIndexChanged.connect(self._set_energy_kind)
        self.apply_button.clicked.connect(self._apply_and_save)
        self.apply_only_action.triggered.connect(self._apply_only)
        self.preview_action.triggered.connect(self._show_preview)
        self.save_network_action.triggered.connect(self._save_network)
        self.save_file_action.triggered.connect(self._save_file)
        self.preview_button.clicked.connect(self._show_preview)
        self.save_network_button.clicked.connect(self._save_network)
        self.save_file_button.clicked.connect(self._save_file)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self.apply_save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.apply_save_shortcut.activated.connect(self._apply_and_save)
        for widget, name in (
                (self.species_list, "物质列表"), (self.stage_list, "反应阶段列表"),
                (self.stage_inspector.stage_name, "阶段标签"),
                (self.stage_inspector.stage_role, "阶段角色"),
                (self.diagnostics_list, "能量检查问题清单"),
                (self.apply_button, "应用反应路径并保存项目"),
                (self.apply_menu_button, "更多反应路径操作"),
                (self.preview_button, "预览反应路径计算"),
                (self.undo_button, "撤销本搭建器中的上一步编辑"),
                (self.redo_button, "重做本搭建器中的下一步编辑"),
                (self.cancel_button, "关闭反应路径搭建器"),
                (self.restore_draft_button, "检查并恢复未应用草稿"),
                (self.export_draft_button, "复制未应用草稿文本")):
            widget.setAccessibleName(translate(name, self.language))
        self.stage_list.setToolTip(translate(
            "方向键选择阶段；Enter 查看详情；Delete 删除所选阶段（可撤销）。", self.language))
        self.undo_button.setToolTip(translate("只撤销当前搭建器草稿，不修改项目撤销历史。", self.language))
        self.redo_button.setToolTip(translate("只重做当前搭建器草稿，不修改项目撤销历史。", self.language))
        self.setTabOrder(self.species_list, self.stage_list)
        self.setTabOrder(self.stage_list, self.stage_inspector.stage_name)
        self.setTabOrder(self.diagnostics_list, self.apply_button)
        self.setTabOrder(self.apply_button, self.apply_menu_button)
        self.setTabOrder(self.apply_menu_button, self.preview_button)
        self.setTabOrder(self.preview_button, self.cancel_button)
        self.controller.busyChanged.connect(self._busy_changed)
        self.controller.failed.connect(self._controller_failed)
        if hasattr(self.controller, "builderDraftFinished"):
            self.controller.builderDraftFinished.connect(self._builder_draft_finished)
        if hasattr(self.controller, "reactionPreviewReady"):
            self.controller.reactionPreviewReady.connect(self._reaction_preview_ready)
        if hasattr(self.controller, "operationFinished"):
            self.controller.operationFinished.connect(self._operation_finished)
        for source in self.project.source_files:
            self.source_combo.addItem(f"{source.display_name} · {source.id[:8]}", source.id)
        self._update_jobs()
        self._render_species()
        self._load_recipe()
        if focus_node_id or focus_entry_id:
            self._focus_associated_species(focus_node_id, focus_entry_id)
        if create_new_path:
            path_label = translate("新建路径", getattr(parent, "language", "zh_CN"))
            self._new_path(name=f"{path_label} {len(self.project.paths) + 1}")
        if candidate_cards:
            self.network = propose_imported_job_cards(self.project, self.network, candidate_cards)
            if self.builder_draft is not None:
                self.builder_draft.network = self.network
                self.builder_draft._undo_states.clear()
                self.builder_draft._redo_states.clear()
            if self._draft_new_path is not None:
                self.network["path_reactions"] = [item for item in self.network["path_reactions"]
                                                   if item["path_id"] != self._draft_new_path.id]
            self._base_network = deepcopy(read_reaction_network(self.project))
            self._render_species()
            self.preview.setText("已把明确选择的作业加入物质卡草稿；尚未创建阶段或反应边。选择阶段后再预览/应用，或使用“仅保存物质与关系网”保存这些卡片。")
        self._initialize_apply_state()
        self._sync_flow_controls()
        self._initial_dirty_signature = self._draft_dirty_signature()
        self._capture_language_sources()

    def _capture_language_sources(self):
        dynamic_widgets = {self.flow_status, self.preview, self.evidence, self.equation_label,
                           self.legacy_notice}
        self._language_text_sources = []
        self._language_placeholder_sources = []
        self._language_combo_sources = []
        self._language_tab_sources = []
        self._language_accessible_sources = []
        self._language_tooltip_sources = []
        for widget in self.findChildren(QWidget):
            if widget is self.stage_inspector or self.stage_inspector.isAncestorOf(widget):
                continue
            if isinstance(widget, QLabel) and widget not in dynamic_widgets:
                self._language_text_sources.append((widget, source_text(widget.text(), self.language)))
            elif isinstance(widget, (QPushButton, QToolButton)):
                self._language_text_sources.append((widget, source_text(widget.text(), self.language)))
            elif isinstance(widget, QCheckBox):
                self._language_text_sources.append((widget, source_text(widget.text(), self.language)))
            if isinstance(widget, QLineEdit) and widget.placeholderText():
                self._language_placeholder_sources.append(
                    (widget, source_text(widget.placeholderText(), self.language)))
            elif isinstance(widget, QComboBox):
                self._language_combo_sources.append((widget, [
                    source_text(widget.itemText(index), self.language)
                    for index in range(widget.count())]))
            accessible_name = widget.accessibleName()
            if accessible_name:
                self._language_accessible_sources.append(
                    (widget, source_text(accessible_name, self.language)))
            tooltip = widget.toolTip()
            if tooltip and widget is not self.stage_canvas:
                self._language_tooltip_sources.append((widget, source_text(tooltip, self.language)))
        self._language_tab_sources = [
            (tabs, [source_text(tabs.tabText(index), self.language)
                    for index in range(tabs.count())])
            for tabs in self.findChildren(QTabWidget)]
        self._language_dynamic_sources = [
            (widget, source_text(widget.text(), self.language)) for widget in dynamic_widgets]
        self._language_window_title_source = source_text(self.windowTitle(), self.language)

    def set_language(self, language):
        if language not in {"zh_CN", "en"} or language == self.language:
            return
        previous_language = self.language
        dynamic_sources = [(widget, source_text(widget.text(), self.language))
                           for widget, _source in self._language_dynamic_sources]
        self.language = language
        self.setWindowTitle(translate(self._language_window_title_source, language))
        for widget, source in self._language_text_sources:
            widget.setText(translate(source, language))
        for widget, source in self._language_placeholder_sources:
            widget.setPlaceholderText(translate(source, language))
        for combo, sources in self._language_combo_sources:
            for index in range(combo.count()):
                source = (sources[index] if index < len(sources) else
                          source_text(combo.itemText(index), previous_language))
                combo.setItemText(index, translate(source, language))
        for tabs, sources in self._language_tab_sources:
            for index in range(min(tabs.count(), len(sources))):
                tabs.setTabText(index, translate(sources[index], language))
        for widget, source in self._language_accessible_sources:
            widget.setAccessibleName(translate(source, language))
        for widget, source in self._language_tooltip_sources:
            widget.setToolTip(translate(source, language))
        for widget, source in dynamic_sources:
            widget.setText(translate(source, language))
        self.stage_canvas.set_language(language)
        self.stage_inspector.set_language(language)
        self._set_flow_state(self._flow_state)
        self._sync_flow_controls()

    @staticmethod
    def _coefficient_box():
        box = QDoubleSpinBox()
        box.setRange(-1000, 1000)
        box.setDecimals(6)
        box.setValue(1)
        return box

    def _update_jobs(self, *_):
        self.job_combo.clear()
        source = next((item for item in self.project.source_files if item.id == self.source_combo.currentData()), None)
        if source:
            for job in source.jobs:
                states = "正常结束" if job.termination.value == "normal" else job.termination.value
                self.job_combo.addItem(f"作业 {job.ordinal + 1} · {states} · 行 {job.start_line}-{job.end_line}", job.id)

    def _add_species(self):
        source_id, job_id = self.source_combo.currentData(), self.job_combo.currentData()
        source = next((item for item in self.project.source_files if item.id == source_id), None)
        job = next((item for item in source.jobs if item.id == job_id), None) if source else None
        name = self.species_name.text().strip()
        if not source or not job or not name:
            self._error("先填写物质名并明确选择来源文件和 Gaussian 作业。")
            return
        if not any(select_job(source, kind, job_id=job.id).available for kind in EnergyKind):
            self._error("该作业没有可用的能量候选；不可为缺失值创建可计算物质。")
            return
        formula = self._validated_formula()
        if formula is False:
            return
        if self._execute_draft_command({"type": "add_species", "species": {
                "id": new_id(), "name": name, "formula": formula, "starred": False,
                "bindings": [{"source_file_id": source.id, "job_id": job.id, "historical": False}]}}):
            self.species_name.clear()
            self.species_formula.clear()

    def _add_placeholder_species(self):
        name = self.species_name.text().strip()
        if not name:
            self._error("先填写待核查的物质名称；无作业物质只能用于 NOT FOUND 占位或关系网。")
            return
        formula = self._validated_formula()
        if formula is False:
            return
        if self._execute_draft_command({"type": "add_species", "species": {
                "id": new_id(), "name": name, "formula": formula, "starred": False, "bindings": []}}):
            self.species_name.clear()
            self.species_formula.clear()

    def _validated_formula(self):
        formula = self.species_formula.text().strip()
        if formula:
            try:
                from ..core.reaction_network import parse_molecular_formula
                parse_molecular_formula(formula)
            except ValueError as error:
                self._error(str(error))
                return False
        return formula

    def _validate_draft_network(self):
        draft = deepcopy(self.network)
        recipe = next((item for item in draft["path_reactions"]
                       if item["path_id"] == self.path_combo.currentData()), None)
        if recipe and recipe["stages"]:
            zero = recipe.get("zero_point", {})
            if zero.get("kind") in {"reactant", "stage"} and zero.get("stage_id") not in {
                    stage["id"] for stage in recipe["stages"]}:
                reference = next((stage for stage in recipe["stages"] if stage["role"] == "reactant"),
                                 recipe["stages"][0])
                recipe["zero_point"] = {"kind": "reactant" if reference["role"] == "reactant" else "stage",
                                         "stage_id": reference["id"]}
        return validate_network(draft, self.project, allow_unmaterialized=True)

    @staticmethod
    def _check_stage_dag(recipe):
        stages = {stage["id"]: stage for stage in recipe["stages"]}
        remaining = {identifier: set(stage.get("predecessor_stage_ids", []))
                     for identifier, stage in stages.items()}
        emitted = set()
        while remaining:
            ready = [identifier for identifier, parents in remaining.items() if parents <= emitted]
            if not ready:
                raise ValueError("Stage graph contains a cycle")
            for identifier in ready:
                emitted.add(identifier)
                del remaining[identifier]

    def _update_formula(self):
        selected = self._selected_species()
        if len(selected) != 1:
            self._error("请选择一张物质卡后更新分子式。")
            return
        formula = self._validated_formula()
        if formula is False:
            return
        if self._execute_draft_command({"type": "update_species", "species_id": selected[0],
                                        "fields": {"formula": formula}}):
            self._show_evidence(self.species_list.currentItem())

    def _selected_species(self):
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.species_list.selectedItems()]

    def _selection_changed(self):
        selected = self.species_list.selectedItems()
        if len(selected) == 1:
            self._show_evidence(selected[0])
            identifier = selected[0].data(Qt.ItemDataRole.UserRole)
            species = next((item for item in self.network["species"] if item["id"] == identifier), None)
            self.species_formula.setText((species or {}).get("formula", ""))
        elif len(selected) != 1:
            self.binding_combo.clear()
        self._render_edges()

    def _add_binding(self):
        selected = self._selected_species()
        source_id, job_id = self.source_combo.currentData(), self.job_combo.currentData()
        if len(selected) != 1 or not source_id or not job_id:
            self._error("请选择一张物质卡以及要关联的具体来源和作业。")
            return
        species = next(item for item in self.network["species"] if item["id"] == selected[0])
        if any(binding["source_file_id"] == source_id and binding["job_id"] == job_id
               for binding in species["bindings"]):
            self._error("该来源与作业已绑定到这张物质卡。")
            return
        bindings = deepcopy(species["bindings"])
        bindings.append({"source_file_id": source_id, "job_id": job_id, "historical": False})
        if self._execute_draft_command({"type": "update_species", "species_id": species["id"],
                                        "fields": {"bindings": bindings}}):
            self._show_evidence(self.species_list.currentItem())

    def _render_species(self):
        selected = set(self._selected_species())
        self.species_list.clear()
        for species in sorted(self.network["species"], key=lambda item: (not item["starred"], item["name"].casefold(), item["id"])):
            if self.filter_starred.isChecked() and not species["starred"]:
                continue
            status = "★" if species["starred"] else "☆"
            item = QListWidgetItem(f"{status} {species['name']} · {species['id'][:8]}")
            item.setData(Qt.ItemDataRole.UserRole, species["id"])
            bindings = species["bindings"]
            item.setToolTip("\n".join(f"{binding['source_file_id'][:8]} / 作业 {binding['job_id'][:8]}" for binding in bindings))
            self.species_list.addItem(item)
            if species["id"] in selected:
                item.setSelected(True)
        self.relation_target.clear()
        for species in self.network["species"]:
            self.relation_target.addItem(species["name"] + " · " + species["id"][:8], species["id"])
        self._render_edges()

    def _toggle_star(self):
        identifiers = set(self._selected_species())
        if len(identifiers) != 1:
            self._error("请选择一张具体物质卡后再加星或取消星标。")
            return
        species_id = next(iter(identifiers))
        species = next(item for item in self.network["species"] if item["id"] == species_id)
        self._execute_draft_command({"type": "set_star", "species_id": species_id,
                                     "starred": not species["starred"]})

    def _show_evidence(self, item, *_):
        self.binding_combo.clear()
        if not item:
            return
        species = next((entry for entry in self.network["species"] if entry["id"] == item.data(Qt.ItemDataRole.UserRole)), None)
        if not species:
            return
        records = []
        direct_edges = [edge for edge in self.network["edges"] if species["id"] in
                        (edge["source_species_id"], edge["target_species_id"])]
        linked_nodes = [link for link in self.network["node_links"] if species["id"] in link["species_ids"]]
        records.append(f"物质 UUID：{species['id']}\n分子式：{species.get('formula') or '未填写（此物质参与的计量边需人工核对）'}\n直接关系边：{len(direct_edges)}；关联节点：{len(linked_nodes)}")
        for binding in species["bindings"]:
            source = next((value for value in self.project.source_files if value.id == binding["source_file_id"]), None)
            job = next((value for value in source.jobs if value.id == binding["job_id"]), None) if source else None
            if not source or not job:
                records.append(f"失效历史绑定：{binding['source_file_id']} / {binding['job_id']}")
                continue
            self.binding_combo.addItem(f"{source.display_name} / 作业 {job.ordinal + 1} · {job.id[:8]}",
                                       (source.id, job.id))
            records.append(f"{source.display_name}\n路径：{source.original_path}\nSHA-256：{source.sha256}\n"
                f"作业 {job.ordinal + 1}，行 {job.start_line}-{job.end_line}，终止：{job.termination.value}")
            for kind, energy in job.energies.items():
                records.append(f"{kind.value}: {energy.value_hartree:.12f} Eh · 行 {energy.source_line}")
            total = select_job(source, EnergyKind.GIBBS_TOTAL, job_id=job.id)
            records.append("Gibbs (SCF + 热校正): " + (f"{total.energy.value_hartree:.12f} Eh" if total.available else "不可用：缺少同作业加数"))
        self.evidence.setText("\n\n".join(records) or "此物质尚无关联作业")

    def _add_stage(self, species_ids=None):
        selected = list(species_ids) if isinstance(species_ids, list) else self._selected_species()
        if not selected:
            self._error("先选择一个或多个明确物质，再添加阶段。")
            return
        label = self.stage_name.text().strip() or " + ".join(
            item["name"] for item in self.network["species"] if item["id"] in selected)
        stage = {"id": new_id(), "role": self.stage_role.currentData(), "label": label,
            "predecessor_stage_id": self.predecessor_combo.currentData(),
            "predecessor_stage_ids": ([self.predecessor_combo.currentData()]
                                       if self.predecessor_combo.currentData() else []),
            "species": [{"species_id": identifier, "coefficient": self.composition_coefficient.value()} for identifier in selected],
            "terms": [], "confirm_additional_terms": False, "node_id": None, "entry_id": None,
            "historical": False, "missing": self.missing_transition.isChecked(),
            "normalization_confirmed": False, "normalization_note": ""}
        if stage["missing"] and stage["role"] != "transition_state":
            self._error("NOT FOUND 只用于尚未找到的过渡态。")
            return
        if self._execute_draft_command({"type": "add_stage", "stage": stage}):
            self.stage_name.clear()

    def _snap_to_stage(self, species_ids, stage_id):
        known = {species["id"] for species in self.network["species"]}
        if not isinstance(species_ids, list) or not species_ids or not set(species_ids) <= known:
            self._error("拖入的物质卡身份不属于当前项目。")
            return
        if stage_id is None:
            self._add_stage(species_ids)
            return
        stage = next((item for item in self._current_recipe()["stages"] if item["id"] == stage_id), None)
        if stage is None:
            self._error("目标阶段已失效。")
            return
        existing = {component["species_id"] for component in stage["species"]}
        composition = deepcopy(stage["species"])
        for identifier in species_ids:
            if identifier not in existing:
                composition.append({"species_id": identifier,
                                    "coefficient": self.composition_coefficient.value()})
        if composition != stage["species"] and self._execute_draft_command({
                "type": "set_composition", "stage_id": stage_id, "species": composition}):
            self.preview.setText("物质已加入阶段组成；能量账本仍需明确选择作业与系数。")

    def _snap_to_ledger(self, species_ids, _item_id):
        if not isinstance(species_ids, list):
            self._error("拖入的能量物质卡无效。")
            return
        self._add_terms(species_ids)

    def _update_stage(self):
        stage = self._current_stage()
        if stage is None:
            self._error("请先选择要编辑的阶段。")
            return
        predecessor = self.predecessor_combo.currentData()
        if predecessor == stage["id"]:
            self._error("阶段不能以自身为局部前驱。")
            return
        role = self.stage_role.currentData()
        missing = self.missing_transition.isChecked()
        if missing and role != "transition_state":
            self._error("NOT FOUND 只用于尚未找到的过渡态。")
            return
        if missing and stage["terms"]:
            self._error("已有关联能量项的阶段不能标为 NOT FOUND；请先移除能量项。")
            return
        old_parents = BuilderDraft._parent_ids(stage)
        extras = [value for value in old_parents
                  if value != stage.get("predecessor_stage_id") and value != predecessor]
        new_parents = ([predecessor] if predecessor else []) + extras
        science_changed = (role != stage["role"] or missing != stage.get("missing", False) or
                           set(new_parents) != set(old_parents))
        fields = {"role": role, "missing": missing,
                  "label": self.stage_name.text().strip() or stage["label"],
                  "predecessor_stage_ids": new_parents}
        if not science_changed:
            fields["normalization_confirmed"] = self.normalization_confirmed.isChecked()
            fields["normalization_note"] = self.normalization_note.text().strip()
        self._execute_draft_command({"type": "update_stage", "stage_id": stage["id"], "fields": fields})

    def _add_stage_predecessor(self):
        stage = self._current_stage()
        predecessor = self.additional_predecessor_combo.currentData()
        if stage is None or predecessor is None:
            self._error("先选择当前阶段和一条候选前驱阶段。")
            return
        parents = BuilderDraft._parent_ids(stage)
        if predecessor == stage["id"] or predecessor in parents:
            self._error("该前驱无效或已经连接。")
            return
        self._execute_draft_command({"type": "add_connection",
                                     "connection": self._new_stage_connection(predecessor, stage["id"])})

    def _add_terms(self, species_ids=None):
        stage = self._current_stage()
        selected = list(species_ids) if isinstance(species_ids, list) else self._selected_species()
        if not stage or not selected:
            self._error("选择一个阶段和一个或多个物质，才能加入能量账本。")
            return
        target = self._selected_ledger_target()
        if target is None:
            self._error("递推模式下，请先选择当前阶段的一条入边；根阶段使用阶段账本。")
            return
        if stage.get("missing"):
            self._error("NOT FOUND 过渡态没有可计算的能量项；先取消缺值占位再添加作业。")
            return
        kind = self.kind_combo.currentData()
        proposed = []
        for identifier in selected:
            species = next((item for item in self.network["species"] if item["id"] == identifier), None)
            if species is None:
                self._error("拖入的物质卡身份不属于当前项目。")
                return
            live_bindings = [item for item in species["bindings"] if not item["historical"]]
            if len(selected) == 1:
                selected_pair = self.binding_combo.currentData()
                binding = next((item for item in live_bindings if
                    (item["source_file_id"], item["job_id"]) == selected_pair), None)
                if binding is None and len(live_bindings) == 1:
                    binding = live_bindings[0]
            else:
                binding = live_bindings[0] if len(live_bindings) == 1 else None
            if binding is None:
                self._error(f"{species['name']} 的来源/作业绑定不明确；请逐张物质选择作业并加入账本。")
                return
            source = next((item for item in self.project.source_files if item.id == binding["source_file_id"]), None)
            selection = select_job(source, EnergyKind(kind), job_id=binding["job_id"]) if source else None
            if not selection or not selection.available:
                self._error(f"{species['name']} 的明确作业缺少 {kind}；不会自动换作业。")
                return
            proposed.append({"species_id": identifier, "source_file_id": binding["source_file_id"],
                "job_id": binding["job_id"], "energy_kind": kind, "coefficient": self.energy_coefficient.value(),
                "system_mode": self.system_mode.currentData(), "reason": self.reason.text().strip() or "用户确认",
                "historical": False})
        ledger = target.get("terms", []) if target is not stage else stage["terms"]
        combined = [*ledger, *proposed]
        confirm_additional = False
        if target is stage and any(term["system_mode"] == "complete_system" for term in combined) and len(combined) > 1:
            answer = QMessageBox.question(self, "完整体系与附加能量项", "当前阶段将同时使用完整体系作业和其他能量项。已逐项确认不会重复计算？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            confirm_additional = answer == QMessageBox.StandardButton.Yes
            if not confirm_additional:
                return
        if target is stage:
            command = {"type": "set_energy_terms", "stage_id": stage["id"], "terms": combined}
            if confirm_additional:
                command["confirm_additional_terms"] = True
        else:
            command = {"type": "update_connection", "connection_id": target["id"],
                       "fields": {"terms": combined}}
        self._execute_draft_command(command)

    def _selected_ledger_target(self):
        stage = self._current_stage()
        if stage is None:
            return None
        recipe = self._current_recipe()
        if recipe.get("energy_mode", "absolute") != "edge_recursive" or not stage.get("predecessor_stage_ids"):
            return stage
        item = self.connection_list.currentItem()
        edge_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((edge for edge in recipe.get("connections", []) if edge["id"] == edge_id), None)

    def _set_energy_mode(self, *_):
        mode = self.energy_mode_combo.currentData() or "absolute"
        self._execute_draft_command({"type": "set_path_options", "path_options": {"energy_mode": mode}})

    def _set_energy_kind(self, *_):
        kind = self.kind_combo.currentData() or EnergyKind.GIBBS_TOTAL.value
        self._execute_draft_command({"type": "set_path_options", "path_options": {"energy_kind": kind}})

    def _render_ledger(self, *_):
        self.ledger_list.clear()
        stage = self._current_stage()
        if not stage:
            return
        target = self._selected_ledger_target()
        if target is None:
            return
        names = {item["id"]: item["name"] for item in self.network["species"]}
        terms = target.get("terms", []) if target is not stage else stage["terms"]
        for index, term in enumerate(terms):
            item = QListWidgetItem(f"{term['coefficient']:+g} × {names.get(term['species_id'], '?')} · "
                f"{term['energy_kind']} · {term['system_mode']} · 作业 {term['job_id'][:8]} · {term['reason']}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.ledger_list.addItem(item)

    def _render_composition(self, *_):
        self.composition_list.clear()
        stage = self._current_stage()
        if stage is None:
            return
        names = {item["id"]: item["name"] for item in self.network["species"]}
        for index, component in enumerate(stage["species"]):
            item = QListWidgetItem(f"{component['coefficient']:g} × {names.get(component['species_id'], '?')} · "
                                   f"{component['species_id'][:8]}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.composition_list.addItem(item)

    def _update_composition(self):
        stage, item = self._current_stage(), self.composition_list.currentItem()
        if stage is None or item is None:
            self._error("请先选择阶段内的物质组成项。")
            return
        coefficient = self.composition_coefficient.value()
        if coefficient <= 0:
            self._error("反应式计量系数必须大于零。")
            return
        composition = deepcopy(stage["species"])
        composition[item.data(Qt.ItemDataRole.UserRole)]["coefficient"] = coefficient
        self._execute_draft_command({"type": "set_composition", "stage_id": stage["id"], "species": composition})

    def _remove_composition(self):
        stage, item = self._current_stage(), self.composition_list.currentItem()
        if stage is None or item is None:
            return
        composition = deepcopy(stage["species"])
        del composition[item.data(Qt.ItemDataRole.UserRole)]
        self._execute_draft_command({"type": "set_composition", "stage_id": stage["id"], "species": composition})

    def _remove_term(self):
        stage, item = self._current_stage(), self.ledger_list.currentItem()
        if stage is None or item is None:
            return
        target = self._selected_ledger_target()
        if target is None:
            return
        terms = target.get("terms", []) if target is not stage else stage["terms"]
        updated = deepcopy(terms)
        del updated[item.data(Qt.ItemDataRole.UserRole)]
        if target is stage:
            self._execute_draft_command({"type": "set_energy_terms", "stage_id": stage["id"],
                                         "terms": updated, "confirm_additional_terms": False})
        else:
            self._execute_draft_command({"type": "update_connection", "connection_id": target["id"],
                                         "fields": {"terms": updated}})

    def _update_term(self):
        stage, item = self._current_stage(), self.ledger_list.currentItem()
        if stage is None or item is None:
            self._error("请先选择要编辑的能量账本项。")
            return
        target = self._selected_ledger_target()
        if target is None:
            return
        terms = target.get("terms", []) if target is not stage else stage["terms"]
        updated = deepcopy(terms)
        term = updated[item.data(Qt.ItemDataRole.UserRole)]
        term["coefficient"] = self.energy_coefficient.value()
        term["system_mode"] = self.system_mode.currentData()
        term["reason"] = self.reason.text().strip() or term["reason"]
        confirm_additional = False
        if target is stage and any(value["system_mode"] == "complete_system" for value in updated) and len(updated) > 1:
            answer = QMessageBox.question(self, "完整体系与附加能量项",
                "修改后阶段包含完整体系作业和其他能量项。已逐项确认不会重复计算？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            confirm_additional = True
        if target is stage:
            command = {"type": "set_energy_terms", "stage_id": stage["id"], "terms": updated,
                       "confirm_additional_terms": confirm_additional}
        else:
            command = {"type": "update_connection", "connection_id": target["id"],
                       "fields": {"terms": updated}}
        self._execute_draft_command(command)

    def _remove_stage(self):
        stage = self._current_stage()
        if stage:
            self._execute_draft_command({"type": "remove_stage", "stage_id": stage["id"]})

    def _current_recipe(self):
        path_id = self.path_combo.currentData()
        recipe = next((item for item in self.network["path_reactions"] if item["path_id"] == path_id), None)
        if recipe is None:
            return {"path_id": path_id, "stages": [], "connections": [], "zero_point": {"kind": "reactant", "stage_id": ""},
                    "preset": "relative_energy", "energy_kind": self.kind_combo.currentData() or "gibbs_total",
                    "energy_mode": "absolute", "historical": False}
        return recipe

    def _render_connections(self, *_):
        preferred_edge = self._selected_connection_id
        blocked = self.connection_list.blockSignals(True)
        self.connection_list.clear()
        stage = self._current_stage()
        if stage is None:
            self.connection_list.blockSignals(blocked)
            self._load_connection_fields(None)
            self._render_ledger()
            self._render_edge_stoich()
            return
        recipe = self._current_recipe()
        labels = {item["id"]: item["label"] for item in recipe["stages"]}
        selected_row = -1
        for edge in recipe.get("connections", []):
            if edge["target_stage_id"] != stage["id"]:
                continue
            status = "✓ 已确认" if edge["confirmed"] else "! 待确认"
            item = QListWidgetItem(f"{labels.get(edge['source_stage_id'], '?')} → {labels.get(edge['target_stage_id'], '?')} · {status}")
            item.setData(Qt.ItemDataRole.UserRole, edge["id"])
            self.connection_list.addItem(item)
            if edge["id"] == preferred_edge:
                selected_row = self.connection_list.count() - 1
        if self.connection_list.count():
            self.connection_list.setCurrentRow(max(0, selected_row))
        else:
            self.connection_confirmed.setChecked(False)
            self.connection_note.clear()
        self.connection_list.blockSignals(blocked)
        self._load_connection_fields(self.connection_list.currentItem())
        self._render_ledger()
        self._render_edge_stoich()

    def _new_stage_connection(self, source_id, target_id):
        recipe = self._current_recipe()
        stages = {stage["id"]: stage for stage in recipe["stages"]}
        source, target = stages[source_id], stages[target_id]
        return {"id": new_id(), "source_stage_id": source_id, "target_stage_id": target_id,
            "confirmed": False, "note": "", "terms": [],
            "reactants": deepcopy(source["species"]), "products": deepcopy(target["species"])}

    def _current_connection(self):
        item = self.connection_list.currentItem()
        edge_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((edge for edge in self._current_recipe().get("connections", [])
                     if edge["id"] == edge_id), None)

    def _builder_snapshot(self):
        if self.builder_draft is not None:
            return self.builder_draft.snapshot()
        return {"project_id": self.project.id, "base_revision": self.project.revision,
                "path_id": self.path_combo.currentData(), "generation": 0,
                "network": deepcopy(self.network), "layout": {}, "path_options": {},
                "legacy_mode": "empty"}

    def _execute_draft_command(self, command):
        if self.builder_draft is None:
            self._error("当前没有可编辑的路径草稿。")
            return False
        previous_generation = self.builder_draft.generation
        previous_network = deepcopy(self.builder_draft.network)
        try:
            self.builder_draft.execute(command)
        except (ValueError, TypeError, KeyError) as error:
            self._error(error)
            return False
        self.network = self.builder_draft.network
        self._update_undo_buttons()
        if self.builder_draft.generation == previous_generation:
            return True
        self._draft_generation_changed()
        if command.get("type") == "move_stage":
            self._builder_layouts[self.builder_draft.path_id] = deepcopy(self.builder_draft.layout)
            return True
        select_id = command.get("stage_id")
        preserve_editor = command.get("type") in {"add_species", "update_species", "set_star", "remove_species"}
        if command.get("type") == "add_stage":
            select_id = command.get("stage", {}).get("id")
        if command.get("type") == "remove_stage" and self._selected_stage_id == command.get("stage_id"):
            select_id = None
        if command.get("type") == "add_connection":
            select_id = command.get("connection", {}).get("target_stage_id")
        self._selected_connection_id = None
        self._render_species()
        self._render_stages(select_id, preserve_editor=preserve_editor)
        notice = self._confirmation_invalidation_notice(previous_network, self.network, command)
        if notice:
            self.stage_inspector.set_change_notice(notice)
        return True

    def _confirmation_invalidation_notice(self, previous_network, network, command):
        kind = command.get("type")
        reason = None
        if kind == "set_composition":
            reason = "阶段组成"
        elif kind == "set_energy_terms":
            reason = "阶段能量项"
        elif kind == "update_connection" and set(command.get("fields", {})) & {"reactants", "products", "terms"}:
            reason = "连接组成或能量项"
        elif kind == "set_zero":
            reason = "统一零点"
        elif kind == "update_stage" and set(command.get("fields", {})) & {
                "role", "missing", "predecessor_stage_ids"}:
            reason = "阶段角色、缺值或前驱"
        elif kind == "update_species" and set(command.get("fields", {})) & {"formula", "bindings"}:
            reason = "物质分子式或来源绑定"
        elif kind == "set_path_options" and set(command.get("path_options", {})) & {
                "energy_mode", "energy_kind"}:
            reason = "路径能量模式或能量类型"
        elif kind in {"add_connection", "remove_connection", "remove_stage"}:
            reason = "路径拓扑"
        if reason is None:
            return ""

        path_id = self.builder_draft.path_id
        before = next((item for item in previous_network.get("path_reactions", [])
                       if item.get("path_id") == path_id), None)
        after = next((item for item in network.get("path_reactions", [])
                      if item.get("path_id") == path_id), None)
        before_stages = {item["id"]: item for item in (before or {}).get("stages", [])}
        after_stages = {item["id"]: item for item in (after or {}).get("stages", [])}
        cleared_stage_ids = [identifier for identifier, old in before_stages.items()
            if (old.get("normalization_confirmed") or old.get("confirm_additional_terms")) and
            not (after_stages.get(identifier, {}).get("normalization_confirmed") or
                 after_stages.get(identifier, {}).get("confirm_additional_terms"))]
        old_stage_names = {item["id"]: item.get("label", item["id"][:8])
                           for item in (before or {}).get("stages", [])}
        new_stage_names = {item["id"]: item.get("label", item["id"][:8])
                           for item in (after or {}).get("stages", [])}
        stage_names = [new_stage_names.get(identifier, old_stage_names.get(identifier, identifier[:8]))
                       for identifier in cleared_stage_ids]
        after_edges = {item["id"]: item for item in (after or {}).get("connections", [])}
        old_edges = {item["id"]: item for item in (before or {}).get("connections", [])}
        cleared_edge_ids = [identifier for identifier, old in old_edges.items()
            if old.get("confirmed") and not after_edges.get(identifier, {}).get("confirmed")]
        connection_names = []
        for identifier in cleared_edge_ids:
            edge = after_edges.get(identifier, old_edges[identifier])
            connection_names.append(f"{old_stage_names.get(edge['source_stage_id'], '?')} → "
                                    f"{new_stage_names.get(edge['target_stage_id'], '?')}")
        if not stage_names and not connection_names:
            return ""
        template = translate(
            "科学数据变更（{reason}）已清除核对：阶段 {stages}；反应边 {connections}。请重新检查并逐项确认。",
            self.language)
        return template.format(
            reason=translate(reason, self.language),
            stages="、".join(stage_names) if stage_names else translate("无", self.language),
            connections="、".join(connection_names) if connection_names else translate("无", self.language))

    def _update_undo_buttons(self):
        if hasattr(self, "undo_button"):
            self.undo_button.setEnabled(bool(self.builder_draft and self.builder_draft._undo_states))
            self.redo_button.setEnabled(bool(self.builder_draft and self.builder_draft._redo_states))

    def _undo_builder(self):
        if self.builder_draft is None or not self.builder_draft.undo():
            return
        self._draft_generation_changed()
        self.stage_inspector.set_change_notice("")
        self.network = self.builder_draft.network
        self._selected_connection_id = None
        self._update_undo_buttons()
        self._render_species()
        self._render_stages(self._selected_stage_id)

    def _redo_builder(self):
        if self.builder_draft is None or not self.builder_draft.redo():
            return
        self._draft_generation_changed()
        self.stage_inspector.set_change_notice("")
        self.network = self.builder_draft.network
        self._selected_connection_id = None
        self._update_undo_buttons()
        self._render_species()
        self._render_stages(self._selected_stage_id)

    def _stage_list_selection_changed(self, item, *_):
        if self._syncing_stage_selection or item is None:
            return
        stage_id = item.data(Qt.ItemDataRole.UserRole)
        self._selected_stage_id = stage_id
        self._selected_connection_id = None
        self.stage_canvas.select_stage(stage_id)

    def _open_stage_details_from_keyboard(self):
        item = self.stage_list.currentItem()
        if item is None:
            return
        stage_id = item.data(Qt.ItemDataRole.UserRole)
        self.main_tabs.setCurrentIndex(0)
        self.stage_views.setCurrentIndex(0)
        self.right_tabs.setCurrentIndex(0)
        self.stage_inspector.set_draft(self._builder_snapshot(), stage_id, "stage")
        self.right_panel_scroll.ensureWidgetVisible(self.stage_inspector.stage_name, 8, 8)
        self.stage_inspector.stage_name.setFocus()

    def _canvas_selection_requested(self, kind, identifier):
        snapshot = self._builder_snapshot()
        if kind == "stage":
            self._selected_stage_id = identifier
            self._selected_connection_id = None
            self._syncing_stage_selection = True
            try:
                row = next((index for index in range(self.stage_list.count())
                            if self.stage_list.item(index).data(Qt.ItemDataRole.UserRole) == identifier), -1)
                if row >= 0:
                    self.stage_list.setCurrentRow(row)
            finally:
                self._syncing_stage_selection = False
            self.stage_inspector.set_draft(snapshot, identifier, "stage")
            return
        if kind == "connection":
            recipe = next((item for item in snapshot["network"]["path_reactions"]
                           if item["path_id"] == snapshot["path_id"]), None)
            edge = next((item for item in recipe.get("connections", []) if item["id"] == identifier), None) if recipe else None
            if edge is None:
                return
            self._selected_stage_id = edge["target_stage_id"]
            self._selected_connection_id = identifier
            self._syncing_stage_selection = True
            try:
                row = next((index for index in range(self.stage_list.count())
                            if self.stage_list.item(index).data(Qt.ItemDataRole.UserRole) == self._selected_stage_id), -1)
                if row >= 0:
                    self.stage_list.setCurrentRow(row)
                edge_row = next((index for index in range(self.connection_list.count())
                                 if self.connection_list.item(index).data(Qt.ItemDataRole.UserRole) == identifier), -1)
                if edge_row >= 0:
                    self.connection_list.setCurrentRow(edge_row)
            finally:
                self._syncing_stage_selection = False
            self.stage_inspector.set_draft(snapshot, identifier, "connection")

    def _inspect_connection(self, item, *_):
        if item is None:
            return
        connection_id = item.data(Qt.ItemDataRole.UserRole)
        if not connection_id:
            return
        self._selected_connection_id = connection_id
        self.stage_canvas.select_connection(connection_id)
        self.stage_inspector.set_draft(self._builder_snapshot(), connection_id, "connection")

    def _render_edge_stoich(self, *_):
        self.edge_stoich_list.clear()
        edge = self._current_connection()
        if edge is None:
            return
        side = self.edge_side_combo.currentData() or "reactants"
        names = {item["id"]: item["name"] for item in self.network["species"]}
        edge.setdefault(side, [])
        for index, term in enumerate(edge[side]):
            item = QListWidgetItem(f"{term['coefficient']:g} × {names.get(term['species_id'], '失效物质')}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.edge_stoich_list.addItem(item)

    def _add_edge_stoich(self):
        edge = self._current_connection()
        selected = self._selected_species()
        if edge is None or len(selected) != 1:
            self._error("请选择一条反应边和一张物质卡，再加入边级计量项。")
            return
        side = self.edge_side_combo.currentData()
        terms = deepcopy(edge.get(side, []))
        existing = next((term for term in terms if term["species_id"] == selected[0]), None)
        if existing:
            existing["coefficient"] = self.composition_coefficient.value()
        else:
            terms.append({"species_id": selected[0], "coefficient": self.composition_coefficient.value()})
        self._execute_draft_command({"type": "update_connection", "connection_id": edge["id"],
                                     "fields": {side: terms}})

    def _update_edge_stoich(self):
        edge, item = self._current_connection(), self.edge_stoich_list.currentItem()
        if edge is None or item is None:
            self._error("先选择要更新的边级计量项。")
            return
        side = self.edge_side_combo.currentData()
        terms = deepcopy(edge.get(side, []))
        terms[item.data(Qt.ItemDataRole.UserRole)]["coefficient"] = self.composition_coefficient.value()
        self._execute_draft_command({"type": "update_connection", "connection_id": edge["id"],
                                     "fields": {side: terms}})

    def _remove_edge_stoich(self):
        edge, item = self._current_connection(), self.edge_stoich_list.currentItem()
        if edge is None or item is None:
            return
        side = self.edge_side_combo.currentData()
        terms = deepcopy(edge.get(side, []))
        del terms[item.data(Qt.ItemDataRole.UserRole)]
        self._execute_draft_command({"type": "update_connection", "connection_id": edge["id"],
                                     "fields": {side: terms}})

    def _load_connection_fields(self, item, *_):
        edge_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        edge = next((value for value in self._current_recipe().get("connections", [])
                     if value["id"] == edge_id), None)
        self.connection_confirmed.setChecked(bool(edge and edge["confirmed"]))
        self.connection_note.setText(edge["note"] if edge else "")

    def _confirm_connection(self):
        item = self.connection_list.currentItem()
        edge_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        edge = next((value for value in self._current_recipe().get("connections", [])
                     if value["id"] == edge_id), None)
        if edge is None:
            self._error("请选择一条入边后进行逐边确认。")
            return
        note = self.connection_note.text().strip()
        if self.connection_confirmed.isChecked() and not note:
            self._error("确认反应边时必须填写核对依据。")
            return
        self._execute_draft_command({"type": "update_connection", "connection_id": edge_id,
            "fields": {"confirmed": self.connection_confirmed.isChecked(), "note": note}})

    def _remove_connection(self):
        stage = self._current_stage()
        item = self.connection_list.currentItem()
        edge_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if stage is None or edge_id is None:
            self._error("请选择一条入边后再删除。")
            return
        self._execute_draft_command({"type": "remove_connection", "connection_id": edge_id})

    def _current_stage(self):
        item = self.stage_list.currentItem()
        if not item:
            return None
        return next((stage for stage in self._current_recipe()["stages"] if stage["id"] == item.data(Qt.ItemDataRole.UserRole)), None)

    def _render_stages(self, select_id=None, *, preserve_editor=False):
        recipe = self._current_recipe()
        stage_ids = {stage["id"] for stage in recipe["stages"]}
        if select_id is not None:
            self._selected_stage_id = select_id if select_id in stage_ids else None
        elif self._selected_stage_id not in stage_ids:
            self._selected_stage_id = recipe["stages"][0]["id"] if recipe["stages"] else None
        preferred_id = self._selected_stage_id
        self._syncing_stage_selection = True
        blocked = self.stage_list.blockSignals(True)
        try:
            self.stage_list.clear()
            labels = {item["id"]: item["name"] for item in self.network["species"]}
            for stage in recipe["stages"]:
                species_text = " + ".join(labels.get(item["species_id"], "失效物质") for item in stage["species"])
                label = f"{stage['role']} · {stage['label']}  [{species_text}]  | 前驱 {len(stage.get('predecessor_stage_ids', []))} | " + (
                    "NOT FOUND" if stage.get("missing") else f"能量项 {len(stage['terms'])}")
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, stage["id"])
                self.stage_list.addItem(item)
                if stage["id"] == preferred_id:
                    self.stage_list.setCurrentItem(item)
        finally:
            self.stage_list.blockSignals(blocked)
            self._syncing_stage_selection = False
        stage_labels = {stage["id"]: " + ".join(
            ("" if component["coefficient"] == 1 else f"{component['coefficient']:g} ") +
            labels.get(component["species_id"], "?") for component in stage["species"])
            for stage in recipe["stages"]}
        children = {stage["id"]: 0 for stage in recipe["stages"]}
        for stage in recipe["stages"]:
            for parent in stage.get("predecessor_stage_ids", []):
                if parent in children:
                    children[parent] += 1
        branched = any(len(stage.get("predecessor_stage_ids", [])) > 1 for stage in recipe["stages"]) or any(
            count > 1 for count in children.values())
        if branched:
            descriptions = [f"{stage_labels[parent]} → {stage_labels[stage['id']] }"
                for stage in recipe["stages"] for parent in stage.get("predecessor_stage_ids", [])]
            equation = "反应网络边：" + "；".join(descriptions)
        else:
            equation = " → ".join(stage_labels[stage["id"]] for stage in recipe["stages"])
        self.equation_label.setText(equation or "路径反应式待构建")
        self.predecessor_combo.blockSignals(True)
        self.additional_predecessor_combo.blockSignals(True)
        previous = self.predecessor_combo.currentData()
        self.predecessor_combo.clear()
        self.predecessor_combo.addItem("未指定局部前驱", None)
        for stage in recipe["stages"]:
            self.predecessor_combo.addItem(stage["label"], stage["id"])
        index = self.predecessor_combo.findData(previous)
        self.predecessor_combo.setCurrentIndex(max(0, index))
        self.additional_predecessor_combo.clear()
        self.additional_predecessor_combo.addItem("选择一个额外前驱…", None)
        for stage in recipe["stages"]:
            self.additional_predecessor_combo.addItem(stage["label"], stage["id"])
        self.predecessor_combo.blockSignals(False)
        self.additional_predecessor_combo.blockSignals(False)
        self._update_zero_points()
        if not preserve_editor:
            self._load_stage_fields()
        self._render_composition()
        self._render_connections()
        self._render_ledger()
        snapshot = self._builder_snapshot()
        self.stage_canvas.set_draft(snapshot)
        connection_ids = {edge["id"] for edge in recipe.get("connections", [])}
        if self._selected_connection_id in connection_ids:
            self.stage_canvas.select_connection(self._selected_connection_id)
        elif preferred_id is not None:
            self._selected_connection_id = None
            self.stage_canvas.select_stage(preferred_id)
        else:
            self._selected_connection_id = None
            self.stage_inspector.set_draft(snapshot, None)
        self._update_undo_buttons()

    def _load_stage_fields(self, *_):
        stage = self._current_stage()
        if stage is None:
            return
        self.stage_role.setCurrentIndex(max(0, self.stage_role.findData(stage["role"])))
        self.missing_transition.setChecked(stage.get("missing", False))
        self.normalization_confirmed.setChecked(stage.get("normalization_confirmed", False))
        self.normalization_note.setText(stage.get("normalization_note", ""))
        self.stage_name.setText(stage["label"])
        self.predecessor_combo.setCurrentIndex(max(0, self.predecessor_combo.findData(stage["predecessor_stage_id"])))

    def _update_zero_points(self, *_):
        current = self._current_recipe().get("zero_point", {})
        previous = self.zero_combo.currentData() if self.zero_combo.count() else None
        if previous is None:
            previous = (current.get("kind", "reactant"), current.get("stage_id", ""))
        self.zero_combo.blockSignals(True)
        self.zero_combo.clear()
        self.zero_combo.addItem("反应物总能量（默认零点）", ("reactant", ""))
        for stage in self._current_recipe()["stages"]:
            self.zero_combo.addItem(f"阶段：{stage['label']}", ("stage", stage["id"]))
        self.zero_combo.addItem("自定义参考表达式…", ("custom_expression", ""))
        self.zero_combo.addItem("手工绝对参考能量…", ("manual", ""))
        index = next((i for i in range(self.zero_combo.count())
                      if self.zero_combo.itemData(i) == previous), -1)
        if index < 0:
            wanted = (current.get("kind", "reactant"), current.get("stage_id", ""))
            index = next((i for i in range(self.zero_combo.count())
                          if self.zero_combo.itemData(i) == wanted), -1)
        self.zero_combo.setCurrentIndex(max(0, index))
        self.zero_combo.blockSignals(False)
        self._zero_mode_changed()

    def _zero_mode_changed(self, *_):
        mode = self.zero_combo.currentData()[0] if self.zero_combo.currentData() else "reactant"
        self.custom_zero.setVisible(mode == "custom_expression")
        self.manual_zero.setVisible(mode == "manual")
        self.manual_unit.setVisible(mode == "manual")
        if mode != "custom_expression" or self.custom_zero.text().strip():
            self._set_zero_point_from_controls()

    def _set_zero_point_from_controls(self, *_):
        if self.builder_draft is None or not self.zero_combo.currentData():
            return False
        mode, identifier = self.zero_combo.currentData()
        if mode == "reactant":
            stage = next((item for item in self._current_recipe().get("stages", [])
                          if item["role"] == "reactant"), None)
            if stage is None:
                return False
            zero = {"kind": "reactant", "stage_id": stage["id"]}
        elif mode == "stage":
            zero = {"kind": "stage", "stage_id": identifier}
        elif mode == "custom_expression":
            expression = self.custom_zero.text().strip()
            if not expression:
                return False
            compiled = compile_expression(expression, self.project.alias_bindings,
                                          purpose=ExpressionPurpose.SYSTEM)
            if not compiled.valid:
                self._error("自定义零点表达式无效，需使用项目已有来源别名，例如 @{A}。")
                return False
            zero = {"kind": "custom_expression", "expression": expression}
        else:
            zero = {"kind": "manual", "value": self.manual_zero.value(),
                    "unit": self.manual_unit.currentData()}
        return self._execute_draft_command({"type": "set_zero", "zero_point": zero})

    def _new_path(self, name=None):
        if self.controller.read_only:
            self._error("当前项目为只读，不能创建路径。")
            return
        if self._draft_new_path is not None:
            self._error("请先应用或取消当前新建路径草稿，再创建下一条路径。")
            return
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "新建反应路径", "路径名称：")
            if not ok or not name.strip():
                return
        name = str(name).strip()
        if not name:
            return
        color = ("#AD83FF", "#FFA96C", "#52CDB8", "#68ACFF")[len(self.project.paths) % 4]
        self._draft_new_path = ReactionPath(new_id(), name, (), energy_kind=EnergyKind.GIBBS_TOTAL,
                                      calculation_mode=CalculationMode.RELATIVE, unit=Unit.KCAL_MOL, color=color)
        self.path_combo.addItem(f"{name} · 新建", self._draft_new_path.id)
        self.path_combo.setCurrentIndex(self.path_combo.count() - 1)
        self._render_stages()

    def _render_edges(self):
        self.edge_list.clear()
        names = {item["id"]: item["name"] for item in self.network["species"]}
        starred = {item["id"] for item in self.network["species"] if item["starred"]}
        selected = set(self._selected_species())
        edges = [edge for edge in self.network["edges"] if not selected or
                 edge["source_species_id"] in selected or edge["target_species_id"] in selected]
        edges.sort(key=lambda edge: (edge["target_species_id"] not in starred,
                                      names.get(edge["target_species_id"], "").casefold()))
        for edge in edges:
            item = QListWidgetItem(f"{names.get(edge['source_species_id'], '?')} —{edge['relation']}→ {names.get(edge['target_species_id'], '?')} · {edge['note']}")
            item.setData(Qt.ItemDataRole.UserRole, edge["id"])
            self.edge_list.addItem(item)

    def _add_edge(self):
        selected = self._selected_species()
        target = self.relation_target.currentData()
        if len(selected) != 1 or not target or selected[0] == target:
            self._error("选择一张物质卡作为起点，并明确选择不同的邻居。")
            return
        exists = any(edge["source_species_id"] == selected[0] and edge["target_species_id"] == target
                     and edge["relation"] == self.relation_kind.currentData() for edge in self.network["edges"])
        if not exists:
            self.network["edges"].append({"id": new_id(), "source_species_id": selected[0],
                "target_species_id": target, "relation": self.relation_kind.currentData(), "note": ""})
        self._render_edges()

    def _remove_edge(self):
        item = self.edge_list.currentItem()
        if item:
            identifier = item.data(Qt.ItemDataRole.UserRole)
            self.network["edges"] = [edge for edge in self.network["edges"] if edge["id"] != identifier]
            self._render_edges()

    def _deploy_edge(self):
        edge_items = self.edge_list.selectedItems()
        if not edge_items:
            self._error("先明确选择一条前驱/后继关系边。")
            return
        selected_ids = {item.data(Qt.ItemDataRole.UserRole) for item in edge_items}
        selected_edges = [edge for edge in self.network["edges"] if edge["id"] in selected_ids]
        if not selected_edges:
            self._error("所选关系边已失效，请刷新物质关系网。")
            return
        targets = list(dict.fromkeys(edge["target_species_id"] for edge in selected_edges))
        predecessor_id = self.predecessor_combo.currentData()
        stages = {stage["id"]: stage for stage in self._current_recipe()["stages"]}
        if predecessor_id not in stages:
            self._error("先在“局部前驱”中选择要从哪个反应阶段展开这组关系边。")
            return
        species_names = {item["id"]: item["name"] for item in self.network["species"]}
        stage_names = {item["id"]: item["label"] for item in self._current_recipe()["stages"]}
        candidates = "\n".join(f"{stage_names[predecessor_id]} → {species_names.get(identifier, '?')}"
                                for identifier in targets)
        answer = QMessageBox.question(self, "快速部署分支候选",
            f"将从“{stage_names[predecessor_id]}”平行创建以下阶段：\n\n{candidates}\n\n"
            "这是候选部署预览；后续仍需逐一核对反应式、边计量和能量账本。继续创建？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        # _add_stage leaves this common predecessor selected, so candidates form
        # parallel branches rather than a fabricated serial chain.
        for identifier in targets:
            self._add_stage([identifier])

    def _focus_associated_species(self, node_id, entry_id):
        links = next((link for link in self.network["node_links"] if link["node_id"] == node_id), None)
        if links:
            self._render_species()
            self.species_list.clearSelection()
            for index in range(self.species_list.count()):
                item = self.species_list.item(index)
                if item.data(Qt.ItemDataRole.UserRole) in links["species_ids"]:
                    item.setSelected(True)
                    self.species_list.setCurrentItem(item)
            self.evidence.setText(f"来自图表路径点 {entry_id[:8]} / 节点 {node_id[:8]}。请选择具体物质后再执行加星。")

    def _recipe_for_preview(self):
        options = self._path_options()
        options["energy_mode"] = self.energy_mode_combo.currentData() or "absolute"
        options["energy_kind"] = self.kind_combo.currentData() or EnergyKind.GIBBS_TOTAL.value
        if not self._execute_draft_command({"type": "set_path_options", "path_options": options}):
            raise ValueError(self.preview.text())
        if not self._set_zero_point_from_controls():
            raise ValueError("请先为当前路径选择并设置有效的零点。")
        recipe = self._current_recipe()
        if recipe is None:
            raise ValueError("当前路径还没有反应阶段。")
        return recipe

    def _preview(self):
        return self._request_reaction_preview("preview")

    def _request_reaction_preview(self, mode):
        if self.controller.busy or not self._rebase_star_changes():
            return False
        self._clear_reaction_preview()
        self.preview.setText(translate("正在核查来源并计算当前草稿…", self.language))
        try:
            recipe = self._recipe_for_preview()
            options = self._path_options()
        except (ValueError, KeyError, TypeError) as error:
            self._error(error)
            return False
        if recipe is None:
            self._error(translate("当前路径还没有可检查的反应阶段。", self.language))
            return False
        path_id = self.path_combo.currentData()
        generation = self.builder_draft.generation if self.builder_draft is not None else 0
        new_path = self._draft_new_path if self._draft_new_path and self._draft_new_path.id == path_id else None
        comparison_path_id = (self._legacy_conversion_preview.source_path_id
                              if self._legacy_conversion_active and self._legacy_conversion_preview else None)
        self.preview.setText(translate("正在核查来源并计算当前草稿…", self.language))
        accepted = self.controller.preview_reaction_recipe(
            self.network, path_id, draft_generation=generation, base_revision=self.project.revision,
            new_path=new_path, path_options=options, identity_policy=self._identity_policy,
            comparison_path_id=comparison_path_id)
        if not accepted:
            self._error(translate("项目正在处理其他操作，或项目修订已变化；请稍后重新检查。", self.language))
            return False
        self._pending_token = self.controller.active_task_token
        self._pending_operation = "preview"
        self._pending_preview_mode = mode
        self._accepted_preview = None
        self._flow_state = "previewing"
        self.flow_status.setText(translate("正在核查来源并计算当前草稿…", self.language))
        self._sync_flow_controls()
        return True

    def _apply_and_save(self):
        if self._is_applied_generation_current():
            if self._flow_state == "saved":
                self.flow_status.setText(translate("当前草稿已应用并保存。", self.language))
                return True
            return self._start_file_save()
        # Recheck source fingerprints at the moment the user applies. A preview
        # can remain visible while an external log changes on disk.
        return self._request_reaction_preview("apply_save")

    def _apply_only(self):
        if self._is_applied_generation_current():
            self.flow_status.setText(translate("当前草稿已应用到项目内存。", self.language))
            return True
        return self._request_reaction_preview("apply_only")

    def _apply(self):
        return self._apply_only()

    def _show_preview(self):
        return self._request_reaction_preview("preview")

    def _preview_matches_current(self, preview):
        project = self.controller.project
        generation = self.builder_draft.generation if self.builder_draft is not None else 0
        return bool(project and preview.project_id == project.id and
                    preview.base_revision == project.revision and
                    preview.path_id == self.path_combo.currentData() and
                    preview.draft_generation == generation)

    def _reaction_preview_ready(self, token, preview):
        if token != self._pending_token or self._pending_operation != "preview":
            self.controller.discard_reaction_preview(token)
            return
        if not self._preview_matches_current(preview):
            self.controller.discard_reaction_preview(token)
            self._accepted_preview = None
            self.flow_status.setText(translate("草稿或项目已变化；这份预览已作废，请重新检查。", self.language))
            return
        self._accepted_preview = (token, preview)
        self._render_reaction_preview(preview)

    def _render_reaction_preview(self, preview):
        self.diagnostics_list.clear()
        for issue in preview.diagnostics:
            severity = translate("错误" if issue.severity == "error" else
                                 "警告" if issue.severity == "warning" else "提示", self.language)
            message = self._preview_issue_text(issue)
            item = QListWidgetItem(f"{severity} · {message}")
            item.setData(Qt.ItemDataRole.UserRole, {
                "path_id": issue.path_id, "stage_id": issue.stage_id,
                "connection_id": issue.connection_id, "species_id": issue.species_id,
                "source_file_id": issue.source_file_id, "code": issue.code,
                "detail": issue.detail,
            })
            self.diagnostics_list.addItem(item)
        if not preview.diagnostics:
            self.diagnostics_list.addItem(translate("当前没有阻塞问题。", self.language))
        if preview.path_result is None:
            self.preview.setText(translate("无法生成当前路径预览。请根据问题清单修正配方。", self.language))
            return

        preview_network = (read_reaction_network(preview.prepared_project)
                           if preview.prepared_project is not None else self.network)
        recipe = next((item for item in preview_network.get("path_reactions", [])
                       if item["path_id"] == preview.path_id), None)
        stage_by_entry = {stage.get("entry_id"): stage for stage in (recipe or {}).get("stages", [])}
        stage_by_id = {stage["id"]: stage for stage in (recipe or {}).get("stages", [])}
        values = {}
        for node in preview.path_result.nodes:
            stage = stage_by_entry.get(node.entry_id)
            values[stage["id"]] = node.absolute_hartree if node.valid and not stage.get("missing") else None
        unit = preview.path_result.unit
        unit_label = UNIT_LABELS[unit]
        quantity = {EnergyKind.GIBBS_TOTAL: "ΔG", EnergyKind.SCF: "ΔE",
                    EnergyKind.GIBBS_CORRECTION: "ΔGcorr"}.get(preview.path_result.energy_kind,
                                                                 preview.path_result.energy_kind.value)
        lines = [translate("草稿预览", self.language) +
                 f" · revision {preview.base_revision} · generation {preview.draft_generation}"]
        zero = (recipe or {}).get("zero_point", {})
        zero_stage = stage_by_id.get(zero.get("stage_id"))
        zero_label = (zero_stage["label"] if zero_stage else
                      translate("自定义或手工参考", self.language) if zero else
                      translate("未设置", self.language))
        lines.append(f"{translate('统一零点', self.language)}：{zero_label} · {quantity}")
        for node in preview.path_result.nodes:
            stage = stage_by_entry.get(node.entry_id)
            if stage is None:
                continue
            missing = bool(stage.get("missing"))
            if missing or not node.valid:
                absolute = relative = translate("未计算", self.language)
            else:
                absolute = f"{node.absolute_hartree:.12f} Eh" if node.absolute_hartree is not None else translate("未计算", self.language)
                relative = (f"{from_hartree(node.relative_hartree, unit):+.4f} {unit_label} "
                            f"({node.relative_hartree:+.12f} Eh)") if node.relative_hartree is not None else translate("未计算", self.language)
            local = ""
            predecessor_values = [values.get(parent) for parent in stage.get("predecessor_stage_ids", [])]
            predecessor_values = [value for value in predecessor_values if value is not None]
            if node.valid and node.absolute_hartree is not None and predecessor_values:
                differences = [node.absolute_hartree - value for value in predecessor_values]
                local = "；" + translate("局部步差", self.language) + " " + " / ".join(
                    f"{from_hartree(value, unit):+.4f} {unit_label}" for value in differences)
            deps = node.dependencies
            provenance = ""
            if deps:
                provenance = "；" + translate("来源行", self.language) + " " + " / ".join(
                    f"{dep.kind.value} · {dep.source_file_id[:8]}/{dep.job_id[:8]} · {translate('行', self.language)} {dep.source_line}"
                    for dep in deps)
            lines.append(f"{stage['role']} {stage['label']}：{translate('绝对能量', self.language)} {absolute}；"
                         f"{quantity} {relative}{local}{provenance}")

        if preview.comparison_path_result is not None and self._legacy_conversion_active:
            source_path_id = self._legacy_conversion_preview.source_path_id
            old_path = next((item for item in self.project.paths if item.id == source_path_id), None)
            old_nodes = {item.id: item for item in self.project.nodes}
            old_entries = {entry.id: old_nodes.get(entry.node_id) for entry in old_path.entries} if old_path else {}
            new_nodes = {item.entry_id: item for item in preview.path_result.nodes}
            lines.append(translate("原路径与转换草稿对照", self.language))
            for old_result in preview.comparison_path_result.nodes:
                old_node = old_entries.get(old_result.entry_id)
                new_result = new_nodes.get(old_result.entry_id)
                old_value = (f"{old_result.absolute_hartree:+.12f} Eh" if old_result.valid and
                             old_result.absolute_hartree is not None else translate("未计算", self.language))
                if new_result is None:
                    new_value = translate("未计算", self.language)
                else:
                    new_value = (f"{new_result.absolute_hartree:+.12f} Eh" if new_result.valid and
                                 new_result.absolute_hartree is not None else translate("未计算", self.language))
                lines.append(f"{old_node.label if old_node else old_result.node_id[:8]}：{old_value} → {new_value}")
        self.preview.setText("\n".join(lines))
        if preview.blocking:
            self.flow_status.setText(translate("当前来源或能量存在阻塞项，请先处理问题清单。", self.language))
        else:
            self.flow_status.setText(translate("预检完成；当前草稿与来源修订匹配。", self.language))

    def _preview_issue_text(self, issue):
        custom = {
            "source_changed": "来源日志内容已改变，本次能量不能作为当前结果。",
            "source_missing": "来源日志文件找不到，请重新定位到该来源。",
            "source_unreadable": "来源日志无法读取，请检查文件权限或占用状态。",
            "source_unverified": "来源日志没有可用的 SHA-256 指纹，不能验证当前内容。",
            "source_unavailable": "来源日志当前不可用。",
            "missing_transition_state": "此过渡态尚未找到；它保持缺值，不能用于计算。",
            "energy_unavailable": "当前作业或能量项不能生成有效能量。",
            "recipe_invalid": "配方未通过结构校验。",
            "path_missing": "当前路径已不存在。",
        }
        message = translate(custom.get(issue.code, diagnostic_text(issue.code, self.language)), self.language)
        if issue.stage_id:
            stage = next((item for item in (self._current_recipe() or {}).get("stages", [])
                          if item["id"] == issue.stage_id), None)
            if stage:
                message = f"{stage['label']}：{message}"
        if issue.source_file_id:
            source = next((item for item in self.project.source_files
                           if item.id == issue.source_file_id), None)
            if source:
                message = f"{source.display_name}：{message}"
        if issue.detail:
            message += f" · {issue.detail}"
        return message

    def _focus_preview_diagnostic(self, item):
        target = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(target, dict):
            return
        self.main_tabs.setCurrentIndex(0)
        if target.get("connection_id"):
            self.stage_views.setCurrentIndex(0)
            self.right_tabs.setCurrentIndex(0)
            self._canvas_selection_requested("connection", target["connection_id"])
            self.right_panel_scroll.ensureWidgetVisible(self.stage_inspector.summary, 8, 8)
            return
        if target.get("stage_id"):
            self.stage_views.setCurrentIndex(0)
            self.right_tabs.setCurrentIndex(0)
            wanted = target["stage_id"]
            row = next((index for index in range(self.stage_list.count())
                        if self.stage_list.item(index).data(Qt.ItemDataRole.UserRole) == wanted), -1)
            if row >= 0:
                self.stage_list.setCurrentRow(row)
            self._selected_stage_id = wanted
            self.stage_canvas.select_stage(wanted)
            self.stage_inspector.set_draft(self._builder_snapshot(), wanted, "stage")
            self.right_panel_scroll.ensureWidgetVisible(self.stage_inspector.stage_name, 8, 8)
            self.stage_inspector.stage_name.setFocus()
            return
        source_id = target.get("source_file_id")
        if source_id:
            self.main_tabs.setCurrentWidget(self.evidence_page)
            source = next((item for item in self.project.source_files if item.id == source_id), None)
            connection = next((item for item in getattr(self.controller, "connections", ())
                               if item.source_file_id == source_id), None)
            self.evidence.setText("\n".join((
                source.display_name if source else source_id,
                str(connection.path) if connection and connection.path else "",
                f"SHA-256: {source.sha256}" if source and source.sha256 else "SHA-256: —",
                f"{connection.state}: {connection.detail}" if connection else translate("尚无来源检查结果。", self.language),
            )))

    def _clear_reaction_preview(self):
        if self._accepted_preview:
            token, _preview = self._accepted_preview
            discard = getattr(self.controller, "discard_reaction_preview", None)
            if callable(discard):
                discard(token)
        self._accepted_preview = None
        if hasattr(self, "diagnostics_list"):
            self.diagnostics_list.clear()

    def _draft_generation_changed(self):
        self._clear_reaction_preview()
        if hasattr(self, "preview"):
            self.preview.setText(translate("草稿已改变；旧预览已清除，请重新检查。", self.language))
        generation = self.builder_draft.generation if self.builder_draft is not None else 0
        if self._applied_generation is not None and generation != self._applied_generation:
            self._flow_state = "draft"
            self.flow_status.setText(translate("草稿已改变；之前的预览和应用状态已失效。", self.language))
        self._sync_flow_controls()

    def _draft_signature(self):
        try:
            return json.dumps({"network": self.network, "options": self._path_options()},
                              sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError):
            return None

    def _draft_dirty_signature(self):
        try:
            snapshot = {
                "network": self.network,
                "layout": self.builder_draft.layout if self.builder_draft is not None else {},
                "path_options": self._path_options(),
            }
            return json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError):
            return None

    def _draft_is_dirty(self):
        current = self._draft_dirty_signature()
        return current is not None and current != self._initial_dirty_signature

    def _draft_payload(self):
        if self.builder_draft is None:
            return None
        snapshot = self.builder_draft.snapshot()
        snapshot.update({
            "project_id": self.project.id,
            "base_revision": self.builder_draft.base_revision,
            "path_id": self.builder_draft.path_id,
            "generation": self.builder_draft.generation,
            "network": deepcopy(self.network),
            "layout": deepcopy(self.builder_draft.layout),
            "path_options": self._path_options(),
            "legacy_mode": self.builder_draft.legacy_mode,
        })
        return snapshot

    def _ask_draft_exit(self, reason):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(translate("未应用的草稿", self.language))
        message = ("切换路径前，如何处理当前未应用草稿？" if reason == "path" else
                   "当前有尚未应用的编辑。请选择如何处理草稿。")
        box.setText(translate(message, self.language))
        if getattr(self.controller, "read_only", False):
            keep = box.addButton(translate("复制草稿文本并继续", self.language),
                                 QMessageBox.ButtonRole.AcceptRole)
            keep_choice = "export"
        else:
            keep = box.addButton(translate("保留草稿", self.language), QMessageBox.ButtonRole.AcceptRole)
            keep_choice = "keep"
        discard = box.addButton(translate("放弃草稿", self.language), QMessageBox.ButtonRole.DestructiveRole)
        keep_editing = box.addButton(translate("继续编辑", self.language), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep_editing)
        box.exec()
        return {keep: keep_choice, discard: "discard"}.get(box.clickedButton(), "continue")

    def _ask_recovery_draft(self, payload, revision_conflict):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(translate("找到反应路径草稿", self.language))
        if revision_conflict:
            message = translate(
                "找到基于修订 {base} 的草稿；当前项目是修订 {current}。恢复后必须重新检查来源与配方，"
                "不会自动应用。是否恢复为待检查草稿？", self.language).format(
                    base=payload["base_revision"], current=self.project.revision)
        else:
            message = translate("找到当前项目和路径的未应用草稿。是否恢复为待检查草稿？", self.language)
        box.setText(message)
        restore = box.addButton(translate("恢复为草稿", self.language), QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton(translate("放弃恢复副本", self.language), QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(restore)
        box.exec()
        return "restore" if box.clickedButton() == restore else "discard"

    def _request_recovery_for_path(self, path_id):
        if (not path_id or path_id in self._recovery_load_tokens.values() or
                not hasattr(self.controller, "load_builder_draft")):
            return
        if self.controller.busy:
            return
        if self.controller.load_builder_draft(self.project.id, path_id):
            self._recovery_load_tokens[self.controller.active_task_token] = path_id

    def _restore_draft_clicked(self):
        self._request_recovery_for_path(self.path_combo.currentData())

    def _copy_draft_text(self):
        try:
            payload = self._draft_payload()
            if payload is None:
                raise ValueError("No editable draft is available")
            envelope = {**payload, "format": "gaussianreadpro.builder-draft", "version": 1}
            text = json.dumps(envelope, ensure_ascii=False, allow_nan=False, indent=2)
        except (TypeError, ValueError) as error:
            self.flow_status.setText(translate("草稿文本无法导出。", self.language) + f" · {error}")
            return False
        QApplication.clipboard().setText(text)
        self.flow_status.setText(translate("未应用草稿文本已复制到剪贴板。", self.language))
        return True

    def _restore_active_path_selection(self):
        index = self.path_combo.findData(self._active_path_id)
        if index >= 0 and self.path_combo.currentIndex() != index:
            self.path_combo.blockSignals(True)
            self.path_combo.setCurrentIndex(index)
            self.path_combo.blockSignals(False)

    def _path_selection_changed(self, *_):
        if self._path_change_bypass:
            self._load_recipe()
            return
        target_id = self.path_combo.currentData()
        if target_id == self._active_path_id:
            return
        if not self._draft_is_dirty():
            self._load_recipe()
            return
        self._request_draft_exit("path", target_id=target_id)

    def _request_draft_exit(self, reason, *, target_id=None):
        if self._draft_exit_pending is not None:
            if reason == "path":
                self._restore_active_path_selection()
            return
        if not self._draft_is_dirty():
            self._continue_draft_exit(reason, target_id)
            return
        choice = self._ask_draft_exit(reason)
        if choice == "continue":
            if reason == "path":
                self._restore_active_path_selection()
            return
        if choice == "keep":
            self._start_draft_exit_task("builder_draft_save", self._draft_payload(), reason, target_id)
            return
        if choice == "export":
            if self._copy_draft_text():
                self._continue_draft_exit(reason, target_id)
            return
        if choice == "discard":
            if self._persisted_draft_generation is not None and self.builder_draft is not None:
                self._start_draft_exit_task("builder_draft_remove", {
                    "project_id": self.project.id,
                    "path_id": self.builder_draft.path_id,
                    "generation": self._persisted_draft_generation,
                }, reason, target_id)
            else:
                self._discard_active_draft()
                self._continue_draft_exit(reason, target_id)

    def _start_draft_exit_task(self, operation, payload, reason, target_id):
        if not payload:
            self.flow_status.setText(translate("当前没有可保留的草稿。", self.language))
            return
        if operation == "builder_draft_save":
            accepted = self.controller.save_builder_draft(payload)
        else:
            accepted = self.controller.remove_builder_draft(
                payload["project_id"], payload["path_id"], payload["generation"])
        if not accepted:
            self.flow_status.setText(translate("草稿操作未能启动；窗口仍保持打开。", self.language))
            return
        self._draft_exit_pending = {
            "operation": operation, "reason": reason, "target_id": target_id,
            "generation": payload.get("generation"),
        }
        self._draft_exit_token = self.controller.active_task_token

    def _discard_active_draft(self):
        if self.builder_draft is None:
            return
        path_id = self.builder_draft.path_id
        self.network = deepcopy(self._base_network)
        if any(path.id == path_id for path in self.project.paths):
            self.builder_draft = BuilderDraft.from_project(self.project, path_id)
            self.builder_draft.network = deepcopy(self.network)
        else:
            self.builder_draft = None
            if self._draft_new_path is not None and self._draft_new_path.id == path_id:
                self._draft_new_path = None
        self._persisted_draft_generation = None

    def _continue_draft_exit(self, reason, target_id=None):
        if reason == "path":
            if self.path_combo.currentData() != target_id:
                index = self.path_combo.findData(target_id)
                if index >= 0:
                    self.path_combo.blockSignals(True)
                    self.path_combo.setCurrentIndex(index)
                    self.path_combo.blockSignals(False)
            self._path_change_bypass = True
            try:
                self._load_recipe()
            finally:
                self._path_change_bypass = False
            return
        self._allow_close = True
        QDialog.reject(self)

    def _builder_draft_finished(self, token, operation, succeeded, data, code, detail):
        if operation == "builder_draft_load" and token in self._recovery_load_tokens:
            path_id = self._recovery_load_tokens.pop(token)
            if not succeeded:
                self.flow_status.setText(translate("草稿恢复失败；当前项目没有改变。", self.language) +
                                         f" · {detail or code}")
                return
            if data is None:
                if path_id == self._active_path_id:
                    self.flow_status.setText(translate("此路径没有已保留的草稿。", self.language))
                return
            self._recovery_payloads[path_id] = data
            if path_id == self._active_path_id:
                self._offer_recovered_draft(data)
            return
        if token != self._draft_exit_token or self._draft_exit_pending is None:
            return
        pending = self._draft_exit_pending
        if operation != pending["operation"]:
            return
        self._draft_exit_token = None
        self._draft_exit_pending = None
        if not succeeded:
            message = detail or code or "草稿文件操作失败。"
            self.flow_status.setText(translate("草稿文件操作失败；窗口仍保持打开。", self.language) +
                                     f" · {message}")
            return
        if operation == "builder_draft_save":
            self._persisted_draft_generation = pending["generation"]
        else:
            self._discard_active_draft()
        self._continue_draft_exit(pending["reason"], pending["target_id"])

    def _offer_recovered_draft(self, payload):
        if (payload.get("project_id") != self.project.id or
                payload.get("path_id") != self._active_path_id):
            return
        revision_conflict = payload["base_revision"] != self.project.revision
        if self._ask_recovery_draft(payload, revision_conflict) != "restore":
            self.controller.remove_builder_draft(payload["project_id"], payload["path_id"],
                                                 payload["generation"])
            return
        if not any(path.id == payload["path_id"] for path in self.project.paths):
            self.flow_status.setText(translate("草稿对应的路径已不存在；草稿文件仍保留。", self.language))
            return
        draft = BuilderDraft.from_project(self.project, payload["path_id"])
        network = deepcopy(payload["network"])
        if not isinstance(network, dict) or set(network) != set(empty_network()):
            self.flow_status.setText(translate("草稿结构无效；未恢复，恢复文件仍保留。", self.language))
            return
        options = deepcopy(payload["path_options"])
        if (set(options) != {"label", "unit", "color"} or
                not isinstance(options.get("label"), str) or not options["label"].strip() or
                len(options["label"]) > 256 or not isinstance(options.get("unit"), str) or
                options.get("unit") not in {unit.value for unit in Unit} or
                not isinstance(options.get("color"), str) or
                not re.fullmatch(r"#[0-9a-fA-F]{6}", options["color"])):
            self.flow_status.setText(translate("草稿路径选项无效；未恢复，恢复文件仍保留。", self.language))
            return
        if any(not isinstance(network.get(key), list)
               for key in ("species", "edges", "node_links", "path_reactions")):
            self.flow_status.setText(translate("草稿结构无效；未恢复，恢复文件仍保留。", self.language))
            return
        if any(not isinstance(item, dict) for item in network["species"]):
            self.flow_status.setText(translate("草稿结构无效；未恢复，恢复文件仍保留。", self.language))
            return
        if any(not isinstance(item.get("bindings"), list) or
               any(not isinstance(binding, dict) for binding in item["bindings"])
               for item in network["species"]):
            self.flow_status.setText(translate("草稿结构无效；未恢复，恢复文件仍保留。", self.language))
            return
        for item in network["path_reactions"]:
            if (not isinstance(item, dict) or not isinstance(item.get("stages"), list) or
                    not isinstance(item.get("connections"), list) or
                    any(not isinstance(stage, dict) or not isinstance(stage.get("terms", []), list) or
                        any(not isinstance(term, dict) for term in stage.get("terms", []))
                        for stage in item["stages"]) or
                    any(not isinstance(edge, dict) or not isinstance(edge.get("terms", []), list) or
                        any(not isinstance(term, dict) for term in edge.get("terms", []))
                        for edge in item["connections"])):
                self.flow_status.setText(translate("草稿结构无效；未恢复，恢复文件仍保留。", self.language))
                return
        recipe = next((item for item in network["path_reactions"]
                       if item.get("path_id") == payload["path_id"]), None)
        known_stage_ids = {stage.get("id") for stage in (recipe or {}).get("stages", [])}
        layout = BuilderDraft._sanitize_layout(payload["layout"], known_stage_ids)
        draft.base_revision = payload["base_revision"]
        draft.generation = payload["generation"]
        draft.network = network
        draft.layout = layout
        draft.path_options = options
        draft.legacy_mode = payload["legacy_mode"]
        # Preserve stale source/job references in a conflicted draft for review;
        # the worker's mandatory preflight still verifies them before apply.
        known_jobs = set(draft.source_job_ids)
        for species in network["species"]:
            for binding in species.get("bindings", []):
                if isinstance(binding, Mapping):
                    known_jobs.add((binding.get("source_file_id"), binding.get("job_id")))
        for path_recipe in network["path_reactions"]:
            for stage in path_recipe.get("stages", []):
                for term in stage.get("terms", []):
                    known_jobs.add((term.get("source_file_id"), term.get("job_id")))
            for edge in path_recipe.get("connections", []):
                for term in edge.get("terms", []):
                    known_jobs.add((term.get("source_file_id"), term.get("job_id")))
        draft.source_job_ids = frozenset(known_jobs)
        try:
            draft._validate_local(draft.network, draft.layout, draft.path_options)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            self.flow_status.setText(translate("草稿结构无效；未恢复，恢复文件仍保留。", self.language) +
                                     f" · {error}")
            return
        draft._undo_states.clear()
        draft._redo_states.clear()
        self.builder_draft = draft
        self.network = deepcopy(draft.network)
        self._builder_layouts[draft.path_id] = deepcopy(draft.layout)
        self._persisted_draft_generation = draft.generation
        self._recovery_revision_conflict = revision_conflict
        self._clear_reaction_preview()
        self._load_recipe()
        self.builder_draft.path_options = options
        self.path_name.setText(options.get("label", ""))
        self.path_unit.setCurrentIndex(max(0, self.path_unit.findData(options.get("unit"))))
        self.path_color.setText(options.get("color", "#336699"))
        self._applied_generation = None
        self._applied_project_id = None
        self._applied_revision = None
        self._applied_signature = None
        self._flow_state = "draft"
        self._initial_dirty_signature = self._draft_dirty_signature()
        self._update_undo_buttons()
        if revision_conflict:
            message = translate("恢复草稿来自修订 {base}，当前为修订 {current}；先重新检查来源和配方，再应用。",
                                self.language).format(base=payload["base_revision"],
                                                      current=self.project.revision)
        else:
            message = translate("已恢复为未应用草稿；请检查内容后再应用。", self.language)
        self.flow_status.setText(message)
        self._sync_flow_controls()

    def reject(self):
        if self._allow_close:
            QDialog.reject(self)
            return
        self._request_draft_exit("close")

    def accept(self):
        if self._allow_close:
            QDialog.accept(self)
            return
        self._request_draft_exit("close")

    def _is_applied_generation_current(self):
        project = self.controller.project
        generation = self.builder_draft.generation if self.builder_draft is not None else 0
        return bool(self._applied_generation is not None and project and
                    self._applied_project_id == project.id and self._applied_revision == project.revision and
                    self._applied_generation == generation and self._applied_signature == self._draft_signature())

    def _initialize_apply_state(self):
        if self.builder_draft is None:
            self._flow_state = "draft"
            return
        recipe = next((item for item in self.network.get("path_reactions", [])
                       if item["path_id"] == self.builder_draft.path_id), None)
        stages = (recipe or {}).get("stages", [])
        already_applied = bool(stages) and all(stage.get("node_id") and stage.get("entry_id") for stage in stages)
        if not already_applied:
            self._applied_generation = None
            self._applied_project_id = None
            self._applied_revision = None
            self._applied_signature = None
            self._flow_state = "draft"
            return
        project = self.controller.project
        self._applied_generation = self.builder_draft.generation
        self._applied_project_id = project.id
        self._applied_revision = project.revision
        self._applied_signature = self._draft_signature()
        status = getattr(getattr(getattr(self.controller, "backend", None), "recovery", None), "status", None)
        saved_revision = getattr(status, "saved_revision", None)
        self._flow_state = ("saved" if self.controller.path is not None and saved_revision is not None
                            and saved_revision >= project.revision else "applied_unsaved")
        self.flow_status.setText(translate("当前路径已应用并保存。" if self._flow_state == "saved"
                                           else "当前路径已应用到项目内存；尚未保存。", self.language))

    def _set_flow_state(self, state, message=None):
        self._flow_state = state
        labels = {
            "draft": "应用并保存", "previewing": "正在检查…", "preview_ready": "应用并保存",
            "applying": "正在应用…", "applied_unsaved": "保存项目", "saving": "正在保存…",
            "saved": "已保存", "conflict": "项目已变化",
        }
        self.apply_button.setText(translate(labels.get(state, "应用并保存"), self.language))
        if message is not None:
            self.flow_status.setText(translate(message, self.language))
        self._sync_flow_controls()

    def _sync_flow_controls(self):
        if not hasattr(self, "apply_button"):
            return
        busy = bool(getattr(self.controller, "busy", False))
        read_only = bool(getattr(self.controller, "read_only", False))
        self.apply_button.setEnabled(not busy and not read_only and self._flow_state != "conflict"
                                     and self._flow_state != "saved")
        self.preview_button.setEnabled(not busy)
        self.apply_menu_button.setEnabled(not busy)
        self.apply_only_action.setEnabled(not busy and not read_only)
        self.save_network_button.setEnabled(not busy and not read_only)
        self.save_file_button.setEnabled(not busy)
        self.new_path_button.setEnabled(not busy and not read_only)
        editing_locked = busy and self._pending_operation in {"apply", "save", "network"}
        self.main_tabs.setEnabled(not editing_locked)
        for widget in (self.path_combo, self.path_name, self.path_unit, self.path_color,
                       self.energy_mode_combo, self.kind_combo):
            widget.setEnabled(not editing_locked and not busy)
        self.cancel_button.setEnabled(not editing_locked)

    def _commit_reaction_preview(self, token, preview, *, save_after):
        if not self._preview_matches_current(preview) or preview.blocking:
            self.controller.discard_reaction_preview(token)
            self._set_flow_state("draft", "预览已过期或存在阻塞项，请修正后重新检查。")
            return False
        path_id = preview.path_id
        new_path = self._draft_new_path if self._draft_new_path and self._draft_new_path.id == path_id else None
        try:
            options = self._path_options()
        except ValueError as error:
            self._error(error)
            return False
        accepted = self.controller.apply_reaction_recipe(
            self.network, path_id, new_path, options, identity_policy=self._identity_policy,
            preview_token=token, draft_generation=preview.draft_generation)
        if not accepted:
            self._set_flow_state("draft", "项目或草稿已变化；预览没有应用，请重新检查。")
            return False
        self._accepted_preview = None
        self._pending_token = self.controller.active_task_token
        self._pending_operation = "apply"
        self._applying_base_revision = preview.base_revision
        self._apply_save_requested = save_after
        self._set_flow_state("applying", "预检通过；正在把路径应用到项目内存…")
        return True

    def _apply_now(self, *, save_after):
        return self._request_reaction_preview("apply_save" if save_after else "apply_only")

    def _sync_after_apply(self):
        self.project = self.controller.project
        if self.project is None:
            return
        path_id = self.path_combo.currentData()
        if self._draft_new_path and self._draft_new_path.id == path_id:
            self._draft_new_path = None
        self.network = read_reaction_network(self.project)
        self._base_network = deepcopy(self.network)
        self.builder_draft = None
        current_path = next((path for path in self.project.paths if path.id == path_id), None)
        if current_path:
            row = self.path_combo.findData(path_id)
            if row >= 0:
                self.path_combo.setItemText(row, f"{current_path.label} · {current_path.id[:8]}")
        self._load_recipe()
        self._initial_dirty_signature = self._draft_dirty_signature()
        self._applied_generation = self.builder_draft.generation if self.builder_draft else 0
        self._applied_project_id = self.project.id
        self._applied_revision = self.project.revision
        self._applied_signature = self._draft_signature()
        self._flow_state = "applied_unsaved"
        self._sync_flow_controls()

    def _start_file_save(self):
        if self.controller.busy:
            return False
        if self._flow_state == "conflict":
            self._error(translate("项目已变化；先重新打开或保留当前草稿。", self.language))
            return False
        destination = None
        if self.controller.path is None:
            from PySide6.QtWidgets import QFileDialog
            ux = self.project.workspace_state.get("ux_v2", {})
            pending_name = ux.get("pending_project_name", "") if isinstance(ux, Mapping) else ""
            default_name = f"{pending_name}.grproj" if pending_name else ""
            destination, _ = QFileDialog.getSaveFileName(
                self, translate("保存反应路径项目", self.language), default_name,
                "GaussianReadPro project (*.grproj)")
            if not destination:
                if self._applied_generation is not None:
                    self._set_flow_state("applied_unsaved", "路径已应用到项目内存；文件选择已取消，尚未保存。")
                else:
                    self.flow_status.setText(translate("文件选择已取消；项目仍未保存。", self.language))
                return False
        if not self.controller.save(destination):
            self.flow_status.setText(translate("保存任务未接受；项目仍保留在内存中，可重试。", self.language))
            self._sync_flow_controls()
            return False
        self._pending_token = self.controller.active_task_token
        self._pending_operation = "save"
        self._set_flow_state("saving", "正在保存指定项目修订…")
        return True

    def _save_network(self):
        if not self._rebase_star_changes():
            return
        try:
            validate_network(self.network, self.project)
        except (ValueError, TypeError) as error:
            self._error(error)
            return
        if self.controller.update_reaction_network(self.network):
            self._pending_token = self.controller.active_task_token
            self._pending_operation = "network"
            self._applying_base_revision = self.project.revision
            self._set_flow_state("applying", "正在更新物质关系网到项目内存…")

    def _save_file(self):
        if self.network != read_reaction_network(self.controller.project):
            self._error(translate("窗口内有尚未应用的草稿；请先应用，再保存项目文件。", self.language))
            return
        return self._start_file_save()

    def _controller_failed(self, code, message=""):
        if self._pending_operation in {"preview", "apply", "save", "network"}:
            self.flow_status.setText(translate("后台操作失败；请检查问题清单或重试。", self.language) +
                                     (f" · {message}" if message else f" · {code}"))

    def _operation_finished(self, token, operation, succeeded, project_id, revision, path):
        if token != self._pending_token:
            return
        pending = self._pending_operation
        expected = {"preview": "reaction_preview", "apply": "calculate",
                    "save": "save", "network": "calculate"}.get(pending)
        if operation != expected:
            return
        self._pending_token = None
        self._pending_operation = None
        if pending == "preview":
            preview = self._accepted_preview[1] if self._accepted_preview and self._accepted_preview[0] == token else None
            mode = self._pending_preview_mode
            self._pending_preview_mode = None
            if not succeeded or preview is None or not self._preview_matches_current(preview):
                self.controller.discard_reaction_preview(token)
                self._accepted_preview = None
                self._set_flow_state("draft", "预检结果已过期或未完成，请重新检查。")
                return
            if preview.blocking:
                self.controller.discard_reaction_preview(token)
                self._accepted_preview = None
                self._set_flow_state("draft", "当前来源或能量存在阻塞项，请先处理问题清单。")
                return
            if self._recovery_revision_conflict:
                self._recovery_revision_conflict = False
                if self.builder_draft is not None:
                    self.builder_draft.base_revision = preview.base_revision
            if mode == "preview":
                self._set_flow_state("preview_ready", "预检通过；点击“应用并保存”继续。")
                return
            self._commit_reaction_preview(token, preview, save_after=(mode == "apply_save"))
            return

        if pending in {"apply", "network"}:
            current = self.controller.project
            applied = bool(current and current.id == project_id and
                           current.revision > (self._applying_base_revision or -1))
            if not applied:
                self._set_flow_state("draft", "项目没有接受这次应用；草稿仍保留。")
                return
            self._sync_after_apply()
            if not succeeded:
                self._set_flow_state("applied_unsaved", "已应用到项目内存，但后台刷新失败；文件尚未保存。")
                return
            if pending == "network":
                self._set_flow_state("applied_unsaved", "物质关系网已应用到项目内存；尚未保存项目文件。")
                return
            if self._apply_save_requested:
                self._apply_save_requested = False
                self._start_file_save()
            else:
                self._set_flow_state("applied_unsaved", "路径已应用到项目内存；尚未保存项目文件。")
            return

        if pending == "save":
            current = self.controller.project
            status = getattr(getattr(getattr(self.controller, "backend", None), "recovery", None), "status", None)
            saved_revision = getattr(status, "saved_revision", None)
            saved = bool(succeeded and current and project_id == current.id and
                         self.controller.path is not None and saved_revision is not None and
                         saved_revision >= current.revision)
            if saved:
                persisted_generation = self._persisted_draft_generation
                applied_generation = self._applied_generation
                self._sync_after_apply()
                self._applied_revision = self.project.revision
                self._set_flow_state("saved", "项目文件已保存到当前修订。")
                if persisted_generation is not None and persisted_generation == applied_generation:
                    if self.controller.remove_builder_draft(current.id, self._active_path_id,
                                                            persisted_generation):
                        self._persisted_draft_generation = None
            else:
                if current and self._applied_generation is not None:
                    self._sync_after_apply()
                self._set_flow_state("applied_unsaved", "路径已应用到项目内存；项目文件保存失败，可重试保存。")

    def _busy_changed(self, _busy, _operation):
        self._sync_flow_controls()

    def _rebase_star_changes(self):
        latest = self.controller.project
        if latest.revision == self.project.revision:
            return True
        if (latest.id != self.project.id or latest.source_files != self.project.source_files or
                latest.nodes != self.project.nodes or latest.paths != self.project.paths):
            self._error("项目计算内容已变化；草稿仍保留在窗口中，请重新打开搭建窗口核对后应用。")
            return False
        current_network = read_reaction_network(latest)
        def without_stars(network):
            value = deepcopy(network)
            for species in value["species"]:
                species.pop("starred", None)
            return value
        if without_stars(current_network) != without_stars(self._base_network):
            self._error("项目关系网已变化；草稿仍保留在窗口中，请重新核对后应用。")
            return False
        base_stars = {item["id"]: item["starred"] for item in self._base_network["species"]}
        latest_stars = {item["id"]: item["starred"] for item in current_network["species"]}
        for species in self.network["species"]:
            identifier = species["id"]
            if identifier not in base_stars:
                continue
            if (species["starred"] != base_stars[identifier] and
                    latest_stars[identifier] != base_stars[identifier] and
                    species["starred"] != latest_stars[identifier]):
                self._error("同一物质的星标在其他窗口改变；请核对该物质后再应用。")
                return False
            if species["starred"] == base_stars[identifier]:
                species["starred"] = latest_stars[identifier]
        self.project = latest
        self._base_network = deepcopy(current_network)
        self._render_species()
        return True

    def _error(self, message):
        self.preview.setText("操作未应用：" + str(message))

    def _load_recipe(self, *_):
        path_id = self.path_combo.currentData()
        previous_path_id = self._active_path_id
        if path_id != self._active_path_id:
            self._clear_reaction_preview()
            self._flow_state = "draft"
            self._applied_generation = None
            self._applied_project_id = None
            self._applied_revision = None
            self._applied_signature = None
            self._active_path_id = path_id
        if path_id != self._identity_policy_path:
            self._identity_policy = "regenerate"
            self._identity_policy_path = path_id
            self._legacy_conversion_active = False
            self._legacy_conversion_preview = None
        if self.builder_draft is not None and self.builder_draft.path_id != path_id:
            self._builder_layouts[self.builder_draft.path_id] = deepcopy(self.builder_draft.layout)
            self.builder_draft = None
        if self.builder_draft is None and path_id and any(path.id == path_id for path in self.project.paths):
            self.builder_draft = BuilderDraft.from_project(self.project, path_id)
            self.builder_draft.layout = deepcopy(self._builder_layouts.get(path_id, self.builder_draft.layout))
            self.builder_draft.network = self.network
        if (self.builder_draft is None and self._draft_new_path is not None and
                self._draft_new_path.id == path_id):
            new_path = self._draft_new_path
            self.builder_draft = BuilderDraft(
                self.project.id, self.project.revision, path_id, self.network,
                deepcopy(self._builder_layouts.get(path_id, {})),
                {"label": new_path.label, "unit": new_path.unit.value, "color": new_path.color},
                "empty", source_job_ids=frozenset((source.id, job.id)
                    for source in self.project.source_files for job in source.jobs),
                path_energy_kind=new_path.energy_kind.value)
        recipe = next((item for item in self.network["path_reactions"]
                       if item["path_id"] == path_id), None)
        self.kind_combo.blockSignals(True)
        if recipe:
            self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(recipe["energy_kind"])))
        elif path_id:
            selected_path = next((value for value in self.project.paths if value.id == path_id), None)
            if selected_path is None and self._draft_new_path and self._draft_new_path.id == path_id:
                selected_path = self._draft_new_path
            if selected_path is not None:
                self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(selected_path.energy_kind.value)))
        self.kind_combo.blockSignals(False)
        self.energy_mode_combo.blockSignals(True)
        self.energy_mode_combo.setCurrentIndex(max(0, self.energy_mode_combo.findData(
            recipe.get("energy_mode", "absolute") if recipe else "absolute")))
        self.energy_mode_combo.blockSignals(False)
        path = next((item for item in self.project.paths if item.id == self.path_combo.currentData()), None)
        if path is None and self._draft_new_path and self._draft_new_path.id == self.path_combo.currentData():
            path = self._draft_new_path
        if path is not None:
            self.path_name.setText(path.label)
            self.path_unit.setCurrentIndex(max(0, self.path_unit.findData(path.unit.value)))
            self.path_color.setText(path.color)
            if self.builder_draft is not None:
                self.builder_draft.path_options = {"label": path.label, "unit": path.unit.value, "color": path.color}
                self.builder_draft.path_energy_kind = path.energy_kind.value
        self._render_stages()
        if recipe:
            zero = recipe["zero_point"]
            wanted = (zero["kind"], zero.get("stage_id", ""))
            index = next((i for i in range(self.zero_combo.count())
                          if self.zero_combo.itemData(i) == wanted), -1)
            self.zero_combo.blockSignals(True)
            self.zero_combo.setCurrentIndex(max(0, index))
            self.zero_combo.blockSignals(False)
            self.custom_zero.setText(zero.get("expression", ""))
            if zero.get("kind") == "manual":
                self.manual_zero.setValue(zero["value"])
                self.manual_unit.blockSignals(True)
                self.manual_unit.setCurrentIndex(max(0, self.manual_unit.findData(zero["unit"])))
                self.manual_unit.blockSignals(False)
            self._zero_mode_changed()
            current_path = next((path for path in self.project.paths if path.id == recipe["path_id"]), None)
            if current_path and recipe.get("reference_signature") and recipe["reference_signature"] != reference_signature(current_path.reference_expression):
                self.preview.setText("零点已不同步：此路径的参考表达式在搭建窗口外发生变更；重新应用前需确认重建。")
        else:
            self.custom_zero.clear()
            self.manual_zero.setValue(0.0)
            self.manual_unit.blockSignals(True)
            self.manual_unit.setCurrentIndex(0)
            self.manual_unit.blockSignals(False)
        self._refresh_legacy_panel()
        if hasattr(self, "apply_button"):
            self._initialize_apply_state()
            self._sync_flow_controls()
        if previous_path_id != path_id:
            self._initial_dirty_signature = self._draft_dirty_signature()

    def _refresh_legacy_panel(self):
        path_id = self.path_combo.currentData()
        path = next((item for item in self.project.paths if item.id == path_id), None)
        draft = self.builder_draft
        if self._legacy_conversion_active and path is not None:
            self.legacy_panel.show()
            self.legacy_notice.setText("已生成转换预览草稿；项目仍保持原 node/entry 身份，取消搭建器不会改动旧路径。预览会并列检查原路径与新配方的值和来源依赖。")
            self.legacy_convert_button.hide()
            self.legacy_expert_button.hide()
            self.legacy_continue_button.show()
            return
        if path is None or draft is None or draft.legacy_mode == "existing_recipe":
            self.legacy_panel.hide()
            return
        self.legacy_panel.show()
        self.legacy_nodes.clear()
        self.legacy_continue_button.setVisible(bool(path.entries))
        self.legacy_convert_button.setVisible(draft.legacy_mode == "legacy_supported")
        shared_nodes = {entry.node_id for other in self.project.paths if other.id != path.id
                        for entry in other.entries}
        path_nodes = {entry.node_id for entry in path.entries}
        self.legacy_new_path_button.setVisible(
            draft.legacy_mode == "legacy_supported" and
            (bool(path_nodes & shared_nodes) or len(path_nodes) != len(path.entries)))
        self.legacy_jobs_new_path_button.setVisible(
            draft.legacy_mode in {"legacy_expert", "legacy_invalid"})
        self.legacy_expert_button.setVisible(draft.legacy_mode in {"legacy_expert", "legacy_invalid"})
        if draft.legacy_mode == "empty":
            self.legacy_notice.setText("当前路径没有计算节点。可从作业候选创建物质卡，再明确添加阶段；作业顺序不会自动连成反应边。")
            self.legacy_nodes.hide()
            self.legacy_convert_button.hide()
            self.legacy_new_path_button.hide()
            self.legacy_jobs_new_path_button.hide()
            self.legacy_expert_button.hide()
            self.legacy_jobs_new_path_button.hide()
            self.legacy_continue_button.hide()
            return
        self.legacy_nodes.show()
        self.legacy_notice.setText(
            f"这条路径尚未配置可视化阶段，保留 {len(path.entries)} 个现有节点。{draft.legacy_reason} 原表达式和值保持只读，直到你明确生成并应用转换草稿。")
        nodes = {node.id: node for node in self.project.nodes}
        result = next((item for item in getattr(self.controller, "results", ())
                       if item.project_id == self.project.id and item.path_id == path.id and
                       item.revision == self.project.revision), None)
        values = {item.entry_id: item for item in result.nodes} if result else {}
        lines = []
        for entry in path.entries:
            node = nodes[entry.node_id]
            expression = (node.expression.draft_text if node.expression.draft_error else
                          render_expression(node.expression, self.project.alias_bindings))
            value = values.get(entry.id)
            absolute = (f"{value.absolute_hartree:.12f} Eh" if value and value.absolute_hartree is not None
                        else "无当前修订值")
            lines.append(f"{node.label} · {node.role.value} · {entry.id[:8]} / {node.id[:8]}\n"
                         f"{expression}\n绝对能量：{absolute}")
        self.legacy_nodes.setPlainText("\n\n".join(lines))
        enabled = not getattr(self.controller, "read_only", False) and not getattr(self.controller, "busy", False)
        self.legacy_convert_button.setEnabled(enabled and draft.legacy_mode == "legacy_supported")
        self.legacy_new_path_button.setEnabled(enabled)
        self.legacy_jobs_new_path_button.setEnabled(enabled)

    def _show_legacy_overview(self):
        path = next((item for item in self.project.paths if item.id == self.path_combo.currentData()), None)
        if path is not None:
            LegacyReadOnlyDialog(self.project, path, self).exec()

    def _open_legacy_expression(self):
        path = next((item for item in self.project.paths if item.id == self.path_combo.currentData()), None)
        if path is None or not path.entries:
            return
        from .expression_editor import ExpressionDialog
        ExpressionDialog(self.controller, node_id=path.entries[0].node_id,
                         language=getattr(self.parent(), "language", "zh_CN"), parent=self).exec()

    def _convert_legacy(self):
        path = next((item for item in self.project.paths if item.id == self.path_combo.currentData()), None)
        if path is None or self.builder_draft is None:
            return
        self._run_legacy_conversion(path, self.builder_draft)

    def _convert_legacy_to_new_path(self):
        source_path = next((item for item in self.project.paths
                            if item.id == self.path_combo.currentData()), None)
        source_draft = self.builder_draft
        if source_path is None or source_draft is None:
            return
        if self._draft_new_path is not None:
            self._error("先应用或取消当前新路径草稿，再从旧路径创建可视化副本。")
            return
        self._draft_new_path = ReactionPath(new_id(), source_path.label + " · 可视化副本", (),
            source_path.energy_kind, None, CalculationMode.RELATIVE,
            source_path.unit, source_path.color, source_path.visible)
        self.path_combo.addItem(f"{self._draft_new_path.label} · 新建", self._draft_new_path.id)
        self.path_combo.setCurrentIndex(self.path_combo.count() - 1)
        self._run_legacy_conversion(source_path, source_draft, target_path=self._draft_new_path)

    def _propose_new_path_from_jobs(self):
        from .import_summary import JobCandidateDialog
        source_path = next((item for item in self.project.paths
                            if item.id == self.path_combo.currentData()), None)
        if source_path is None:
            return
        if self._draft_new_path is not None:
            self._error("先应用或取消当前新路径草稿，再从作业候选创建另一条路径。")
            return
        candidates = JobCandidateDialog(self.project, parent=self)
        if candidates.exec() != QDialog.DialogCode.Accepted or not candidates.selected_candidates:
            return
        self._draft_new_path = ReactionPath(new_id(), source_path.label + " · 新可视化路径", (),
            source_path.energy_kind, None, CalculationMode.RELATIVE,
            source_path.unit, source_path.color, source_path.visible)
        self.path_combo.addItem(f"{self._draft_new_path.label} · 新建", self._draft_new_path.id)
        self.path_combo.setCurrentIndex(self.path_combo.count() - 1)
        self.network = propose_imported_job_cards(self.project, self.network,
                                                  candidates.selected_candidates)
        self._render_species()
        retained = "、".join(node.label for node in self.project.nodes
                            if any(entry.node_id == node.id for entry in source_path.entries))
        self.preview.setText(f"已选择 {len(candidates.selected_candidates)} 个作业作为物质卡草稿；原路径保留且未采用的旧节点为：{retained or '无'}。尚未自动建立阶段或反应边。")

    def _run_legacy_conversion(self, source_path, source_draft, target_path=None):
        dialog = LegacyConversionDialog(self.project, source_path, source_draft, self,
                                        target_path=target_path)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.preview is None:
            return
        self.network = deepcopy(dialog.preview.network)
        self._identity_policy = dialog.preview.identity_policy
        self._identity_policy_path = dialog.preview.path_id
        self._legacy_conversion_active = True
        self._legacy_conversion_preview = dialog.preview
        self._render_species()
        self._load_recipe()
        self._show_preview()

    def _path_options(self):
        label, color = self.path_name.text().strip(), self.path_color.text().strip()
        if not label or len(label) > 256:
            raise ValueError("路径名称不能为空且不能超过 256 字符。")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("路径颜色须为 #RRGGBB。")
        return {"label": label, "unit": self.path_unit.currentData(), "color": color.lower()}

    def closeEvent(self, event):
        if not self._allow_close:
            event.ignore()
            self._request_draft_exit("close")
            return
        for signal_name, slot in (("busyChanged", self._busy_changed),
                                  ("failed", self._controller_failed),
                                  ("reactionPreviewReady", self._reaction_preview_ready),
                                  ("operationFinished", self._operation_finished),
                                  ("builderDraftFinished", self._builder_draft_finished)):
            signal = getattr(self.controller, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)
