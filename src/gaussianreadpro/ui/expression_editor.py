"""Component and expert editors sharing the core expression document."""

from PySide6.QtCore import Qt, QTimer, QStringListModel, QLocale, QMimeData
from PySide6.QtGui import QColor, QTextCursor, QTextCharFormat, QDrag, QFontDatabase
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QCompleter, QDialog,
    QDoubleSpinBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTableWidget,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget, QHeaderView, QListWidget, QListWidgetItem, QSplitter, QLineEdit)

from ..core.expressions import (AliasIndex, components_expression, composite_gibbs_expression,
    edit_expression, render_expression)
from ..core.models import EnergyRef
from ..core.parser import select_job
from ..services.expression_editor import component_form
from .i18n import translate, diagnostic_text
from .tables import KIND_LABELS, UNIT_LABELS
from .glass_widgets import GlassPanel
from ..presentation.palette import get_palette


def _glass_theme():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    theme = app.property("glassTheme") if app is not None else None
    return theme if theme in {"light", "dark"} else "light"


class SpeciesLibrary(QListWidget):
    def startDrag(self, actions):
        item = self.currentItem()
        if item:
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(item.data(Qt.ItemDataRole.UserRole + 1))
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)


class ComponentTable(QTableWidget):
    def __init__(self, dialog):
        super().__init__(0, 6)
        self.dialog = dialog
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setObjectName("componentTable")
        self.setAccessibleName("表达式组分 / Expression components")
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def dragEnterEvent(self, event):
        if isinstance(event.source(), SpeciesLibrary) and event.source() is self.dialog.library:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if event.source() is self.dialog.library:
            ref = self.dialog.library.currentItem().data(Qt.ItemDataRole.UserRole)
            self.dialog.add_component(ref=ref)
            event.acceptProposedAction()


