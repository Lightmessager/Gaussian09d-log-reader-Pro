"""Source-linked RF8 analysis pages; displayed log text is always plain text."""
import csv
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QTextCursor
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)
from .i18n import translate
from ..core.elements import element_symbol


_CONFIG = {
    "结构": ("structures", "读取结构"),
    "振动": ("vibrations", "读取频率"),
    "热化学": ("thermochemistry", "读取热化学"),
    "NBO 分析": ("nbo", "检查 NBO 节"),
    "IRC 分析": ("irc", "读取 IRC 路径"),
    "日志查看器": ("log", "打开所选作业"),
}


class AnalysisPage(QWidget):
    request = Signal(str, str, str)
    structure_request = Signal(object)

    def __init__(self, title, controller, language="zh_CN", parent=None):
        super().__init__(parent)
        self.title, self.controller, self.language = title, controller, language
        self.module, action_text = _CONFIG[title]
        self.result = None
        self._headers = []
        self._irc_row_points = []
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)
        self.heading = QLabel(translate(title, language))
        self.heading.setProperty("i18n_source", title)
        root.addWidget(self.heading)
        row = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(220)
        self.source_combo.currentIndexChanged.connect(self._sources_changed)
        self.job_combo = QComboBox()
        self.job_combo.setMinimumWidth(220)
        self.load_button = QPushButton(action_text)
        self.load_button.setProperty("i18n_source", action_text)
        self.load_button.clicked.connect(self.load_selected)
        self.export_button = QPushButton("导出 CSV")
        self.export_button.setProperty("i18n_source", "导出 CSV")
        self.export_button.clicked.connect(self.export_csv)
        self.export_button.setEnabled(False)
        row.addWidget(self.source_combo, 1)
        row.addWidget(self.job_combo, 1)
        row.addWidget(self.load_button)
        row.addWidget(self.export_button)
        root.addLayout(row)
        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选显示行…")
        self.search.setProperty("i18n_placeholder", "筛选显示行…")
        self.search.textChanged.connect(self._filter_rows)
        root.addWidget(self.search)
        self.status = QLabel("选择来源与作业；读取前会重新校验来源 SHA-256。")
        self.status.setProperty("i18n_source", "选择来源与作业；读取前会重新校验来源 SHA-256。")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.status)
        self.point_info = QLabel()
        self.point_info.setWordWrap(True)
        self.point_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.point_info.setVisible(self.module == "irc")
        root.addWidget(self.point_info)
        self.structure_canvas = StructureCanvas()
        self.structure_canvas.hide()
        root.addWidget(self.structure_canvas)
        self.table = QTableWidget(0, 0)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.currentCellChanged.connect(self._irc_selection_changed)
        root.addWidget(self.table, 1)
        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("analysisLogText")
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_text.hide()
        root.addWidget(self.log_text, 1)
        self._sources_changed()

    def set_language(self, language):
        self.language = language
        self.heading.setText(translate(self.title, language))
        for widget in (self.load_button, self.export_button):
            widget.setText(translate(widget.property("i18n_source"), language))
        self.search.setPlaceholderText(translate("筛选显示行…", language))
        for column, raw in enumerate(getattr(self, "_raw_headers", [])):
            self.table.setHorizontalHeaderItem(column, QTableWidgetItem(translate(raw, language)))
        if self.result:
            self.show_result(self.result)
        else:
            self.status.setText(translate("选择来源与作业；读取前会重新校验来源 SHA-256。", language))

    def update_project(self, project, connections):
        previous_source = self.source_combo.currentData()
        previous_job = self.job_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        if project:
            for source in project.source_files:
                connection = next((c for c in connections if c.source_file_id == source.id), None)
                marker = "" if connection and connection.state == "available" else " · 来源不可用"
                self.source_combo.addItem(source.display_name + marker, source.id)
        index = self.source_combo.findData(previous_source)
        if index >= 0:
            self.source_combo.setCurrentIndex(index)
        self.source_combo.blockSignals(False)
        self._sources_changed()
        index = self.job_combo.findData(previous_job)
        if index >= 0:
            self.job_combo.setCurrentIndex(index)

    def _sources_changed(self, *_):
        self.job_combo.clear()
        project = self.controller.project
        source_id = self.source_combo.currentData()
        source = next((item for item in project.source_files if item.id == source_id), None) if project else None
        if source:
            for job in source.jobs:
                termination = job.termination.value
                self.job_combo.addItem(f"Job {job.ordinal + 1} · {termination} · L{job.start_line}-{job.end_line}", job.id)
        self.load_button.setEnabled(bool(source and source.jobs))

    def load_selected(self):
        source_id, job_id = self.source_combo.currentData(), self.job_combo.currentData()
        if not source_id or not job_id:
            return
        if self.module == "structures":
            project = self.controller.project
            self.structure_request.emit({"project_id": project.id, "revision": project.revision,
                                         "source_file_id": source_id, "job_id": job_id,
                                         "purpose": "analysis_structure"})
        else:
            self.request.emit(self.module, source_id, job_id)
        self.load_button.setEnabled(False)
        self.status.setText("正在读取并核对来源…")

    def show_result(self, result):
        self.result = result
        self.load_button.setEnabled(True)
        if result.get("module") not in (None, self.module):
            return
        status = result.get("status", "unknown")
        if status == "available":
            self.status.setText(f"Source SHA-256 verified · Job {result.get('job_ordinal', '—')} · lines {result.get('job_start', '—')}–{result.get('job_end', '—')}" if self.language == "en" else f"来源 SHA-256 已匹配 · Job {result.get('job_ordinal', '—')} · 行 {result.get('job_start', '—')}–{result.get('job_end', '—')}")
            if self.module == "nbo":
                self.status.setText(self.status.text() + f" · Gaussian NBO {result.get('version')} · {result.get('row_count', 0)} 行")
            elif self.module == "irc":
                branches = ", ".join(result.get("branches", []))
                self.status.setText(self.status.text() + f" · {result.get('point_count', 0)} points · {branches} · TS {result.get('ts_energy_hartree', 0):.6f} Eh")
        elif status == "no_data":
            messages = {"no_harmonic_frequencies": "该作业没有可识别的谐振动频率行。",
                        "no_supported_thermochemistry": "该作业没有已支持的热化学输出字段。",
                        "no_nbo_section": "已核验作业中没有识别到受支持的 NBO 节。",
                        "no_irc_section": "已核验作业中没有识别到受支持的 IRC 节。",
                        "no_supported_thermochemistry": "该作业没有已支持的热化学输出字段。"}
            self.status.setText(translate(messages.get(result.get("reason"), "所选作业没有此类数据。"), self.language))
        elif status == "unsupported_format":
            self.status.setText(translate("检测到相关节标题或版本，但当前解析器尚未支持此格式；不会展示猜测结果。", self.language))
        else:
            labels = {"source_unavailable": "来源未连接或无法验证。", "source_changed": "日志已变化，来源指纹不再匹配。",
                      "source_unreadable": "无法读取来源文件。", "size_limit": "来源超过 64 MiB 的分析读取上限。",
                      "job_range_invalid": "作业行范围与来源文件不匹配。", "cancelled": "读取已取消。",
                      "parse_error": f"解析遇到无效字段：{result.get('reason', 'unknown')}。"}
            self.status.setText(translate(labels.get(status, f"读取未完成：{status}"), self.language))
        if self.module == "log":
            text = result.get("text", "")
            self.log_text.setPlainText(text)
            self.log_text.show()
            self.table.hide()
            self.export_button.setEnabled(False)
            return
        self.log_text.hide()
        self.table.show()
        if self.module != "structures":
            self.structure_canvas.hide()
        if self.module == "structures":
            data = result.get("structure", {})
            if data.get("status") != "available":
                self.structure_canvas.hide()
                self._set_table(["状态"], [[data.get("status", "unavailable")]])
            else:
                self.structure_canvas.set_structure(data)
                self.structure_canvas.show()
                self._set_table(["原子", "元素", "原子序数", "X (Å)", "Y (Å)", "Z (Å)"],
                                [[index + 1, element_symbol(atom["atomic_number"]), atom["atomic_number"], *[f"{value:.8f}" for value in atom["xyz"]]]
                                 for index, atom in enumerate(data.get("atoms", []))])
        elif self.module == "vibrations":
            rows = [[item["mode"], f"{item['frequency_cm1']:.4f}", "虚频" if item["imaginary"] else "正常",
                     "" if item["ir_intensity_km_mol"] is None else f"{item['ir_intensity_km_mol']:.4f}", item["source_line"]]
                    for item in result.get("modes", [])]
            self._set_table(["模式", "频率 (cm⁻¹)", "类型", "IR 强度", "来源行"], rows)
        elif self.module == "thermochemistry":
            rows = [[item["term"], f"{item['value']:.12g}", item["unit"], item["source_line"]]
                    for item in result.get("values", []) + result.get("conditions", [])]
            self._set_table(["字段", "读取值", "单位", "来源行"], rows)
        elif self.module in {"nbo", "irc"}:
            if self.module == "nbo" and status == "available":
                headers = ["分析节", "行类型", "原子", "元素", "电荷 (e)", "Core (e)",
                           "Valence (e)", "Rydberg (e)", "Total (e)", "供体 NBO", "受体 NBO",
                           "E(2) (kcal/mol)", "ΔE (hartree)", "F(i,j) (hartree)", "来源行"]
                rows = []
                for section in result.get("sections", []):
                    for item in section.get("rows", []):
                        rows.append([section["name"], "NPA" if "atom" in item else "E(2)",
                                     item.get("atom", ""), item.get("element", ""), item.get("charge", ""),
                                     item.get("core", ""), item.get("valence", ""), item.get("rydberg", ""),
                                     item.get("total", ""), item.get("donor", ""), item.get("acceptor", ""),
                                     item.get("e2_kcal_mol", ""), item.get("energy_gap_hartree", ""),
                                     item.get("fock_coupling_hartree", ""), item["source_line"]])
                self._set_table(headers, rows)
            elif self.module == "nbo":
                self._set_table(["NBO 节标题", "来源行"],
                                [[item.get("text", ""), item.get("line", "")]
                                 for item in result.get("sections", []) if isinstance(item, dict)])
            elif self.module == "irc":
                self._irc_row_points = result.get("points", []) if status == "available" else []
                self.point_info.clear()
                if status == "available":
                    self._set_table(["分支", "步骤", "反应坐标", "相对 TS 能量 (Eh)", "坐标行", "汇总行", "结构行"],
                                    [[item["branch"], item["step"], f"{item['reaction_coordinate']:.5f}",
                                      f"{item['relative_energy_hartree']:.5f}", item["source_line"],
                                      item["summary_line"], item["structure"]["line_start"] if item["structure"] else ""]
                                     for item in self._irc_row_points])
                    self.table.selectRow(0)
                else:
                    self._set_table(["节标题", "来源行"], [[item["text"], item["line"]]
                                    for item in result.get("sections", [])])
        self.export_button.setEnabled(bool(self._headers and self.table.rowCount()))

    def _irc_selection_changed(self, row, _column, _old_row, _old_column):
        if self.module != "irc":
            return
        self.structure_canvas.hide()
        if not 0 <= row < len(self._irc_row_points):
            self.point_info.clear()
            return
        point = self._irc_row_points[row]
        structure = point.get("structure")
        branch = {"forward": "正向", "reverse": "反向", "transition_state": "过渡态"}.get(point["branch"], point["branch"]) if self.language != "en" else point["branch"]
        if structure:
            self.structure_canvas.set_structure(structure)
            self.structure_canvas.show()
            self.point_info.setText((
                f"{branch} · 点 {point['step']} · 坐标行 {point['source_line']} · "
                f"能量汇总行 {point['summary_line']} · 结构行 {structure['line_start']}–{structure['line_end']}"
            ) if self.language != "en" else (
                f"{branch} · point {point['step']} · coordinate line {point['source_line']} · "
                f"energy summary line {point['summary_line']} · structure lines {structure['line_start']}–{structure['line_end']}"))
        else:
            self.point_info.setText((
                f"{branch} · 点 {point['step']} · 能量汇总行 {point['summary_line']} · 无已核验的逐点结构"
            ) if self.language != "en" else (
                f"{branch} · point {point['step']} · energy summary line "
                f"{point['summary_line']} · no verified point structure"))

    def _set_table(self, headers, rows):
        self._raw_headers = list(headers)
        self._headers = [translate(value, self.language) for value in headers]
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(self._headers)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if column and str(value).replace('.', '', 1).replace('-', '', 1).isdigit() else Qt.AlignmentFlag.AlignLeft))
                self.table.setItem(row_index, column, item)
        self._filter_rows()

    def _filter_rows(self, *_):
        query = self.search.text().casefold().strip()
        for row in range(self.table.rowCount()):
            match = not query or any(query in (self.table.item(row, col).text().casefold()
                                               if self.table.item(row, col) else "")
                                     for col in range(self.table.columnCount()))
            self.table.setRowHidden(row, not match)
        if self.module == "log" and self.log_text.isVisible():
            self.log_text.moveCursor(QTextCursor.MoveOperation.Start)
            if query:
                self.log_text.find(self.search.text())

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出分析表", f"{self.module}.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(self._headers)
            for row in range(self.table.rowCount()):
                if self.table.isRowHidden(row):
                    continue
                writer.writerow([self.table.item(row, col).text() if self.table.item(row, col) else ""
                                 for col in range(self.table.columnCount())])


