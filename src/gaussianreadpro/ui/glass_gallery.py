"""Visible G1 theme/component gallery and reproducible native screenshot capture."""
import argparse
import json
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..presentation.palette import get_palette
from .glass_widgets import GlassBackdrop, GlassPanel
from .theme import apply_theme

_RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def _icon(name, theme, size=22):
    allowed = set(get_palette(theme)["icons"])
    if name not in allowed or Path(name).name != name:
        raise ValueError("Unknown bundled theme icon")
    renderer = QSvgRenderer(str(_RESOURCES / "icons" / name))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid local SVG icon: {name}")
    image = QPixmap(size, size)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return QIcon(image)


class ThemeGallery(QMainWindow):
    """A small visual harness; production page layouts remain untouched in G1."""

    def __init__(self, theme="light", reduced=False):
        super().__init__()
        self._theme = theme
        self._reduced = bool(reduced)
        apply_theme(QApplication.instance(), theme, reduced=reduced)
        self.setWindowTitle("GaussianReaderPro · Liquid Glass G1 gallery")
        self.setAccessibleName("GaussianReaderPro liquid glass theme gallery")
        self.resize(1180, 800)

        self.backdrop = GlassBackdrop(theme, reduced=reduced)
        self.setCentralWidget(self.backdrop)
        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(18)

        header = GlassPanel("toolbar", theme, reduced=reduced)
        bar = QHBoxLayout(header)
        bar.setContentsMargins(12, 4, 12, 4)
        mark = QLabel("G")
        mark.setObjectName("wordmark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(42, 42)
        title = QLabel("GaussianReaderPro")
        title.setObjectName("brand")
        subtitle = QLabel("Lavender mist · Sunset glass")
        subtitle.setObjectName("muted")
        names = QVBoxLayout()
        names.setSpacing(1)
        names.addWidget(title)
        names.addWidget(subtitle)
        bar.addWidget(mark)
        bar.addLayout(names)
        bar.addStretch(1)
        for label, icon, tip in (("Sources", "file.svg", "Open source file"),
                                 ("Paths", "chart.svg", "View reaction paths"),
                                 ("Settings", "settings.svg", "Open appearance settings")):
            button = QPushButton(_icon(icon, theme, 20), label)
            button.setAccessibleName(tip)
            button.setToolTip(tip)
            bar.addWidget(button)
        self.theme_button = QPushButton("Dark preview" if theme == "light" else "Light preview")
        self.theme_button.setAccessibleName("Toggle sample theme")
        self.theme_button.clicked.connect(self.toggle_theme)
        bar.addWidget(self.theme_button)
        root.addWidget(header)

        columns = QHBoxLayout()
        columns.setSpacing(18)
        columns.addWidget(self._navigation(theme, reduced), 0)
        main = QVBoxLayout()
        main.setSpacing(14)
        eyebrow = QLabel("THEME TOKENS / COMPONENT PREVIEW")
        eyebrow.setObjectName("eyebrow")
        heading = QLabel("Reaction paths")
        heading.setObjectName("title")
        intro = QLabel("Soft lavender surfaces with warm sunset emphasis, tuned for readable research data.")
        intro.setObjectName("muted")
        main.addWidget(eyebrow)
        main.addWidget(heading)
        main.addWidget(intro)
        main.addWidget(self._toolbar(theme, reduced))
        main.addWidget(self._data_panel(theme, reduced), 1)
        main.addWidget(self._controls_panel(theme, reduced))
        columns.addLayout(main, 1)
        columns.addWidget(self._inspector(theme, reduced), 0)
        root.addLayout(columns, 1)

    @staticmethod
    def _navigation(theme, reduced):
        panel = GlassPanel("elevated", theme, reduced=reduced)
        panel.setFixedWidth(174)
        layout = QVBoxLayout(panel)
        label = QLabel("WORKSPACE")
        label.setObjectName("eyebrow")
        layout.addWidget(label)
        for title, name in (("Overview", "settings.svg"), ("Source files", "file.svg"),
                            ("Reaction paths", "chart.svg")):
            button = QPushButton(_icon(name, theme), title)
            button.setAccessibleName(f"Navigate to {title}")
            button.setCheckable(True)
            if title == "Reaction paths":
                button.setChecked(True)
            layout.addWidget(button)
        layout.addStretch(1)
        footer = QLabel("LOCAL FIRST\nOffline · Traceable · Recoverable")
        footer.setObjectName("muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        return panel

    @staticmethod
    def _toolbar(theme, reduced):
        panel = GlassPanel("toolbar", theme, reduced=reduced)
        row = QHBoxLayout(panel)
        path = QComboBox()
        path.addItems(["Path 01 · Reference: R", "Path 02 · Comparison"])
        row.addWidget(path, 1)
        add = QPushButton("＋ Import logs")
        add.setObjectName("primary")
        add.setAccessibleName("Import Gaussian log files")
        row.addWidget(add)
        return panel

    @staticmethod
    def _data_panel(theme, reduced):
        panel = GlassPanel("surface", theme, reduced=reduced)
        layout = QVBoxLayout(panel)
        header = QHBoxLayout()
        heading = QLabel("Path nodes · 4 steps")
        heading.setObjectName("section")
        state = QLabel("Saved · fingerprint verified")
        state.setObjectName("badge")
        header.addWidget(heading)
        header.addStretch(1)
        header.addWidget(state)
        layout.addLayout(header)
        table = QTableWidget(4, 4)
        table.setHorizontalHeaderLabels(["Step", "Reaction node", "System energy / Eh", "Relative / kcal/mol"])
        values = (("1", "R · Reactant", "−150.00000000", "+0.000"),
                  ("2", "TS1 · Transition state", "−149.97600000", "+15.060"),
                  ("3", "I1 · Intermediate", "−150.00800000", "−5.020"),
                  ("4", "P · Product", "−150.02500000", "−15.688"))
        for r, record in enumerate(values):
            for c, value in enumerate(record):
                item = QTableWidgetItem(value)
                if c in (0, 2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(r, c, item)
        table.selectRow(1)
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.setColumnWidth(0, 64)
        table.setColumnWidth(1, 196)
        table.setColumnWidth(2, 174)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(200)
        layout.addWidget(table, 1)
        return panel

    def _controls_panel(self, theme, reduced):
        panel = GlassPanel("toolbar", theme, reduced=reduced)
        row = QHBoxLayout(panel)
        line = QLineEdit()
        line.setPlaceholderText("Search a source, node or expression…")
        row.addWidget(line, 1)
        save = QPushButton("Save project")
        save.setObjectName("primary")
        row.addWidget(save)
        self.effects = QCheckBox("Reduce visual effects")
        self.effects.setChecked(reduced)
        self.effects.toggled.connect(lambda value: self.apply_appearance(self._theme, value))
        row.addWidget(self.effects)
        return panel

    @staticmethod
    def _inspector(theme, reduced):
        panel = GlassPanel("surface", theme, reduced=reduced)
        panel.setFixedWidth(236)
        layout = QVBoxLayout(panel)
        heading = QLabel("Node details")
        heading.setObjectName("section")
        layout.addWidget(heading)
        label = QLabel("TS1 · ΔG‡")
        label.setObjectName("muted")
        layout.addWidget(label)
        formula_title = QLabel("Expression")
        formula_title.setObjectName("muted")
        layout.addWidget(formula_title)
        formula = QLineEdit("@{TS1}")
        formula.setAccessibleName("Current node expression")
        layout.addWidget(formula)
        amount = QLabel("+15.060")
        amount.setObjectName("number")
        layout.addWidget(amount)
        unit = QLabel("kcal/mol · Relative Gibbs free energy")
        unit.setObjectName("muted")
        unit.setWordWrap(True)
        layout.addWidget(unit)
        layout.addSpacing(10)
        ok = QLabel("Valid · Job 1 · line 4")
        ok.setObjectName("statusSuccess")
        layout.addWidget(ok)
        layout.addStretch(1)
        return panel

    def apply_appearance(self, theme, reduced):
        self._theme, self._reduced = theme, bool(reduced)
        apply_theme(QApplication.instance(), theme, reduced=reduced)
        self.backdrop.set_appearance(theme, reduced)
        for panel in self.findChildren(GlassPanel):
            panel.set_appearance(theme, reduced)
        self.theme_button.setText("Dark preview" if theme == "light" else "Light preview")

    def toggle_theme(self):
        self.apply_appearance("dark" if self._theme == "light" else "light", self._reduced)


def capture_gallery(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(["gaussianreadpro-glass-gallery"])
    window = ThemeGallery()
    window.show()

    def capture():
        records = []
        for theme, reduced, name in (("light", False, "g1-light.png"),
                                     ("dark", False, "g1-dark.png"),
                                     ("light", True, "g1-reduced.png")):
            window.apply_appearance(theme, reduced)
            app.processEvents()
            path = output / name
            if not window.grab().save(str(path), "PNG"):
                raise OSError(f"Could not save native Qt screenshot: {path}")
            records.append({"theme": theme, "reduced": reduced, "screenshot": str(path.resolve()),
                            "size": [window.width(), window.height()]})
        (output / "gallery.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(records, ensure_ascii=False, indent=2))
        window.close()
        app.quit()

    QTimer.singleShot(700, capture)
    return app.exec()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Capture native light/dark/reduced screenshots and exit")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--reduced", action="store_true")
    args = parser.parse_args(argv)
    if args.output:
        return capture_gallery(args.output)
    app = QApplication.instance() or QApplication(["gaussianreadpro-glass-gallery"])
    window = ThemeGallery(args.theme, args.reduced)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
