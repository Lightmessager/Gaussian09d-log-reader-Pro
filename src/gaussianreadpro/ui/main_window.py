"""S4 scientific workbench: navigation, real tables, provenance and save feedback."""
from pathlib import Path
from collections.abc import Mapping

from PySide6.QtCore import QByteArray, QSortFilterProxyModel, Qt, QTimer, QItemSelectionModel, QSize
from PySide6.QtGui import QAction, QKeySequence, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame, QMenu, QInputDialog, QColorDialog,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter,
    QStackedWidget, QTabBar, QTableView, QVBoxLayout, QWidget, QWidgetAction, QDialog, QSizePolicy)

from ..core.expressions import render_expression
from .. import APP_NAME, VERSION_LABEL
from .profile_preview import ProfilePreview
from .plot_inspector import PlotInspector, build_plot_inspector_snapshot
from .profile_view import ProfilePanel
from ..core.plot_spec import build_plot_spec
from .tables import ID_ROLE, SORT_ROLE, KIND_LABELS, STATE_LABELS, UNIT_LABELS, NodeTable, SourceTable, SourceProxy
from .i18n import translate
from .theme import apply_theme
from .glass_widgets import GlassBackdrop, GlassPanel, GlassButton
from ..presentation.palette import get_palette
from .analysis_pages import AnalysisPage, ProjectTablesPage
from .project_actions import ProjectActions
from .workflow_state import derive_save_feedback, derive_workflow, normalize_project_name
from .import_summary import ImportSummaryDialog


