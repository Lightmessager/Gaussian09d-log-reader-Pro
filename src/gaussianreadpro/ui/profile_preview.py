"""S4 native preview of computed values; full PlotSpec/Plotly arrives in S7."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget, QToolTip

from .tables import UNIT_LABELS
from .i18n import translate
from ..presentation.palette import get_palette
from ..core.plot_spec import visual_curve_runs


class ProfilePreview(QWidget):
    selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(215)
        self.setMouseTracking(True)
        self.points = []
        self.positions = []
        self.result = None
        self.path = None
        self.selected_id = None
        self.language = "zh_CN"
        self.dark = False
        self.graph_edges = []
        self.setObjectName("profilePreview")

    def set_data(self, project, path, result, selected_id=None):
        self.path, self.result, self.selected_id = path, result, selected_id
        self.points = []
        self.graph_edges = []
        if project and path and result:
            nodes = {node.id: node for node in project.nodes}
            values = {node.entry_id: node for node in result.nodes}
            for entry in path.entries:
                value = values.get(entry.id)
                self.points.append((entry.position, nodes[entry.node_id], value))
            try:
                from ..core.reaction_network import read_reaction_network
                reaction = next((item for item in read_reaction_network(project)["path_reactions"]
                                 if item["path_id"] == path.id and not item["historical"]), None)
                if reaction:
                    entries = {stage["id"]: stage["entry_id"] for stage in reaction["stages"]}
                    self.graph_edges = [(entries[parent], entries[stage["id"]])
                        for stage in reaction["stages"] for parent in stage["predecessor_stage_ids"]
                        if parent in entries and entries[parent] and stage["entry_id"]]
            except ValueError:
                self.graph_edges = []
        self.update()

    def set_language(self, language):
        self.language = language
        self.update()

    def set_theme(self, dark):
        self.dark = bool(dark)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = get_palette("dark" if self.dark else "light")["colors"]
        painter.fillRect(self.rect(), QColor(palette["surface"]))
        self.positions = []
        if self.path and not self.path.visible:
            painter.setPen(QColor(palette["muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Path hidden" if self.language == "en" else "当前路径已隐藏")
            return
        valid = [(pos, node, value) for pos, node, value in self.points if value and value.valid and value.display_value is not None]
        if not valid:
            painter.setPen(QColor(palette["muted"]))
            text = "导入文件，选择能量类型并设置参考体系" if not self.points else "暂无可绘制的有效结果 · 请检查参考、草稿与来源诊断"
            if self.language == "en":
                text = "Import files, choose an energy type and set a reference" if not self.points else "No valid result to plot · Check the reference, drafts and source diagnostics"
            painter.drawText(self.rect().adjusted(20, 15, -20, -15), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
            return
        compact = self.width() < 360 or self.height() < 180
        left, top = (66, 26) if compact else (78, 30)
        right, bottom = (22, 36) if compact else (34, 64)
        area = QRectF(left, top, max(60, self.width() - left - right), max(56 if compact else 80, self.height() - top - bottom))
        values = [value.display_value for _, _, value in valid]
        lo, hi = min(values), max(values)
        spread = hi - lo
        padding = max(spread * .24, .5 if self.path.unit != "hartree" else .002)
        lo, hi = lo - padding, hi + padding
        painter.setFont(QFont(self.font().family(), 9 if compact else 10))
        for step in range(5):
            fraction = step / 4
            y = area.bottom() - fraction * area.height()
            number = lo + fraction * (hi - lo)
            painter.setPen(QPen(QColor(palette["border_soft"]), 1))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor(palette["muted"]))
            painter.drawText(QRectF(0, y - 9, 67, 18), Qt.AlignmentFlag.AlignRight, f"{number:.3f}" if self.path.unit == "hartree" else f"{number:.1f}")
        mode = "绝对能量" if self.path.calculation_mode == "absolute" else "相对能量" if self.path.calculation_mode == "relative" else "能量差"
        painter.drawText(QRectF(10, 0, self.width() - 20, 22), Qt.AlignmentFlag.AlignLeft, f"{translate(mode, self.language)} / {UNIT_LABELS[self.path.unit.value]}")
        count = len(self.points)
        def position(step, value):
            return QPointF(area.left() + (step + .5) / max(count, 1) * area.width(),
                           area.bottom() - (value-lo) / (hi-lo) * area.height())
        if self.graph_edges:
            entry_ids = {entry.node_id: entry.id for entry in self.path.entries}
            curves = visual_curve_runs([(entry_ids[node.id], pos, value.display_value)
                    if value and value.valid and value.display_value is not None else None
                    for pos, node, value in self.points], edges=self.graph_edges)
        else:
            curves = visual_curve_runs([(pos, value.display_value) if value and value.valid and value.display_value is not None
                                        else None for pos, node, value in self.points])
        for run in curves:
            curve = QPainterPath()
            curve.moveTo(position(*run[0]))
            for item in run[1:]:
                curve.lineTo(position(*item))
            for width, alpha in ((10, .07), (6, .17), (2.2, 1)):
                color = QColor(self.path.color); color.setAlphaF(alpha)
                painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawPath(curve)
        for pos, node, value in self.points:
            if value is None or not value.valid or value.display_value is None:
                continue
            point = position(pos, value.display_value)
            x, y = point.x(), point.y()
            selected = node.id == self.selected_id
            color = QColor(palette["sunset"] if selected else self.path.color)
            glow = QRadialGradient(point, 17 if selected else 11)
            center = QColor(color); center.setAlpha(80 if selected else 40)
            edge = QColor(color); edge.setAlpha(0)
            glow.setColorAt(0, center); glow.setColorAt(1, edge)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(point, 17 if selected else 11, 17 if selected else 11)
            if selected:
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(point, 10, 10)
            painter.setPen(QPen(QColor(palette["text"]), .8))
            painter.setBrush(color)
            painter.drawEllipse(point, 5.5 if selected else 4.5, 5.5 if selected else 4.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(palette["text"]))
            painter.drawText(QRectF(x - 46 if compact else x - 60, y - 24, 92 if compact else 120, 18),
                             Qt.AlignmentFlag.AlignCenter, f"{value.display_value:+.3f}")
            label = self.fontMetrics().elidedText(node.label, Qt.TextElideMode.ElideRight,
                                                  int(area.width() / count) - (4 if compact else 0))
            painter.setPen(QColor(palette["muted"]))
            painter.drawText(QRectF(x - area.width() / count / 2, area.bottom() + (8 if compact else 13),
                                    area.width() / count, 18 if compact else 21), Qt.AlignmentFlag.AlignCenter, label)
            self.positions.append((point, node, value))
        footer = "Reaction step · curves are visual guides" if self.language == "en" else "反应步骤 · 曲线仅作视觉引导"
        if not compact:
            painter.drawText(QRectF(area.left(), self.height() - 20, area.width(), 16), Qt.AlignmentFlag.AlignRight, footer)

    def _hit(self, position):
        return next(((node, value) for point, node, value in self.positions
                     if math.hypot(point.x() - position.x(), point.y() - position.y()) < 25), None)

    def mousePressEvent(self, event):
        hit = self._hit(event.position())
        if hit and event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(hit[0].id)

    def mouseMoveEvent(self, event):
        hit = self._hit(event.position())
        if hit:
            node, value = hit
            system = "System" if self.language == "en" else "体系"
            absolute = f"\n{system}: {value.absolute_hartree} Eh" if value.absolute_hartree is not None and self.path.calculation_mode != "direct_difference" else ""
            QToolTip.showText(event.globalPosition().toPoint(), f"{node.label}\n{value.display_value:+.6f} {UNIT_LABELS[value.unit.value]}{absolute}", self)
        else:
            QToolTip.hideText()
