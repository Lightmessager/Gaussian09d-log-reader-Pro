"""Offline Three.js/Plotly panel with guarded events and native fallback."""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal, Slot, QBuffer, QIODevice
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QInputDialog, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget, QMenu,
    QToolButton, QScrollArea, QFrame, QButtonGroup, QLayout)

from ..core.plot_spec import build_plot_spec, clean_view_state, compare_points, plot_payload
from ..core.models import snapshot_to_dict
from ..presentation.palette import get_palette
from .glass_widgets import GlassPanel
from .i18n import translate

RESOURCES = Path(__file__).resolve().parents[1] / "resources" / "plot"


def _visual_style(dark):
    palette = get_palette("dark" if dark else "light")
    colors, profile = palette["colors"], palette["profile"]
    return {"background": profile["canvas"], "foreground": profile["text"],
            "grid": profile["grid"], "zero": profile["muted"],
            "label_background": profile["panel"], "label_line": profile["border"],
            "selection": profile["path_a"], "focus": profile["focus"], "warning": colors["warning"],
            "paper_selection": get_palette("light")["profile"]["focus"],
            "paper_background": "#FFFFFF",
            "paper_foreground": "#292137", "paper_grid": "#E9E1EF", "paper_zero": "#B9ACC9"}


class PlotBridge(QObject):
    dataChanged = Signal(str)
    resetRequested = Signal()
    imageRequested = Signal(str)
    readySignal = Signal(int, str)
    renderedSignal = Signal(str)
    eventSignal = Signal(str)
    errorSignal = Signal(str)
    imageSignal = Signal(str)

    @Slot(int, str)
    def pageReady(self, protocol, version):
        self.readySignal.emit(protocol, version)

    @Slot(str)
    def rendered(self, raw):
        self.renderedSignal.emit(raw)

    @Slot(str)
    def event(self, raw):
        self.eventSignal.emit(raw)

    @Slot(str)
    def failed(self, message):
        self.errorSignal.emit(message)

    @Slot(str)
    def imageReady(self, raw):
        self.imageSignal.emit(raw)