class StructureCanvas(QWidget):
    """Small rotatable ball-and-stick view from the verified Gaussian coordinates."""
    COLORS = {1: "#f4f5f8", 6: "#4b5565", 7: "#5279db", 8: "#e35d6a", 9: "#65ac72",
              15: "#e39b3e", 16: "#e0c34c", 17: "#58aa67", 35: "#9a6847", 53: "#8e63ad"}

    @staticmethod
    def _label_color(fill):
        """Choose whichever of near-black or white contrasts more with an atom."""
        color = QColor(fill)
        channels = [color.redF(), color.greenF(), color.blueF()]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                  for value in channels]
        luminance = .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]
        return QColor("#17131F" if (luminance + .05) / .05 >= 1.05 / (luminance + .05)
                      else "#FFFFFF")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setObjectName("structureCanvas")
        self.setMouseTracking(True)
        self.atoms = []
        self.bonds = []
        self.yaw = .55
        self.pitch = .35
        self._drag = None
        self.setToolTip("拖动旋转结构 / Drag to rotate")

    def set_structure(self, structure):
        self.atoms = structure.get("atoms", [])
        self.bonds = structure.get("bonds", [])
        self.caption = structure.get("orientation", "Gaussian orientation")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        if not self.atoms:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "没有可显示的结构")
            return
        coords = [atom["xyz"] for atom in self.atoms]
        center = [sum(point[i] for point in coords) / len(coords) for i in range(3)]
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        rotated = []
        for xyz in coords:
            x, y, z = (xyz[i] - center[i] for i in range(3))
            x, z = cy*x + sy*z, -sy*x + cy*z
            y, z = cp*y - sp*z, sp*y + cp*z
            rotated.append((x, y, z))
        extent = max((max(abs(point[0]), abs(point[1])) for point in rotated), default=1) or 1
        scale = min((self.width() - 70) / (2*extent), (self.height() - 48) / (2*extent))
        cx, cy0 = self.width()/2, self.height()/2
        projected = [(cx + x*scale, cy0 - y*scale, z) for x, y, z in rotated]
        bond = QColor(self.palette().color(QPalette.ColorRole.Text))
        bond.setAlpha(155)
        painter.setPen(QPen(bond, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for first, second in self.bonds:
            if first < len(projected) and second < len(projected):
                a, b = projected[first], projected[second]
                painter.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))
        for index in sorted(range(len(self.atoms)), key=lambda i: projected[i][2]):
            x, y, _ = projected[index]
            number = self.atoms[index]["atomic_number"]
            radius = 7 if number == 1 else 10
            fill = QColor(self.COLORS.get(number, "#a09aa6"))
            outline = QColor(self.palette().color(QPalette.ColorRole.Text))
            outline.setAlpha(200)
            painter.setPen(QPen(outline, 1))
            painter.setBrush(fill)
            painter.drawEllipse(int(x-radius), int(y-radius), 2*radius, 2*radius)
            if number != 1:
                painter.setPen(self._label_color(fill))
                painter.drawText(int(x-radius), int(y-radius), 2*radius, 2*radius,
                                 Qt.AlignmentFlag.AlignCenter, element_symbol(number))
        painter.setPen(self.palette().color(QPalette.ColorRole.Mid))
        painter.drawText(10, self.height()-10, f"{getattr(self, 'caption', 'Gaussian orientation')} · Å · drag to rotate")

    def mousePressEvent(self, event):
        self._drag = event.position()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        position = event.position()
        self.yaw += (position.x() - self._drag.x()) * .012
        self.pitch = max(-1.45, min(1.45, self.pitch + (position.y() - self._drag.y()) * .012))
        self._drag = position
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None


