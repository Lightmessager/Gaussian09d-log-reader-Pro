"""Interactive, read-only rendering surface for a reaction path draft."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json
import math

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
                           QPolygonF, QTransform, QPainterPathStroker)
from PySide6.QtWidgets import (QApplication, QGraphicsItem, QGraphicsObject,
                              QGraphicsPathItem, QGraphicsPolygonItem,
                              QGraphicsScene, QGraphicsView)

from .i18n import translate


SPECIES_MIME = "application/x-gaussianreadpro-species-v1"


_ROLE_LABELS = {
    "reactant": "反应物",
    "intermediate": "中间体",
    "transition_state": "过渡态",
    "product": "产物",
    "unspecified": "待选角色",
}


class _StageCardItem(QGraphicsObject):
    moved = Signal(str, float, float)
    selected = Signal(str)

    WIDTH = 312
    HEIGHT = 194
    COMPOSITION_ZONE = QRectF(12, 96, 288, 38)
    ENERGY_ZONE = QRectF(12, 142, 288, 39)

    def __init__(self, stage, species_names, *, is_zero, energy_kind, language):
        super().__init__()
        self.stage = deepcopy(stage)
        self.stage_id = stage["id"]
        self.species_names = species_names
        self.is_zero = is_zero
        self.energy_kind = energy_kind
        self.language = language
        self._press_position = None
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges |
                      QGraphicsItem.GraphicsItemFlag.ItemIsFocusable)
        self.setZValue(2)
        self.setToolTip(self._tooltip())
        self.setData(0, "stage")
        self.setData(1, self.stage_id)

    def boundingRect(self):
        return QRectF(0, 0, self.WIDTH, self.HEIGHT)

    def _text(self, value):
        return translate(value, self.language)

    def _role_text(self):
        return self._text(_ROLE_LABELS.get(self.stage.get("role"), "待选角色"))

    def _composition_text(self):
        parts = []
        for item in self.stage.get("species", []):
            name = self.species_names.get(item.get("species_id"), "?")
            coefficient = item.get("coefficient", 1)
            parts.append(f"{coefficient:g} {name}")
        return " + ".join(parts) if parts else self._text("拖入物质卡以添加组成")

    def _energy_text(self):
        if self.stage.get("missing"):
            return self._text("NOT FOUND · 无能量值")
        terms = self.stage.get("terms", [])
        if not terms:
            return self._text("拖入有唯一作业绑定的物质卡以添加能量项")
        items = []
        for term in terms:
            name = self.species_names.get(term.get("species_id"), "?")
            binding = f"{term.get('source_file_id', '')[:8]}/{term.get('job_id', '')[:8]}"
            items.append(f"{term.get('coefficient', 1):g} {name} · {binding}")
        return "；".join(items)

    def _tooltip(self):
        pieces = [f"{self.stage.get('label', '')} · {self._role_text()}"]
        if self.is_zero:
            pieces.append(self._text("零点"))
        if self.stage.get("missing"):
            pieces.append(self._text("NOT FOUND · 无能量值"))
        pieces.append(self._text("组成：") + self._composition_text())
        pieces.append(self._text("能量项：") + self._energy_text())
        if not self.stage.get("normalization_confirmed"):
            pieces.append(self._text("待核对阶段组成与统一零点可比性"))
        return "\n".join(pieces)

    def drop_zone_at(self, point):
        if self.COMPOSITION_ZONE.contains(point):
            return "composition"
        if self.ENERGY_ZONE.contains(point):
            return "energy"
        return None

    def mousePressEvent(self, event):
        self._press_position = self.pos()
        self.selected.emit(self.stage_id)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._press_position is not None:
            current = self.pos()
            if (current - self._press_position).manhattanLength() > 0.5:
                self.moved.emit(self.stage_id, current.x(), current.y())
        self._press_position = None

    def keyPressEvent(self, event):
        moves = {
            Qt.Key.Key_Left: (-24, 0), Qt.Key.Key_Right: (24, 0),
            Qt.Key.Key_Up: (0, -24), Qt.Key.Key_Down: (0, 24),
        }
        delta = moves.get(event.key())
        if delta:
            position = self.pos() + QPointF(*delta)
            self.setPos(position)
            self.moved.emit(self.stage_id, position.x(), position.y())
            event.accept()
            return
        super().keyPressEvent(event)

    def paint(self, painter, option, widget=None):
        palette = QApplication.palette()
        background = palette.color(palette.ColorRole.Base)
        text = palette.color(palette.ColorRole.Text)
        muted = palette.color(palette.ColorRole.PlaceholderText)
        border = QColor("#7450AF") if self.isSelected() else palette.color(palette.ColorRole.Mid)
        if self.is_zero:
            border = QColor("#C46428")
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(border, 2 if self.isSelected() or self.is_zero else 1))
        painter.setBrush(QBrush(background))
        painter.drawRoundedRect(self.boundingRect(), 15, 15)

        title_font = QFont(painter.font())
        title_font.setBold(True)
        title_font.setPointSize(max(10, title_font.pointSize()))
        painter.setFont(title_font)
        painter.setPen(text)
        title = self.stage.get("label", "")
        painter.drawText(QRectF(14, 9, 184, 24), Qt.AlignmentFlag.AlignVCenter, title)

        role_rect = QRectF(202, 9, 98, 24)
        role_color = QColor("#7450AF")
        role_color.setAlpha(34)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(role_color)
        painter.drawRoundedRect(role_rect, 8, 8)
        painter.setPen(text)
        painter.setFont(painter.font())
        painter.drawText(role_rect, Qt.AlignmentFlag.AlignCenter, self._role_text())

        if self.is_zero:
            badge = QRectF(14, 38, 76, 21)
            painter.setPen(QPen(QColor("#C46428"), 1))
            painter.setBrush(QColor("#C46428"))
            painter.drawRoundedRect(badge, 7, 7)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, self._text("零点"))
        elif self.stage.get("role") == "transition_state":
            painter.setPen(QPen(QColor("#C46428"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(14, 38, 105, 21), 7, 7)
            painter.setPen(QColor("#C46428"))
            painter.drawText(QRectF(14, 38, 105, 21), Qt.AlignmentFlag.AlignCenter, self._text("过渡态"))

        painter.setPen(QPen(palette.color(palette.ColorRole.Midlight), 1))
        painter.setBrush(QBrush(palette.color(palette.ColorRole.AlternateBase)))
        painter.drawRoundedRect(self.COMPOSITION_ZONE, 7, 7)
        painter.drawRoundedRect(self.ENERGY_ZONE, 7, 7)
        painter.setPen(muted)
        small_font = QFont(painter.font())
        small_font.setPointSize(max(8, small_font.pointSize() - 2))
        painter.setFont(small_font)
        painter.drawText(QRectF(15, 63, 285, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self._text("组成 · 拖放区域"))
        painter.drawText(QRectF(15, 134, 285, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self._text("能量项 · 拖放区域"))
        painter.setPen(QPen(QColor("#C46428") if self.stage.get("missing") else text, 1))
        single_line_flags = int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.TextFlag.TextSingleLine)
        painter.drawText(self.COMPOSITION_ZONE.adjusted(5, 0, -5, 0),
                         single_line_flags,
                         self._composition_text())
        painter.drawText(self.ENERGY_ZONE.adjusted(5, 0, -5, 0),
                         single_line_flags,
                         self._energy_text())


class _ConnectionPathItem(QGraphicsPathItem):
    def __init__(self, path, connection_id, selected_callback, color):
        super().__init__(path)
        self.connection_id = connection_id
        self.selected_callback = selected_callback
        self.color = color
        self.setPen(QPen(color, 2))
        self.setZValue(-2)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setData(0, "connection")
        self.setData(1, connection_id)

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(16)
        return stroker.createStroke(self.path())

    def mousePressEvent(self, event):
        self.selected_callback(self.connection_id)
        super().mousePressEvent(event)

    def paint(self, painter, option, widget=None):
        self.setPen(QPen(QColor("#C46428") if self.isSelected() else self.color,
                         3 if self.isSelected() else 2))
        super().paint(painter, option, widget)


class ReactionCanvas(QGraphicsView):
    """A visual projection of one BuilderDraft path; edits are emitted as commands."""

    selectionRequested = Signal(str, str)
    commandRequested = Signal(dict)
    dropRejected = Signal(str)

    def __init__(self, parent=None, *, language="zh_CN"):
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self.language = language
        self._draft = None
        self._recipe = None
        self._stage_items = {}
        self._selected_stage_id = None
        self._selected_connection_id = None
        self._selected_kind = "stage"
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(300, 240)
        self.setObjectName("reactionCanvas")
        self.setToolTip(translate("阶段画布：拖动物质卡到组成区或能量区；拖动阶段只改变布局。", language))

    def _text(self, value):
        return translate(value, self.language)

    def set_language(self, language):
        if language == self.language:
            return
        self.language = language
        self.setToolTip(translate(
            "阶段画布：拖动物质卡到组成区或能量区；拖动阶段只改变布局。", language))
        if self._draft is not None:
            self.set_draft(self._draft)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(100, self._center_selected)

    def _center_selected(self):
        selected = self._stage_items.get(self._selected_stage_id)
        if selected is not None:
            self.centerOn(selected)
        elif self._selected_connection_id and self._recipe:
            edge = next((item for item in self._recipe.get("connections", [])
                         if item["id"] == self._selected_connection_id), None)
            target = self._stage_items.get(edge["target_stage_id"]) if edge else None
            if target is not None:
                self.centerOn(target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        selected = self._stage_items.get(self._selected_stage_id)
        if selected is not None:
            self.centerOn(selected)
        elif self._selected_connection_id and self._recipe:
            edge = next((item for item in self._recipe.get("connections", [])
                         if item["id"] == self._selected_connection_id), None)
            target = self._stage_items.get(edge["target_stage_id"]) if edge else None
            if target is not None:
                self.centerOn(target)

    def set_draft(self, snapshot):
        self._draft = deepcopy(snapshot)
        network = self._draft.get("network", {})
        path_id = self._draft.get("path_id")
        self._recipe = next((item for item in network.get("path_reactions", [])
                             if item.get("path_id") == path_id), None)
        self._scene.clear()
        self._stage_items.clear()
        recipe = self._recipe
        if recipe is None or not recipe.get("stages"):
            empty = self._scene.addText(self._text("尚无可视化阶段。选择物质卡后添加阶段。"))
            empty.setDefaultTextColor(QApplication.palette().color(QApplication.palette().ColorRole.Text))
            self._scene.setSceneRect(empty.boundingRect().adjusted(-24, -24, 24, 24))
            return
        stages = recipe["stages"]
        species_names = {item["id"]: item["name"] for item in network.get("species", [])}
        stage_by_id = {stage["id"]: stage for stage in stages}
        positions = self._positions(stages, recipe.get("connections", []), self._draft.get("layout", {}))
        zero = recipe.get("zero_point", {})
        zero_stage_id = zero.get("stage_id") if zero.get("kind") in {"stage", "reactant"} else None
        if zero.get("kind") == "reactant" and not zero_stage_id:
            zero_stage_id = next((item["id"] for item in stages if item.get("role") == "reactant"), None)
        for edge in recipe.get("connections", []):
            source = stage_by_id.get(edge.get("source_stage_id"))
            target = stage_by_id.get(edge.get("target_stage_id"))
            if source is None or target is None:
                continue
            start, end = self._edge_points(positions[source["id"]], positions[target["id"]])
            path = QPainterPath(start)
            distance = max(38, (end.x() - start.x()) * 0.42)
            path.cubicTo(start + QPointF(distance, 0), end - QPointF(distance, 0), end)
            color = QApplication.palette().color(QApplication.palette().ColorRole.Mid)
            line = _ConnectionPathItem(path, edge["id"], self._connection_selected, color)
            self._scene.addItem(line)
            direction = end - path.pointAtPercent(0.96)
            angle = math.atan2(direction.y(), direction.x())
            arrow_points = [end,
                            end - QPointF(math.cos(angle - 0.5) * 12, math.sin(angle - 0.5) * 12),
                            end - QPointF(math.cos(angle + 0.5) * 12, math.sin(angle + 0.5) * 12)]
            arrow = QGraphicsPolygonItem(QPolygonF(arrow_points))
            arrow.setPen(QPen(color, 1))
            arrow.setBrush(QBrush(color))
            arrow.setZValue(-2)
            arrow.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            arrow.setData(0, "connection-arrow")
            arrow.setData(1, edge["id"])
            self._scene.addItem(arrow)

        for stage in stages:
            item = _StageCardItem(stage, species_names, is_zero=stage["id"] == zero_stage_id,
                                  energy_kind=recipe.get("energy_kind", "gibbs_total"), language=self.language)
            item.setPos(positions[stage["id"]])
            item.selected.connect(self._stage_selected)
            item.moved.connect(self._stage_moved)
            self._scene.addItem(item)
            self._stage_items[stage["id"]] = item
        if self._selected_stage_id in self._stage_items:
            self._stage_items[self._selected_stage_id].setSelected(True)
        if self._selected_connection_id:
            connection_item = next((item for item in self._scene.items()
                                    if isinstance(item, _ConnectionPathItem) and
                                    item.connection_id == self._selected_connection_id), None)
            if connection_item:
                connection_item.setSelected(True)
        self._scene.setSceneRect(self._scene.itemsBoundingRect().adjusted(-30, -30, 30, 30))

    def _positions(self, stages, connections, layout):
        parents = {stage["id"]: list(stage.get("predecessor_stage_ids", [])) or
                   ([stage["predecessor_stage_id"]] if stage.get("predecessor_stage_id") else [])
                   for stage in stages}
        ranks = {stage["id"]: 0 for stage in stages}
        for _ in range(len(stages)):
            changed = False
            for stage in stages:
                rank = max((ranks[parent] + 1 for parent in parents[stage["id"]] if parent in ranks), default=0)
                if rank > ranks[stage["id"]]:
                    ranks[stage["id"]] = rank
                    changed = True
            if not changed:
                break
        rows = defaultdict(int)
        result = {}
        manual = layout.get("stages", {}) if isinstance(layout, dict) else {}
        for stage in stages:
            identifier = stage["id"]
            point = manual.get(identifier) if isinstance(manual, dict) else None
            if isinstance(point, dict) and set(point) == {"x", "y"}:
                try:
                    x, y = float(point["x"]), float(point["y"])
                    if math.isfinite(x) and math.isfinite(y) and abs(x) <= 100000 and abs(y) <= 100000:
                        result[identifier] = QPointF(x, y)
                        continue
                except (TypeError, ValueError, OverflowError):
                    pass
            rank = ranks[identifier]
            row = rows[rank]
            rows[rank] += 1
            result[identifier] = QPointF(40 + rank * 382, 40 + row * 226)
        return result

    @classmethod
    def _edge_points(cls, source_position, target_position):
        source_rect = QRectF(source_position.x(), source_position.y(), cls._card_width(), cls._card_height())
        target_rect = QRectF(target_position.x(), target_position.y(), cls._card_width(), cls._card_height())
        if target_rect.center().x() >= source_rect.center().x():
            start = QPointF(source_rect.right(), source_rect.center().y())
            end = QPointF(target_rect.left(), target_rect.center().y())
        else:
            start = QPointF(source_rect.left(), source_rect.center().y())
            end = QPointF(target_rect.right(), target_rect.center().y())
        return start, end

    @staticmethod
    def _card_width():
        return _StageCardItem.WIDTH

    @staticmethod
    def _card_height():
        return _StageCardItem.HEIGHT

    def stage_item(self, stage_id):
        return self._stage_items.get(stage_id)

    def stage_count(self):
        return len(self._stage_items)

    def rendered_connection_pairs(self):
        if not self._recipe:
            return ()
        return tuple((edge["source_stage_id"], edge["target_stage_id"])
                     for edge in self._recipe.get("connections", []))

    def select_stage(self, stage_id):
        item = self._stage_items.get(stage_id)
        if item is None:
            return False
        self._stage_selected(stage_id)
        self.centerOn(item)
        return True

    def select_connection(self, connection_id):
        if not self._recipe or not any(edge["id"] == connection_id for edge in self._recipe.get("connections", [])):
            return False
        self._connection_selected(connection_id)
        edge = next(item for item in self._recipe["connections"] if item["id"] == connection_id)
        target = self._stage_items.get(edge["target_stage_id"])
        if target is not None:
            self.centerOn(target)
        return True

    def _stage_selected(self, stage_id):
        self._selected_stage_id = stage_id
        self._selected_connection_id = None
        self._selected_kind = "stage"
        for identifier, item in self._stage_items.items():
            item.setSelected(identifier == stage_id)
        for item in self._scene.items():
            if isinstance(item, _ConnectionPathItem):
                item.setSelected(False)
        self.selectionRequested.emit("stage", stage_id)

    def _connection_selected(self, connection_id):
        self._selected_connection_id = connection_id
        self._selected_stage_id = None
        self._selected_kind = "connection"
        for item in self._stage_items.values():
            item.setSelected(False)
        for item in self._scene.items():
            if isinstance(item, _ConnectionPathItem):
                item.setSelected(item.connection_id == connection_id)
        self.selectionRequested.emit("connection", connection_id)

    def _stage_moved(self, stage_id, x, y):
        self.commandRequested.emit({"type": "move_stage", "stage_id": stage_id, "x": x, "y": y})

    def apply_species_drop(self, species_ids, stage_id, zone):
        """Translate an explicit card drop into one command without editing the snapshot."""
        if zone not in {"composition", "energy"} or not self._draft or not self._recipe:
            return False
        stage = next((item for item in self._recipe["stages"] if item["id"] == stage_id), None)
        if stage is None:
            return False
        species_by_id = {item["id"]: item for item in self._draft["network"].get("species", [])}
        identifiers = list(dict.fromkeys(species_ids))
        if not identifiers or any(identifier not in species_by_id for identifier in identifiers):
            self.dropRejected.emit(self._text("拖放内容不是当前物质库中的卡片。"))
            return False
        if zone == "composition":
            composition = deepcopy(stage.get("species", []))
            existing = {item["species_id"] for item in composition}
            for identifier in identifiers:
                if identifier not in existing:
                    composition.append({"species_id": identifier, "coefficient": 1.0})
            if composition == stage.get("species", []):
                self.dropRejected.emit(self._text("所选物质已经在该阶段组成中。"))
                return False
            self.commandRequested.emit({"type": "set_composition", "stage_id": stage_id, "species": composition})
            return True

        if stage.get("missing"):
            self.dropRejected.emit(self._text("NOT FOUND 阶段不能添加能量项。"))
            return False
        if self._recipe.get("energy_mode") == "edge_recursive":
            self.dropRejected.emit(self._text("当前使用边局部差递推；请在详情中编辑边能量项。"))
            return False
        if len(identifiers) != 1:
            self.dropRejected.emit(self._text("能量项每次只接受一张物质卡；请明确选择来源作业。"))
            return False
        species = species_by_id[identifiers[0]]
        bindings = [item for item in species.get("bindings", []) if not item.get("historical")]
        if len(bindings) != 1:
            self.dropRejected.emit(self._text("该物质卡没有唯一的当前来源作业绑定；未添加能量项。"))
            return False
        binding = bindings[0]
        terms = deepcopy(stage.get("terms", []))
        if any(term["species_id"] == species["id"] and term["source_file_id"] == binding["source_file_id"]
               and term["job_id"] == binding["job_id"] for term in terms):
            self.dropRejected.emit(self._text("该作业已是阶段能量项。"))
            return False
        terms.append({
            "species_id": species["id"], "source_file_id": binding["source_file_id"],
            "job_id": binding["job_id"], "energy_kind": self._recipe["energy_kind"],
            "coefficient": 1.0, "system_mode": "component",
            "reason": self._text("画布添加的能量项；待核对口径"), "historical": False,
        })
        self.commandRequested.emit({"type": "set_energy_terms", "stage_id": stage_id, "terms": terms})
        return True

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(SPECIES_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(SPECIES_MIME):
            scene_point = self.mapToScene(event.position().toPoint())
            stage_item = next((item for item in self._scene.items(scene_point)
                               if isinstance(item, _StageCardItem)), None)
            if stage_item and stage_item.drop_zone_at(stage_item.mapFromScene(scene_point)):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(SPECIES_MIME):
            super().dropEvent(event)
            return
        try:
            identifiers = json.loads(bytes(event.mimeData().data(SPECIES_MIME)).decode("utf-8"))
        except (ValueError, UnicodeError):
            event.ignore()
            return
        scene_point = self.mapToScene(event.position().toPoint())
        stage_item = next((item for item in self._scene.items(scene_point)
                           if isinstance(item, _StageCardItem)), None)
        zone = stage_item.drop_zone_at(stage_item.mapFromScene(scene_point)) if stage_item else None
        if stage_item and self.apply_species_drop(identifiers, stage_item.stage_id, zone):
            event.acceptProposedAction()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clearSelection()
            self._selected_stage_id = None
            event.accept()
            return
        super().keyPressEvent(event)