class ProfilePanel(QWidget):
    selectionRequested = Signal(str, str, str)
    speciesSelectionRequested = Signal(str, str, str)
    exportedNotice = Signal(str)
    modeChanged = Signal(str)
    panelRequested = Signal(int)
    editRequested = Signal()
    reactionBuilderRequested = Signal()
    sourceReady = Signal(object)
    pathCreateRequested = Signal()
    pathColorRequested = Signal(str)
    pathRequested = Signal(str)

    def __init__(self, native, controller, parent=None):
        super().__init__(parent)
        self.native, self.controller = native, controller
        self.spec, self.active_path = None, None
        self.language, self.dark = "zh_CN", False
        self.webview, self.bridge, self.web_profile, self.page = None, None, None, None
        self.ready, self.failure, self.summary = False, "", {}
        self.last_payload, self._fingerprint = None, None
        self._render_id, self._selection, self._capture = 0, [], None
        self._rendering, self._project_id, self._disposed = False, None, False
        self._readonly_state = {}
        self.details_widget = None
        self.workbench = True
        self.blocked_requests, self.javascript_errors = [], []
        self.load_events = []
        self._webgl_notice = ""
        self._structure_signature = None
        self._structure_requested_signature = None
        self._structure_data = {"status":"no_selection"}
        self._molecule_choice = None
        self._source_request = None
        self.clipboard_writer = lambda text: QApplication.clipboard().setText(text)
        self.controller.structureReady.connect(self._structure_ready)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.toolbar_panel = GlassPanel("toolbar", parent=self)
        self.toolbar_panel.setObjectName("profileToolbar")
        self.toolbar_panel.setProperty("profileChrome", "panel")
        self.toolbar_panel.setProperty("profileSurface", True)
        self.toolbar_panel.setContentsMargins(0, 0, 0, 0)
        toolbar_layout = QVBoxLayout(self.toolbar_panel)
        toolbar_layout.setContentsMargins(8, 5, 8, 5)
        toolbar_layout.setSpacing(0)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.view_combo = QComboBox(self)
        self.view_combo.addItems(["2D", "3D"])
        self.view_combo.setAccessibleName(self.t("图表维度"))
        self.view_combo.hide()
        self.dimension_switch = QWidget()
        switch_layout = QHBoxLayout(self.dimension_switch)
        switch_layout.setContentsMargins(0, 0, 0, 0)
        switch_layout.setSpacing(2)
        self.dimension_group = QButtonGroup(self)
        self.dimension_buttons = []
        for index, text in enumerate(("2D", "3D")):
            control = QPushButton(text)
            control.setObjectName("profileDimension")
            control.setCheckable(True)
            self.dimension_group.addButton(control, index)
            switch_layout.addWidget(control)
            self.dimension_buttons.append(control)
        self.dimension_group.idClicked.connect(self.view_combo.setCurrentIndex)
        self.compare_box = QCheckBox()
        self.compare_box.setText(self.t("比较"))
        self.compare_box.setAccessibleName(self.t("比较路径"))
        self.paths_button = QToolButton()
        self.paths_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.paths_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.paths_button.setAccessibleName(self.t("路径显隐"))
        self.paths_menu = QMenu(self.paths_button)
        self.paths_button.setMenu(self.paths_menu)
        self._path_actions = {}
        self.theme_combo = QComboBox()
        self.theme_combo.setMinimumWidth(120)
        for text, key in (("跟随界面", "auto"), ("浅色", "light"), ("深色", "dark")):
            self.theme_combo.addItem(text, key)
        self.camera_combo = QComboBox()
        self.camera_combo.addItems(["相机预设", "等轴测", "路径正视", "俯视", "恢复已保存相机"])
        self.camera_combo.setAccessibleName(self.t("相机预设"))
        self.dragmode_combo = QComboBox()
        self.dragmode_combo.addItems(["旋转", "平移"])
        self.dragmode_combo.setAccessibleName(self.t("相机控制"))
        self._camera_dragmode = "orbit"
        self._interaction_modes = {"2d": "pan", "3d": "orbit"}
        self.reset_button, self.barrier_button = QPushButton(), QPushButton("ΔE‡")
        self.reaction_builder_button = QPushButton("编辑反应路径…")
        self.export_button, self.expand_button = QPushButton(), QPushButton("⤢")
        self.more_button = QToolButton()
        self.more_button.setText(self.t("更多"))
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(self.more_button)
        self.more_button.setMenu(self.more_menu)
        self.more_menu.addAction(self.t("路径节点与编辑…"), lambda: self.panelRequested.emit(0))
        self.more_menu.addAction(self.t("节点详情…"), lambda: self.panelRequested.emit(2))
        self.more_menu.addSeparator()
        theme_menu = self.more_menu.addMenu(self.t("图表主题"))
        for index, title in enumerate(("跟随界面", "浅色", "深色")):
            theme_menu.addAction(self.t(title), lambda checked=False, index=index: self.theme_combo.setCurrentIndex(index))
        camera_menu = self.more_menu.addMenu(self.t("相机预设"))
        for index, title in enumerate(("等轴测", "路径正视", "俯视", "恢复已保存相机"), 1):
            camera_menu.addAction(self.t(title), lambda checked=False, index=index: self._camera_preset_changed(index))
        camera_menu.addAction(self.t("平移控制"), lambda: self._dragmode_changed(1))
        camera_menu.addAction(self.t("旋转控制"), lambda: self._dragmode_changed(0))
        self.more_menu.addAction(self.t("标记所选节点间的势垒"), self.mark_barrier)
        self.more_menu.addAction(self.t("放大图表"), self.expand)
        self.reset_button.setAccessibleName(self.t("重置视口"))
        self.export_button.setAccessibleName(self.t("导出…"))
        self.theme_combo.setAccessibleName(self.t("图表主题"))
        self.compare_box.setAccessibleName(self.t("比较路径"))
        for widget in (self.dimension_switch, self.paths_button, self.compare_box):
            toolbar.addWidget(widget)
        toolbar.addStretch()
        for widget in (self.reaction_builder_button, self.reset_button, self.export_button, self.more_button):
            toolbar.addWidget(widget)
        toolbar_layout.addLayout(toolbar)
        self.camera_controls = QWidget(self)
        self.camera_controls.setVisible(False)
        for widget in (self.theme_combo, self.camera_combo, self.dragmode_combo, self.barrier_button, self.expand_button):
            widget.setParent(self)
            widget.hide()
        layout.addWidget(self.toolbar_panel)
        self.warning = QLabel()
        self.warning.setTextFormat(Qt.TextFormat.PlainText)
        self.warning.setWordWrap(True)
        self.warning.setObjectName("muted")
        layout.addWidget(self.warning)
        self.stack = QStackedWidget()
        self.stack.addWidget(native)
        self.stack.setMinimumHeight(150)
        layout.addWidget(self.stack, 1)
        self.difference = QLabel()
        self.difference.setTextFormat(Qt.TextFormat.PlainText)
        self.difference.setWordWrap(True)
        layout.addWidget(self.difference)
        self.view_combo.currentIndexChanged.connect(self.options_changed)
        self.compare_box.toggled.connect(self.options_changed)
        self.theme_combo.currentIndexChanged.connect(self.options_changed)
        self.camera_combo.activated.connect(self._camera_preset_changed)
        self.dragmode_combo.currentIndexChanged.connect(self._dragmode_changed)
        self.reset_button.clicked.connect(self.reset_view)
        self.reset_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.reset_button.customContextMenuRequested.connect(self.reset_menu)
        self.barrier_button.clicked.connect(self.mark_barrier)
        self.reaction_builder_button.clicked.connect(self.reactionBuilderRequested)
        self.export_button.clicked.connect(self.choose_export)
        self.expand_button.clicked.connect(self.expand)
        controller.exported.connect(self.exportedNotice)
        controller.busyChanged.connect(lambda *_: self.update_actions())
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.fallback("图表加载超时，已切换到原生二维。"))
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.timeout.connect(lambda: self.abort_capture("图像捕获超时，请重试。"))
        self.retranslate()

    def t(self, text):
        return translate(text, self.language)

    def set_language(self, language):
        self.language = language
        self.retranslate()
        self.refresh()

    def set_theme(self, dark):
        self.dark = dark
        self.refresh()

    def retranslate(self):
        if getattr(self, "_expanded", None):
            self._expanded.setWindowTitle(self.t("能量剖面"))
            if hasattr(self._expanded, "details_toggle"):
                self._expanded.details_toggle.setText(self.t("节点详情"))
                self._expanded.details_toggle.setAccessibleName(self.t("节点详情"))
        self.compare_box.setText(self.t("比较路径"))
        self.more_button.setText(self.t("更多"))
        menu_actions = self.more_menu.actions()
        for action, title in zip(menu_actions, ("路径节点与编辑…", "节点详情…", "", "图表主题", "相机预设", "标记所选节点间的势垒", "放大图表")):
            if title:
                action.setText(self.t(title))
        if len(menu_actions) > 4:
            theme_menu, camera_menu = menu_actions[3].menu(), menu_actions[4].menu()
            for menu, title, options in ((theme_menu, "图表主题", ("跟随界面", "浅色", "深色")),
                                         (camera_menu, "相机预设", ("等轴测", "路径正视", "俯视", "恢复已保存相机"))):
                menu.setTitle(self.t(title))
                for action, item in zip(menu.actions(), options):
                    action.setText(self.t(item))
            camera_menu.actions()[-2].setText(self.t("平移控制"))
            camera_menu.actions()[-1].setText(self.t("旋转控制"))
        for control in self.dimension_buttons:
            control.setAccessibleName(control.text() + " · " + self.t("图表维度"))
        self.paths_button.setAccessibleName(self.t("路径显隐"))
        self.view_combo.setAccessibleName(self.t("图表维度"))
        self.reset_button.setText(self.t("重置视口"))
        self.export_button.setText(self.t("导出…"))
        self.reaction_builder_button.setText(self.t("编辑反应路径…"))
        self.expand_button.setToolTip(self.t("放大图表"))
        self.expand_button.setAccessibleName(self.t("放大图表"))
        self.barrier_button.setToolTip(self.t("明确标注所选前驱与已指定 TS 的局部势垒"))
        self.barrier_button.setAccessibleName(self.t("明确标注所选前驱与已指定 TS 的局部势垒"))
        self.theme_combo.setToolTip(self.t("图表主题"))
        for index, text in enumerate(("跟随界面", "浅色", "深色")):
            self.theme_combo.setItemText(index, self.t(text))
        self.compare_box.setAccessibleName(self.t("比较路径"))
        self.theme_combo.setAccessibleName(self.t("图表主题"))
        self.reset_button.setAccessibleName(self.t("重置视口"))
        self.export_button.setAccessibleName(self.t("导出…"))
        self.camera_combo.setAccessibleName(self.t("相机预设"))
        self.dragmode_combo.setAccessibleName(self.t("相机控制"))
        for index, text in enumerate(("相机预设", "等轴测", "路径正视", "俯视", "恢复已保存相机")):
            self.camera_combo.setItemText(index, self.t(text))
        for index, text in enumerate(("旋转", "平移")):
            self.dragmode_combo.setItemText(index, self.t(text))
        self._resize_toolbar(self.width())

    def _resize_toolbar(self, width):
        compact = width < 900
        self.compare_box.setText(self.t("比较") if compact else self.t("比较路径"))
        self.theme_combo.setItemText(0, self.t("自动") if compact else self.t("跟随界面"))
        self.reset_button.setText(self.t("重置") if compact else self.t("重置视口"))
        self.export_button.setText(self.t("导出") if compact else self.t("导出…"))
        self.reaction_builder_button.setText(self.t("搭建路径") if compact else self.t("编辑反应路径…"))
        self.compare_box.setToolTip(self.t("比较路径"))
        self.theme_combo.setToolTip(self.t("图表主题") + " · " + self.t("跟随界面 / 浅色 / 深色"))
        self.camera_combo.setToolTip(self.t("三维视角预设"))
        self.dragmode_combo.setToolTip(self.t("三维拖动方式"))
        self.paths_button.setToolTip(self.t("路径显隐提示"))
        self.theme_combo.setMinimumWidth(94 if compact else 120)
        labels = ("相机", "等轴", "正视", "俯视", "恢复") if compact else (
            "相机预设", "等轴测", "路径正视", "俯视", "恢复已保存相机")
        for index, text in enumerate(labels):
            self.camera_combo.setItemText(index, self.t(text))
        self.camera_combo.setMinimumWidth(128 if compact else 172)
        self.dragmode_combo.setMinimumWidth(74 if compact else 92)
        self.toolbar_panel.setProperty("compact", compact)

    def _sync_paths_menu(self, payload):
        """Build view-only visibility controls from paths compatible with the active chart."""
        self.paths_menu.clear()
        self._path_actions.clear()
        if not self.spec or not self.spec.paths:
            self.paths_button.setText(self.t("路径") + " · 0/0")
            self.paths_button.setEnabled(False)
            return
        active = next((p for p in self.spec.paths if p.id == self.active_path), None)
        if active is None:
            active = self.spec.paths[0]
        candidates = [p for p in self.spec.paths
                      if p.kind == active.kind and p.mode == active.mode]
        hidden = set(self.state.get("hidden_paths", []))
        enabled = [p for p in candidates if p.visible]
        visible_count = sum(p.id not in hidden for p in enabled)
        for path in candidates:
            action = self.paths_menu.addAction(path.label)
            swatch = QPixmap(16, 16)
            swatch.fill(Qt.GlobalColor.transparent)
            painter = QPainter(swatch)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor(path.color))
            painter.setBrush(QColor(path.color))
            painter.drawEllipse(3, 3, 10, 10)
            painter.end()
            action.setIcon(QIcon(swatch))
            action.setCheckable(True)
            action.setChecked(path.visible and path.id not in hidden)
            action.setEnabled(path.visible)
            action.setToolTip(path.label if path.visible else self.t("路径在项目中已隐藏"))
            action.setData(path.id)
            action.toggled.connect(lambda checked, item=action: self._path_visibility_changed(item, checked))
            self._path_actions[path.id] = action
        self.paths_button.setText(f"{self.t('路径')} · {visible_count}/{len(enabled)}")
        self.paths_button.setAccessibleName(
            f"{self.t('路径显隐')} · {visible_count}/{len(enabled)}")
        self.paths_button.setEnabled(bool(candidates))

    def _path_visibility_changed(self, action, checked):
        if not self.spec or self._rendering:
            return
        path_id = action.data()
        hidden = set(self.state.get("hidden_paths", []))
        if checked:
            hidden.discard(path_id)
        else:
            hidden.add(path_id)
            self._selection = [pair for pair in self._selection if pair[0] != path_id]
        # A path toggle is an explicit request to compare; it only changes plot_state.
        self._rendering = True
        self.compare_box.setChecked(True)
        self._rendering = False
        self.save_state(compare=True, hidden_paths=sorted(hidden), selected_points=[list(pair) for pair in self._selection])
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_toolbar(event.size().width())

    @property
    def state(self):
        return self._readonly_state if self.controller.read_only else self.controller.plot_state

    def save_state(self, **changes):
        if self.controller.read_only:
            self._readonly_state = clean_view_state({**self._readonly_state, **changes}, self.spec)
        else:
            self.controller.set_plot_state(**changes)

    def set_spec(self, spec, active_path):
        self.spec, self.active_path = spec, active_path
        if spec and spec.project_id != self._project_id:
            self._project_id = spec.project_id
            self._readonly_state = dict(self.controller.plot_state)
            self._selection = [tuple(pair) for pair in clean_view_state(self.state, spec).get("selected_points", [])]
            restored = self.controller.workspace.get("node_id")
            active = next((p for p in spec.paths if p.id == active_path), None)
            if active and restored and "selected_points" not in self.state:
                entry = next((p for p in active.points if p.node_id == restored), None)
                if entry:
                    self._selection = [(active_path, entry.entry_id)]
            self._fingerprint = None
        if spec and spec.paths and self.webview is None and not self.failure:
            if QApplication.platformName() not in ("offscreen", "minimal") and not os.environ.get("GRPR_NATIVE_PLOT"):
                self.create_browser()
        self.refresh()

    def create_browser(self):
        try:
            from PySide6.QtWebChannel import QWebChannel
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
            from PySide6.QtWebEngineWidgets import QWebEngineView
            panel = self
            class Offline(QWebEngineUrlRequestInterceptor):
                def interceptRequest(self, info):
                    if info.requestUrl().scheme() not in ("file", "qrc", "data", "blob", "about"):
                        panel.blocked_requests.append(info.requestUrl().toString())
                        info.block(True)
            class Page(QWebEnginePage):
                def javaScriptConsoleMessage(self, level, message, line, source):
                    if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                        panel.javascript_errors.append(f"{message} ({source}:{line})")
                def acceptNavigationRequest(self, url, type, main):
                    allowed = not main or url.scheme() == "about" or (url.isLocalFile() and Path(url.toLocalFile()).resolve() == (RESOURCES / "profile.html").resolve())
                    panel.load_events.append({"navigation": url.toString(), "local":url.toLocalFile(), "allowed":allowed})
                    return allowed
            self.webview = QWebEngineView()
            self.web_profile = QWebEngineProfile(self)
            self.interceptor = Offline(self.web_profile)
            self.web_profile.setUrlRequestInterceptor(self.interceptor)
            self.web_profile.downloadRequested.connect(lambda request: request.cancel())
            self.page = Page(self.web_profile, self.webview)
            self.webview.setPage(self.page)
            for attribute in (QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                              QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows):
                self.page.settings().setAttribute(attribute, False)
            self.channel = QWebChannel(self.page)
            self.bridge = PlotBridge(self.channel)
            self.channel.registerObject("bridge", self.bridge)
            self.page.setWebChannel(self.channel)
            self.bridge.readySignal.connect(self.page_ready)
            self.bridge.renderedSignal.connect(self.rendered)
            self.bridge.eventSignal.connect(self.handle_event)
            self.bridge.errorSignal.connect(self.fallback)
            self.bridge.imageSignal.connect(self.image_ready)
            self.page.renderProcessTerminated.connect(lambda status, code: self.fallback(f"WebEngine renderer stopped ({code})"))
            self.page.loadingChanged.connect(lambda info: self.load_events.append({"url":info.url().toString(),
                "status":info.status().name,"code":info.errorCode(),"description":info.errorString()}))
            self.webview.loadFinished.connect(lambda ok: None if ok else self.fallback("本地图表页面加载失败。"))
            self.stack.addWidget(self.webview)
            if not (RESOURCES / "vendor/plotly.min.js").is_file():
                raise FileNotFoundError("Missing local Plotly asset")
            self.timeout.start(15000)
            self.webview.load(QUrl.fromLocalFile(str(RESOURCES / "profile.html")))
        except (ImportError, RuntimeError, OSError) as error:
            self.fallback(str(error))

    def page_ready(self, protocol, version):
        if self._disposed:
            return
        if protocol != 2:
            self.fallback("Unsupported plot protocol")
            return
        self.timeout.stop()
        self.ready, self.failure = True, ""
        self.stack.setCurrentWidget(self.webview)
        self._fingerprint = None
        self.refresh()

    def fallback(self, message):
        if self._disposed:
            return
        self.timeout.stop()
        self.ready, self.failure = False, str(message)
        self.stack.setCurrentWidget(self.native)
        if self.spec:
            # The native view cannot render 3D, but a renderer failure must not
            # discard the user's multi-path comparison choice.
            self.save_state(mode="2d")
        self.abort_capture(message)
        self.refresh()

    def refresh(self):
        if not self.spec:
            self.update_actions()
            return
        self._rendering = True
        state = clean_view_state(self.state, self.spec)
        mode = state.get("mode", "2d")
        self.view_combo.setCurrentIndex(int(mode == "3d"))
        self.dimension_buttons[int(mode == "3d")].setChecked(True)
        self.camera_controls.hide()
        self.camera_combo.hide()
        self.dragmode_combo.hide()
        self.compare_box.setChecked(state.get("compare", False))
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(state.get("theme", "auto"))))
        self._rendering = False
        payload = plot_payload(self.spec, self.active_path, compare=state.get("compare", False), state=state,
                               language=self.language, dark=self.dark, selected=self._selection)
        payload["visual_style"] = _visual_style(payload["dark"])
        payload["camera_dragmode"] = self._interaction_modes.get(payload["view"], self._camera_dragmode)
        payload["workbench"] = self.workbench
        payload["paths_editable"] = not self.controller.read_only and not self.controller.busy
        if self._webgl_notice and payload["view"] != "3d":
            payload["warnings"].append(self._webgl_notice)
        payload["compare"] = state.get("compare", False)
        payload["profile_tokens"] = get_palette("dark" if payload["dark"] else "light")["profile"]
        hidden = set(state.get("hidden_paths", []))
        active = next((p for p in self.spec.paths if p.id == self.active_path), None)
        payload["workbench_paths"] = [{"id": p.id, "label": p.label, "color": p.color,
                                       "visible": p.visible and p.id not in hidden}
                                      for p in self.spec.paths if active and p.kind == active.kind and p.mode == active.mode]
        from ..presentation.profile_view_model import inspector_payload
        payload["inspector"] = inspector_payload(self.controller.project, payload, state, self.controller.connections, self._selection)
        payload["inspector"]["editable"] = not self.controller.read_only
        choices = payload["inspector"]["structure_candidates"]
        keys = [(v["source_file_id"],v["job_id"]) for v in choices]
        choice = self._molecule_choice if self._molecule_choice in keys else keys[0] if len(keys) == 1 else None
        detail = payload["inspector"]["detail"]
        signature = (payload["project_id"],payload["revision"],detail["path_id"],detail["entry_id"],*choice) if detail and choice else None
        request_structure = signature is not None and signature != self._structure_requested_signature
        if signature is None:
            self._structure_signature = None
            self._structure_requested_signature = None
            self._structure_data = {"status":"choose_source" if len(keys)>1 else "no_source" if detail and detail["valid"] else "no_selection"}
        elif signature != self._structure_signature:
            self._structure_signature = signature
            self._structure_data = {"status":"loading"}
        payload["inspector"]["structure"] = self._structure_data
        payload["inspector"]["structure_choice"] = list(choice) if choice else None
        self.barrier_button.setText(payload["barrier_label"])
        self.barrier_button.setAccessibleName(
            payload["barrier_label"] + " · " + self.t("明确标注所选前驱与已指定 TS 的局部势垒"))
        self.native.set_theme(payload["dark"])
        if self.page is not None:
            self.page.setBackgroundColor(QColor(payload["visual_style"]["background"]))
        self.warning.setText(" · ".join(v for v in [*payload["warnings"], self.t(self.failure) if self.failure else "", self.t(self._webgl_notice)] if v))
        self.warning.setVisible(bool(self.warning.text()))
        self._sync_paths_menu(payload)
        self.update_difference(payload)
        self.toolbar_panel.setVisible(not (self.workbench and self.ready))
        self.difference.setVisible(not (self.workbench and self.ready))
        self.warning.setVisible(bool(self.warning.text()) and not (self.workbench and self.ready))
        self.layout().setSpacing(0 if self.workbench and self.ready else 7)
        if not self._capture:
            self.send(payload)
            if request_structure and self.ready and self.workbench:
                self._structure_requested_signature = signature
                request = {k:self.last_payload[k] for k in ("project_id","revision","render_id")}
                request.update(source_file_id=choice[0],job_id=choice[1],signature=signature,purpose="structure")
                QTimer.singleShot(0,lambda request=request:self.controller.request_structure(request) if not self._disposed else None)
        self.update_actions()

    def _structure_ready(self, result):
        if self._disposed or not self.controller.project or result.get("project_id") != self.controller.project.id or result.get("revision") != self.controller.project.revision:
            return
        if result["structure"].get("status") in ("changed","missing","unreadable","unverified"):
            QTimer.singleShot(0,self.controller.calculate)
        if result.get("purpose") == "source":
            if result.get("request_id") == self._source_request:
                self.sourceReady.emit(result["structure"])
            if self._structure_signature and tuple(self._structure_signature[-2:]) == (result["source_file_id"],result["job_id"]) and self._structure_data.get("status") in ("loading","cancelled"):
                self._structure_data = result["structure"]
                self.refresh()
            return
        if tuple(result.get("signature", ())) != self._structure_signature:
            return
        self._structure_data = result["structure"]
        self.refresh()

    def send(self, payload, *, force=False):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if raw == self._fingerprint and not force:
            return
        self._fingerprint = raw
        self._render_id += 1
        self.last_payload = {**payload, "render_id": self._render_id}
        if self.ready:
            self.bridge.dataChanged.emit(json.dumps(self.last_payload, ensure_ascii=False, allow_nan=False))

    def options_changed(self, *_):
        if self._rendering or not self.spec:
            return
        mode = "3d" if self.view_combo.currentIndex() else "2d"
        changed = self.state.get("mode", "2d") != mode
        self.save_state(mode=mode, compare=self.compare_box.isChecked(), theme=self.theme_combo.currentData())
        if changed:
            self.modeChanged.emit(mode)
        self.refresh()

    def _camera_preset_changed(self, index):
        if not self.last_payload or self.last_payload.get("view") != "3d" or index <= 0:
            return
        presets = {
            1: {"eye": {"x": -1.1, "y": -1.9, "z": 1.05}, "center": {"x": 0, "y": 0, "z": 0}, "up": {"x": 0, "y": 0, "z": 1}},
            2: {"eye": {"x": 0, "y": -3.0, "z": 0.15}, "center": {"x": 0, "y": 0, "z": 0}, "up": {"x": 0, "y": 0, "z": 1}},
            3: {"eye": {"x": 0.05, "y": 0.05, "z": 3.0}, "center": {"x": 0, "y": 0, "z": 0}, "up": {"x": 0, "y": 1, "z": 0}},
        }
        if index == 4:
            key = self.last_payload["context"] + "/3d"
            viewport = snapshot_to_dict(self.state.get("viewports", {}).get(key, {}))
            if viewport.get("three_v1"):
                if self.ready:
                    self.page.runJavaScript("window.grpr.setViewport(" + json.dumps(viewport, allow_nan=False) + ")")
                self.camera_combo.setCurrentIndex(0)
                return
            camera = viewport.get("camera") or self.last_payload["default_camera"]
        else:
            camera = presets[index]
        if self.ready:
            self.page.runJavaScript("window.grpr.setCamera(" + json.dumps(camera, allow_nan=False) + ")")
        self.camera_combo.setCurrentIndex(0)

    def _dragmode_changed(self, index):
        self._camera_dragmode = "pan" if index else "orbit"
        self._interaction_modes["3d"] = self._camera_dragmode
        if self.last_payload and self.last_payload.get("view") == "3d" and self.ready:
            self.page.runJavaScript("window.grpr.setDragmode(" + json.dumps(self._camera_dragmode) + ")")

    def set_table_selection(self, pairs):
        self._selection = list(dict.fromkeys(pairs))[-2:]
        self.save_state(selected_points=[list(pair) for pair in self._selection])
        self.refresh()

    def _valid_envelope(self, data):
        payload, project = self.last_payload, self.controller.project
        return bool(isinstance(data, dict) and payload and project and data.get("project_id") == payload["project_id"] == project.id
                    and type(data.get("revision")) is int and data["revision"] == payload["revision"] == project.revision
                    and type(data.get("render_id")) is int and data["render_id"] == payload["render_id"])

    def handle_event(self, raw):
        if len(raw) > 65536 or self._capture:
            return
        try:
            data = json.loads(raw)
            if not self._valid_envelope(data):
                return
            if data.get("type") == "workbench_action":
                action = data.get("action")
                if action == "mode" and data.get("mode") in ("2d", "3d"):
                    self.view_combo.setCurrentIndex(int(data["mode"] == "3d"))
                elif action == "new_path" and not self.controller.read_only and not self.controller.busy:
                    QTimer.singleShot(0, self.pathCreateRequested.emit)
                elif action in ("path_color", "active_path") and any(p.id == data.get("path_id") for p in self.spec.paths):
                    path_id = data["path_id"]
                    if action == "active_path":
                        QTimer.singleShot(0, lambda path_id=path_id: self.pathRequested.emit(path_id))
                    elif not self.controller.read_only and not self.controller.busy:
                        QTimer.singleShot(0, lambda path_id=path_id: self.pathColorRequested.emit(path_id))
                elif action == "compare" and type(data.get("enabled")) is bool:
                    compatible = [p for p in self.spec.paths if p.visible and p.kind == self.last_payload["kind"] and p.mode == self.last_payload["mode"]]
                    if not data["enabled"] or len(compatible) > 1:
                        self.compare_box.setChecked(data["enabled"])
                elif action == "path" and type(data.get("visible")) is bool and any(p.id == data.get("path_id") for p in self.spec.paths):
                    hidden = set(self.state.get("hidden_paths", []))
                    hidden.discard(data["path_id"]) if data["visible"] else hidden.add(data["path_id"])
                    if not data["visible"]:
                        self._selection = [pair for pair in self._selection if pair[0] != data["path_id"]]
                    self.save_state(compare=True, hidden_paths=sorted(hidden), selected_points=[list(p) for p in self._selection])
                    self.refresh()
                elif action == "details" and type(data.get("visible")) is bool and type(data.get("drawer")) is bool:
                    self.save_state(details_visible=data["visible"], details_drawer_open=data["drawer"])
                    self.refresh()
                elif action == "reset":
                    self.reset_view()
                elif action == "export":
                    QTimer.singleShot(0, self.choose_export)
                elif action == "menu":
                    self.more_menu.popup(QCursor.pos())
                elif action == "edit_expression":
                    if self.last_payload.get("inspector",{}).get("detail") and not self.controller.read_only:
                        self.editRequested.emit()
                elif action == "copy_value":
                    detail = self.last_payload.get("inspector",{}).get("detail")
                    if detail and detail["valid"]:
                        value_text = str(detail["value"])+" "+self.last_payload["unit_label"]
                        QTimer.singleShot(0,lambda value_text=value_text:self.clipboard_writer(value_text))
                elif action == "pair_steps":
                    if len(self._selection) == 2 and self._selection[0][0] != self._selection[1][0]:
                        used = set(self._selection)
                        pairs = [snapshot_to_dict(g) for g in self.state.get("step_pairs",()) if not any(tuple(k) in used for k in g)]
                        self.save_state(step_pairs=[*pairs,[list(k) for k in self._selection]])
                        self.refresh()
                elif action == "structure_source":
                    choices = self.last_payload.get("inspector",{}).get("structure_candidates",[])
                    index = data.get("index")
                    if type(index) is int and 0 <= index < len(choices):
                        self._molecule_choice = (choices[index]["source_file_id"],choices[index]["job_id"])
                        self.refresh()
                elif action == "locate_source":
                    sources = (self.last_payload.get("inspector",{}).get("detail") or {}).get("sources",[])
                    index = data.get("index",0)
                    if type(index) is int and 0 <= index < len(sources):
                        source = sources[index]
                        self._source_request = str(uuid4())
                        self.controller.request_structure({**{k:self.last_payload[k] for k in ("project_id","revision","render_id")},
                            "purpose":"source","request_id":self._source_request,"source_file_id":source["source_file_id"],"job_id":source["job_id"],"line":source["line"]})
                elif action == "dragmode" and data.get("mode") in ("orbit", "pan", "zoom"):
                    view = self.last_payload.get("view", "2d")
                    mode = data["mode"]
                    self._interaction_modes[view] = mode
                    if mode in ("orbit", "pan"):
                        self._camera_dragmode = mode
                        self.dragmode_combo.setCurrentIndex(int(mode == "pan"))
                    if self.ready:
                        self.page.runJavaScript("window.grpr.setDragmode(" + json.dumps(mode) + ")")
                    self.refresh()
                    self.refresh()
            elif data.get("type") == "select":
                candidates = {(p["id"], point["entry_id"], point["node_id"]) for p in self.last_payload["paths"] if p["visible"]
                              for point in p["points"] if point["valid"]}
                supplied = data.get("points")
                if not isinstance(supplied, list) or len(supplied) > 2:
                    return
                items = [item for item in supplied if isinstance(item, dict)
                    and (item.get("path_id"), item.get("entry_id"), item.get("node_id")) in candidates]
                if not items:
                    return
                pairs = [(item["path_id"], item["entry_id"]) for item in items]
                self._selection = list(dict.fromkeys((self._selection if data.get("additive") is True else []) + pairs))[-2:]
                self.save_state(selected_points=[list(pair) for pair in self._selection])
                last = items[-1]
                self.selectionRequested.emit(last["path_id"], last["node_id"], last["entry_id"])
                self.refresh()
            elif data.get("type") == "species_select":
                identity = (data.get("path_id"), data.get("entry_id"), data.get("node_id"))
                candidates = {(p["id"], point["entry_id"], point["node_id"])
                              for p in self.last_payload["paths"] if p["visible"]
                              for point in p["points"] if point["valid"]}
                if identity not in candidates:
                    return
                self.speciesSelectionRequested.emit(identity[0], identity[2], identity[1])
            elif data.get("type") == "view_state":
                changes = {}
                if "hidden_paths" in data:
                    changes["hidden_paths"] = data["hidden_paths"]
                if isinstance(data.get("label_offsets"), dict):
                    changes["label_offsets"] = {**self.state.get("label_offsets", {}), **data["label_offsets"]}
                if isinstance(data.get("barrier_offset"), list) and self.state.get("barrier"):
                    changes["barrier"] = {**self.state["barrier"], "offset": data["barrier_offset"]}
                if isinstance(data.get("viewport"), dict):
                    key = self.last_payload["context"] + "/" + self.last_payload["view"]
                    views = {k: dict(v) for k, v in self.state.get("viewports", {}).items() if isinstance(v, dict) or hasattr(v, "items")}
                    previous = {} if data["viewport"].get("reset") else views.get(key, {})
                    views[key] = {**previous, **{k: v for k, v in data["viewport"].items() if k != "reset"}}
                    changes["viewports"] = views
                cleaned = clean_view_state({**self.state, **changes}, self.spec)
                self.save_state(**cleaned)
                # The live chart already reflects a pan or camera move; persist without resetting the drag.
                if "hidden_paths" in changes:
                    self.refresh()
            elif data.get("type") == "webgl_fallback":
                self.save_state(mode="2d")
                reason = str(data.get("reason") or "WebGL unavailable")[:300]
                self._webgl_notice = ("3D unavailable; showing 2D: " if self.language == "en" else "三维不可用，已切换二维：") + reason
                self._fingerprint = None
                self.refresh()
        except (ValueError, TypeError, KeyError, AttributeError):
            return

    def rendered(self, raw):
        try:
            data = json.loads(raw)
            if not self._valid_envelope(data):
                return
            self.summary = data
            if data.get("view") == "3d":
                self._webgl_notice = ""
            if self._capture and data["render_id"] == self._capture.get("render_id"):
                if self._capture["payload"].get("export_scope") == "workbench":
                    QTimer.singleShot(150, lambda identity=self._capture["id"]: self._capture_workbench(identity))
                else:
                    self.bridge.imageRequested.emit(json.dumps({"request_id": self._capture["id"], "render_id": data["render_id"]}))
        except (ValueError, TypeError):
            return

    def update_difference(self, payload):
        pair = compare_points(self.spec, self._selection, payload["unit"])
        symbol = {"scf": "ΔE", "gibbs_total": "ΔG", "gibbs_correction": "ΔGcorr"}.get(payload["kind"], "ΔE")
        if payload["mode"] == "direct_difference":
            symbol = "Δ" + symbol
        self.barrier_button.setEnabled(bool(pair and pair["barrier_eligible"] and not self.controller.read_only))
        self.barrier_button.setVisible(not self.workbench and payload["view"] == "2d" and bool(pair or payload.get("barrier")))
        if pair:
            self.difference.setText(f"{symbol} ({pair['second']} − {pair['first']}) = {pair['value']:+.8g} {payload['unit_label']}")
        elif len(self._selection) == 2:
            self.difference.setText(self.t("所选节点的参考或类型不同，不能直接比较。"))
        else:
            self.difference.setText(self.t("Ctrl/Shift 点选两个有效节点查看能量差；势垒须明确标注。"))

    def mark_barrier(self):
        if not self.last_payload:
            return
        pair = compare_points(self.spec, self._selection, self.last_payload["unit"])
        if pair and pair["barrier_eligible"]:
            self.save_state(barrier={key: pair[key] for key in ("path_id", "from_entry", "to_entry")})
            self.refresh()

    def reset_view(self):
        if not self.last_payload:
            return
        key = self.last_payload["context"] + "/" + self.last_payload["view"]
        self.save_state(viewports={k: v for k, v in self.state.get("viewports", {}).items() if k != key})
        if self.ready:
            self.bridge.resetRequested.emit()
        self._camera_dragmode = "orbit"
        self._interaction_modes[self.last_payload["view"]] = "orbit" if self.last_payload["view"] == "3d" else "pan"
        self.dragmode_combo.setCurrentIndex(0)
        self.refresh()

    def reset_menu(self, position):
        if not self.spec:
            return
        menu = QMenu(self)
        for label, changes in (("重置标签偏移", {"label_offsets": {}}), ("清除势垒标注", {"barrier": None}),
                               ("显示全部图例路径", {"hidden_paths": []})):
            action = menu.addAction(self.t(label))
            action.triggered.connect(lambda checked=False, changes=changes: self.reset_options(changes))
        menu.exec(self.reset_button.mapToGlobal(position))

    def reset_options(self, changes):
        self.save_state(**changes)
        self.refresh()

    def update_actions(self):
        usable = self.ready and not self._capture
        self.view_combo.setEnabled(usable)
        for control in self.dimension_buttons:
            control.setEnabled(usable)
        self.camera_combo.setEnabled(usable and self.last_payload is not None and self.last_payload.get("view") == "3d")
        self.dragmode_combo.setEnabled(usable and self.last_payload is not None and self.last_payload.get("view") == "3d")
        self.compare_box.setEnabled(usable and bool(self.spec and len(self.spec.paths) > 1))
        self.theme_combo.setEnabled(not self._capture)
        self.export_button.setEnabled(not self.controller.busy and not self._capture and self.last_payload is not None)
        if not self.reaction_builder_button.property("sharedProjectAction"):
            self.reaction_builder_button.setEnabled(bool(self.controller.project) and not self.controller.busy
                                                    and not self.controller.read_only and not self._capture)
        self.reset_button.setEnabled(self.spec is not None and not self._capture)

    def expand(self):
        if hasattr(self, "_expanded") and self._expanded:
            self._expanded.close()
            return
        original = self.parentWidget().layout()
        index = original.indexOf(self)
        class ExpandedProfile(QDialog):
            def resizeEvent(dialog, event):
                super().resizeEvent(event)
                if hasattr(dialog, "details_toggle"):
                    dialog.details_toggle.setVisible(dialog.width() >= 1024)
                    dialog.details_scroll.setVisible(dialog.width() >= 1024 and dialog.details_toggle.isChecked())

        dialog = ExpandedProfile(self.window())
        dialog.setObjectName("root")
        dialog.setWindowTitle(self.t("能量剖面"))
        layout = QVBoxLayout(dialog)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        body = QHBoxLayout()
        details = None if self.workbench else self.details_widget
        details_layout = details.parentWidget().layout() if details else None
        details_index = details_layout.indexOf(details) if details_layout else -1
        if details:
            toggle = QPushButton(self.t("节点详情"))
            toggle.setCheckable(True)
            toggle.setChecked(True)
            toggle.setAccessibleName(self.t("节点详情"))
            toggle.setAccessibleDescription(self.t("选中节点摘要"))
            layout.addWidget(toggle, 0, Qt.AlignmentFlag.AlignRight)
            sidebar = QScrollArea()
            sidebar.setWidgetResizable(True)
            sidebar.setFrameShape(QFrame.Shape.NoFrame)
            sidebar.setMinimumWidth(270)
            sidebar.setMaximumWidth(340)
            sidebar.setWidget(details)
            details.show()
            dialog.details_toggle, dialog.details_scroll = toggle, sidebar
            toggle.toggled.connect(lambda checked: sidebar.setVisible(checked and dialog.width() >= 1024))
        body.addWidget(self, 1)
        if details:
            body.addWidget(sidebar)
        layout.addLayout(body, 1)
        self._expanded = dialog
        def restore():
            if details and details_layout:
                sidebar.takeWidget()
                details_layout.insertWidget(details_index, details)
                details.show()
            original.insertWidget(index, self, 1)
            self._expanded = None
            dialog.deleteLater()
        dialog.finished.connect(restore)
        dialog.showMaximized()

    def choose_export(self):
        if not self.last_payload or self.controller.busy:
            return
        formats = ["PNG", "HTML"] if self.last_payload["view"] == "3d" else ["PNG", "SVG", "PDF", "HTML"]
        labels = [self.t("仅图表 PNG（3D 当前场景 / 2D 白底论文图）") if f == "PNG" else f for f in formats]
        labels.append(self.t("工作台展示图 PNG（含工具栏与详情）"))
        choice, ok = QInputDialog.getItem(self, self.t("导出能量剖面"), self.t("格式（每次创建独立结果包，含数据与来源）"), labels, editable=False)
        if not ok:
            return
        format = formats[labels.index(choice)].lower() if choice != labels[-1] else "workbench_png"
        language, ok = QInputDialog.getItem(self, self.t("导出语言"), self.t("导出语言独立于界面"), ["中文", "English"], int(self.language == "en"), False)
        if not ok:
            return
        destination, _ = QFileDialog.getSaveFileName(self, self.t("新建导出结果包目录"), "Energy-profile-" + format.lower(), options=QFileDialog.Option.DontConfirmOverwrite)
        if destination:
            self.export_to(destination, format, language="en" if language == "English" else "zh_CN")

    def export_to(self, destination, format, *, language=None):
        if not self.spec or self.controller.busy or self._capture:
            return False
        payload = plot_payload(self.spec, self.active_path, compare=self.state.get("compare", False), state=self.state,
                               language=language or self.language, dark=self.dark, selected=self._selection)
        payload["visual_style"] = _visual_style(payload["dark"])
        payload["compare"] = self.state.get("compare", False)
        if self.last_payload and self.last_payload["project_id"] == payload["project_id"] and self.last_payload["revision"] == payload["revision"]:
            for key in ("workbench", "workbench_paths", "profile_tokens", "camera_dragmode"):
                if key in self.last_payload:
                    payload[key] = deepcopy(self.last_payload[key])
        from ..presentation.profile_view_model import inspector_payload
        payload["inspector"] = inspector_payload(self.controller.project, payload, self.state, self.controller.connections, self._selection)
        payload["inspector"]["editable"] = False
        detail = payload["inspector"].get("detail")
        matches = detail and self._structure_signature and tuple(self._structure_signature[:4]) == (payload["project_id"], payload["revision"], detail["path_id"], detail["entry_id"])
        payload["inspector"]["structure"] = deepcopy(self._structure_data) if matches and self._structure_data.get("status") == "available" else {"status": "not_exported"}
        payload["inspector"]["structure_choice"] = list(self._molecule_choice) if self._molecule_choice else None
        if format == "html":
            # Embed verified selected coordinates only. Other nodes explicitly lack
            # embedded structures; never export cache filenames or an old molecule.
            payload["offline_details"] = {}
            comparison = plot_payload(self.spec, self.active_path, compare=True, state=self.state,
                language=payload["language"], dark=self.dark, selected=self._selection)
            payload["offline_paths"] = comparison["paths"]
            payload["offline_warnings"] = comparison["warnings"]
            payload["offline_table"] = inspector_payload(self.controller.project, comparison, self.state, self.controller.connections, self._selection)
            for path in comparison["paths"]:
                for point in path["points"]:
                    single = {**payload, "paths": [{**path, "visible": True, "points": [{**point, "selected": True}]}]}
                    vm = inspector_payload(self.controller.project, single, self.state, self.controller.connections, [(path["id"], point["entry_id"])])
                    current = payload["inspector"].get("detail")
                    model = payload["inspector"]["structure"] if current and current["entry_id"] == point["entry_id"] else {"status": "not_exported"}
                    payload["offline_details"][point["entry_id"]] = {"detail": vm["detail"], "structure_candidates": vm["structure_candidates"], "structure": model, "structure_choice": payload["inspector"]["structure_choice"] if model.get("status") == "available" else None}
        if format == "workbench_png":
            format = "png"
            payload["export_scope"] = "workbench"
        if format == "png" and (payload["view"] == "3d" or payload.get("export_scope") == "workbench"):
            if not self.ready:
                return False
            # Capture the new renderer with the guarded export-language snapshot.
            payload["image_capture"] = True
            self._capture = {"id": uuid4().hex, "destination": destination, "payload": payload}
            self.controller._workspace_timer.stop()
            self.send(payload, force=True)
            self._capture["render_id"] = self.last_payload["render_id"]
            self.capture_timer.start(15000)
            self.update_actions()
            return True
        return self.controller.export_plot(payload, destination, format)

    def _capture_workbench(self, identity):
        if not self._capture or self._capture["id"] != identity:
            return
        if self.summary.get("render_id") != self._capture["render_id"] or not self.ready:
            self.abort_capture("图表已更新，请重新导出。")
            return
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not self.webview.grab().save(buffer, "PNG"):
            self.abort_capture("图像捕获失败，请重试。")
            return
        self.image_ready(json.dumps({**{k: self.last_payload[k] for k in ("project_id", "revision", "render_id")},
            "request_id": identity, "uri": "data:image/png;base64," + base64.b64encode(bytes(buffer.data())).decode("ascii")}))

    def image_ready(self, raw):
        if not self._capture or len(raw) > 48*1024*1024:
            return
        try:
            data = json.loads(raw)
            if not self._valid_envelope(data) or data.get("request_id") != self._capture["id"]:
                self.abort_capture("图表已更新，请重新导出。")
                return
            prefix = "data:image/png;base64,"
            if not isinstance(data.get("uri"), str) or not data["uri"].startswith(prefix):
                raise ValueError("Invalid PNG capture")
            image = base64.b64decode(data["uri"][len(prefix):], validate=True)
            if isinstance(data.get("viewport"), dict):
                key = self._capture["payload"]["context"] + "/" + self._capture["payload"]["view"]
                viewport = clean_view_state({"viewports": {key: data["viewport"]}}, self.spec)["viewports"][key]
                self._capture["payload"]["viewport"] = viewport
                self._capture["payload"]["viewports"] = {**self._capture["payload"].get("viewports", {}), key: viewport}
            captured, self._capture = self._capture, None
            self.capture_timer.stop()
            if self.controller._workspace_dirty or self.controller._plot_dirty:
                self.controller._workspace_timer.start(400)
            if not self.controller.export_plot(captured["payload"], captured["destination"], "png", image):
                self.warning.setText(self.t("图表已更新，请重新导出。"))
                self.warning.show()
            self._fingerprint = None
            self.refresh()
        except (ValueError, TypeError, KeyError):
            self.abort_capture("图像捕获失败，请重试。")

    def abort_capture(self, message):
        if self._capture:
            self._capture = None
            self.capture_timer.stop()
            if self.controller._workspace_dirty or self.controller._plot_dirty:
                self.controller._workspace_timer.start(400)
            self._fingerprint = None
            self.refresh()
            self.warning.setText(self.t(str(message)))
            self.warning.show()

    def dispose(self):
        self._disposed = True
        self.timeout.stop()
        self.capture_timer.stop()
        if self.webview:
            self.webview.setPage(None)
            self.page.deleteLater()
