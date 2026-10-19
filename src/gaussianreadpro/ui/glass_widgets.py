"""Small QPainter glass primitives; no widget-tree capture or graphics effects."""
import re

from PySide6.QtCore import Qt, QRectF, QEvent, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QFrame, QWidget, QPushButton

from ..presentation.palette import get_palette


def _appearance_defaults(theme, reduced):
    app = QApplication.instance()
    if theme is None:
        theme = app.property("glassTheme") if app else None
    if reduced is None:
        reduced = app.property("glassReducedEffects") if app else False
    return theme if theme in ("light", "dark") else "light", bool(reduced)


class GlassButton(QPushButton):
    """A bounded accent-edge transition; never applies effects to a widget tree."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        app = QApplication.instance()
        self._reduce_motion = bool(app.property("glassReduceMotion")) if app else False
        self._edge = 0.0
        self._hovered = False
        self._pressed = False
        self._transition = QVariantAnimation(self)
        self._transition.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._transition.valueChanged.connect(self._edge_changed)

    def _edge_changed(self, value):
        self._edge = float(value)
        self.update()

    def _target(self):
        if not self.isEnabled():
            return 0.0
        return 1.0 if self._pressed else .65 if self._hovered or self.hasFocus() else 0.0

    def set_reduce_motion(self, reduced):
        self._reduce_motion = bool(reduced)
        self._transition.stop()
        self._edge_changed(self._target() if self.isVisible() else 0.0)

    def _animate_edge(self, duration=140):
        self._transition.stop()
        target = self._target()
        if self._reduce_motion or not self.isVisible() or abs(self._edge-target) < .001:
            self._edge_changed(target)
            return
        self._transition.setDuration(duration)
        self._transition.setStartValue(self._edge)
        self._transition.setEndValue(target)
        self._transition.start()

    def event(self, event):
        result = super().event(event)
        if not hasattr(self, "_transition"):
            return result
        kind = event.type()
        if kind == QEvent.Type.Hide:
            self._hovered = self._pressed = False
            self._transition.stop()
            self._edge = 0.0
        elif kind in (QEvent.Type.Enter, QEvent.Type.Leave):
            self._hovered = kind == QEvent.Type.Enter
            self._animate_edge()
        elif kind in (QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.EnabledChange):
            self._animate_edge()
        return result

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._pressed = self.isDown()
        self._animate_edge(90)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._pressed = self.isDown()
        self._animate_edge(90)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._edge <= 0:
            return
        theme, _ = _appearance_defaults(None, None)
        color = QColor(get_palette(theme)["colors"]["primary"])
        color.setAlphaF(self._edge)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        painter.end()


class GlassBackdrop(QWidget):
    """Cached lavender-to-sunset ambient paint for a gallery or window background."""

    def __init__(self, theme=None, *, reduced=None, parent=None):
        super().__init__(parent)
        theme, reduced = _appearance_defaults(theme, reduced)
        self._theme = theme
        self._reduced = bool(reduced)
        self._cache = None
        self._energy_profile = False
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setObjectName("glassBackdrop")

    @property
    def reduced(self):
        return self._reduced

    def set_appearance(self, theme, reduced=False):
        if theme not in ("light", "dark"):
            raise ValueError("theme must be 'light' or 'dark'")
        if (theme, bool(reduced)) != (self._theme, self._reduced):
            self._theme, self._reduced, self._cache = theme, bool(reduced), None
            self.update()

    def set_energy_profile(self, enabled):
        enabled = bool(enabled)
        if enabled != self._energy_profile:
            self._energy_profile = enabled
            self._cache = None
            self.update()

    def resizeEvent(self, event):
        self._cache = None
        super().resizeEvent(event)

    def _background(self):
        if self._cache is not None:
            return self._cache
        palette = get_palette(self._theme)
        ratio = self.devicePixelRatioF()
        image = self._cache = QPixmap(max(1, round(self.width() * ratio)),
                                      max(1, round(self.height() * ratio)))
        image.setDevicePixelRatio(ratio)
        colors, glow = palette["colors"], palette["colors"]["glow"]
        canvas = palette["profile"]["canvas"] if self._energy_profile else colors["canvas"]
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(QRectF(0, 0, self.width(), self.height()), QColor(canvas))
        if not self._reduced and not self._energy_profile:
            first = QRadialGradient(QRectF(0, 0, self.width() * .86, self.height() * .86).center(), max(self.width(), self.height()) * .66)
            inner = QColor(glow[0]); inner.setAlpha(34)
            outer = QColor(glow[0]); outer.setAlpha(0)
            first.setColorAt(0, inner)
            first.setColorAt(1, outer)
            painter.fillRect(QRectF(0, 0, self.width(), self.height()), first)
            second = QRadialGradient(QRectF(self.width() * .24, self.height() * .20,
                                             self.width() * 1.12, self.height() * 1.12).center(), max(self.width(), self.height()) * .72)
            inner = QColor(glow[1]); inner.setAlpha(24)
            outer = QColor(glow[1]); outer.setAlpha(0)
            second.setColorAt(0, inner)
            second.setColorAt(1, outer)
            painter.fillRect(QRectF(0, 0, self.width(), self.height()), second)
        painter.end()
        return image

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._background())


class GlassPanel(QFrame):
    """Rounded surface with a restrained top highlight and a layered edge."""

    VARIANTS = {"toolbar", "surface", "elevated"}

    def __init__(self, variant="surface", theme=None, *, reduced=None, parent=None):
        if variant not in self.VARIANTS:
            raise ValueError(f"variant must be one of {sorted(self.VARIANTS)}")
        super().__init__(parent)
        theme, reduced = _appearance_defaults(theme, reduced)
        self._variant, self._theme, self._reduced = variant, theme, bool(reduced)
        self.setObjectName("glassPanel")
        self.setProperty("glassVariant", variant)
        self.setProperty("reducedEffects", self._reduced)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setContentsMargins(16, 14, 16, 14)

    @property
    def variant(self):
        return self._variant

    @property
    def reduced(self):
        return self._reduced

    def set_appearance(self, theme, reduced=False):
        if theme not in ("light", "dark"):
            raise ValueError("theme must be 'light' or 'dark'")
        self._theme, self._reduced = theme, bool(reduced)
        self.setProperty("reducedEffects", self._reduced)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        tokens = get_palette(self._theme)
        colors, metrics = tokens["colors"], tokens["metrics"]
        profile = tokens["profile"]
        chrome = self.property("profileChrome")
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = 0 if chrome in ("header", "sidebar", "transparent") else 14 if chrome == "panel" else {"toolbar": metrics["radius_toolbar"], "surface": metrics["radius_card"],
                  "elevated": metrics["radius_card"]}[self._variant]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(bounds, radius, radius)
        if self._variant == "elevated" and not self._reduced and chrome is None:
            for inset, alpha in ((5, 12), (3, 18)):
                shadow = QPainterPath()
                shadow.addRoundedRect(bounds.adjusted(0, inset, 0, inset), radius + inset, radius + inset)
                painter.fillPath(shadow, QColor(53, 34, 67, alpha))
        if chrome in ("header", "sidebar"):
            fill = QColor(profile["header" if chrome == "header" else "sidebar"])
        elif chrome == "transparent":
            fill = QColor(0, 0, 0, 0)
        elif chrome == "panel":
            raw = profile["panel"]
            match = re.fullmatch(r"rgba\((\d+),(\d+),(\d+),(0(?:\.\d+)?|1(?:\.0+)?)\)", raw)
            fill = QColor(*(int(match.group(i)) for i in (1, 2, 3)), round(float(match.group(4)) * 255)) if match else QColor(raw)
        else:
            fill = QColor(colors["surface"] if self._variant != "toolbar" else colors["toolbar"])
            opacity = metrics["glass_opacity" if self._variant != "toolbar" else "glass_toolbar_opacity"]
            fill.setAlpha(255 if self._reduced else round(255 * opacity))
        painter.fillPath(shape, fill)
        border_color = profile["border"] if chrome or self.property("profileSurface") else colors["border"]
        match = re.fullmatch(r"rgba\((\d+),(\d+),(\d+),(0(?:\.\d+)?|1(?:\.0+)?)\)", border_color)
        border = QColor(*(int(match.group(i)) for i in (1, 2, 3)), round(float(match.group(4)) * 255)) if match else QColor(border_color)
        if chrome != "transparent":
            painter.setPen(border)
            painter.drawPath(shape)
        if not self._reduced and chrome is None:
            stroke = QPainterPath()
            stroke.moveTo(bounds.left() + radius, bounds.top() + .75)
            stroke.lineTo(bounds.right() - radius, bounds.top() + .75)
            highlight = QColor(colors["highlight"])
            if self.property("profileSurface"):
                highlight.setAlpha(65)
            painter.setPen(highlight)
            painter.drawPath(stroke)
        painter.end()
