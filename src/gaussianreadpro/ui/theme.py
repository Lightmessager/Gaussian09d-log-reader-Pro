"""Application palette and QSS generated from the shared lavender/sunset tokens."""
from PySide6.QtGui import QColor, QFont, QPalette, QStyleHints
import re

from ..presentation.palette import get_palette

INK = "#292137"
MUTED = "#6E627D"
ACCENT = "#7450AF"


def _qcolor(value):
    match = re.fullmatch(r"rgba\((\d+),(\d+),(\d+),(0(?:\.\d+)?|1(?:\.0+)?)\)", value)
    if match:
        red, green, blue = (int(match.group(i)) for i in (1, 2, 3))
        return QColor.fromRgb(red, green, blue, round(float(match.group(4)) * 255))
    return QColor(value)


def _stylesheet(c, m, reduced, profile=None):
    c = dict(c)
    for key in ("glass_fill", "glass_toolbar", "overlay"):
        match = re.fullmatch(r"rgba\((\d+),(\d+),(\d+),(0(?:\.\d+)?|1(?:\.0+)?)\)", c[key])
        if match:
            r, g, b = (int(match.group(i)) for i in (1, 2, 3))
            a = round(float(match.group(4)) * 255)
            c[key] = f"rgba({r},{g},{b},{a})"
    card = c["surface"] if reduced else c["glass_fill"]
    toolbar = c["elevated"] if reduced else c["glass_toolbar"]
    profile = dict(profile or {})
    for key, value in tuple(profile.items()):
        match = re.fullmatch(r"rgba\((\d+),(\d+),(\d+),(0(?:\.\d+)?|1(?:\.0+)?)\)", value)
        if match:
            r, g, b = (int(match.group(i)) for i in (1, 2, 3))
            profile[key] = f"rgba({r},{g},{b},{round(float(match.group(4)) * 255)})"
    return f"""
QMainWindow, QWidget#root {{ background:{c['canvas']}; color:{c['text']}; }}
QWidget {{ color:{c['text']}; font-size:{m['font_body']}px; }}
QFrame#topbar {{ background:{toolbar}; border:1px solid {c['highlight']}; border-bottom:1px solid {c['border']}; border-radius:{m['radius_toolbar']}px; }}
QLabel#brand {{ color:{c['primary']}; font-size:19px; font-weight:700; }}
QLabel#wordmark {{ background:{c['primary']}; color:{c['surface']}; border-radius:12px; font-size:23px; font-weight:700; }}
QLabel#muted {{ color:{c['muted']}; }}
QLabel#eyebrow {{ color:{c['primary']}; font-size:{m['font_small']}px; font-weight:700; letter-spacing:1px; }}
QLabel#title {{ color:{c['text']}; font-size:{m['font_heading']}px; font-weight:700; }}
QLabel#section {{ color:{c['text']}; font-size:16px; font-weight:650; }}
QLabel#number {{ color:{c['primary']}; font-size:25px; font-weight:650; }}
QLabel#badge {{ background:{c['primary_soft']}; color:{c['primary']}; padding:6px 11px; border:1px solid {c['border_soft']}; border-radius:{m['radius_badge']}px; font-size:{m['font_small']}px; }}
QFrame#card {{ background:{card}; border:1px solid {c['highlight']}; border-bottom-color:{c['border']}; border-radius:{m['radius_card']}px; }}
QFrame#sidebar {{ background:{c['navigation']}; border:1px solid {c['highlight']}; border-radius:{m['radius_card']}px; }}
QFrame#sidebar QLabel {{ color:{c['navigation_text']}; font-size:{m['font_small']}px; }}
QListWidget#navigation {{ background:transparent; border:0; outline:0; color:{c['navigation_text']}; }}
QListWidget#navigation::item {{ padding:11px 8px; margin:3px 6px; border:1px solid transparent; border-radius:12px; color:{c['navigation_text']}; }}
QListWidget#navigation[compact="true"]::item {{ padding:7px 1px; margin:3px 2px; }}
QListWidget#navigation::item:selected {{ background:{c['primary_soft']}; border-left:3px solid {c['primary']}; color:{c['selection_text']}; font-weight:600; }}
QListWidget#navigation::item:hover {{ background:{c['field_hover']}; }}
QPushButton {{ background:{c['surface']}; color:{c['text']}; border:1px solid {c['border']}; border-bottom-color:{c['muted']}; border-radius:{m['radius_control']}px; padding:7px 13px; min-height:{m['control_height'] - 16}px; }}
QPushButton:hover {{ background:{c['field_hover']}; border-color:{c['primary']}; }}
QPushButton:focus {{ border:2px solid {c['primary']}; padding:6px 12px; }}
QPushButton:pressed {{ background:{c['primary_soft']}; border-color:{c['primary']}; }}
QPushButton:checked {{ background:{c['primary_soft']}; color:{c['selection_text']}; border-color:{c['primary']}; }}
QPushButton:disabled {{ color:{c['disabled']}; background:{c['surface']}; border-color:{c['border_soft']}; }}
QPushButton#primary {{ background:{c['sunset']}; color:{c['on_sunset']}; border:1px solid {c['sunset']}; font-weight:650; }}
QPushButton#primary:hover {{ background:{c['sunset']}; border-color:{c['on_sunset']}; }}
QPushButton#primary:disabled {{ color:{c['muted']}; background:{c['border_soft']}; border-color:{c['border_soft']}; }}
QPushButton#quiet {{ background:transparent; border:0; color:{c['muted']}; padding:4px 8px; }}
QPushButton#profileDimension {{ background:transparent; border:1px solid {c['border_soft']}; border-radius:7px; min-width:32px; padding:6px 9px; font-weight:600; }}
QPushButton#profileDimension:checked {{ background:{c['primary_soft']}; border-color:{c['lavender']}; color:{c['selection_text']}; }}
QLabel#inspectorEnergy {{ color:{c['sunset']}; font-size:23px; font-weight:650; padding:8px 0; }}
QToolButton {{ background:{c['surface']}; color:{c['text']}; border:1px solid {c['border']}; border-bottom-color:{c['muted']}; border-radius:{m['radius_control']}px; padding:6px 10px; min-height:{m['control_height'] - 16}px; }}
QToolButton:hover {{ background:{c['field_hover']}; border-color:{c['primary']}; }}
QToolButton:focus {{ border:2px solid {c['primary']}; padding:5px 9px; }}
QToolButton:pressed, QToolButton:checked {{ background:{c['primary_soft']}; border-color:{c['primary']}; }}
QToolButton:disabled {{ color:{c['disabled']}; background:{c['surface']}; border-color:{c['border_soft']}; }}
QLineEdit, QComboBox, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{ background:{c['field']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:{m['radius_control']}px; padding:7px 9px; selection-background-color:{c['primary']}; selection-color:{c['surface']}; min-height:{m['control_height'] - 16}px; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border:2px solid {c['primary']}; padding:6px 8px; }}
QComboBox::drop-down {{ border:0; width:24px; }}
QComboBox QAbstractItemView {{ background:{c['overlay']}; color:{c['text']}; border:1px solid {c['border']}; selection-background-color:{c['primary_soft']}; selection-color:{c['selection_text']}; padding:4px; outline:0; }}
QMenu {{ background:{c['overlay']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:12px; padding:5px; }}
QMenu::item {{ padding:7px 24px 7px 10px; border-radius:7px; }}
QMenu::item:selected {{ background:{c['primary_soft']}; color:{c['selection_text']}; }}
QDialog {{ background:{c['canvas']}; color:{c['text']}; }}
QTabWidget::pane {{ background:{c['surface']}; border:1px solid {c['border']}; border-radius:12px; top:-1px; }}
QTabBar::tab {{ background:{c['navigation']}; color:{c['muted']}; border:1px solid {c['border']}; border-radius:9px; padding:7px 12px; margin:2px; }}
QTabBar::tab:selected {{ background:{c['primary_soft']}; color:{c['selection_text']}; }}
QTableView {{ background:{c['surface']}; alternate-background-color:{c['field_hover']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:12px; gridline-color:{c['border_soft']}; selection-background-color:{c['primary_soft']}; selection-color:{c['selection_text']}; outline:0; }}
QTableView::item {{ padding:7px 10px; border-bottom:1px solid {c['border_soft']}; }}
QTableView::item:selected {{ background:{c['primary_soft']}; color:{c['selection_text']}; }}
QHeaderView::section {{ background:{c['navigation']}; color:{c['muted']}; padding:10px 9px; border:0; border-bottom:1px solid {c['border']}; font-size:{m['font_small']}px; font-weight:600; }}
QSplitter::handle {{ background:transparent; }}
QSplitter::handle:hover {{ background:{c['primary_soft']}; }}
QScrollArea {{ background:transparent; border:0; }}
QScrollBar:vertical, QScrollBar:horizontal {{ background:transparent; width:9px; height:9px; margin:1px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background:{c['border']}; border-radius:4px; min-height:25px; min-width:25px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
QProgressBar {{ background:{c['border_soft']}; border:0; border-radius:4px; max-height:7px; min-height:7px; text-align:center; color:{c['text']}; }}
QProgressBar::chunk {{ background:{c['primary']}; border-radius:4px; }}
QLabel#error {{ background:{c['surface']}; color:{c['danger']}; padding:9px 14px; border:1px solid {c['danger']}; border-radius:10px; }}
QLabel#statusSuccess {{ color:{c['success']}; }}
QLabel#statusWarning {{ color:{c['warning']}; }}
QLabel#statusDanger {{ color:{c['danger']}; }}
QStatusBar {{ background:{toolbar}; border-top:1px solid {c['border']}; color:{c['muted']}; }}
QToolTip {{ background:{c['overlay']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:8px; padding:6px 8px; }}
QFrame#glassPanel {{ background:transparent; border:0; }}
QFrame#topbar, QFrame#sidebar {{ background:transparent; border:0; }}
QListWidget#recentProjects {{ background:transparent; border:0; outline:0; }}
QListWidget#recentProjects::item {{ padding:9px 11px; margin:2px 0; border:1px solid transparent; border-radius:9px; }}
QListWidget#recentProjects::item:hover {{ background:{c['field_hover']}; }}
QListWidget#recentProjects::item:selected {{ background:{c['primary_soft']}; color:{c['selection_text']}; border-color:{c['border']}; }}
QListWidget#speciesLibrary, QListWidget#batchTargets {{ background:{c['field']}; border:1px solid {c['border_soft']}; border-radius:10px; outline:0; }}
QListWidget#speciesLibrary::item, QListWidget#batchTargets::item {{ padding:8px 9px; margin:2px 4px; border:1px solid transparent; border-radius:8px; }}
QListWidget#speciesLibrary::item:hover, QListWidget#batchTargets::item:hover {{ background:{c['field_hover']}; }}
QListWidget#speciesLibrary::item:selected, QListWidget#batchTargets::item:selected {{ background:{c['primary_soft']}; color:{c['selection_text']}; border-color:{c['primary']}; }}
QTableWidget#componentTable {{ background:{c['field']}; alternate-background-color:{c['field_hover']}; border:1px solid {c['border_soft']}; border-radius:9px; selection-background-color:{c['primary_soft']}; selection-color:{c['selection_text']}; }}
QTableWidget#componentTable::item {{ padding:4px 5px; border-bottom:1px solid {c['border_soft']}; }}
QPlainTextEdit#expertExpression, QPlainTextEdit#expressionPreview, QPlainTextEdit#batchPreview {{ background:{c['field']}; border:1px solid {c['border_soft']}; border-radius:10px; padding:10px; }}
QLabel#builderNotice {{ background:{c['navigation']}; color:{c['muted']}; border:1px solid {c['border_soft']}; border-radius:9px; padding:8px 10px; }}
QLabel#editorDiagnostics {{ background:{c['field']}; color:{c['muted']}; border:1px solid {c['border_soft']}; border-radius:9px; padding:7px 10px; }}
QLabel#editorDiagnostics[status="valid"] {{ color:{c['success']}; border-color:{c['border']}; }}
QLabel#editorDiagnostics[status="error"] {{ color:{c['danger']}; border-color:{c['danger']}; background:{c['field_hover']}; }}
QLabel#batchSelectionSummary {{ color:{c['primary']}; background:{c['primary_soft']}; border:1px solid {c['border']}; border-radius:8px; padding:7px 9px; }}
QWidget#root {{ background:{profile.get('canvas', c['canvas'])}; }}
QFrame#topbar {{ background:{profile.get('header', toolbar)}; border:0; border-bottom:1px solid {profile.get('border', c['border'])}; border-radius:0; }}
QFrame#sidebar {{ background:{profile.get('sidebar', c['navigation'])}; border:0; border-right:1px solid {profile.get('border', c['border'])}; border-radius:0; }}
QFrame#sidebar QLabel {{ color:{profile.get('muted', c['muted'])}; }}
QListWidget#navigation {{ color:{profile.get('muted', c['muted'])}; font-size:14px; }}
QListWidget#navigation::item {{ border-radius:10px; margin:3px 7px; padding:10px 0px 10px 10px; }}
QListWidget#navigation::item:selected {{ background:{profile.get('panel_highlight', c['primary_soft'])}; border-left:3px solid {profile.get('focus', c['sunset'])}; color:{profile.get('text', c['text'])}; }}
QFrame#profileChart {{ background:transparent; border:0; border-radius:0; }}
QFrame#profileInspector {{ background:{profile.get('panel', c['glass_fill'])}; border:1px solid {profile.get('border', c['border'])}; border-radius:16px; }}
QFrame#profileToolbar {{ background:{profile.get('panel', c['glass_toolbar'])}; border:1px solid {profile.get('border', c['border'])}; border-radius:14px; }}
QPushButton#profileDimension {{ color:{profile.get('muted', c['muted'])}; border:1px solid transparent; min-width:54px; min-height:30px; padding:5px 12px; }}
QPushButton#profileDimension:checked {{ background:{profile.get('panel_highlight', c['primary_soft'])}; color:{profile.get('text', c['text'])}; border-color:{profile.get('focus', c['primary'])}; }}
QFrame#profileInspector QLabel {{ color:{profile.get('text', c['text'])}; }}
QLabel#brand {{ color:{profile.get('text', c['text'])}; font-size:20px; font-weight:600; }}
QLabel#headerPage {{ color:{profile.get('axis', c['muted'])}; font-size:18px; }}
QPushButton#shellAction {{ background:transparent; border:0; border-radius:6px; font-size:14px; padding:6px 12px; min-height:24px; }}
QPushButton#shellAction:hover {{ background:{profile.get('panel_highlight', c['primary_soft'])}; }}
"""