def label(text="", name=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setProperty("i18n_source", text)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, primary=False):
    widget = GlassButton(text)
    widget.setProperty("i18n_source", text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


def card(variant="surface"):
    frame = GlassPanel(variant)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 15, 18, 15)
    layout.setSpacing(12)
    return frame, layout


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._rendering = False
        self._allow_close = False
        self._close_when_idle = False
        self._pending_import = None
        self._pending_import_source_ids = None
        self._import_summary_dialog = None
        self._pending_open = None
        self._pending_project_name = ""
        self._requested_project_name = ""
        self._pending_save_request = None
        self._save_status = None
        self._pending_builder_after_new = False
        self._pending_new_path_after_new = False
        self._selected_source = None
        self._selected_node = None
        self._selected_entry_id = None
        self._last_project = None
        self._last_error = ""
        self._save_error = False
        self._widths_initialized = False
        self._chart_selecting = False
        self.language = "zh_CN"
        self.theme = "system"
        self.visual_effects = "standard"
        self.reduce_motion = False
        self._glass_theme = "light"
        self._compact = False
        self.setWindowTitle(APP_NAME + " " + VERSION_LABEL + " · 计算化学工作台")
        self.resize(1440, 920)
        self.setMinimumSize(840, 680)
        self.setAcceptDrops(True)
        self.project_actions = ProjectActions(self)
        self._wire_project_actions()
        root = GlassBackdrop("light")
        root.setObjectName("root")
        self.backdrop = root
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._topbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._sidebar())
        workspace = QWidget()
        work = QVBoxLayout(workspace)
        self.work_layout = work
        work.setContentsMargins(12, 9, 12, 0)
        work.setSpacing(0)
        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        self.eyebrow = label("WORKSPACE / 研究工作区", "eyebrow")
        self.title = label("项目概览", "title")
        title_box.addWidget(self.eyebrow)
        title_box.addWidget(self.title)
        heading.addLayout(title_box)
        heading.addStretch()
        self.recalculate = self._action_button("calculate")
        heading.addWidget(self.recalculate)
        self.import_button = self._action_button("import_logs")
        self.import_button.setObjectName("primary")
        heading.addWidget(self.import_button)
        self.page_heading = QWidget()
        self.page_heading.setObjectName("pageHeading")
        self.page_heading.setLayout(heading)
        work.addWidget(self.page_heading)
        self.banner = label("", "error")
        self.banner.setWordWrap(True)
        self.banner.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.banner.hide()
        work.addWidget(self.banner)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._home())
        self.stack.addWidget(self._files())
        self.stack.addWidget(self._reaction())
        self._add_analysis_routes()
        work.addWidget(self.stack, 1)
        body.addWidget(workspace, 1)
        root_layout.addLayout(body, 1)
        self.setCentralWidget(root)
        self.task_label = label("就绪 · 全部计算与项目数据保留在本机", "muted")
        self.task_progress = QProgressBar()
        self.task_progress.setTextVisible(False)
        self.task_progress.setFixedWidth(160)
        self.task_progress.hide()
        self.cancel_button = button("取消导入", self.controller.cancel)
        self.cancel_button.setObjectName("quiet")
        self.cancel_button.hide()
        self.statusBar().addWidget(self.task_label, 1)
        self.statusBar().addPermanentWidget(self.task_progress)
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.controller.changed.connect(self.refresh)
        self.controller.busyChanged.connect(self.busy_changed)
        self.controller.progress.connect(self.progress_changed)
        self.controller.failed.connect(self.show_error)
        self.controller.message.connect(self.show_message)
        self.controller.statusChanged.connect(self.saved_changed)
        self.controller.operationFinished.connect(self._operation_finished)
        self.controller.bootstrapped.connect(self.bootstrap_ready)
        self.controller.recentChanged.connect(self.populate_recent)
        self.controller.recoveryOffered.connect(self.recovery_offer)
        self.controller.analysisReady.connect(self.analysis_ready)
        self.controller.structureReady.connect(self.structure_ready)
        self.controller.closed.connect(self.finish_close)
        self._shortcuts()
        self._configure_replica_shell()
        self.refresh()

    def _topbar(self):
        frame = QFrame()
        frame.setObjectName("topbar")
        frame.setProperty("profileChrome", "header")
        frame.setFixedHeight(50)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)
        logo = label("G", "wordmark")
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        self.brand = label(APP_NAME, "brand")
        self.brand.setToolTip(APP_NAME + " " + VERSION_LABEL)
        layout.addWidget(self.brand)
        layout.addSpacing(16)
        self.project_name = GlassButton("未命名项目")
        self.project_name.setObjectName("projectNameButton")
        self.project_name.setProperty("i18n_source", "未命名项目")
        self.project_name.setAccessibleName("重命名当前项目")
        self.project_name.setToolTip("点击重命名项目")
        self.project_name.clicked.connect(self.rename_current_project)
        self.project_name.setMinimumWidth(0)
        self.project_name.setMaximumWidth(150)
        self.project_name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.project_name)
        self.saved = label("尚未保存", "badge")
        self.saved.setMinimumWidth(72)
        layout.addWidget(self.saved)
        self.recovery_saved = label("已保留恢复副本", "muted")
        self.recovery_saved.hide()
        layout.addWidget(self.recovery_saved)
        layout.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索文件或节点…")
        self.search.setProperty("i18n_placeholder", "搜索文件或节点…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(235)
        self.search.setAccessibleName("搜索文件或节点 / Search files or nodes")
        self.search.textChanged.connect(self.filter_changed)
        layout.addWidget(self.search)
        self.new_button = self._action_button("new_project")
        self.open_button = self._action_button("open_project")
        self.save_button = self._action_button("save_project")
        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "zh_CN")
        self.language_combo.addItem("EN", "en")
        self.language_combo.setToolTip("界面语言 / Interface language")
        self.language_combo.currentIndexChanged.connect(self.language_changed)
        self.theme_combo = QComboBox()
        for title, key in (("跟随系统", "system"), ("浅色", "light"), ("深色", "dark")):
            self.theme_combo.addItem(title, key)
        self.theme_combo.setToolTip("界面主题 / Appearance")
        self.language_combo.setAccessibleName("界面语言 / Interface language")
        self.theme_combo.setAccessibleName("界面主题 / Appearance")
        self.more_button = GlassButton("更多")
        self.more_button.setProperty("i18n_source", "项目操作")
        self.more_button.setAccessibleName("更多项目操作")
        self.more_menu = QMenu(self.more_button)
        self.more_button.setMenu(self.more_menu)
        self.theme_combo.currentIndexChanged.connect(self.theme_changed)
        layout.addWidget(self.new_button)
        layout.addWidget(self.open_button)
        layout.addWidget(self.save_button)
        self.builder_button = GlassButton()
        self.builder_button.setObjectName("editReactionPath")
        self.project_actions.bind_button("edit_reaction_path", self.builder_button)
        layout.insertWidget(layout.indexOf(self.search), self.builder_button)
        layout.addWidget(self.language_combo)
        layout.addWidget(self.theme_combo)
        self.appearance_button = GlassButton()
        self.appearance_button.setFixedWidth(36)
        self.appearance_button.setIcon(self._resource_icon("settings.svg"))
        self.appearance_menu = QMenu(self.appearance_button)
        self.visual_effects_action = self.appearance_menu.addAction("减少视觉效果")
        self.motion_action = self.appearance_menu.addAction("减少动态效果")
        for action, text in ((self.visual_effects_action, "减少视觉效果"), (self.motion_action, "减少动态效果")):
            action.setProperty("i18n_source", text)
            action.setCheckable(True)
        self.visual_effects_action.toggled.connect(self.effects_changed)
        self.motion_action.toggled.connect(self.motion_changed)
        self.appearance_button.setMenu(self.appearance_menu)
        layout.addWidget(self.appearance_button)
        layout.addWidget(self.more_button)
        return frame

    def _wire_project_actions(self):
        callbacks = {
            "new_project": self.new_project,
            "open_project": self.choose_open,
            "save_project": self.save_project,
            "save_as": lambda: self.save_project(True),
            "edit_reaction_path": self.open_reaction_builder,
            "new_reaction_path": lambda: self.open_reaction_builder(create_new_path=True),
            "new_reaction_path_advanced": lambda: self.manage_path("new_advanced"),
            "import_logs": self.choose_files,
            "show_sources": lambda: self.activate_route("sources"),
            "reconnect_source": self._workflow_reconnect_source,
            "show_path_nodes": lambda: self.activate_route("path_nodes"),
            "calculate": self.controller.calculate,
            "rename_project_file": self.rename_current_project,
        }
        for key, callback in callbacks.items():
            self.project_actions.action(key).triggered.connect(
                lambda _checked=False, callback=callback: callback())

    def _action_button(self, key):
        widget = GlassButton()
        widget.setProperty("i18n_source", self.project_actions.action(key).property("i18n_source"))
        self.project_actions.bind_button(key, widget)
        return widget

    def _sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setProperty("profileChrome", "sidebar")
        self.sidebar.setFixedWidth(196)
        layout = QVBoxLayout(self.sidebar)
        layout.setContentsMargins(0, 9, 0, 0)
        self.nav_heading = label("    研究工作台")
        layout.addWidget(self.nav_heading)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setIconSize(QSize(24, 24))
        self.navigation.setProperty("compact", False)
        self.nav_text = ["首页", "计算日志", "能量剖面", "结构", "振动", "热化学", "NBO 分析", "IRC 分析", "表格", "日志查看器", "设置"]
        self.nav_icons = ("home.svg", "file.svg", "chart.svg", "structures.svg", "vibrations.svg", "thermo.svg", "cube.svg", "irc.svg", "table.svg", "file.svg", "settings.svg")
        self.nav_source_text = list(self.nav_text)
        for text, icon in zip(self.nav_text, self.nav_icons):
            item = QListWidgetItem("   " + text)
            item.setIcon(self._resource_icon(icon))
            item.setToolTip(text)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, text)
            item.setSizeHint(QSize(190, 60))
            self.navigation.addItem(item)
        self.navigation.item(1).setHidden(False)
        self.navigation.setCurrentRow(0)
        self.navigation.currentRowChanged.connect(self.page_changed)
        self.navigation.itemClicked.connect(lambda item: self.activate_route("energy") if self.navigation.row(item) == 2 and hasattr(self, "compact_tabs") else None)
        layout.addWidget(self.navigation)
        self.nav_footer = label("LOCAL FIRST\n离线 · 可追溯 · 可恢复")
        self.nav_footer.setWordWrap(True)
        layout.addWidget(self.nav_footer)
        return self.sidebar

    def _add_analysis_routes(self):
        self.analysis_pages = {}
        self.project_tables = None
        for title in self.nav_source_text[3:]:
            if title == "表格":
                page = ProjectTablesPage()
                self.project_tables = page
            elif title == "设置":
                page = QWidget()
                inner = QVBoxLayout(page)
                inner.setContentsMargins(28, 28, 28, 28)
                inner.addWidget(label("设置", "title"))
                note = label("界面语言、主题、减少动效和视觉效果在窗口右上角“设置”菜单中调整；更改会立即生效并保存在本机偏好中，不会增加科学项目修订。", "muted")
                note.setWordWrap(True)
                inner.addWidget(note)
                inner.addWidget(button("打开设置菜单", lambda: self.appearance_menu.popup(self.appearance_button.mapToGlobal(self.appearance_button.rect().bottomLeft()))))
                inner.addStretch()
            else:
                page = AnalysisPage(title, self.controller, self.language)
                self.analysis_pages[title] = page
                page.request.connect(self.controller.request_analysis)
                page.structure_request.connect(self.controller.request_structure)
            self.stack.addWidget(page)

    def analysis_ready(self, result):
        title = {"vibrations": "振动", "thermochemistry": "热化学", "nbo": "NBO 分析",
                 "irc": "IRC 分析", "log": "日志查看器"}.get(result.get("module"))
        page = self.analysis_pages.get(title)
        if page:
            page.show_result(result)

    def structure_ready(self, result):
        page = self.analysis_pages.get("结构")
        if page:
            page.show_result({**result, "module": "structures", **result.get("structure", {})})

    def _configure_replica_shell(self):
        from PySide6.QtGui import QPixmap
        topbar = self.findChild(QFrame, "topbar")
        logo = self.findChild(QLabel, "wordmark")
        logo.setObjectName("appLogo")
        logo.setPixmap(QPixmap(str(Path(__file__).resolve().parents[1] / "resources/icons/app-icon.png")).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        logo.setFixedSize(24, 24)
        self.header_page = label("/   能量剖面", "headerPage")
        self.header_page.setContentsMargins(26, 0, 0, 0)
        topbar.layout().insertWidget(2, self.header_page)
        self.recent_button = button("最近", lambda: None)
        self.recent_menu = QMenu(self.recent_button)
        self.recent_menu.aboutToShow.connect(self._populate_recent_menu)
        self.recent_button.setMenu(self.recent_menu)
        self.recent_button.setIcon(self._resource_icon("file.svg"))
        for control in (self.open_button, self.recent_button, self.appearance_button):
            control.setObjectName("shellAction")
        topbar.layout().insertWidget(topbar.layout().indexOf(self.appearance_button), self.recent_button)
        self.open_button.setIcon(self._resource_icon("folder.svg"))
        self.appearance_button.setFixedWidth(112)
        self.appearance_button.setProperty("i18n_source", "设置")
        for combo, title in ((self.language_combo, "界面语言"), (self.theme_combo, "界面主题")):
            topbar.layout().removeWidget(combo)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.addWidget(label(title))
            row_layout.addWidget(combo)
            action = QWidgetAction(self.appearance_menu)
            action.setDefaultWidget(row)
            self.appearance_menu.insertAction(self.visual_effects_action, action)
        self.more_menu.clear()
        for key in ("new_project", "open_project", "save_project", "save_as", "rename_project_file"):
            self.more_menu.addAction(self.project_actions.action(key))
        self.more_menu.addSeparator()
        for key in ("import_logs", "show_sources", "calculate", "show_path_nodes"):
            self.more_menu.addAction(self.project_actions.action(key))
        self.more_menu.addSeparator()
        for key in ("new_reaction_path", "new_reaction_path_advanced"):
            self.more_menu.addAction(self.project_actions.action(key))
        self.more_menu.setTitle(translate("项目操作", self.language))
        self.render_layout()

    def _populate_recent_menu(self):
        self.recent_menu.clear()
        for path in self.controller.preferences.get("recent_projects", []):
            self.recent_menu.addAction(str(path), lambda checked=False, path=path: self.open_path(path))
        if self.recent_menu.isEmpty():
            self.recent_menu.addAction(translate("暂无最近项目", self.language)).setEnabled(False)

    def _show_reaction_panel(self, index):
        self.activate_route("path_nodes" if index == 0 else "energy")
        self.compact_tabs.setCurrentIndex(index)

    def render_layout(self):
        """Apply responsive visibility and the active stable route in one place."""
        if not hasattr(self, "inspector") or not hasattr(self, "header_page"):
            return
        compact_home = self.height() < 760
        if getattr(self, "_compact_home_order", None) != compact_home:
            self._set_home_section_order(compact_home)
        compact_recent_actions = self.width() < 1024
        if getattr(self, "_compact_recent_actions", None) != compact_recent_actions:
            self._set_recent_actions_layout(compact_recent_actions)
        compact = self.width() < 1180
        narrow = self.width() < 1024
        self._compact, self._narrow_layout = compact, narrow
        energy = self.navigation.currentRow() == 2 and self._compact_focus_index == 1
        if energy:
            self.work_layout.setContentsMargins(0, 0, 0, 0)
        else:
            self.work_layout.setContentsMargins(12, 9, 12, 0)
        self.sidebar.setFixedWidth(64 if compact else 196)
        self.nav_heading.setVisible(not compact)
        self.nav_footer.setVisible(not compact)
        self.brand.setVisible(not compact)
        self.project_name.show()
        self.saved.show()
        self.header_page.setVisible(not narrow)
        self.search.setVisible(not narrow)
        self.new_button.setVisible(not narrow)
        self.open_button.setVisible(not narrow)
        self.save_button.show()
        self.builder_button.show()
        self.recent_button.show()
        self.more_button.show()
        self.search.setMaximumWidth(130 if narrow else 165 if compact else 235)
        self.project_name.setMinimumWidth(78)
        self.project_name.setMaximumWidth(112 if narrow else 150)
        if self.navigation.property("compact") != compact:
            self.navigation.setProperty("compact", compact)
            self.navigation.style().unpolish(self.navigation)
            self.navigation.style().polish(self.navigation)
        for index, raw in enumerate(self.nav_source_text):
            display = "路径" if self.language == "en" and raw == "反应路径" else raw
            self.navigation.item(index).setText("" if compact else "   " + translate(display, self.language))
            self.navigation.item(index).setToolTip(translate(raw, self.language))
            self.navigation.item(index).setData(Qt.ItemDataRole.AccessibleTextRole, translate(raw, self.language))
        self.chart_hint.setVisible(False)
        self.node_table.setMinimumHeight(110 if compact else 160)
        self.preview.setMinimumHeight(150 if compact else 215)
        self.reference_label.setVisible(self._compact_focus_index == 0 and not narrow)
        self.inspector.setVisible(self._compact_focus_index == 2 or not compact)
        self.compact_tabs.setVisible(self.navigation.currentRow() == 2 and not energy)
        self.compact_tabs.setAccessibleName(translate("Reaction view / 反应视图", self.language))
        for index, text in enumerate(("路径节点", "能量图", "节点详情")):
            self.compact_tabs.setTabText(index, translate(text, self.language))
        self.reaction_pages.setCurrentIndex(0 if self._compact_focus_index == 1 else 1)
        self.reaction_edit_tools.setVisible(self._compact_focus_index == 0)
        self.node_editor.setVisible(self._compact_focus_index != 1)
        self.vertical.setVisible(self._compact_focus_index in (0, 1))
        self.path_card.setVisible(self._compact_focus_index == 0)
        self.chart_card.setVisible(self._compact_focus_index == 1)
        self.controls_row.setVisible(self._compact_focus_index == 0)
        self.page_heading.setVisible(not energy)
        self.statusBar().setVisible(not energy)
        if self.navigation.currentRow() == 2:
            route_title = "能量剖面" if energy else "反应路径"
            self.title.setText(translate(route_title, self.language))
        else:
            self.title.setText(translate(self.nav_source_text[max(0, self.navigation.currentRow())], self.language))
        title = self.nav_source_text[max(0, self.navigation.currentRow())]
        self.header_page.setText("/   " + translate(title, self.language))
        self.appearance_button.setText(translate("设置", self.language))
        self.more_button.setText(translate("项目操作", self.language))
        self.more_button.setAccessibleName(translate("更多项目操作", self.language))
        self.more_menu.setTitle(translate("项目操作", self.language))
        for combo, narrow_width, long_width in ((self.path_combo, 220, 300),
                                                (self.kind_combo, 124, 170),
                                                (self.unit_combo, 106, 120),
                                                (self.mode_combo, 122, 160)):
            combo.setMaximumWidth(narrow_width if narrow else long_width)
            combo.setToolTip(combo.currentText())
            for index in range(combo.count()):
                combo.setItemData(index, combo.itemText(index), Qt.ItemDataRole.ToolTipRole)
        self._update_reaction_control_widths(narrow)

    def _set_home_section_order(self, compact):
        if not hasattr(self, "home_layout"):
            return
        layout = self.home_layout
        for widget in (self.home_welcome, self.home_recent_card, self.home_workflow_card, self.home_footer):
            layout.removeWidget(widget)
        layout.removeItem(self.home_metrics)
        sections = (
            (self.home_recent_card, self.home_welcome, self.home_workflow_card, self.home_metrics, self.home_footer)
            if compact else
            (self.home_welcome, self.home_metrics, self.home_workflow_card, self.home_recent_card, self.home_footer)
        )
        for section in sections:
            if section is self.home_metrics:
                layout.addLayout(section)
            else:
                layout.addWidget(section, 1 if section is self.home_recent_card else 0)
        self._compact_home_order = compact

    def _set_recent_actions_layout(self, compact):
        if not hasattr(self, "recent_actions_layout"):
            return
        layout = self.recent_actions_layout
        buttons = self.recent_action_buttons
        for widget in buttons:
            layout.removeWidget(widget)
        for column in range(len(buttons)):
            layout.setColumnStretch(column, 0)
        positions = ((0, 0), (0, 1), (1, 0), (1, 1), (2, 0)) if compact else tuple((0, i) for i in range(len(buttons)))
        columns = 2 if compact else len(buttons)
        for column in range(columns):
            layout.setColumnStretch(column, 1)
        for widget, (row, column) in zip(buttons, positions):
            layout.addWidget(widget, row, column)
        self._compact_recent_actions = compact

    @staticmethod
    def _resource_icon(name, theme="light"):
        from PySide6.QtGui import QIcon, QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer
        path = Path(__file__).resolve().parents[1] / "resources" / "icons" / name
        svg = path.read_text(encoding="utf-8").replace("#7450AF", get_palette(theme)["profile"]["axis"])
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not renderer.isValid():
            return QIcon()
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def _home(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.home_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        self.welcome, inner = card()
        inner.setContentsMargins(32, 28, 32, 28)
        inner.addWidget(label("GAUSSIAN ANALYSIS", "eyebrow"))
        inner.addWidget(label("从计算记录，到清晰的能量路径。", "title"))
        text = label("导入 Gaussian .log / .out 文件，查看作业来源、构建反应路径。\n每个数值保留原始行号；表达式与工作状态自动备份。", "muted")
        text.setWordWrap(True)
        inner.addWidget(text)
        actions = QHBoxLayout()
        actions.addWidget(button("＋ 导入计算日志", self.choose_files, True))
        actions.addWidget(button("打开已有项目", self.choose_open))
        actions.addStretch()
        inner.addLayout(actions)
        layout.addWidget(self.welcome)
        metrics = QHBoxLayout()
        self.metric_values = []
        for title in ("源文件", "反应节点", "反应路径"):
            frame, content = card()
            content.addWidget(label(title, "muted"))
            number = label("0", "number")
            content.addWidget(number)
            self.metric_values.append(number)
            metrics.addWidget(frame)
        layout.addLayout(metrics)
        self.home_workflow_card, workflow_layout = card()
        workflow_header = QHBoxLayout()
        workflow_header.addWidget(label("工作流提示", "section"))
        workflow_header.addStretch()
        self.workflow_next_button = button("继续下一步", self._run_workflow_next, True)
        workflow_header.addWidget(self.workflow_next_button)
        workflow_layout.addLayout(workflow_header)
        self.workflow_hint = label("导入来源、整理路径、检查能量并保存项目。", "muted")
        self.workflow_hint.setWordWrap(True)
        workflow_layout.addWidget(self.workflow_hint)
        layout.addWidget(self.home_workflow_card)
        recent, recent_layout = card()
        self.home_recent_card = recent
        recent_layout.addWidget(label("继续研究", "section"))
        self.recent = QListWidget()
        self.recent.setObjectName("recentProjects")
        self.recent.itemDoubleClicked.connect(self.open_recent)
        self.recent.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.recent.customContextMenuRequested.connect(self.recent_context_menu)
        self.recent.currentItemChanged.connect(lambda *_: self.update_actions())
        self.recent.setMinimumHeight(150)
        recent_layout.addWidget(self.recent)
        self.recent_actions_layout = QGridLayout()
        self.recent_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_actions_layout.setHorizontalSpacing(8)
        self.recent_actions_layout.setVerticalSpacing(8)
        self.recent_open_button = button("打开", self.open_recent)
        self.recent_rename_button = button("重命名", self.rename_selected_recent)
        self.recent_remove_button = button("从最近移除", self.remove_selected_recent)
        self.recent_delete_button = button("删除项目文件", self.delete_selected_recent)
        self.recent_action_buttons = (self.recent_open_button, self.recent_rename_button,
                                      self.recent_remove_button, self.recent_delete_button)
        self.continue_button = button("继续上次工作", self.continue_last)
        self.recent_action_buttons += (self.continue_button,)
        for control in self.recent_action_buttons:
            control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        recent_layout.addLayout(self.recent_actions_layout)
        layout.addWidget(recent, 1)
        footer = label("将文件或文件夹拖入窗口开始导入。项目以 .grproj 保存，日志始终保留独立来源。", "muted")
        self.home_footer = footer
        footer.setWordWrap(True)
        layout.addWidget(footer)
        self.home_welcome = self.welcome
        self.home_metrics = metrics
        scroll = QScrollArea()
        self.home_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _table(self, model, *, sorting=True):
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(34)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setSortingEnabled(sorting)
        if sorting:
            table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(160)
        return table

    def _files(self):
        page, layout = card()
        row = QHBoxLayout()
        row.addWidget(label("计算来源", "section"))
        row.addStretch()
        self.file_filter = QComboBox()
        for text, data in (("全部状态", ""), ("已解析", "已解析"), ("未连接 / 已变更", "来源"), ("失败", "读取失败")):
            self.file_filter.addItem(text, data)
        self.file_filter.currentIndexChanged.connect(self.filter_changed)
        row.addWidget(self.file_filter)
        self.recursive = QCheckBox("包含子目录")
        self.recursive.setProperty("i18n_source", "包含子目录")
        row.addWidget(self.recursive)
        self.folder_button = button("导入文件夹", self.choose_folder)
        row.addWidget(self.folder_button)
        layout.addLayout(row)
        self.source_model = SourceTable(self)
        self.source_proxy = SourceProxy(self)
        self.source_proxy.setSourceModel(self.source_model)
        self.source_proxy.setSortRole(SORT_ROLE)
        self.source_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.source_proxy.setFilterKeyColumn(-1)
        self.source_table = self._table(self.source_proxy)
        self.source_table.setObjectName("sourceTable")
        self.source_table.selectionModel().selectionChanged.connect(self.source_selected)
        self.source_table.horizontalHeader().sectionResized.connect(self.table_widths_changed)
        self.source_table.horizontalHeader().sortIndicatorChanged.connect(self.table_sort_changed)
        layout.addWidget(self.source_table, 1)
        self.source_detail = QPlainTextEdit()
        self.source_detail.setReadOnly(True)
        self.source_detail.setMaximumHeight(160)
        self.source_detail.setPlaceholderText("选择文件以核查作业、数值原文与来源行号")
        self.source_detail.setProperty("i18n_placeholder", "选择文件以核查作业、数值原文与来源行号")
        layout.addWidget(self.source_detail)
        actions = QHBoxLayout()
        self.reconnect_button = button("重新定位选中来源", self.choose_reconnect)
        actions.addWidget(self.reconnect_button)
        self.remove_source_button = button("移除来源…", self.remove_source)
        actions.addWidget(self.remove_source_button)
        actions.addStretch()
        actions.addWidget(label("表格排序独立于反应路径顺序", "muted"))
        layout.addLayout(actions)
        return page

    def _reaction(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.path_combo = QComboBox()
        self.path_combo.setMinimumWidth(135)
        self.path_combo.currentIndexChanged.connect(self.path_selected)
        controls.addWidget(self.path_combo, 1)
        self.kind_combo = QComboBox()
        for key, text in KIND_LABELS.items():
            self.kind_combo.addItem(text, key)
        self.kind_combo.currentIndexChanged.connect(lambda: self.option_changed(kind=self.kind_combo.currentData()))
        self.kind_combo.currentIndexChanged.connect(lambda *_: self._update_reaction_control_widths(self.width() < 1024))
        controls.addWidget(self.kind_combo)
        self.unit_combo = QComboBox()
        for key, text in UNIT_LABELS.items():
            self.unit_combo.addItem(text, key)
        self.unit_combo.currentIndexChanged.connect(lambda: self.option_changed(unit=self.unit_combo.currentData()))
        controls.addWidget(self.unit_combo)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("相对能量", "relative")
        self.mode_combo.addItem("绝对能量", "absolute")
        self.mode_combo.addItem("直接差值", "direct_difference")
        self.mode_combo.currentIndexChanged.connect(lambda: self.option_changed(mode=self.mode_combo.currentData()))
        controls.addWidget(self.mode_combo)
        self.controls_row = QWidget()
        self.controls_row.setObjectName("profileParameters")
        self.controls_row.setLayout(controls)
        layout.addWidget(self.controls_row)
        tools = QHBoxLayout()
        self.node_menu_button = button("节点…", lambda: None)
        node_menu = QMenu(self)
        for text, callback in (("新增节点", self.new_node), ("复制节点", self.copy_node),
                               ("从当前路径移除节点", self.remove_selected_nodes), ("批量编辑…", self.batch_nodes)):
            action = node_menu.addAction(text)
            action.setProperty("i18n_source", text)
            action.triggered.connect(callback)
        self.node_menu_button.setMenu(node_menu)
        self.path_menu_button = button("路径…", lambda: None)
        path_menu = QMenu(self)
        path_menu.addAction(self.project_actions.action("new_reaction_path"))
        path_menu.addAction(self.project_actions.action("new_reaction_path_advanced"))
        for text, callback in (("复制路径（共享节点）", lambda: self.manage_path("copy")),
                               ("重命名路径", lambda: self.manage_path("rename")),
                               ("删除路径", lambda: self.manage_path("delete")),
                               ("路径颜色", lambda: self.manage_path("color")),
                               ("切换路径显隐", lambda: self.manage_path("visible")),
                               ("批量应用当前参考…", self.batch_paths)):
            action = path_menu.addAction(text)
            action.setProperty("i18n_source", text)
            action.triggered.connect(callback)
        self.path_menu_button.setMenu(path_menu)
        self.edit_expression_button = button("编辑表达式…", self.edit_expression)
        self.edit_reference_button = button("参考体系…", self.edit_reference)
        self.open_builder_button = self._action_button("edit_reaction_path")
        self.undo_button = button("撤销", self.controller.undo)
        self.redo_button = button("重做", self.controller.redo)
        for widget in (self.open_builder_button, self.node_menu_button, self.path_menu_button, self.edit_expression_button,
                       self.edit_reference_button, self.undo_button, self.redo_button):
            tools.addWidget(widget)
        tools.addStretch()
        self.reaction_edit_tools = QWidget()
        self.reaction_edit_tools.setLayout(tools)
        layout.addWidget(self.reaction_edit_tools)
        self.reference_label = label("参考体系：尚未设置 · 选中节点后点击“设为参考”", "muted")
        self.reference_label.setWordWrap(True)
        layout.addWidget(self.reference_label)
        self.horizontal = QSplitter(Qt.Orientation.Horizontal)
        self.horizontal.setChildrenCollapsible(False)
        self.horizontal.setHandleWidth(12)
        self.vertical = QSplitter(Qt.Orientation.Vertical)
        self.vertical.setChildrenCollapsible(False)
        self.vertical.setHandleWidth(12)
        self._compact_focus_index = 1
        self._wide_vertical_sizes = None
        table_card, content = card()
        heading = QHBoxLayout()
        heading.addWidget(label("路径节点", "section"))
        heading.addStretch()
        self.up_button = button("↑", lambda: self.move_selected(-1))
        self.down_button = button("↓", lambda: self.move_selected(1))
        heading.addWidget(self.up_button)
        heading.addWidget(self.down_button)
        self.inspector_toggle = button("属性", self.toggle_inspector)
        heading.addWidget(self.inspector_toggle)
        content.addLayout(heading)
        self.node_model = NodeTable(self)
        self.node_proxy = QSortFilterProxyModel(self)
        self.node_proxy.setSourceModel(self.node_model)
        self.node_proxy.setSortRole(SORT_ROLE)
        self.node_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.node_proxy.setFilterKeyColumn(-1)
        self.node_table = self._table(self.node_proxy)
        self.node_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.node_table.doubleClicked.connect(lambda *_: self.edit_expression())
        self.node_table.setObjectName("nodeTable")
        self.node_table.selectionModel().selectionChanged.connect(self.node_selected)
        self.node_table.horizontalHeader().sectionResized.connect(self.table_widths_changed)
        self.node_table.horizontalHeader().sortIndicatorChanged.connect(self.table_sort_changed)
        content.addWidget(self.node_table, 1)
        self.vertical.addWidget(table_card)
        chart_card, chart_layout = card()
        chart_card.setProperty("profileSurface", True)
        chart_card.setObjectName("profileChart")
        chart_card.setProperty("profileChrome", "transparent")
        chart_card.setContentsMargins(0, 0, 0, 0)
        chart_layout.setContentsMargins(12, 10, 12, 10)
        chart_title = QHBoxLayout()
        chart_title.addStretch()
        self.chart_hint = label("按当前路径顺序展示", "muted")
        chart_title.addWidget(self.chart_hint)
        chart_layout.addLayout(chart_title)
        self.preview = ProfilePreview()
        self.preview.selected.connect(self.select_node)
        self.profile = ProfilePanel(self.preview, self.controller)
        self.profile.selectionRequested.connect(self.chart_selected)
        self.profile.speciesSelectionRequested.connect(self.chart_species_requested)
        self.profile.modeChanged.connect(self.chart_mode_changed)
        self.profile.editRequested.connect(self.edit_expression)
        self.profile.pathCreateRequested.connect(self.project_actions.action("new_reaction_path").trigger)
        self.project_actions.bind_button("edit_reaction_path", self.profile.reaction_builder_button)
        self.profile.pathColorRequested.connect(self.change_profile_path_color)
        self.profile.pathRequested.connect(self.select_profile_path)
        self.profile.sourceReady.connect(self.show_profile_source)
        self.profile.exportedNotice.connect(lambda path: self.show_message(translate("已导出结果包：", self.language) + path))
        chart_layout.addWidget(self.profile, 1)
        self.vertical.addWidget(chart_card)
        self.path_card, self.chart_card = table_card, chart_card
        self.compact_tabs = QTabBar()
        self.compact_tabs.setObjectName("compactReactionTabs")
        self.compact_tabs.setAccessibleName("Reaction view / 反应视图")
        self.compact_tabs.addTab("路径节点")
        self.compact_tabs.addTab("能量图")
        self.compact_tabs.addTab("节点详情")
        self.compact_tabs.setCurrentIndex(self._compact_focus_index)
        self.compact_tabs.currentChanged.connect(self.compact_focus_changed)
        self.compact_tabs.hide()
        self.profile.panelRequested.connect(self.compact_tabs.setCurrentIndex)
        self.horizontal.addWidget(self.vertical)
        self.inspector, inspector_layout = card()
        self.inspector.setProperty("profileSurface", True)
        self.inspector.setObjectName("profileInspector")
        self.inspector.setProperty("profileChrome", "panel")
        self.inspector.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setContentsMargins(14, 14, 14, 14)
        self.inspector.setMinimumWidth(260)
        self.inspector.setMaximumWidth(380)
        self.inspector_scroll = QScrollArea()
        self.inspector_scroll.setWidgetResizable(True)
        self.inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        inspector_body = QWidget()
        inspector_content = QVBoxLayout(inspector_body)
        inspector_content.setContentsMargins(2, 2, 8, 4)
        inspector_content.setSpacing(9)
        self.inspector_scroll.setWidget(inspector_body)
        inspector_layout.addWidget(self.inspector_scroll, 1)
        self.plot_inspector = PlotInspector()
        self.profile.details_widget = self.plot_inspector
        self.plot_inspector.preview.selected.connect(self.select_node)
        inspector_content.addWidget(self.plot_inspector)
        self.node_editor = QWidget()
        inspector_content.addWidget(self.node_editor)
        inspector_content = QVBoxLayout(self.node_editor)
        inspector_content.setContentsMargins(0, 8, 0, 0)
        inspector_content.addWidget(label("节点属性", "section"))
        self.node_name = QLineEdit()
        self.node_name.setPlaceholderText("选中一个节点")
        self.node_name.setProperty("i18n_placeholder", "选中一个节点")
        inspector_content.addWidget(label("显示标签", "muted"))
        inspector_content.addWidget(self.node_name)
        self.role_combo = QComboBox()
        for role, text in (("unspecified", "未指定"), ("reactant", "反应物"), ("intermediate", "中间体"), ("transition_state", "过渡态"), ("product", "产物")):
            self.role_combo.addItem(text, role)
        inspector_content.addWidget(self.role_combo)
        self.apply_node = button("应用标签与角色", self.apply_label)
        inspector_content.addWidget(self.apply_node)
        inspector_content.addWidget(label("体系表达式", "muted"))
        self.expression = QPlainTextEdit()
        self.expression.setReadOnly(True)
        self.expression.setMaximumHeight(88)
        self.expression.setPlaceholderText("导入后自动绑定文件与作业")
        self.expression.setProperty("i18n_placeholder", "导入后自动绑定文件与作业")
        inspector_content.addWidget(self.expression)
        self.reference_button = button("将此节点设为参考", self.set_reference)
        inspector_content.addWidget(self.reference_button)
        self.evidence_title = label("计算与来源证据", "muted")
        inspector_content.addWidget(self.evidence_title)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setMinimumHeight(100)
        inspector_content.addWidget(self.evidence, 1)
        self.evidence_title.hide()
        self.evidence.hide()
        self.horizontal.addWidget(self.inspector)
        self.horizontal.setSizes([760, 300])
        self.vertical.setSizes([300, 300])
        self.horizontal.splitterMoved.connect(self.splitters_changed)
        self.vertical.splitterMoved.connect(self.splitters_changed)
        layout.addWidget(self.horizontal, 1)
        self.legacy_reaction_page = page
        self.energy_page = QWidget()
        self.energy_page.setObjectName("energyWorkbench")
        energy_layout = QVBoxLayout(self.energy_page)
        energy_layout.setContentsMargins(0, 0, 0, 0)
        energy_layout.setSpacing(0)
        energy_layout.addWidget(self.profile)
        self.reaction_pages = QStackedWidget()
        self.reaction_pages.addWidget(self.energy_page)
        self.reaction_pages.addWidget(page)
        reaction = QWidget()
        reaction.setObjectName("reactionRoute")
        reaction_layout = QVBoxLayout(reaction)
        reaction_layout.setContentsMargins(0, 0, 0, 0)
        reaction_layout.setSpacing(6)
        reaction_layout.addWidget(self.compact_tabs)
        reaction_layout.addWidget(self.reaction_pages, 1)
        return reaction

    def _shortcuts(self):
        for key in ("new_project", "open_project", "save_project", "save_as", "edit_reaction_path", "import_logs", "calculate"):
            self.addAction(self.project_actions.action(key))
        for sequence, callback in (("Ctrl+F", lambda: self.search.setFocus()),
                                   ("Ctrl+Z", self.controller.undo),
                                   ("Ctrl+Shift+Z", self.controller.redo)):
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.triggered.connect(callback)
            self.addAction(action)

    def bootstrap_ready(self, preferences, candidates):
        selected_language = preferences.get("language", "system")
        if selected_language == "system":
            from PySide6.QtCore import QLocale
            selected_language = "zh_CN" if QLocale.system().name().lower().startswith("zh") else "en"
        self.language = selected_language
        self.theme = preferences.get("theme", "system")
        self.visual_effects = preferences.get("visual_effects", "standard")
        self.reduce_motion = preferences.get("reduce_motion", False)
        for action, checked in ((self.visual_effects_action, self.visual_effects == "reduced"),
                                (self.motion_action, self.reduce_motion)):
            action.blockSignals(True)
            action.setChecked(checked)
            action.blockSignals(False)
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(self.language)))
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(self.theme)))
        self.retranslate()
        self.apply_appearance()
        geometry = preferences.get("window_geometry")
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except (ValueError, UnicodeError):
                pass  # Invalid local window hints do not block scientific project recovery.
        self.populate_recent()

    def language_changed(self, *_):
        value = self.language_combo.currentData()
        if not value or value == self.language:
            return
        self.language = value
        self.retranslate()
        if self.controller.preferences:
            self.controller.update_preferences(language=value)

    def theme_changed(self, *_):
        value = self.theme_combo.currentData()
        if not value or value == self.theme:
            return
        self.theme = value
        self.apply_appearance()
        if self.controller.preferences:
            self.controller.update_preferences(theme=value)

    def effects_changed(self, checked):
        self.visual_effects = "reduced" if checked else "standard"
        self.apply_appearance()
        if self.controller.preferences:
            self.controller.update_preferences(visual_effects=self.visual_effects)

    def motion_changed(self, checked):
        self.reduce_motion = bool(checked)
        self.apply_appearance()
        if self.controller.preferences:
            self.controller.update_preferences(reduce_motion=self.reduce_motion)

    def apply_appearance(self):
        from PySide6.QtWidgets import QApplication
        dark = apply_theme(QApplication.instance(), self.theme,
                           reduced=self.visual_effects == "reduced", reduce_motion=self.reduce_motion)
        self._glass_theme = "dark" if dark else "light"
        self.appearance_button.setIcon(self._resource_icon("settings.svg", self._glass_theme))
        for index, icon in enumerate(self.nav_icons):
            self.navigation.item(index).setIcon(self._resource_icon(icon, self._glass_theme))
        self.preview.set_theme(dark)
        self.plot_inspector.set_theme(dark)
        self.profile.set_theme(dark)

    def set_localized_text(self, widget, text):
        widget.setProperty("i18n_source", text)
        widget.setText(translate(text, self.language))

    def show_message(self, text):
        self.set_localized_text(self.task_label, text)

    def retranslate(self):
        """Change presentation only; project IDs, calculations and view state stay intact."""
        for widget in self.findChildren(QWidget):
            original = widget.property("i18n_source")
            if isinstance(widget, QLabel) and original is not None:
                widget.setText(translate(original, self.language))
            elif isinstance(widget, QPushButton) and original is not None:
                widget.setText(translate(original, self.language))
            elif isinstance(widget, QCheckBox) and original is not None:
                widget.setText(translate(original, self.language))
            placeholder = widget.property("i18n_placeholder")
            if placeholder is not None:
                widget.setPlaceholderText(translate(placeholder, self.language))
        self.appearance_button.setAccessibleName(translate("外观设置", self.language))
        self.appearance_button.setToolTip(translate("外观设置", self.language))
        self.nav_heading.setText(translate("研究工作台", self.language))
        self.nav_footer.setText("    LOCAL FIRST\n    Offline · Traceable · Recoverable" if self.language == "en" else "    LOCAL FIRST\n    离线 · 可追溯 · 可恢复")
        self.render_layout()
        combos = ((self.language_combo, {"zh_CN": "中文", "en": "EN"}),
                  (self.theme_combo, {"system": "跟随系统", "light": "浅色", "dark": "深色"}),
                  (self.file_filter, {"": "全部状态", "已解析": "已解析", "来源": "未连接 / 已变更", "读取失败": "失败"}),
                  (self.kind_combo, KIND_LABELS), (self.unit_combo, UNIT_LABELS),
                  (self.mode_combo, {"relative": "相对能量", "absolute": "绝对能量", "direct_difference": "直接差值"}),
                  (self.role_combo, {"unspecified": "未指定", "reactant": "反应物", "intermediate": "中间体", "transition_state": "过渡态", "product": "产物"}))
        for combo, mapping in combos:
            for i in range(combo.count()):
                combo.setItemText(i, translate(mapping.get(combo.itemData(i), combo.itemText(i)), self.language))
        self._update_reaction_control_widths(self.width() < 1024)
        self.source_model.set_language(self.language)
        for action in self.findChildren(QAction):
            raw = action.property("i18n_source")
            if raw:
                action.setText(translate(raw, self.language))
        self.node_model.set_language(self.language)
        self.preview.set_language(self.language)
        self.plot_inspector.set_language(self.language)
        self.profile.set_language(self.language)
        for page in getattr(self, "analysis_pages", {}).values():
            page.set_language(self.language)
        if getattr(self, "project_tables", None):
            self.project_tables.set_language(self.language)
        self.refresh()

    def populate_recent(self):
        preferences, candidates = self.controller.preferences, self.controller.candidates
        self.recent.clear()
        for path in preferences.get("recent_projects", []):
            item = QListWidgetItem(f"{Path(path).stem}\n{path}")
            item.setData(ID_ROLE, ("project", path))
            self.recent.addItem(item)
        for candidate in candidates:
            if candidate.error_code is None:
                item = QListWidgetItem(f"恢复副本 · 修订 {candidate.revision}\n{candidate.path.name}")
                item.setData(ID_ROLE, ("recovery", str(candidate.path)))
                self.recent.addItem(item)
        if not self.recent.count():
            item = QListWidgetItem("暂无最近项目 · 导入日志开始研究")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(item)
        self.continue_button.setEnabled(bool(preferences.get("recent_projects")))
        self.update_actions()

    def continue_last(self):
        paths = self.controller.preferences.get("recent_projects", [])
        if paths:
            self.open_path(paths[0])

    def open_recent(self, item=None):
        if isinstance(item, bool) or item is None:
            item = self.recent.currentItem()
        data = item.data(ID_ROLE) if item else None
        if data and not self.controller.busy:
            if data[0] == "recovery":
                self.controller.recover_project(data[1])
            else:
                self.open_path(data[1])

    def _selected_recent_path(self):
        item = self.recent.currentItem()
        data = item.data(ID_ROLE) if item else None
        return data[1] if data and data[0] == "project" else None

    def rename_selected_recent(self):
        path = self._selected_recent_path()
        if path:
            self._rename_recent_path(path)

    def remove_selected_recent(self):
        path = self._selected_recent_path()
        if path:
            self._remove_recent_path(path)

    def delete_selected_recent(self):
        path = self._selected_recent_path()
        if path:
            self._delete_recent_path(path)

    def _open_recent_path(self, path):
        if not self.controller.busy:
            self.open_path(path)

    def _rename_recent_path(self, path):
        if not self.controller.busy:
            self.rename_project_path(path)

    def _remove_recent_path(self, path):
        if not self.controller.busy:
            self.controller.remove_recent_project(path)

    def _delete_recent_path(self, path):
        if not self.controller.busy:
            self.confirm_delete_project(path)

    def recent_context_menu(self, position):
        item = self.recent.itemAt(position)
        data = item.data(ID_ROLE) if item else None
        if not data or data[0] != "project":
            return
        menu = QMenu(self.recent)
        menu.addAction(translate("打开", self.language), lambda: self._open_recent_path(data[1]))
        menu.addAction(translate("从最近移除", self.language), lambda: self._remove_recent_path(data[1]))
        menu.addAction(translate("重命名项目文件…", self.language), lambda: self._rename_recent_path(data[1]))
        menu.addAction(translate("删除项目文件…", self.language), lambda: self._delete_recent_path(data[1]))
        menu.exec(self.recent.mapToGlobal(position))

    def rename_project_path(self, path):
        if self.controller.busy:
            return
        try:
            source = Path(path).resolve()
        except (OSError, ValueError) as exc:
            self.show_error("invalid_project_path", str(exc))
            return
        raw, ok = QInputDialog.getText(
            self, translate("重命名项目", self.language),
            translate("新名称（.grproj 为固定扩展名）", self.language), text=source.stem)
        if not ok:
            return
        try:
            filename = normalize_project_name(raw)
        except ValueError as exc:
            self.show_error("invalid_project_name", str(exc))
            return
        if filename == source.stem:
            return
        if filename.casefold() == source.stem.casefold():
            self.show_error("rename_case_only_unsupported", filename)
            return
        target = source.with_name(filename + ".grproj")
        answer = QMessageBox.question(
            self, translate("确认重命名项目", self.language),
            translate("将项目文件改名为：", self.language) + "\n" + str(target),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.controller.rename_project(str(source), str(target)):
            self.show_error("operation_not_started", "")

    def confirm_delete_project(self, path):
        full_path = str(Path(path).resolve())
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("删除项目文件")
        box.setText(f"将永久删除此项目文件：\n{full_path}\n\n此操作不会删除来源日志或其他文件。")
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Yes).setText("删除项目文件")
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.controller.delete_project_file(path)

    def rename_current_project(self):
        path = self.controller.path
        if self.controller.busy or not self.controller.project or self.controller.read_only:
            return
        if path:
            self.rename_project_path(str(path))
            return
        raw, ok = QInputDialog.getText(
            self, translate("重命名项目", self.language),
            translate("项目名称（将在首次保存时作为文件名）", self.language),
            text=self._current_pending_project_name() or "")
        if not ok:
            return
        try:
            name = normalize_project_name(raw)
        except ValueError as exc:
            self.show_error("invalid_project_name", str(exc))
            return
        if name == self._current_pending_project_name():
            return
        self._pending_project_name = name
        self.controller.set_workspace(ux_v2={"version": 1, "pending_project_name": name})
        self.refresh()

    def _current_pending_project_name(self):
        ux_v2 = self.controller.workspace.get("ux_v2", {})
        if isinstance(ux_v2, Mapping) and ux_v2.get("pending_project_name"):
            return str(ux_v2["pending_project_name"])
        return self._pending_project_name or self._requested_project_name

    def new_project(self, open_builder=False, create_new_path=False):
        if not self.controller.busy:
            raw_name, ok = QInputDialog.getText(
                self, translate("新建项目", self.language),
                translate("项目名称（将在首次保存时作为文件名）", self.language))
            if not ok:
                return
            try:
                self._requested_project_name = normalize_project_name(raw_name)
            except ValueError as exc:
                self.show_error("invalid_project_name", str(exc))
                return
            self._pending_builder_after_new = bool(open_builder)
            self._pending_new_path_after_new = bool(create_new_path)
            self.banner.hide()
            if not self.controller.new_project():
                self._requested_project_name = ""

    def choose_open(self):
        if self.controller.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开研究项目", "", APP_NAME + " (*.grproj)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        self.banner.hide()
        self.controller.open_project(path)

    def choose_files(self):
        if self.controller.busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "导入 Gaussian 日志", "", "Gaussian 日志 (*.log *.out);;全部文件 (*)")
        if paths:
            self.import_paths(paths)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "导入文件夹")
        if folder:
            self.import_paths([folder])

    def import_paths(self, paths):
        if self.controller.busy:
            return
        self.banner.hide()
        if self.controller.project is None:
            self._pending_import = paths
            self.controller.new_project()
        else:
            self.navigation.setCurrentRow(2)
            before = {source.id for source in self.controller.project.source_files}
            if self.controller.import_files(paths, recursive=self.recursive.isChecked()):
                self._pending_import_source_ids = before

    def save_project(self, save_as=False):
        if self.controller.busy or self.controller.project is None:
            return
        self.banner.hide()
        path = None
        if save_as or self.controller.path is None or self.controller.read_only:
            default_name = (self._current_pending_project_name() or "研究项目").strip()
            if not default_name.lower().endswith(".grproj"):
                default_name += ".grproj"
            path, _ = QFileDialog.getSaveFileName(self, translate("保存研究项目", self.language), default_name, APP_NAME + " (*.grproj)",
                                                 options=QFileDialog.Option.DontConfirmOverwrite)
            if not path:
                return
            if not path.lower().endswith(".grproj"):
                path += ".grproj"
            try:
                normalize_project_name(Path(path).name)
            except ValueError as exc:
                self.show_error("invalid_project_name", str(exc))
                return
        first_save = self.controller.path is None
        if not self.controller.save(path):
            self.show_error("operation_not_started", "")
            return
        target_path = path if path is not None else self.controller.path
        self._pending_save_request = {
            "token": self.controller.active_task_token,
            "project_id": self.controller.project.id,
            "revision": self.controller.project.revision,
            "path": str(Path(target_path).resolve()) if target_path is not None else None,
            "first_save": first_save,
        }

    def _operation_finished(self, token, operation, success, project_id, revision, path):
        if operation == "new":
            requested, self._requested_project_name = self._requested_project_name, ""
            if success and self.controller.project and requested:
                self._pending_project_name = requested
                self.controller.set_workspace(ux_v2={"version": 1, "pending_project_name": requested})
                self.refresh()
            else:
                self._pending_project_name = ""
        elif operation in ("open", "recover") and success:
            self._pending_project_name = ""
        elif operation == "rename_project" and success:
            if path and self.controller.path and Path(path).resolve() == self.controller.path:
                self._pending_project_name = ""
                self.refresh()

        if operation == "import":
            before_ids, self._pending_import_source_ids = self._pending_import_source_ids, None
            if success and self.controller.project and self.controller.project.id == project_id:
                QTimer.singleShot(0, lambda project_id=project_id, before_ids=before_ids or set():
                                  self._show_import_summary(project_id, before_ids))

        request = self._pending_save_request
        if not request or token != request["token"] or operation != "save":
            return
        self._pending_save_request = None
        event_path = str(Path(path).resolve()) if path else None
        expected_path = request["path"]
        matches = (success and project_id == request["project_id"]
                   and type(revision) is int and revision >= request["revision"]
                   and event_path == expected_path
                   and self.controller.path is not None
                   and str(self.controller.path) == expected_path
                   and self._save_status is not None
                   and self._save_status.saved_revision is not None
                   and self._save_status.saved_revision >= request["revision"])
        if matches:
            self._save_error = False
            if request["first_save"]:
                self.controller.clear_pending_project_name()
            self._pending_project_name = ""
            self._requested_project_name = ""
            self.banner.hide()
            self.saved_changed(self._save_status)
            self.refresh()
        else:
            self._save_error = True
            if success:
                self._last_error = "项目保存结果与提交的项目修订或目标路径不匹配。"
                self.set_localized_text(self.banner, "保存未成功；项目名称与当前工作已保留。\n" + self._last_error)
                self.banner.show()
            self.saved_changed(self._save_status)

    def page_changed(self, page):
        if hasattr(self, "stack"):
            self.stack.setCurrentIndex(page)
            self.backdrop.set_energy_profile(page == 2)
            self.eyebrow.setVisible(page != 2)
            self.title.setText(translate(self.nav_source_text[page], self.language))
            if not self._rendering and page in (0, 1, 2):
                self.controller.set_workspace(page=page)
            self.render_layout()

    def activate_route(self, route):
        """Navigate by stable route key while preserving the existing stack indices."""
        routes = {"home": (0, None), "sources": (1, None),
                  "path_nodes": (2, 0), "energy": (2, 1)}
        if route not in routes:
            raise ValueError(f"Unknown route: {route}")
        page, reaction_tab = routes[route]
        self.navigation.setCurrentRow(page)
        if reaction_tab is not None:
            self.compact_tabs.setCurrentIndex(reaction_tab)
        self.render_layout()

    def filter_changed(self, *_):
        if not hasattr(self, "source_proxy"):
            return
        query = self.search.text()
        self.node_proxy.setFilterFixedString(query)
        self.source_proxy.setFilterFixedString(query)
        self.source_proxy.set_state_filter(self.file_filter.currentData() or "")
        if not self._rendering:
            self.controller.set_workspace(filter=query, file_filter=self.file_filter.currentData())

    def path_selected(self, *_):
        if not self._rendering and self.path_combo.currentData():
            self.controller.set_workspace(path_id=self.path_combo.currentData())
            self.refresh()

    def option_changed(self, **values):
        if not self._rendering:
            self.controller.path_options(**values)

    def _selected_id(self, table):
        rows = table.selectionModel().selectedRows()
        return rows[0].data(ID_ROLE) if rows else None

    def source_selected(self, *_):
        self._selected_source = self._selected_id(self.source_table)
        project = self.controller.project
        source = next((s for s in project.source_files if s.id == self._selected_source), None) if project else None
        lines = []
        if source:
            lines = [source.original_path, f"SHA256: {source.sha256 or ('Unavailable' if self.language == 'en' else '未取得')}"]
            connection = next((c for c in self.controller.connections if c.source_file_id == source.id), None)
            if connection:
                lines.append(("Current source: " if self.language == "en" else "当前来源：") + translate(STATE_LABELS.get(connection.state, connection.state), self.language))
            if source.import_state.value == "failed":
                if source.sha256:
                    reason = "文件为空" if source.size_bytes == 0 else "未找到能量字段"
                else:
                    reason = "文件读取错误"
                lines.append(("Source diagnostic: " if self.language == "en" else "来源诊断：")
                             + translate(reason, self.language))
            for job in source.jobs:
                if self.language == "en":
                    lines.append(f"Job {job.ordinal + 1} · {job.termination.value} · lines {job.start_line}–{job.end_line}")
                    lines += [f"  {translate(kind.value, self.language)}: {v.raw_text} Eh · line {v.source_line}" for kind, v in job.energies.items()]
                else:
                    lines.append(f"作业 {job.ordinal + 1} · {job.termination.value} · 行 {job.start_line}–{job.end_line}")
                    lines += [f"  {kind.value}: {v.raw_text} Eh · 行 {v.source_line}" for kind, v in job.energies.items()]
                lines += ["  " + d.code for d in job.diagnostics]
        self.source_detail.setPlainText("\n".join(lines))
        if not self._rendering:
            self.controller.set_workspace(source_id=self._selected_source)
        self.update_actions()

    def node_selected(self, *_):
        self._selected_node = self._selected_id(self.node_table)
        path = self.controller.selected_path
        self._selected_entry_id = next((entry.id for entry in path.entries
                                        if entry.node_id == self._selected_node), None) if path and self._selected_node else None
        if not self._rendering:
            self.controller.set_workspace(node_id=self._selected_node)
        self.update_inspector()
        if not self._rendering and not self._chart_selecting and self.controller.selected_path:
            path = self.controller.selected_path
            selected = set(self.selected_node_ids())
            self.profile.set_table_selection([(path.id, e.id) for e in path.entries if e.node_id in selected])

    def chart_selected(self, path_id, node_id, entry_id):
        self._chart_selecting = True
        try:
            self._selected_entry_id = entry_id
            self._selected_node = node_id
            self.controller.set_workspace(path_id=path_id, node_id=node_id)
            if self.controller.read_only:
                self.controller.workspace.update(path_id=path_id, node_id=node_id)
            self.refresh()
            self.select_node(node_id)
        finally:
            self._chart_selecting = False

    def chart_mode_changed(self, mode):
        if self.profile.workbench:
            return
        if getattr(self.profile, "_expanded", None):
            return
        if mode == "3d":
            self._two_dimensional_sizes = self.vertical.sizes()
            total = sum(self._two_dimensional_sizes)
            self.vertical.setSizes([int(total*.3), int(total*.7)])
        elif hasattr(self, "_two_dimensional_sizes"):
            self.vertical.setSizes(self._two_dimensional_sizes)
        self.controller.set_workspace(vertical_splitter=self.vertical.sizes())

    def select_node(self, node_id):
        for row in range(self.node_proxy.rowCount()):
            index = self.node_proxy.index(row, 0)
            if index.data(ID_ROLE) == node_id:
                self.node_table.selectRow(row)
                self.node_table.scrollTo(index)
                return

    def update_inspector(self):
        project = self.controller.project
        node = next((n for n in project.nodes if n.id == self._selected_node), None) if project else None
        self.node_name.setText(node.label if node else "")
        self.expression.setPlainText(node.expression.draft_text if node and node.expression.draft_text is not None
                                     else render_expression(node.expression, project.alias_bindings) if node else "")
        evidence = []
        path = self.controller.selected_path
        result = next((r for r in self.controller.results if path and r.path_id == path.id), None)
        entry_id = self._selected_entry_id
        if path and self._selected_node and not any(entry.id == entry_id and entry.node_id == self._selected_node for entry in path.entries):
            entry_id = next((entry.id for entry in path.entries if entry.node_id == self._selected_node), None)
        value = next((v for v in result.nodes if v.entry_id == entry_id and v.node_id == self._selected_node), None) if result and entry_id else None
        if node:
            self.role_combo.setCurrentIndex(self.role_combo.findData(node.role.value))
            if value:
                if self.language == "en":
                    evidence += [f"System energy: {value.absolute_hartree} Eh", f"Reference energy: {value.reference_hartree} Eh",
                                 f"Current result: {value.display_value if value.valid else 'Unavailable'} {UNIT_LABELS[value.unit.value]}"]
                else:
                    evidence += [f"体系能量: {value.absolute_hartree} Eh", f"参考能量: {value.reference_hartree} Eh",
                                 f"当前结果: {value.display_value if value.valid else '不可用'} {UNIT_LABELS[value.unit.value]}"]
                for dep in value.dependencies:
                    evidence += [f"\n{dep.source_label} · {'line' if self.language == 'en' else '行'} {dep.source_line}", f"{translate(dep.kind.value, self.language)}: {dep.value_hartree} Eh"]
                evidence += [("\nDiagnostics: " if self.language == "en" else "\n诊断：") + d.code for d in (*value.diagnostics, *result.diagnostics)]
            else:
                evidence.append("Waiting for current revision calculation" if self.language == "en" else "等待当前修订计算完成")
            if node.expression.draft_error:
                evidence.append(("Invalid draft: " if self.language == "en" else "草稿有误：") + node.expression.draft_error.code)
        self.evidence.setPlainText("\n".join(evidence))
        snapshot = build_plot_inspector_snapshot(project, path, result, self._selected_node, entry_id,
                                                  self.controller.connections) if project and path else None
        preview_result = result if snapshot and snapshot["status"] in ("valid", "invalid") else None
        self.plot_inspector.set_snapshot(snapshot, project, path, preview_result)
        self.preview.set_data(project, self.controller.selected_path, result, self._selected_node)
        self.profile.set_spec(self.controller.plot_spec or (build_plot_spec(project, ()) if project else None),
                              self.controller.selected_path.id if self.controller.selected_path else None)
        self.update_actions()

    def set_reference(self):
        if self._selected_node:
            self.controller.reference_node(self._selected_node)

    def apply_label(self):
        if self._selected_node:
            self.controller.rename_node(self._selected_node, self.node_name.text(), self.role_combo.currentData())

    def edit_expression(self):
        if not self.controller.busy and not self.controller.read_only and self._selected_node and self.controller.selected_path:
            from .expression_editor import ExpressionDialog
            dialog = ExpressionDialog(self.controller, node_id=self._selected_node, language=self.language, parent=self)
            dialog.exec()
            dialog.deleteLater()

    def show_profile_source(self, value):
        """Verified excerpt in a real source/job/line viewer; never read files on UI."""
        from PySide6.QtGui import QTextCursor
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        en = self.language == "en"
        dialog.setWindowTitle(("Log Viewer · " if en else "日志查看器 · ")+value.get("source_label",""))
        layout = QVBoxLayout(dialog)
        heading = QLabel(f"{value.get('source_label','')} · Job {value.get('job_ordinal','—')} · SHA-256 {value.get('source_sha256','—')}")
        heading.setTextFormat(Qt.TextFormat.PlainText);heading.setWordWrap(True);layout.addWidget(heading)
        text = QPlainTextEdit();text.setReadOnly(True);text.setObjectName("profileSourceExcerpt")
        excerpt = value.get("excerpt")
        text.setPlainText(excerpt["text"] if excerpt else (("Source unavailable: " if en else "来源不可用：")+value.get("status","unavailable")))
        layout.addWidget(text)
        if excerpt:
            cursor = text.textCursor();cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(QTextCursor.MoveOperation.Down,QTextCursor.MoveMode.MoveAnchor,excerpt["line"]-excerpt["start"])
            cursor.select(QTextCursor.SelectionType.LineUnderCursor);text.setTextCursor(cursor);text.ensureCursorVisible()
        dialog.resize(900,500);dialog.show();self._profile_source_dialog = dialog

    def edit_reference(self):
        if not self.controller.busy and not self.controller.read_only and self.controller.selected_path:
            if self.controller.selected_path.calculation_mode == "direct_difference":
                self.show_error("direct_difference", translate("直接差值路径不能再次设置参考。", self.language))
                return
            from .expression_editor import ExpressionDialog
            dialog = ExpressionDialog(self.controller, path_id=self.controller.selected_path.id, language=self.language, parent=self)
            dialog.exec()
            dialog.deleteLater()

    def new_node(self):
        text, ok = QInputDialog.getText(self, translate("新增节点", self.language), translate("显示标签", self.language))
        if ok and text.strip():
            self.controller.add_node(text.strip())

    def copy_node(self):
        if self._selected_node and not self.controller.busy:
            node = next((n for n in self.controller.project.nodes if n.id == self._selected_node), None)
            if node:
                self.controller.add_node(node.label + " (2)", copy_id=node.id)

    def selected_node_ids(self):
        return [row.data(ID_ROLE) for row in self.node_table.selectionModel().selectedRows()]

    def remove_selected_nodes(self):
        identifiers = self.selected_node_ids()
        if identifiers:
            self.controller.remove_nodes(identifiers)

    def manage_path(self, action):
        if self.controller.busy or self.controller.read_only or not self.controller.project:
            return
        path = self.controller.selected_path
        if action in ("new", "new_advanced"):
            from .path_editor import NewPathDialog
            project_id = self.controller.project.id
            dialog = NewPathDialog(self.controller.project, path, language=self.language, parent=self)
            if dialog.exec() == QDialog.DialogCode.Accepted and self.controller.project and self.controller.project.id == project_id:
                values = dialog.values()
                self.controller.edit_path("new", **values)
        elif action in ("copy", "rename"):
            text, ok = QInputDialog.getText(self, translate("路径管理", self.language),
                        translate("路径名称（副本共享节点，编辑节点会影响所有引用路径）", self.language),
                        text=(path.label + " (2)" if action == "copy" and path else path.label if action == "rename" and path else ""))
            if ok and text.strip():
                self.controller.edit_path(action, text.strip())
        elif path and action == "color":
            self.change_profile_path_color(path.id)
        elif path and action == "visible":
            self.controller.edit_path("visible", not path.visible)
        elif path and action == "delete":
            answer = QMessageBox.question(self, translate("删除路径", self.language), path.label)
            if answer == QMessageBox.StandardButton.Yes:
                self.controller.edit_path("delete")

    def select_profile_path(self, path_id):
        if not self.controller.project or not any(p.id == path_id for p in self.controller.project.paths):
            return
        if self.controller.read_only:
            self.controller.workspace.update(path_id=path_id)
        else:
            self.controller.set_workspace(path_id=path_id)
        self.refresh()

    def change_profile_path_color(self, path_id):
        if self.controller.busy or self.controller.read_only or not self.controller.project:
            return
        project_id = self.controller.project.id
        path = next((p for p in self.controller.project.paths if p.id == path_id), None)
        if not path:
            return
        color = QColorDialog.getColor(QColor(path.color), parent=self)
        if color.isValid() and self.controller.project and self.controller.project.id == project_id:
            self.controller.edit_path("color", color.name(), path_id=path_id)

    def batch_nodes(self):
        self.open_batch(False)

    def batch_paths(self):
        self.open_batch(True)

    def open_batch(self, paths):
        if self.controller.busy or self.controller.read_only or not self.controller.selected_path:
            return
        from .batch_editor import BatchDialog
        dialog = BatchDialog(self.controller, self.selected_node_ids(), paths=paths, language=self.language, parent=self)
        dialog.exec()
        dialog.deleteLater()

    def remove_source(self):
        if not self._selected_source or self.controller.busy or self.controller.read_only:
            return
        from ..core.project_edits import find_source_usage, remove_sources
        project = self.controller.project
        usage = find_source_usage(project, [self._selected_source])
        cascade = False
        if usage.in_use:
            nodes = [n.label for n in project.nodes if n.id in usage.node_ids]
            paths = [p.label for p in project.paths if p.id in usage.reference_path_ids]
            box = QMessageBox(self)
            box.setWindowTitle(translate("来源仍被引用", self.language))
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setText(translate("级联删除将移除以下依赖节点和参考路径：", self.language) + "\n" + "\n".join(nodes + paths))
            remove = box.addButton(translate("级联删除", self.language), QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(translate("取消", self.language), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() != remove:
                return
            cascade = True
        self.controller.apply_change(remove_sources(project, [self._selected_source], cascade=cascade))

    def move_selected(self, direction):
        rows = self.node_table.selectionModel().selectedRows()
        if rows:
            self.controller.move_node(rows[0].data(ID_ROLE + 2), direction)

    def choose_reconnect(self):
        if self._selected_source:
            path, _ = QFileDialog.getOpenFileName(self, "重新定位日志（必须指纹一致）", "", "日志 (*.log *.out);;全部文件 (*)")
            if path:
                self.controller.reconnect(self._selected_source, path)

    def _show_import_summary(self, project_id, previous_source_ids):
        project = self.controller.project
        if project is None or project.id != project_id:
            return
        added_source_ids = {source.id for source in project.source_files} - set(previous_source_ids)
        dialog = ImportSummaryDialog(project, added_source_ids=added_source_ids, parent=self)
        self._import_summary_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.finished.connect(lambda result, dialog=dialog, project_id=project_id:
                                self._import_summary_finished(dialog, result, project_id))
        dialog.show()

    def _import_summary_finished(self, dialog, result, project_id):
        if self._import_summary_dialog is dialog:
            self._import_summary_dialog = None
        project = self.controller.project
        if (result == QDialog.DialogCode.Accepted and project and project.id == project_id and
                dialog.selected_candidates):
            self.open_reaction_builder(candidate_cards=dialog.selected_candidates,
                                       create_new_path=not bool(project.paths))

    def open_reaction_builder(self, path_id=None, node_id=None, entry_id=None, *, create_new_path=False,
                              candidate_cards=None):
        if isinstance(path_id, bool):
            path_id = None
        if self.controller.busy:
            return
        if not self.controller.project:
            self.new_project(open_builder=True, create_new_path=create_new_path)
            return
        from .reaction_builder import ReactionBuilderDialog
        chosen_path = path_id or (self.controller.selected_path.id if self.controller.selected_path else None)
        dialog = ReactionBuilderDialog(self.controller, chosen_path, focus_node_id=node_id,
                                       create_new_path=create_new_path,
                                       candidate_cards=candidate_cards,
                                       focus_entry_id=entry_id, parent=self)
        dialog.exec()

    def _run_workflow_next(self):
        summary = getattr(self, "workflow_summary", None)
        if summary and summary.next_action:
            self.project_actions.action(summary.next_action).trigger()

    def _workflow_reconnect_source(self):
        project = self.controller.project
        if project is None:
            return
        connections = {item.source_file_id: item for item in self.controller.connections}
        target_source_id = next((source.id for source in project.source_files
            if source.id not in connections or connections[source.id].state != "available"), None)
        # Clear filters so the selected problem source is visible in the log table.
        previous_rendering = self._rendering
        self._rendering = True
        try:
            self.search.clear()
            self.file_filter.setCurrentIndex(max(0, self.file_filter.findData("")))
        finally:
            self._rendering = previous_rendering
        self.activate_route("sources")
        if target_source_id is not None:
            QTimer.singleShot(0, lambda source_id=target_source_id:
                              self._select_workflow_source(source_id))

    def _select_workflow_source(self, source_id):
        for row in range(self.source_proxy.rowCount()):
            index = self.source_proxy.index(row, 0)
            if index.data(ID_ROLE) == source_id:
                self.source_table.selectRow(row)
                self.source_table.scrollTo(index)
                return

    def _refresh_workflow_guide(self, project, path):
        summary = derive_workflow(project, self.controller.results, self.controller.connections,
            self._save_status, active_path_id=path.id if path else None,
            busy=self.controller.busy, read_only=self.controller.read_only,
            path=self.controller.path,
            workspace_dirty=getattr(self.controller, "_workspace_dirty", False),
            plot_dirty=getattr(self.controller, "_plot_dirty", False), save_failed=self._save_error)
        self.workflow_summary = summary
        labels = {"sources": "来源", "path": "路径", "check": "能量检查", "save": "保存"}
        states = {"ready": "已就绪", "pending": "待处理", "needs_attention": "需核对"}
        description = " · ".join(f"{labels[step.key]}：{states[step.state]}" for step in summary.steps)
        if summary.issue_count:
            description += f" · {summary.issue_count} 项需要处理"
        self.workflow_hint.setText(description)
        actions = {"import_logs": "导入 Gaussian 日志", "edit_reaction_path": "编辑反应路径",
                   "reconnect_source": "查看并重新定位来源", "show_sources": "查看来源连接状态",
                   "calculate": "检查当前路径能量", "save_project": "保存项目"}
        key = summary.next_action
        self.workflow_next_button.setText(actions.get(key, "流程已完成"))
        self.workflow_next_button.setEnabled(bool(key) and not self.controller.busy)
        self.workflow_next_button.setVisible(bool(key))

    def chart_species_requested(self, path_id, node_id, entry_id):
        self.open_reaction_builder(path_id, node_id, entry_id)

    def refresh(self):
        self._rendering = True
        selected_nodes = set(self.selected_node_ids())
        previous_primary = self._selected_node
        controller, project = self.controller, self.controller.project
        is_new = project is not None and project.id != self._last_project
        if is_new:
            selected_nodes.clear()
            self._last_project = project.id
            self._selected_node = None
            self._selected_source = None
        path = controller.selected_path
        result = next((r for r in controller.results if path and r.path_id == path.id), None)
        self._refresh_workflow_guide(project, path)
        for widget, count in zip(self.metric_values, (len(project.source_files), len(project.nodes), len(project.paths)) if project else (0, 0, 0)):
            widget.setText(str(count))
        name = controller.path.stem if controller.path else (self._current_pending_project_name() or translate("未命名项目", self.language))
        self.project_name.setText(name)
        self.project_name.setToolTip(translate("点击重命名项目", self.language))
        self.setWindowTitle(f"{name} · {APP_NAME} {VERSION_LABEL}")
        self.path_combo.clear()
        if project:
            for item in project.paths:
                self.path_combo.addItem(item.label, item.id)
        if path:
            self.path_combo.setCurrentIndex(self.path_combo.findData(path.id))
            for combo, value in ((self.kind_combo, path.energy_kind.value), (self.unit_combo, path.unit.value), (self.mode_combo, path.calculation_mode.value)):
                if combo.findData(value) < 0:
                    combo.addItem("直接差值", value)
                combo.setCurrentIndex(combo.findData(value))
            reference = ((path.reference_expression.draft_text if path.reference_expression.draft_text is not None else render_expression(path.reference_expression, project.alias_bindings))
                         if path.reference_expression else ("Not set" if self.language == "en" else "尚未设置"))
            if self.language == "en":
                self.reference_label.setText(f"Reference: {reference}" if path.calculation_mode == "relative" else "Absolute energy · no reference subtracted" if path.calculation_mode == "absolute" else "Direct difference · reference is included in node expressions")
            else:
                self.reference_label.setText(f"参考体系：{reference}" if path.calculation_mode == "relative" else "绝对能量模式 · 未扣减参考" if path.calculation_mode == "absolute" else "直接差值模式 · 参考已包含在节点表达式中")
        self.source_model.update(project, controller.connections, path.energy_kind if path else "gibbs_total")
        self.node_model.update(project, path, result)
        for page in getattr(self, "analysis_pages", {}).values():
            page.update_project(project, controller.connections)
        if getattr(self, "project_tables", None):
            self.project_tables.update_project(project, controller.results)
        state = controller.workspace
        if is_new or not self._widths_initialized:
            for table, key, defaults in ((self.source_table, "source_widths", [210, 112, 60, 145, 145]),
                                          (self.node_table, "node_widths", [55, 160, 155, 170, 95])):
                widths = state.get(key, defaults)
                if not isinstance(widths, (list, tuple)) or not all(type(v) is int and 30 <= v <= 2000 for v in widths):
                    widths = defaults
                for index, width in enumerate(widths[:5]):
                    table.setColumnWidth(index, width)
            self._widths_initialized = True
        if is_new:
            self.search.setText(str(state.get("filter", "")))
            page = state.get("page", 2 if project.source_files else 0)
            self.navigation.setCurrentRow(page if type(page) is int and page in (0, 1, 2) else 0)
            self.file_filter.setCurrentIndex(max(0, self.file_filter.findData(state.get("file_filter", ""))))
            for table, key in ((self.source_table, "source_sort"), (self.node_table, "node_sort")):
                order = state.get(key)
                if isinstance(order, (tuple, list)) and len(order) == 2 and type(order[0]) is int and -1 <= order[0] < 6 and order[1] in (0, 1):
                    table.sortByColumn(order[0], Qt.SortOrder(order[1]))
            for splitter, key in ((self.horizontal, "horizontal_splitter"), (self.vertical, "vertical_splitter")):
                sizes = state.get(key)
                if isinstance(sizes, (list, tuple)) and len(sizes) == 2 and all(type(v) is int and 0 < v < 10000 for v in sizes):
                    splitter.setSizes(list(sizes))
        self._selected_node = state.get("node_id") or self._selected_node
        if self._selected_node != previous_primary:
            selected_nodes.clear()
        available = {e.node_id for e in path.entries} if path else set()
        if self._selected_node not in available:
            self._selected_node = None
        self.select_node(self._selected_node)
        for row in range(self.node_proxy.rowCount()):
            index = self.node_proxy.index(row, 0)
            if index.data(ID_ROLE) in selected_nodes:
                self.node_table.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self._selected_source = state.get("source_id") or self._selected_source
        for row in range(self.source_proxy.rowCount()):
            if self.source_proxy.index(row, 0).data(ID_ROLE) == self._selected_source:
                self.source_table.selectRow(row)
                break
        self.update_inspector()
        self.source_selected()
        self._rendering = False
        self.update_actions()

    def update_actions(self):
        controller = self.controller
        idle = not controller.busy
        editable = idle and not controller.read_only
        no_access = "请等待当前任务完成。"
        self.project_actions.set_availability("new_project", idle, "" if idle else no_access)
        self.project_actions.set_availability("open_project", idle, "" if idle else no_access)
        self.project_actions.set_availability("save_project", idle and controller.project is not None,
                                              "" if idle and controller.project is not None else "当前没有可保存的项目。" if idle else no_access)
        self.project_actions.set_availability("save_as", idle and controller.project is not None,
                                              "" if idle and controller.project is not None else "当前没有可另存为的项目。" if idle else no_access)
        self.project_actions.set_availability("edit_reaction_path", idle, "" if idle else no_access)
        self.project_actions.set_availability(
            "new_reaction_path", idle and (controller.project is None or not controller.read_only),
            "当前项目为只读。" if controller.read_only else "" if idle else no_access)
        self.project_actions.set_availability("new_reaction_path_advanced", editable and controller.project is not None,
                                              "只读项目无法创建路径。" if controller.read_only else "请先新建或打开项目。" if not controller.project else "" if idle else no_access)
        self.project_actions.set_availability("import_logs", idle and (controller.project is None or not controller.read_only),
                                              "当前项目为只读。" if controller.read_only else "" if idle else no_access)
        self.project_actions.set_availability("show_sources", idle, "" if idle else no_access)
        self.project_actions.set_availability("show_path_nodes", idle, "" if idle else no_access)
        has_unavailable_source = bool(controller.project and any(
            connection.source_file_id in {source.id for source in controller.project.source_files}
            and connection.state != "available" for connection in controller.connections))
        if controller.project and len(controller.connections) < len(controller.project.source_files):
            connected_ids = {connection.source_file_id for connection in controller.connections}
            has_unavailable_source = has_unavailable_source or any(
                source.id not in connected_ids for source in controller.project.source_files)
        self.project_actions.set_availability("reconnect_source",
            editable and has_unavailable_source,
            "当前项目为只读。" if controller.read_only else "没有需要重新定位的来源。"
            if not has_unavailable_source else "" if idle else no_access)
        self.project_actions.set_availability("calculate", idle and controller.project is not None,
                                              "当前没有可计算的项目。" if not controller.project else "" if idle else no_access)
        can_rename = idle and controller.project is not None and not controller.read_only
        self.project_actions.set_availability("rename_project_file", can_rename,
                                              "当前项目无法重命名。" if not controller.project or controller.read_only else "" if idle else no_access)
        recent_path = self._selected_recent_path()
        recent_data = self.recent.currentItem().data(ID_ROLE) if self.recent.currentItem() else None
        has_recent_project = bool(recent_data and recent_data[0] == "project")
        self.recent_open_button.setEnabled(idle and recent_data is not None and recent_data[0] in ("project", "recovery"))
        self.recent_rename_button.setEnabled(idle and has_recent_project)
        self.recent_remove_button.setEnabled(idle and has_recent_project)
        self.recent_delete_button.setEnabled(idle and has_recent_project)
        self.project_name.setEnabled(can_rename)
        self.project_name.setAccessibleName(translate("重命名当前项目", self.language))
        self.import_button.setEnabled(editable)
        self.folder_button.setEnabled(editable)
        self.language_combo.setEnabled(idle)
        self.theme_combo.setEnabled(idle)
        self.recalculate.setEnabled(idle and controller.project is not None)
        for widget in (self.kind_combo, self.unit_combo, self.mode_combo):
            widget.setEnabled(editable and controller.selected_path is not None)
        self.path_combo.setEnabled(idle and self.path_combo.count() > 0)
        for widget in (self.apply_node, self.reference_button, self.node_name, self.role_combo, self.up_button, self.down_button):
            widget.setEnabled(editable and self._selected_node is not None)
        self.reconnect_button.setEnabled(editable and self._selected_source is not None)
        self.remove_source_button.setEnabled(editable and self._selected_source is not None)
        self.path_menu_button.setEnabled(editable and controller.project is not None)
        self.open_builder_button.setEnabled(self.project_actions.action("edit_reaction_path").isEnabled())
        self.node_menu_button.setEnabled(editable and controller.selected_path is not None)
        self.edit_expression_button.setEnabled(editable and any(n.id == self._selected_node for n in controller.project.nodes) if controller.project else False)
        self.edit_reference_button.setEnabled(editable and controller.selected_path is not None)
        self.undo_button.setEnabled(editable and bool(controller.undo_stack))
        self.redo_button.setEnabled(editable and bool(controller.redo_stack))

    def busy_changed(self, busy, operation):
        self.update_actions()
        self.saved_changed(self._save_status)
        self.task_progress.setVisible(busy)
        self.cancel_button.setVisible(busy and operation == "import")
        if busy:
            self.task_progress.setRange(0, 0)
            names = {"bootstrap": "载入本机工作记录", "import": "正在导入日志", "open": "正在验证项目来源", "save": "正在提交项目", "close": "正在保存并关闭", "calculate": "正在计算当前修订", "workspace": "正在备份工作状态"}
            self.set_localized_text(self.task_label, names.get(operation, "正在处理…"))
        else:
            if str(self.task_label.property("i18n_source") or "").startswith(("正在", "载入")):
                self.set_localized_text(self.task_label, "就绪 · 工作区可继续操作")
            if self._pending_import:
                paths, self._pending_import = self._pending_import, None
                QTimer.singleShot(0, lambda: self.import_paths(paths))
            if self._pending_builder_after_new:
                QTimer.singleShot(0, self._open_pending_builder)
            if self._close_when_idle and not self.controller._closed:
                self._close_when_idle = False
                QTimer.singleShot(0, self.close)

    def _open_pending_builder(self):
        if self.controller.busy:
            return
        should_open, self._pending_builder_after_new = self._pending_builder_after_new, False
        create_new_path, self._pending_new_path_after_new = self._pending_new_path_after_new, False
        if should_open and self.controller.project:
            self.open_reaction_builder(create_new_path=create_new_path)

    def progress_changed(self, done, total, name):
        self.task_progress.setRange(0, max(total, 1))
        self.task_progress.setValue(done)
        self.set_localized_text(self.task_label, f"导入 {done}/{total} · {name}")

    def saved_changed(self, status):
        self._save_status = status
        controller = self.controller
        feedback = derive_save_feedback(
            path=controller.path,
            status=status,
            project_revision=controller.project.revision if controller.project else None,
            busy_operation=controller.operation if controller.busy else "",
            workspace_dirty=controller._workspace_dirty,
            plot_dirty=controller._plot_dirty,
            read_only=controller.read_only,
            save_failed=self._save_error,
        )
        self.set_localized_text(self.saved, feedback.state)
        if feedback.recovery_hint:
            self.set_localized_text(self.recovery_saved, feedback.recovery_hint)
            self.recovery_saved.show()
        else:
            self.recovery_saved.hide()
        if status and status.recovery_error_code:
            self.recovery_saved.setToolTip(str(status.recovery_error_code))
        else:
            self.recovery_saved.setToolTip("")
        if feedback.state == "保存失败":
            detail = (status.error_code if status else None) or self._last_error or "请重试或另存为项目。"
            self.set_localized_text(self.banner, "保存失败。工作仍保留在当前会话；请重试或另存为。\n" + str(detail))
            self.banner.show()
        elif feedback.state == "已保存" and self._save_error:
            self._save_error = False
            self.banner.hide()
        self.recovery_saved.setVisible(bool(feedback.recovery_hint))

    def show_error(self, code, detail):
        self._pending_builder_after_new = False
        self._pending_new_path_after_new = False
        names = {"project_not_found": "找不到项目文件，请重新定位后打开。", "destination_exists": "目标已存在，请选择新的项目文件名。",
                 "fingerprint_mismatch": "日志内容与原来源不同，无法自动重连。", "session_save_failed": "保存未成功，请重试或另存为项目。"}
        names.update({"project_not_file": "所选目标不是项目文件。", "invalid_project_path": "项目文件名无效。",
                      "rename_same_directory_only": "项目只能在当前目录内重命名。", "project_delete_failed": "无法删除项目文件；项目仍可重试。",
                      "project_read_only": "当前项目为只读，不能重命名或删除。", "storage_io_failed": "项目文件被占用或无法访问。"})
        names.update({"plot_sources_changed": "来源已变化，请重新计算图表后再导出。", "stale_plot_export": "图表已更新，请重新导出。",
                      "plot_has_no_valid_values": "没有可导出的可见有效节点，请检查来源、草稿与路径显隐。",
                      "static_plot_export_failed": "静态图像导出失败；当前项目仍保留，请查看详情后重试。",
                      "static_plot_export_timeout": "静态图像导出超时；当前项目仍保留。"})
        names.update({"invalid_project_name": "项目名称无效。请检查长度、保留名和文件名字符。",
                      "rename_case_only_unsupported": "暂不支持只修改文件名大小写。",
                      "operation_not_started": "操作未启动，请等待当前任务完成后重试。"})
        self._last_error = detail
        self.set_localized_text(self.banner, names.get(code, "操作未完成，请查看详情后重试。") + "\n" + detail)
        self.banner.show()
        self.set_localized_text(self.task_label, "操作失败 · 当前工作仍保留")
        if getattr(self, "_closing_attempt", False):
            self._closing_attempt = False
            box = QMessageBox(self)
            box.setWindowTitle("项目尚未完整保存")
            box.setText("保存未成功，窗口仍保留。可以重试、另存为，或取消关闭。")
            retry = box.addButton("重试关闭", QMessageBox.ButtonRole.AcceptRole)
            save_as = box.addButton("另存为", QMessageBox.ButtonRole.ActionRole)
            box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            keep_recovery = None
            recovery = self.controller.backend.recovery
            status = recovery.status if recovery else None
            if status and status.recovery_revision == status.current_revision and not status.recovery_error_code:
                keep_recovery = box.addButton("保留恢复副本并退出", QMessageBox.ButtonRole.DestructiveRole)
            box.exec()
            if box.clickedButton() == retry:
                QTimer.singleShot(0, self.close)
            elif box.clickedButton() == save_as:
                QTimer.singleShot(0, lambda: self.save_project(True))
            elif keep_recovery and box.clickedButton() == keep_recovery:
                self.controller.close(allow_recovery=True)

    def recovery_offer(self, offer):
        box = QMessageBox(self)
        box.setWindowTitle("发现较新的恢复副本")
        box.setText(f"项目修订 {offer.saved_revision}，恢复副本修订 {offer.recovery_revision}。")
        restore = box.addButton("恢复较新的工作", QMessageBox.ButtonRole.AcceptRole)
        disk = box.addButton("打开已保存项目", QMessageBox.ButtonRole.ActionRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == restore:
            self.controller.open_project(offer.project_path, recovery_file=offer.recovery_path)
        elif box.clickedButton() == disk:
            self.controller.open_project(offer.project_path, ignore_recovery=True)

    def splitters_changed(self, *_):
        if not self._rendering:
            if not getattr(self, "_narrow_layout", False) and hasattr(self, "vertical"):
                sizes = self.vertical.sizes()
                if len(sizes) == 2 and all(sizes):
                    self._wide_vertical_sizes = sizes
            self.controller.set_workspace(horizontal_splitter=self.horizontal.sizes(), vertical_splitter=self.vertical.sizes())

    def compact_focus_changed(self, index):
        self._compact_focus_index = index
        if not hasattr(self, "inspector"):
            return
        previous_rendering = self._rendering
        self._rendering = True
        try:
            if index == 2:
                self.inspector.setMaximumWidth(16777215)
                self.horizontal.setSizes([0, 1])
            else:
                self.inspector.setMaximumWidth(340)
                self.horizontal.setSizes([1, 0] if getattr(self, "_narrow_layout", False) else [1060, 387])
                self.vertical.setSizes([1, 0] if index == 0 else [0, 1])
        finally:
            self._rendering = previous_rendering
        self.render_layout()

    def table_widths_changed(self, *_):
        if not self._rendering and hasattr(self, "node_table"):
            self.controller.set_workspace(source_widths=[self.source_table.columnWidth(i) for i in range(5)],
                                          node_widths=[self.node_table.columnWidth(i) for i in range(5)])

    def table_sort_changed(self, *_):
        if not self._rendering and hasattr(self, "node_table"):
            values = {}
            for table, key in ((self.source_table, "source_sort"), (self.node_table, "node_sort")):
                header = table.horizontalHeader()
                values[key] = [header.sortIndicatorSection(), header.sortIndicatorOrder().value]
            self.controller.set_workspace(**values)

    def toggle_inspector(self):
        self.inspector.setVisible(not self.inspector.isVisible())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_layout()

    def _update_reaction_control_widths(self, narrow):
        abbreviations = {
            self.kind_combo: {"gibbs_total": ("吉布斯G", "Gibbs"), "scf": ("SCF", "SCF"),
                              "gibbs_correction": ("热校正", "G corr.")},
            self.mode_combo: {"relative": ("ΔG" if self.kind_combo.currentData() == "gibbs_total" else "ΔE", "ΔG" if self.kind_combo.currentData() == "gibbs_total" else "ΔE"),
                              "absolute": ("绝对", "Absolute"), "direct_difference": ("直接ΔE", "Direct ΔE")},
        }
        for combo, mapping in ((self.kind_combo, KIND_LABELS),
                              (self.mode_combo, {"relative": "相对能量", "absolute": "绝对能量", "direct_difference": "直接差值"}),
                              (self.unit_combo, UNIT_LABELS)):
            for index in range(combo.count()):
                key = combo.itemData(index)
                full = translate(mapping.get(key, combo.itemText(index)), self.language)
                short = abbreviations.get(combo, {}).get(key)
                combo.setItemText(index, short[self.language == "en"] if narrow and short else full)
                combo.setItemData(index, full, Qt.ItemDataRole.ToolTipRole)
            combo.setToolTip(translate(mapping.get(combo.currentData(), combo.currentText()), self.language))

    def dragEnterEvent(self, event):
        if not self.controller.busy and not self.controller.read_only and event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.import_paths([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        if self.controller.busy:
            self._close_when_idle = True
            self.controller.cancel()
            return
        self._closing_attempt = True
        preferences = {"window_geometry": bytes(self.saveGeometry().toBase64()).decode("ascii")}
        self.controller.close(preferences)

    def finish_close(self):
        self.profile.dispose()
        self._allow_close = True
        self.close()
