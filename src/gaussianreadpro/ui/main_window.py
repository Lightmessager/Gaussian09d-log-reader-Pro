"""S4 scientific workbench: navigation, real tables, provenance and save feedback."""
from pathlib import Path

from PySide6.QtCore import QByteArray, QSortFilterProxyModel, Qt, QTimer, QItemSelectionModel, QSize
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame, QMenu, QInputDialog, QColorDialog,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter,
    QStackedWidget, QTabBar, QTableView, QVBoxLayout, QWidget)

from ..core.expressions import render_expression
from .profile_preview import ProfilePreview
from .plot_inspector import PlotInspector, build_plot_inspector_snapshot
from .profile_view import ProfilePanel
from ..core.plot_spec import build_plot_spec
from .tables import ID_ROLE, SORT_ROLE, KIND_LABELS, STATE_LABELS, UNIT_LABELS, NodeTable, SourceTable, SourceProxy
from .i18n import translate
from .theme import apply_theme
from .glass_widgets import GlassBackdrop, GlassPanel, GlassButton
from ..presentation.palette import get_palette


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
        self._pending_open = None
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
        self.setWindowTitle("GaussianReadPro · 计算化学工作台")
        self.resize(1440, 920)
        self.setMinimumSize(860, 680)
        self.setAcceptDrops(True)
        root = GlassBackdrop("light")
        root.setObjectName("root")
        self.backdrop = root
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(16, 14, 16, 12)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._topbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(self._sidebar())
        workspace = QWidget()
        work = QVBoxLayout(workspace)
        work.setContentsMargins(8, 6, 8, 4)
        work.setSpacing(14)
        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        self.eyebrow = label("WORKSPACE / 研究工作区", "eyebrow")
        self.title = label("项目概览", "title")
        title_box.addWidget(self.eyebrow)
        title_box.addWidget(self.title)
        heading.addLayout(title_box)
        heading.addStretch()
        self.recalculate = button("重新计算", self.controller.calculate)
        heading.addWidget(self.recalculate)
        self.import_button = button("＋ 导入日志", self.choose_files, True)
        self.import_button.setObjectName("primary")
        heading.addWidget(self.import_button)
        work.addLayout(heading)
        self.banner = label("", "error")
        self.banner.setWordWrap(True)
        self.banner.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.banner.hide()
        work.addWidget(self.banner)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._home())
        self.stack.addWidget(self._files())
        self.stack.addWidget(self._reaction())
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
        self.controller.bootstrapped.connect(self.bootstrap_ready)
        self.controller.recentChanged.connect(self.populate_recent)
        self.controller.recoveryOffered.connect(self.recovery_offer)
        self.controller.closed.connect(self.finish_close)
        self._shortcuts()
        self.refresh()

    def _topbar(self):
        frame = GlassPanel("toolbar")
        frame.setObjectName("topbar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)
        logo = label("G", "wordmark")
        logo.setFixedSize(36, 36)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        self.brand = label("GaussianReadPro", "brand")
        layout.addWidget(self.brand)
        layout.addSpacing(16)
        self.project_name = label("未命名项目", "muted")
        layout.addWidget(self.project_name)
        self.saved = label("尚未保存", "badge")
        layout.addWidget(self.saved)
        layout.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索文件或节点…")
        self.search.setProperty("i18n_placeholder", "搜索文件或节点…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(235)
        self.search.setAccessibleName("搜索文件或节点 / Search files or nodes")
        self.search.textChanged.connect(self.filter_changed)
        layout.addWidget(self.search)
        self.new_button = button("新建", self.new_project)
        self.open_button = button("打开", self.choose_open)
        self.save_button = button("保存项目", self.save_project)
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
        self.more_button.setProperty("i18n_source", "更多项目操作")
        self.more_button.setAccessibleName("更多项目操作")
        self.more_menu = QMenu(self.more_button)
        for text, callback in (("新建", self.new_project), ("打开", self.choose_open)):
            action = self.more_menu.addAction(text)
            action.setProperty("i18n_source", text)
            action.triggered.connect(callback)
        self.more_button.setMenu(self.more_menu)
        self.theme_combo.currentIndexChanged.connect(self.theme_changed)
        layout.addWidget(self.new_button)
        layout.addWidget(self.open_button)
        layout.addWidget(self.save_button)
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

    def _sidebar(self):
        self.sidebar = GlassPanel("elevated")
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(172)
        layout = QVBoxLayout(self.sidebar)
        layout.setContentsMargins(0, 18, 0, 14)
        self.nav_heading = label("    研究工作台")
        layout.addWidget(self.nav_heading)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setIconSize(QSize(20, 20))
        self.navigation.setProperty("compact", False)
        self.nav_text = ["项目概览", "源文件", "反应路径"]
        self.nav_source_text = list(self.nav_text)
        for text, icon in zip(self.nav_text, ("settings.svg", "file.svg", "chart.svg")):
            item = QListWidgetItem(text)
            item.setIcon(self._resource_icon(icon))
            item.setToolTip(text)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, text)
            self.navigation.addItem(item)
        self.navigation.setCurrentRow(0)
        self.navigation.currentRowChanged.connect(self.page_changed)
        layout.addWidget(self.navigation)
        self.nav_footer = label("LOCAL FIRST\n离线 · 可追溯 · 可恢复")
        self.nav_footer.setWordWrap(True)
        layout.addWidget(self.nav_footer)
        return self.sidebar

    @staticmethod
    def _resource_icon(name, theme="light"):
        from PySide6.QtGui import QIcon, QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer
        path = Path(__file__).resolve().parents[1] / "resources" / "icons" / name
        svg = path.read_text(encoding="utf-8").replace("#7450AF", get_palette(theme)["colors"]["primary"])
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
        recent, recent_layout = card()
        recent_layout.addWidget(label("继续研究", "section"))
        self.recent = QListWidget()
        self.recent.setObjectName("recentProjects")
        self.recent.itemDoubleClicked.connect(self.open_recent)
        self.recent.setMinimumHeight(150)
        recent_layout.addWidget(self.recent)
        row = QHBoxLayout()
        row.addWidget(button("打开选中项目", self.open_recent))
        self.continue_button = button("继续上次工作", self.continue_last)
        row.addWidget(self.continue_button)
        row.addStretch()
        recent_layout.addLayout(row)
        layout.addWidget(recent, 1)
        footer = label("将文件或文件夹拖入窗口开始导入。项目以 .grproj 保存，日志始终保留独立来源。", "muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        scroll = QScrollArea()
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
        layout.addLayout(controls)
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
        for text, callback in (("新建路径", lambda: self.manage_path("new")),
                               ("复制路径（共享节点）", lambda: self.manage_path("copy")),
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
        self.undo_button = button("撤销", self.controller.undo)
        self.redo_button = button("重做", self.controller.redo)
        for widget in (self.node_menu_button, self.path_menu_button, self.edit_expression_button,
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
        self.profile.modeChanged.connect(self.chart_mode_changed)
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
        self.horizontal.addWidget(self.vertical)
        self.inspector, inspector_layout = card()
        self.inspector.setProperty("profileSurface", True)
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
        layout.addWidget(self.compact_tabs)
        layout.addWidget(self.horizontal, 1)
        return page

    def _shortcuts(self):
        for shortcut, callback in ((QKeySequence.StandardKey.Open, self.choose_open),
                                   (QKeySequence.StandardKey.Save, self.save_project),
                                   (QKeySequence.StandardKey.SaveAs, lambda: self.save_project(True)),
                                   (QKeySequence.StandardKey.New, self.new_project)):
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)
        for sequence, callback in (("Ctrl+F", lambda: self.search.setFocus()),
                                   ("Ctrl+I", self.choose_files),
                                   ("F5", self.controller.calculate),
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
        for index, icon in enumerate(("settings.svg", "file.svg", "chart.svg")):
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
        nav = ["项目概览", "源文件", "反应路径"]
        for i, raw in enumerate(nav):
            display = "路径" if self.language == "en" and raw == "反应路径" else raw
            self.navigation.item(i).setText("" if self._compact else translate(display, self.language))
            self.navigation.item(i).setToolTip(translate(raw, self.language))
            self.navigation.item(i).setData(Qt.ItemDataRole.AccessibleTextRole, translate(raw, self.language))
        self.more_button.setAccessibleName(translate("更多项目操作", self.language))
        self.appearance_button.setAccessibleName(translate("外观设置", self.language))
        self.appearance_button.setToolTip(translate("外观设置", self.language))
        self.compact_tabs.setAccessibleName(translate("Reaction view / 反应视图", self.language))
        self.compact_tabs.setTabText(0, translate("路径节点", self.language))
        self.compact_tabs.setTabText(1, translate("能量图", self.language))
        self.compact_tabs.setTabText(2, translate("节点详情", self.language))
        self.nav_heading.setText(translate("研究工作台", self.language))
        self.nav_footer.setText("    LOCAL FIRST\n    Offline · Traceable · Recoverable" if self.language == "en" else "    LOCAL FIRST\n    离线 · 可追溯 · 可恢复")
        self.title.setText(translate(("项目概览", "源文件", "能量剖面" if self._compact_focus_index == 1 else "反应路径")[max(0, self.navigation.currentRow())], self.language))
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

    def new_project(self):
        if not self.controller.busy:
            self.banner.hide()
            self.controller.new_project()

    def choose_open(self):
        if self.controller.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开研究项目", "", "GaussianReadPro (*.grproj)")
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
            self.controller.import_files(paths, recursive=self.recursive.isChecked())

    def save_project(self, save_as=False):
        if self.controller.busy or self.controller.project is None:
            return
        self.banner.hide()
        path = None
        if save_as or self.controller.path is None or self.controller.read_only:
            path, _ = QFileDialog.getSaveFileName(self, "保存研究项目", "研究项目.grproj", "GaussianReadPro (*.grproj)",
                                                 options=QFileDialog.Option.DontConfirmOverwrite)
            if not path:
                return
            if not path.lower().endswith(".grproj"):
                path += ".grproj"
        self.controller.save(path)

    def page_changed(self, page):
        if hasattr(self, "stack"):
            self.stack.setCurrentIndex(page)
            self.eyebrow.setVisible(page != 2)
            self.title.setText(translate(["项目概览", "源文件", "能量剖面" if self._compact_focus_index == 1 else "反应路径"][page], self.language))
            if not self._rendering:
                self.controller.set_workspace(page=page)

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
        if action in ("new", "copy", "rename"):
            text, ok = QInputDialog.getText(self, translate("路径管理", self.language),
                        translate("路径名称（副本共享节点，编辑节点会影响所有引用路径）", self.language),
                        text=(path.label + " (2)" if action == "copy" and path else path.label if action == "rename" and path else ""))
            if ok and text.strip():
                self.controller.edit_path(action, text.strip())
        elif path and action == "color":
            color = QColorDialog.getColor(parent=self)
            if color.isValid():
                self.controller.edit_path("color", color.name())
        elif path and action == "visible":
            self.controller.edit_path("visible", not path.visible)
        elif path and action == "delete":
            answer = QMessageBox.question(self, translate("删除路径", self.language), path.label)
            if answer == QMessageBox.StandardButton.Yes:
                self.controller.edit_path("delete")

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
        for widget, count in zip(self.metric_values, (len(project.source_files), len(project.nodes), len(project.paths)) if project else (0, 0, 0)):
            widget.setText(str(count))
        name = controller.path.stem if controller.path else translate("未命名项目", self.language)
        self.project_name.setText(name)
        self.setWindowTitle(f"{name} · GaussianReadPro")
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
        for widget in (self.new_button, self.open_button):
            widget.setEnabled(idle)
        self.import_button.setEnabled(editable)
        self.folder_button.setEnabled(editable)
        self.save_button.setEnabled(idle and controller.project is not None)
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
        self.node_menu_button.setEnabled(editable and controller.selected_path is not None)
        self.edit_expression_button.setEnabled(editable and any(n.id == self._selected_node for n in controller.project.nodes) if controller.project else False)
        self.edit_reference_button.setEnabled(editable and controller.selected_path is not None)
        self.undo_button.setEnabled(editable and bool(controller.undo_stack))
        self.redo_button.setEnabled(editable and bool(controller.redo_stack))

    def busy_changed(self, busy, operation):
        self.update_actions()
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
            if self._close_when_idle and not self.controller._closed:
                self._close_when_idle = False
                QTimer.singleShot(0, self.close)

    def progress_changed(self, done, total, name):
        self.task_progress.setRange(0, max(total, 1))
        self.task_progress.setValue(done)
        self.set_localized_text(self.task_label, f"导入 {done}/{total} · {name}")

    def saved_changed(self, status):
        if self.controller.read_only:
            self.set_localized_text(self.saved, "只读 · 可另存为")
        elif status is None:
            self.set_localized_text(self.saved, "尚未保存")
        elif status.error_code or status.recovery_error_code:
            self._save_error = True
            self.set_localized_text(self.saved, "保存失败")
            self.set_localized_text(self.banner, "保存失败。工作仍保留在当前会话；请重试或另存为。\n" + str(status.error_code or status.recovery_error_code))
            self.banner.show()
        elif self.controller.project and status.saved_revision == self.controller.project.revision and not self.controller._workspace_dirty and not self.controller._plot_dirty:
            self.set_localized_text(self.saved, "已保存")
            if self._save_error:
                self._save_error = False
                self.banner.hide()
        elif self.controller.project and status.recovery_revision == self.controller.project.revision and not self.controller._workspace_dirty and not self.controller._plot_dirty:
            self.set_localized_text(self.saved, "已备份 · 尚未保存")
        else:
            self.set_localized_text(self.saved, "正在备份…" if status.pending else "有未保存更改")

    def show_error(self, code, detail):
        names = {"project_not_found": "找不到项目文件，请重新定位后打开。", "destination_exists": "目标已存在，请选择新的项目文件名。",
                 "fingerprint_mismatch": "日志内容与原来源不同，无法自动重连。", "session_save_failed": "保存未成功，请重试或另存为项目。"}
        names.update({"plot_sources_changed": "来源已变化，请重新计算图表后再导出。", "stale_plot_export": "图表已更新，请重新导出。",
                      "plot_has_no_valid_values": "没有可导出的可见有效节点，请检查来源、草稿与路径显隐。",
                      "static_plot_export_failed": "静态图像导出失败；当前项目仍保留，请查看详情后重试。",
                      "static_plot_export_timeout": "静态图像导出超时；当前项目仍保留。"})
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
        narrow = getattr(self, "_narrow_layout", False)
        previous_rendering = self._rendering
        self._rendering = True
        try:
            if self.navigation.currentRow() == 2:
                self.title.setText(translate("能量剖面" if index == 1 else "反应路径", self.language))
            self.reaction_edit_tools.setVisible(index == 0)
            self.node_editor.setVisible(index != 1)
            self.reference_label.setVisible(index == 0 and not narrow)
            self.vertical.setVisible(index in (0, 1))
            self.path_card.setVisible(index == 0)
            self.chart_card.setVisible(index == 1)
            self.inspector.setVisible(index == 2 or not narrow)
            if index == 2:
                self.inspector.setMaximumWidth(16777215)
                self.horizontal.setSizes([0, 1])
            else:
                self.inspector.setMaximumWidth(340)
                self.horizontal.setSizes([1, 0] if narrow else [900, 320])
                self.vertical.setSizes([1, 0] if index == 0 else [0, 1])
        finally:
            self._rendering = previous_rendering

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
        if not hasattr(self, "inspector"):
            return
        compact = self.width() < 1180
        narrow = self.width() < 1024
        was_narrow = getattr(self, "_narrow_layout", False)
        self._narrow_layout = narrow
        self._compact = compact
        self.chart_hint.setVisible(False)
        self.reference_label.setVisible(not narrow)
        self.node_table.setMinimumHeight(110 if compact else 160)
        self.preview.setMinimumHeight(150 if compact else 215)
        self.sidebar.setFixedWidth(64 if compact else 172)
        if self.navigation.property("compact") != compact:
            self.navigation.setProperty("compact", compact)
            self.navigation.style().unpolish(self.navigation)
            self.navigation.style().polish(self.navigation)
        self.nav_heading.setVisible(not compact)
        self.nav_footer.setVisible(not compact)
        self.brand.setVisible(not compact)
        self.project_name.setVisible(not narrow)
        self.saved.setVisible(not narrow)
        self.search.setVisible(True)
        self.new_button.setVisible(not narrow)
        self.open_button.setVisible(not narrow)
        self.more_button.setVisible(narrow)
        self.save_button.setText(translate("保存项目", self.language))
        self.search.setMaximumWidth(130 if narrow else 165 if compact else 235)
        for index, text in enumerate(self.nav_source_text):
            display = "路径" if self.language == "en" and text == "反应路径" else text
            self.navigation.item(index).setText("" if compact else translate(display, self.language))
            self.navigation.item(index).setToolTip(translate(text, self.language))
        self.inspector.setVisible(not compact)
        for combo, narrow_width, long_width in ((self.path_combo, 220, 300),
                                                (self.kind_combo, 124, 170),
                                                (self.unit_combo, 106, 120),
                                                (self.mode_combo, 122, 160)):
            combo.setMaximumWidth(narrow_width if narrow else long_width)
            combo.setToolTip(combo.currentText())
            for index in range(combo.count()):
                full = combo.itemText(index)
                combo.setItemData(index, full, Qt.ItemDataRole.ToolTipRole)
        self._update_reaction_control_widths(narrow)
        self.compact_tabs.setVisible(True)
        self.compact_tabs.setTabText(0, translate("路径节点", self.language))
        self.compact_tabs.setTabText(1, translate("能量图", self.language))
        self.compact_tabs.setTabText(2, translate("节点详情", self.language))
        self.compact_focus_changed(self._compact_focus_index)

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