def _apply_palette(app, c):
    palette = app.palette()
    mapping = {
        QPalette.ColorRole.Window: "canvas", QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "surface", QPalette.ColorRole.AlternateBase: "field_hover",
        QPalette.ColorRole.Text: "text", QPalette.ColorRole.Button: "surface",
        QPalette.ColorRole.ButtonText: "text", QPalette.ColorRole.Highlight: "primary",
        QPalette.ColorRole.HighlightedText: "surface", QPalette.ColorRole.ToolTipBase: "overlay",
        QPalette.ColorRole.ToolTipText: "text", QPalette.ColorRole.Mid: "muted",
    }
    for role, token in mapping.items():
        palette.setColor(role, _qcolor(c[token]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["disabled"]))
    app.setPalette(palette)


def apply_theme(app, theme="light", *, reduced=False, reduce_motion=False):
    """Apply a shared theme while preserving the historical bool return contract."""
    font = QFont()
    font.setFamilies(["Segoe UI", "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", "sans-serif"])
    font.setPointSize(10)
    app.setFont(font)
    system_dark = app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    try:
        scheme = app.styleHints().colorScheme()
        if scheme == QStyleHints.ColorScheme.Dark:
            system_dark = True
        elif scheme == QStyleHints.ColorScheme.Light:
            system_dark = False
    except (AttributeError, TypeError):
        pass
    app.setStyle("Fusion")
    dark = theme == "dark" or theme == "system" and system_dark
    tokens = get_palette("dark" if dark else "light")
    _apply_palette(app, tokens["colors"])
    app.setStyleSheet(_stylesheet(tokens["colors"], tokens["metrics"], reduced, tokens["profile"]))
    app.setProperty("glassTheme", "dark" if dark else "light")
    app.setProperty("glassReducedEffects", bool(reduced))
    app.setProperty("glassReduceMotion", bool(reduce_motion))
    from .glass_widgets import GlassBackdrop, GlassPanel, GlassButton
    for widget in app.allWidgets():
        if isinstance(widget, (GlassBackdrop, GlassPanel)):
            widget.set_appearance("dark" if dark else "light", reduced)
        elif isinstance(widget, GlassButton):
            widget.set_reduce_motion(reduce_motion)
    return dark