class TokenEdit(QPlainTextEdit):
    """Reference completion and bracket/error highlighting, using plain text only."""
    def __init__(self, aliases, parent=None):
        super().__init__(parent)
        self.completer = QCompleter(QStringListModel(["@{" + key + "}" for key in aliases]), self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.error_range = None
        self.completer.activated.connect(self.insert_completion)
        self.cursorPositionChanged.connect(self.highlight_brackets)

    def insert_completion(self, token):
        cursor = self.textCursor()
        text = self.toPlainText()[:self.python_position(cursor.position())]
        start = text.rfind("@{")
        if start >= 0 and "}" not in text[start:]:
            cursor.setPosition(self.qt_position(start), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(token)
        self.setTextCursor(cursor)

    def keyPressEvent(self, event):
        if self.completer.popup().isVisible() and event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab, Qt.Key.Key_Escape):
            event.ignore()
            return
        complete = event.key() == Qt.Key.Key_Space and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if not complete:
            super().keyPressEvent(event)
        text = self.toPlainText()[:self.python_position(self.textCursor().position())]
        start = text.rfind("@{")
        prefix = text[start:] if start >= 0 and "}" not in text[start:] else ""
        if complete or prefix:
            self.completer.setCompletionPrefix(prefix)
            rect = self.cursorRect()
            rect.setWidth(max(300, self.completer.popup().sizeHintForColumn(0)))
            self.completer.complete(rect)
        else:
            self.completer.popup().hide()

    def mark(self, start, end, color, *, error=False):
        selection = QTextEdit.ExtraSelection()
        selection.cursor = self.textCursor()
        length = len(self.toPlainText())
        if start >= length and length:
            start, end = length - 1, length
        selection.cursor.setPosition(self.qt_position(max(0, min(length, start))))
        selection.cursor.setPosition(self.qt_position(max(0, min(length, end))), QTextCursor.MoveMode.KeepAnchor)
        shade = QColor(color)
        shade.setAlpha(48 if self._theme_name() == "light" else 68)
        selection.format.setBackground(shade)
        if error:
            selection.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            selection.format.setUnderlineColor(QColor(color))
        return selection

    @staticmethod
    def _theme_name():
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        theme = app.property("glassTheme") if app else "light"
        return theme if theme in ("light", "dark") else "light"

    def qt_position(self, index):
        return len(self.toPlainText()[:index].encode("utf-16-le")) // 2

    def python_position(self, index):
        return len(self.toPlainText().encode("utf-16-le")[:index * 2].decode("utf-16-le", errors="ignore"))

    def highlight_brackets(self):
        text, pos = self.toPlainText(), self.python_position(self.textCursor().position())
        stack, pairs = [], {}
        # Parentheses inside reference tokens are user labels, not operators.
        in_ref = False
        for index, char in enumerate(text):
            if text[index:index + 2] == "@{":
                in_ref = True
            if in_ref:
                if char == "}":
                    in_ref = False
                continue
            if char == "(":
                stack.append(index)
            elif char == ")" and stack:
                begin = stack.pop()
                pairs[begin], pairs[index] = index, begin
        here = pos if pos in pairs else pos - 1
        colors = get_palette(self._theme_name())["colors"]
        selections = [self.mark(index, index + 1, colors["primary"]) for index in (here, pairs[here])] if here in pairs else []
        if self.error_range:
            start, end = self.error_range
            selections.append(self.mark(start, max(start + 1, end), colors["danger"], error=True))
        self.setExtraSelections(selections)


class CompactNumber(QDoubleSpinBox):
    def textFromValue(self, value):
        return repr(value)


class ExpressionDialog(QDialog):
    def __init__(self, controller, *, node_id=None, path_id=None, language="zh_CN", parent=None):
        super().__init__(parent)
        self.controller, self.node_id, self.path_id = controller, node_id, path_id
        self.setObjectName("expressionDialog")
        self.language = language
        self._loading, self._dirty, self._finish_code = True, False, None
        self.rows = []
        project = controller.project
        self.aliases = AliasIndex(project.alias_bindings)
        node = next((n for n in project.nodes if n.id == node_id), None)
        path = next((p for p in project.paths if p.id == path_id), None)
        self.document = node.expression if node else path.reference_expression
        self.document = self.document or edit_expression(None, "", self.aliases)
        self.setWindowTitle(self.t("编辑节点表达式") if node else self.t("编辑参考体系"))
        self.resize(1160, 800)
        self.setMinimumSize(860, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)
        heading_panel = GlassPanel("toolbar", theme=_glass_theme())
        heading_panel.setObjectName("editorHeading")
        heading_layout = QVBoxLayout(heading_panel)
        heading_layout.setContentsMargins(16, 10, 16, 10)
        heading_layout.setSpacing(5)
        title = QLabel(node.label if node else path.label)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("section")
        heading_layout.addWidget(title)
        description = QLabel(self.t("节点体系能量 − 路径参考 = 相对能量；直接差值模式不再扣减参考。"))
        description.setWordWrap(True)
        description.setObjectName("muted")
        heading_layout.addWidget(description)
        layout.addWidget(heading_panel)
        options = QHBoxLayout()
        self.purpose = QComboBox()
        self.purpose.addItem(self.t("体系绝对能量"), "system")
        self.purpose.addItem(self.t("直接能量差"), "difference")
        self.purpose.setCurrentIndex(self.purpose.findData(self.document.purpose.value))
        self.purpose.setEnabled(node is not None)
        self.combination = QComboBox()
        self.combination.addItem(self.t("标准能量类型"), "standard")
        self.combination.addItem(self.t("显式组合近似"), "composite_gibbs")
        self.combination.setCurrentIndex(self.combination.findData(self.document.combination_mode.value))
        options_panel = GlassPanel("toolbar", theme=_glass_theme())
        options_panel.setObjectName("editorOptions")
        options_layout = QHBoxLayout(options_panel)
        options_layout.setContentsMargins(12, 8, 12, 8)
        options_layout.addWidget(self.purpose)
        options_layout.addWidget(self.combination)
        options_layout.addStretch()
        options.addWidget(options_panel)
        layout.addLayout(options)
        self.tabs = QTabWidget()
        builder = QWidget()
        builder_layout = QVBoxLayout(builder)
        builder_layout.setContentsMargins(4, 8, 4, 4)
        builder_layout.setSpacing(10)
        self.table = ComponentTable(self)
        self.table.setHorizontalHeaderLabels([self.t(v) for v in ("正负", "系数", "来源物种", "作业", "能量类型", "移除")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, width in enumerate((52, 74, 190, 140, 142, 56)):
            self.table.setColumnWidth(i, width)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().hide()
        self.library = SpeciesLibrary()
        self.library.setObjectName("speciesLibrary")
        self.library.setAccessibleName(self.t("双击或拖入物种"))
        self.library.setDragEnabled(True)
        self.library.setMaximumWidth(215)
        for source in project.source_files:
            for job in source.jobs:
                ref = EnergyRef(source.id, job.id)
                item = QListWidgetItem(f"{source.display_name}\nJ{job.ordinal + 1} · {job.termination.value} · {source.id[:8]}")
                item.setToolTip(source.original_path)
                item.setData(Qt.ItemDataRole.UserRole, ref)
                item.setData(Qt.ItemDataRole.UserRole + 1, "@{" + self.aliases.label_for(ref) + "}")
                self.library.addItem(item)
        self.library.itemDoubleClicked.connect(lambda item: self.add_component(ref=item.data(Qt.ItemDataRole.UserRole)))
        library_panel = GlassPanel("surface", theme=_glass_theme())
        library_panel.setObjectName("speciesPanel")
        library_panel.setMinimumWidth(190)
        library_layout = QVBoxLayout(library_panel)
        library_layout.setContentsMargins(14, 12, 14, 12)
        library_layout.setSpacing(8)
        library_heading = QLabel(self.t("双击或拖入物种"))
        library_heading.setObjectName("section")
        library_layout.addWidget(library_heading)
        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText(self.t("搜索来源物种…"))
        self.library_search.setAccessibleName(self.t("搜索来源物种…"))
        self.library_search.textChanged.connect(self.filter_library)
        library_layout.addWidget(self.library_search)
        library_layout.addWidget(self.library)
        split = QSplitter()
        split.addWidget(library_panel)
        component_panel = GlassPanel("surface", theme=_glass_theme())
        component_panel.setObjectName("componentPanel")
        component_layout = QVBoxLayout(component_panel)
        component_layout.setContentsMargins(14, 12, 14, 12)
        component_layout.setSpacing(8)
        component_heading = QLabel(self.t("组分与系数"))
        component_heading.setObjectName("section")
        component_layout.addWidget(component_heading)
        component_layout.addWidget(self.table, 1)
        split.addWidget(component_panel)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(10)
        split.setSizes([225, 780])
        builder_layout.addWidget(split)
        row = QHBoxLayout()
        self.add_button = self.make_button("添加组分", self.add_component)
        row.addWidget(self.add_button)
        row.addWidget(QLabel(self.t("能量偏移")))
        self.offset = self.number()
        self.offset_unit = QComboBox()
        for value, text in (("hartree", "Eh"), ("kcal_mol", "kcal/mol"), ("kj_mol", "kJ/mol")):
            self.offset_unit.addItem(text, value)
        row.addWidget(self.offset)
        row.addWidget(self.offset_unit)
        builder_layout.addLayout(row)
        templates = QHBoxLayout()
        self.single_button = self.make_button("单物种模板", self.single_template)
        self.sum_button = self.make_button("添加旁观组分 / 反应物", self.add_component)
        self.composite_button = self.make_button("高层 E + 低层 (G − E)", self.composite_template)
        for button in (self.single_button, self.sum_button, self.composite_button):
            templates.addWidget(button)
        builder_layout.addLayout(templates)
        self.builder_notice = QLabel()
        self.builder_notice.setWordWrap(True)
        self.builder_notice.setObjectName("builderNotice")
        builder_layout.addWidget(self.builder_notice)
        self.tabs.addTab(builder, self.t("组分构建器"))
        expert = QWidget()
        expert_layout = QVBoxLayout(expert)
        expert_layout.addWidget(QLabel(self.t("输入 @{别名}；Ctrl+Space 补全；偏移须写单位，例如 1[kcal/mol]。")))
        self.text = TokenEdit(project.alias_bindings)
        self.text.setObjectName("expertExpression")
        self.text.setAccessibleName(self.t("专家表达式文本"))
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setMinimumHeight(260)
        self.text.setPlainText(self.document.draft_text if self.document.draft_text is not None
                               else render_expression(self.document, self.aliases))
        expert_layout.addWidget(self.text)
        expert_layout.addWidget(self.make_button("插入选中组分的引用", self.insert_reference))
        self.tabs.addTab(expert, self.t("专家文本"))
        layout.addWidget(self.tabs, 1)
        self.diagnostics = QLabel()
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setTextFormat(Qt.TextFormat.PlainText)
        self.diagnostics.setObjectName("editorDiagnostics")
        self.diagnostics.setContentsMargins(10, 6, 10, 6)
        layout.addWidget(self.diagnostics)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(150)
        self.preview.setObjectName("expressionPreview")
        self.preview.setAccessibleName(self.t("计算预览与来源证据"))
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        preview_panel = GlassPanel("surface", theme=_glass_theme())
        preview_panel.setObjectName("expressionPreviewPanel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(14, 10, 14, 10)
        preview_layout.setSpacing(6)
        preview_heading = QLabel(self.t("计算预览与来源证据"))
        preview_heading.setObjectName("section")
        preview_layout.addWidget(preview_heading)
        preview_layout.addWidget(self.preview)
        layout.addWidget(preview_panel)
        footer = QHBoxLayout()
        footer.addWidget(QLabel(self.t("有效表达式和无效草稿均自动保存；关闭后可继续编辑。")))
        footer.addStretch()
        self.close_button = self.make_button("完成", self.accept)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.flush)
        self._load_builder()
        self.text.textChanged.connect(self.expert_changed)
        self.purpose.currentIndexChanged.connect(self.expert_changed)
        self.combination.currentIndexChanged.connect(self.expert_changed)
        self.offset.valueChanged.connect(self.builder_changed)
        self.offset_unit.currentIndexChanged.connect(self.builder_changed)
        self.tabs.currentChanged.connect(self.tab_changed)
        self.controller.changed.connect(self.update_preview)
        self.controller.busyChanged.connect(self.worker_changed)
        self._loading = False
        self.update_diagnostics()
        self.update_preview()

    def t(self, text):
        return translate(text, self.language)

    def make_button(self, text, callback):
        result = QPushButton(self.t(text))
        result.clicked.connect(callback)
        return result

    def number(self):
        value = CompactNumber()
        value.setRange(-1e12, 1e12)
        value.setDecimals(15)
        value.setLocale(QLocale.c())
        return value

    def filter_library(self, query):
        for index in range(self.library.count()):
            item = self.library.item(index)
            item.setHidden(query.casefold() not in item.text().casefold())

    def _load_builder(self):
        form = component_form(self.document)
        if self.document.ast is None and self.document.draft_text == "":
            form = ([], 0., "hartree")
        hint = self.controller.workspace.get("expression_editor", {})
        expected = self.document.draft_text if self.document.draft_text is not None else render_expression(self.document, self.aliases)
        if (form is None and self.document.draft_error and hasattr(hint, "get")
                and hint.get("target") == (self.node_id or self.path_id) and hint.get("text") == expected
                and hint.get("mode") == "builder"):
            try:
                rows = hint["rows"]
                if (not isinstance(rows, (list, tuple)) or len(rows) > 40
                        or hint.get("unit") not in ("hartree", "kcal_mol", "kj_mol")):
                    raise ValueError
                for data in rows:
                    ref = EnergyRef(data["source"], data["job"], "follow_path" if data["kind"] == "follow_path" else "fixed",
                                    None if data["kind"] == "follow_path" else data["kind"]) if data.get("job") else None
                    row = self.add_component(ref=ref, coefficient=data["coefficient"])
                    row["source"].setEditText(data["source_text"])
                self.offset.setValue(hint["offset"])
                self.offset_unit.setCurrentIndex(self.offset_unit.findData(hint["unit"]))
                self.builder_supported = True
                self.builder_notice.setText(self.t("已恢复未完成的组分选择；当前结果仍不可用。"))
                return
            except (KeyError, ValueError, TypeError):
                self.rows.clear()
                self.table.setRowCount(0)
        if form is not None:
            terms, offset, unit = form
            self.offset.setValue(offset)
            self.offset_unit.setCurrentIndex(self.offset_unit.findData(unit))
            if self.offset.value() != offset or len(terms) > 40:
                form = None
            else:
                for ref, coefficient in terms:
                    item = self.add_component(ref=ref, coefficient=coefficient)
                    if item["coefficient"].value() != abs(coefficient):
                        form = None
        self.builder_supported = form is not None
        if form is None:
            self.tabs.setCurrentIndex(1)
            self.builder_notice.setText(self.t("此表达式保留专家模式；不能无损转为组分行，未改写原公式。"))
        else:
            self.builder_notice.setText(self.t("每行绑定文件 UUID、具体作业和能量类型；缺值不会自动换作业。"))

    def add_component(self, checked=False, *, ref=None, coefficient=1.):
        if len(self.rows) >= 40:
            self.diagnostics.setText(self.t("最多 40 个组分；复杂表达式请使用专家文本。"))
            return None
        row = {"sign": QComboBox(), "coefficient": self.number(), "source": QComboBox(),
               "job": QComboBox(), "kind": QComboBox()}
        row["sign"].addItems(["+", "−"])
        row["sign"].setStyleSheet("QComboBox { padding:3px; padding-right:15px; } QComboBox::drop-down { width:14px; }")
        row["sign"].setCurrentIndex(1 if coefficient < 0 else 0)
        row["coefficient"].setMinimum(0.)
        row["coefficient"].setValue(abs(coefficient))
        source = row["source"]
        for item in self.controller.project.source_files:
            source.addItem(f"{item.display_name} · {item.id[:8]}", item.id)
            source.setItemData(source.count() - 1, item.original_path, Qt.ItemDataRole.ToolTipRole)
        source.setEditable(True)
        source.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        source.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        if ref and source.findData(ref.source_file_id) < 0:
            source.addItem(self.t("来源未连接") + " · " + ref.source_file_id, ref.source_file_id)
        if ref:
            source.setCurrentIndex(source.findData(ref.source_file_id))
        source.lineEdit().setCursorPosition(0)
        self.populate_jobs(row, ref)
        for key, text in (("follow_path", "跟随路径"), ("scf", "SCF 电子能"),
                          ("gibbs_total", "Gibbs 总自由能"), ("gibbs_correction", "Gibbs 热校正")):
            row["kind"].addItem(self.t(text), key)
        if ref:
            row["kind"].setCurrentIndex(row["kind"].findData(ref.kind.value if ref.kind else "follow_path"))
        self.rows.append(row)
        index = self.table.rowCount()
        self.table.insertRow(index)
        self.table.setRowHeight(index, 36)
        for column, key in enumerate(("sign", "coefficient", "source", "job", "kind")):
            self.table.setCellWidget(index, column, row[key])
        remove = self.make_button("×", lambda: self.remove_component(row))
        remove.setToolTip(self.t("移除"))
        remove.setStyleSheet("QPushButton { padding:4px; }")
        self.table.setCellWidget(index, 5, remove)
        source.currentIndexChanged.connect(lambda: self.source_changed(row))
        for key in ("sign", "job", "kind"):
            row[key].currentIndexChanged.connect(self.builder_changed)
        row["coefficient"].valueChanged.connect(self.builder_changed)
        source.editTextChanged.connect(self.builder_changed)
        if not self._loading:
            self.builder_changed()
        return row

    def populate_jobs(self, row, ref=None):
        combo = row["job"]
        combo.blockSignals(True)
        combo.clear()
        source = next((s for s in self.controller.project.source_files if s.id == row["source"].currentData()), None)
        if source:
            for job in source.jobs:
                fields = ", ".join(k.value for k in job.energies)
                combo.addItem(f"{job.ordinal + 1} · {job.termination.value} · L{job.start_line}–{job.end_line}", job.id)
                combo.setItemData(combo.count() - 1, fields, Qt.ItemDataRole.ToolTipRole)
            kind = self.controller.selected_path.energy_kind if self.controller.selected_path else "gibbs_total"
            selected = select_job(source, kind).job or select_job(source, "scf").job
            chosen = ref.job_id if ref else selected.id if selected else None
            if chosen and combo.findData(chosen) < 0:
                combo.addItem(self.t("作业未找到") + " · " + chosen, chosen)
            combo.setCurrentIndex(combo.findData(chosen) if chosen else -1)
        elif ref:
            combo.addItem(self.t("作业未找到") + " · " + ref.job_id, ref.job_id)
        combo.blockSignals(False)

    def source_changed(self, row):
        self.populate_jobs(row)
        row["source"].lineEdit().setCursorPosition(0)
        self.builder_changed()

    def remove_component(self, row):
        index = self.rows.index(row)
        self.rows.pop(index)
        self.table.removeRow(index)
        self.builder_changed()

    def row_reference(self, row):
        combo = row["source"]
        if combo.currentIndex() < 0 or combo.currentText() != combo.itemText(combo.currentIndex()):
            raise ValueError(self.t("请从候选列表选择来源物种。"))
        if not row["job"].currentData():
            raise ValueError(self.t("请选择具体作业；异常作业会保留诊断且不产生当前有效结果。"))
        kind = row["kind"].currentData()
        return EnergyRef(combo.currentData(), row["job"].currentData(),
                         "follow_path" if kind == "follow_path" else "fixed", None if kind == "follow_path" else kind)

    def builder_changed(self, *_):
        if self._loading:
            return
        try:
            terms = [(self.row_reference(row), row["coefficient"].value() * (-1 if row["sign"].currentIndex() else 1)) for row in self.rows]
            doc = components_expression(terms, offset=self.offset.value(), offset_unit=self.offset_unit.currentData(),
                                        aliases=self.aliases, purpose=self.purpose.currentData())
            self.combination.blockSignals(True)
            self.combination.setCurrentIndex(0)
            self.combination.blockSignals(False)
            self.set_document(doc)
        except (ValueError, TypeError) as error:
            # Incomplete row choices must also invalidate the current result.
            pieces = []
            for row in self.rows:
                try:
                    token = self.aliases.label_for(self.row_reference(row))
                except ValueError:
                    token = "ref:unresolved"
                coefficient = row["coefficient"].value() * (-1 if row["sign"].currentIndex() else 1)
                pieces.append(f"{coefficient!r} * @{{{token}}}")
            draft = " + ".join(pieces) + f" + {self.offset.value()}[{self.offset_unit.currentData()}]"
            self.set_document(edit_expression(self.document, draft, self.aliases))
            self.diagnostics.setText(str(error))

    def set_document(self, document):
        self.document = document
        self.text.blockSignals(True)
        self.text.setPlainText(document.draft_text if document.draft_text is not None else render_expression(document, self.aliases))
        self.text.blockSignals(False)
        self._dirty = True
        self.timer.start(350)
        self.update_diagnostics()

    def expert_changed(self, *_):
        if self._loading:
            return
        if len(self.text.toPlainText()) > 65536:
            self.text.blockSignals(True)
            self.text.setPlainText(self.document.draft_text if self.document.draft_text is not None else render_expression(self.document, self.aliases))
            self.text.blockSignals(False)
            self.diagnostics.setText(self.t("草稿最多 65536 字符；此次输入未接受。"))
            return
        self.document = edit_expression(self.document, self.text.toPlainText(), self.aliases,
                                       purpose=self.purpose.currentData(), combination_mode=self.combination.currentData())
        self._dirty = True
        self.timer.start(350)
        self.update_diagnostics()

    def tab_changed(self, index):
        if self._loading or index != 0:
            return
        self._loading = True
        self.rows.clear()
        self.table.setRowCount(0)
        self._load_builder()
        self._loading = False

    def single_template(self):
        if not self.rows:
            self.add_component()
        while len(self.rows) > 1:
            self.remove_component(self.rows[-1])
        self.offset.setValue(0.)
        self.builder_changed()

    def composite_template(self):
        if len(self.rows) < 2:
            self.diagnostics.setText(self.t("前两行分别选择高层与低层来源及作业，再应用组合近似模板。"))
            return
        try:
            high, low = (self.row_reference(row) for row in self.rows[:2])
            doc = composite_gibbs_expression(EnergyRef(high.source_file_id, high.job_id, "fixed", "scf"),
                    EnergyRef(low.source_file_id, low.job_id, "fixed", "gibbs_total"),
                    EnergyRef(low.source_file_id, low.job_id, "fixed", "scf"), self.aliases)
            self.combination.blockSignals(True)
            self.combination.setCurrentIndex(1)
            self.combination.blockSignals(False)
            self.purpose.setCurrentIndex(0)
            self.set_document(doc)
            self.tabs.setCurrentIndex(1)
        except (ValueError, TypeError) as error:
            self.diagnostics.setText(str(error))

    def insert_reference(self):
        if not self.rows:
            self.diagnostics.setText(self.t("先在构建器添加并选择组分。"))
            return
        try:
            index = max(0, self.table.currentRow())
            ref = self.row_reference(self.rows[min(index, len(self.rows) - 1)])
            self.text.insertPlainText("@{" + self.aliases.label_for(ref) + "}")
            self.text.setFocus()
        except ValueError as error:
            self.diagnostics.setText(str(error))

    def update_diagnostics(self):
        error = self.document.draft_error
        if error:
            start, end = error.params.get("start", 0), error.params.get("end", 0)
            details = {k: v for k, v in error.params.items() if k not in ("start", "end")}
            self.diagnostics.setText(self.t("草稿有误，当前结果不可用") + f" · {diagnostic_text(error.code, self.language)} ({error.code}) · {start}–{end}\n" + (str(details) if details else ""))
            self.diagnostics.setProperty("status", "error")
            self.text.error_range = (start, end)
        else:
            self.diagnostics.setText(self.t("表达式语法有效；数值和来源检查以后台结果为准。"))
            self.diagnostics.setProperty("status", "valid")
            self.text.error_range = None
        self.diagnostics.style().unpolish(self.diagnostics)
        self.diagnostics.style().polish(self.diagnostics)
        self.text.highlight_brackets()

    def flush(self):
        if not self._dirty:
            return
        if self.controller.busy:
            self.timer.start(100)
            return
        try:
            state = {"target": self.node_id or self.path_id, "mode": "builder" if self.tabs.currentIndex() == 0 else "expert",
                     "text": self.document.draft_text if self.document.draft_text is not None else render_expression(self.document, self.aliases),
                     "offset": self.offset.value(), "unit": self.offset_unit.currentData(), "rows": [
                         {"source": row["source"].currentData(), "source_text": row["source"].currentText(),
                          "job": row["job"].currentData(), "kind": row["kind"].currentData(),
                          "coefficient": row["coefficient"].value() * (-1 if row["sign"].currentIndex() else 1)} for row in self.rows]}
            if self.controller.set_expression(self.document, node_id=self.node_id, path_id=self.path_id, editor_state=state):
                self._dirty = False
        except (ValueError, TypeError) as error:
            self.diagnostics.setText(str(error))
            self._finish_code = None

    def update_preview(self):
        result = next((r for r in self.controller.results if r.path_id == (self.path_id or self.controller.selected_path.id)), None)
        value = next((v for v in result.nodes if v.node_id == self.node_id), None) if result and self.node_id else None
        lines = []
        if self._dirty:
            lines.append(self.t("等待保存当前草稿…"))
        elif value:
            lines += [self.t("体系能量:") + f" {value.absolute_hartree if value.absolute_hartree is not None else '—'} Eh",
                      self.t("参考能量:") + f" {value.reference_hartree if value.reference_hartree is not None else '—'} Eh",
                      self.t("当前结果:") + f" {format(value.display_value, '+.8f') if value.valid else '—'} {UNIT_LABELS[value.unit.value]}"]
            if value.valid and value.absolute_hartree is not None and value.reference_hartree is not None:
                lines.append(f"({value.absolute_hartree} − {value.reference_hartree}) Eh = {value.relative_hartree:.10g} Eh")
            form = component_form(self.document)
            if form:
                for ref, coefficient in form[0]:
                    dependency = next((d for d in value.dependencies if d.source_file_id == ref.source_file_id
                        and d.job_id == ref.job_id and (ref.kind is None or ref.kind == d.kind)), None)
                    if dependency:
                        lines.append(f"{coefficient:+g} × {dependency.source_label} ({dependency.value_hartree} Eh)")
            for dep in value.dependencies:
                lines.append(f"{dep.source_label} · {self.t(KIND_LABELS[dep.kind.value])} · {dep.value_hartree} Eh · L{dep.source_line}")
            lines += [d.code for d in (*value.diagnostics, *result.diagnostics)]
        elif result:
            lines += [self.t("参考能量:") + f" {result.nodes[0].reference_hartree if result.nodes else '—'} Eh"]
            lines += [d.code for d in result.diagnostics]
        else:
            lines.append(self.t("等待当前修订计算完成"))
        self.preview.setPlainText("\n".join(lines))

    def worker_changed(self, busy, operation):
        if not busy:
            if self._dirty:
                self.timer.start(0)
            elif self._finish_code is not None:
                super().done(self._finish_code)

    def done(self, code):
        if self._dirty or self.controller.busy:
            self._finish_code = code
            self.flush()
            if not self._dirty and not self.controller.busy:
                super().done(code)
        else:
            super().done(code)
