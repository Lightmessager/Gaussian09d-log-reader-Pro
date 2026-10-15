"""Stable-ID table projections; sorting never mutates path positions."""
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from ..core import EnergyKind, select_job
from ..core.expressions import expression_references, render_expression
from .i18n import translate
from ..presentation.palette import get_palette

ID_ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
UNIT_LABELS = {"hartree": "Eh", "kcal_mol": "kcal/mol", "kj_mol": "kJ/mol"}
KIND_LABELS = {"gibbs_total": "Gibbs 总自由能", "scf": "SCF 电子能", "gibbs_correction": "Gibbs 热校正"}
STATE_LABELS = {"ready": "已解析", "partial": "部分可用", "failed": "导入失败", "cancelled": "已取消",
                "stale": "来源已变更", "missing": "来源未连接", "pending": "等待解析", "reading": "解析中",
                "changed": "来源已变更", "unverified": "指纹未确认", "unreadable": "无法访问", "available": "已连接"}


def _state_color(valid):
    app = QApplication.instance()
    theme = app.property("glassTheme") if app else "light"
    colors = get_palette(theme if theme in ("light", "dark") else "light")["colors"]
    return QColor(colors["success"] if valid else colors["warning"])


class SnapshotTable(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.headers = []
        self.project = None
        self.language = "zh_CN"

    def set_language(self, language):
        self.language = language
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, max(0, len(self.headers) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (role == Qt.ItemDataRole.ToolTipRole and orientation == Qt.Orientation.Horizontal
                and section == 3 and " / " in self.headers[section]):
            mode, unit = self.headers[section].split(" / ", 1)
            return f"{translate(mode, self.language)} / {unit}"
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            value = self.headers[section]
            if section == 3 and " / " in value:
                mode, unit = value.split(" / ", 1)
                if self.language == "en" and hasattr(self, "path"):
                    kind = self.path.energy_kind.value if self.path else "gibbs_total"
                    symbol = {"gibbs_total": "G", "gibbs_correction": "Gcorr", "scf": "E"}.get(kind, "E")
                    if mode == "相对能量":
                        symbol = "Δ" + symbol
                    elif mode == "能量差":
                        symbol = "Direct Δ" + symbol
                    return f"{symbol} / {unit}"
                return f"{translate(mode, self.language)} / {unit}"
            return translate(value, self.language)
        return None

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if index.isValid() else Qt.ItemFlag.NoItemFlags


class SourceProxy(QSortFilterProxyModel):
    state_filter = ""

    def set_state_filter(self, text):
        self.beginFilterChange()
        self.state_filter = text
        self.endFilterChange()

    def filterAcceptsRow(self, row, parent):
        if not super().filterAcceptsRow(row, parent):
            return False
        if not self.state_filter:
            return True
        model = self.sourceModel()
        source = model.rows[row]
        connection = model.connections.get(source.id)
        state = connection.state if connection and connection.state != "available" else source.import_state.value
        if self.state_filter == "已解析":
            return state == "ready"
        if self.state_filter == "读取失败":
            return state in ("failed", "unreadable")
        if self.state_filter == "来源":
            return state in ("changed", "unverified", "missing", "stale")
        return True


class SourceTable(SnapshotTable):
    def update(self, project, connections, kind):
        self.beginResetModel()
        self.project = project
        self.rows = list(project.source_files) if project else []
        self.connections = {c.source_file_id: c for c in connections}
        self.kind = kind
        self.headers = ["来源文件", "状态", "作业", "SCF / Eh", "Gibbs 总值 / Eh", "目录"]
        self.endResetModel()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        source = self.rows[index.row()]
        if role == ID_ROLE:
            return source.id
        refs = [ref for node in self.project.nodes for ref in expression_references(node.expression)
                if ref.source_file_id == source.id]
        job = next((j for j in source.jobs if refs and j.id == refs[0].job_id), None)
        if job is None:
            job = select_job(source, self.kind).job or select_job(source, EnergyKind.SCF).job
        connection = self.connections.get(source.id)
        state = connection.state if connection and connection.state != "available" else source.import_state.value
        def energy(kind):
            return job.energies[kind].value_hartree if job and kind in job.energies else None
        values = [source.display_name, translate(STATE_LABELS.get(state, state), self.language),
                  str(job.ordinal + 1) if job else "—", energy(EnergyKind.SCF), energy(EnergyKind.GIBBS_TOTAL),
                  str(Path(source.original_path).parent)]
        value = values[index.column()]
        if role == SORT_ROLE:
            return value
        if role == Qt.ItemDataRole.DisplayRole:
            return "—" if value is None else f"{value:.8f}" if isinstance(value, float) else value
        if role == Qt.ItemDataRole.ToolTipRole:
            detail = "\n".join(d.code for d in job.diagnostics) if job else "尚无可绑定的正常作业"
            lines = "\n".join(f"{k.value}: 行 {v.source_line} · {v.raw_text}" for k, v in job.energies.items()) if job else ""
            return f"{source.original_path}\n{STATE_LABELS.get(state, state)}\n{lines}\n{detail}"
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return _state_color(state == "ready")
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (3, 4):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class NodeTable(SnapshotTable):
    def update(self, project, path, result):
        self.beginResetModel()
        self.project, self.path, self.result = project, path, result
        nodes = {n.id: n for n in project.nodes} if project else {}
        self.rows = [(entry, nodes[entry.node_id]) for entry in path.entries] if path else []
        self.results = {n.entry_id: n for n in result.nodes} if result else {}
        unit = UNIT_LABELS.get(path.unit.value, "") if path else "kcal/mol"
        mode = "绝对能量" if path and path.calculation_mode == "absolute" else "能量差" if path and path.calculation_mode == "direct_difference" else "相对能量"
        self.headers = ["步骤", "反应节点", "体系能量 / Eh", f"{mode} / {unit}", "状态", "表达式"]
        self.endResetModel()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry, node = self.rows[index.row()]
        result = self.results.get(entry.id)
        if role == ID_ROLE:
            return node.id
        if role == ID_ROLE + 2:
            return entry.id
        state = "有效" if result and result.valid else "草稿有误" if node.expression.draft_error else "不可用" if result else "等待计算"
        absolute = result.absolute_hartree if result else None
        display = result.display_value if result and result.valid else None
        values = [entry.position + 1, node.label, absolute, display, state,
                  node.expression.draft_text if node.expression.draft_text is not None else render_expression(node.expression, self.project.alias_bindings)]
        value = translate(values[index.column()], self.language) if index.column() == 4 else values[index.column()]
        if role == SORT_ROLE:
            return value
        if role == Qt.ItemDataRole.DisplayRole:
            return "—" if value is None else (f"{value:.8f}" if index.column() == 2 else f"{value:+.3f}") if isinstance(value, float) else value
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join(d.code for d in result.diagnostics) if result and result.diagnostics else str(values[5])
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 4:
            return _state_color(bool(result and result.valid))
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (0, 2, 3):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