class ProjectTablesPage(QWidget):
    """Filterable/exportable view of calculated project path entries."""
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        row = QHBoxLayout()
        self.heading = QLabel("项目数据表")
        self.heading.setProperty("i18n_source", "项目数据表")
        row.addWidget(self.heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选节点、来源或路径…")
        self.search.setProperty("i18n_placeholder", "筛选节点、来源或路径…")
        self.search.textChanged.connect(self.filter_rows)
        row.addWidget(self.search, 1)
        export = QPushButton("导出 CSV")
        export.setProperty("i18n_source", "导出 CSV")
        export.clicked.connect(self.export_csv)
        row.addWidget(export)
        root.addLayout(row)
        self.status = QLabel("显示当前已计算路径数据。")
        root.addWidget(self.status)
        self.table = QTableWidget(0, 0)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        root.addWidget(self.table, 1)
        self.headers = ["路径", "位置", "节点", "角色", "计算值", "单位", "状态", "来源文件", "作业"]
        self.table.setColumnCount(len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)

    def set_language(self, language):
        self.language = language
        self.heading.setText(translate("项目数据表", language))
        self.search.setPlaceholderText(translate("筛选节点、来源或路径…", language))
        button = self.findChild(QPushButton)
        if button:
            button.setText(translate("导出 CSV", language))
        self.headers = [translate(value, language) for value in ["路径", "位置", "节点", "角色", "计算值", "单位", "状态", "来源文件", "作业"]]
        self.table.setHorizontalHeaderLabels(self.headers)
        count = getattr(self, "_entry_count", 0)
        self.status.setText(f"{count} path entries · shows existing project results without recalculating." if language == "en" else f"{count} 个路径节点 · 仅展示项目计算结果，不在此重复计算。")

    def update_project(self, project, results):
        nodes = {node.id: node for node in project.nodes} if project else {}
        result_by_path = {result.path_id: result for result in results}
        rows = []
        if project:
            sources = {source.id: source for source in project.source_files}
            for path in project.paths:
                result = result_by_path.get(path.id)
                values = {item.entry_id: item for item in result.nodes} if result else {}
                for entry in path.entries:
                    node = nodes.get(entry.node_id)
                    value = values.get(entry.id)
                    dependencies = value.dependencies if value else ()
                    source_labels, job_labels = [], []
                    for dep in dependencies:
                        source = sources.get(dep.source_file_id)
                        if source and source.display_name not in source_labels:
                            source_labels.append(source.display_name)
                        job = next((j for j in source.jobs if j.id == dep.job_id), None) if source else None
                        job_label = str(job.ordinal + 1) if job else "—"
                        if job_label not in job_labels:
                            job_labels.append(job_label)
                    shown = "—" if not value or value.display_value is None else f"{value.display_value:.8f}"
                    state = "有效" if value and value.valid else "未计算 / 无效"
                    rows.append([path.label, entry.position + 1, node.label if node else "—",
                                 node.role.value if node else "—", shown,
                                 path.unit.value, state, "; ".join(source_labels) or "—",
                                 "; ".join(job_labels) or "—"])
        self.table.setRowCount(len(rows))
        for ri, row in enumerate(rows):
            for ci, value in enumerate(row):
                self.table.setItem(ri, ci, QTableWidgetItem(str(value)))
        self._entry_count = len(rows)
        self.status.setText(f"{len(rows)} path entries · shows existing project results without recalculating." if getattr(self, "language", "zh_CN") == "en" else f"{len(rows)} 个路径节点 · 仅展示项目计算结果，不在此重复计算。")
        self.filter_rows()

    def filter_rows(self, *_):
        query = self.search.text().casefold().strip()
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, bool(query) and not any(
                query in (self.table.item(row, col).text().casefold() if self.table.item(row, col) else "")
                for col in range(self.table.columnCount())))

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出项目表格", "GaussianReaderPro-tables.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(self.headers)
            for row in range(self.table.rowCount()):
                if not self.table.isRowHidden(row):
                    writer.writerow([self.table.item(row, col).text() if self.table.item(row, col) else ""
                                     for col in range(self.table.columnCount())])
