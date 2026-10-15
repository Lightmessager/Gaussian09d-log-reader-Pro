"""Read-only, identity-safe details for the currently selected profile point."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from ..core.expressions import render_expression
from .i18n import translate
from .profile_preview import ProfilePreview
from .tables import UNIT_LABELS


def build_plot_inspector_snapshot(project, path, result, node_id, entry_id=None, source_connections=()):
    """Build an immutable-by-convention presentation snapshot from exact project IDs.

    Result values are only exposed when they belong to the current project revision,
    path, and entry. A draft, invalid calculation, or unavailable dependency never
    leaks a previous numeric value into the inspector.
    """
    if not project or not path or not node_id:
        return None
    node = next((item for item in project.nodes if item.id == node_id), None)
    if node is None:
        return None
    entry = next((item for item in path.entries
                  if item.node_id == node_id and (entry_id is None or item.id == entry_id)), None)
    if entry is None:
        return None

    is_draft = node.expression.draft_text is not None or node.expression.draft_error is not None
    current_result = bool(result and result.project_id == project.id
                          and result.revision == project.revision
                          and result.path_id == path.id
                          and result.calculation_mode == path.calculation_mode
                          and result.energy_kind == path.energy_kind
                          and result.unit == path.unit)
    value = next((item for item in result.nodes if item.entry_id == entry.id
                  and item.node_id == node_id), None) if current_result and not is_draft else None
    connections = {item.source_file_id: item for item in source_connections}
    source_files = {item.id: item for item in project.source_files}
    dependencies = []
    if value:
        for role, items in (("value", value.dependencies), ("reference", value.reference_dependencies)):
            for dependency in items:
                source = source_files.get(dependency.source_file_id)
                connection = connections.get(dependency.source_file_id)
                source_path = (getattr(connection, "path", None) if connection else None)
                source_path = source_path or (source.original_path if source else None) or (source.relative_path if source else None)
                job = next((job for job in source.jobs if job.id == dependency.job_id), None) if source else None
                dependencies.append({
                    "role": role,
                    "source_file_id": dependency.source_file_id,
                    "source_label": dependency.source_label,
                    "source_path": str(source_path or dependency.source_label),
                    "job_id": dependency.job_id,
                    "job_ordinal": job.ordinal + 1 if job else None,
                    "line": dependency.source_line,
                    "kind": dependency.kind.value,
                    "state": getattr(connection, "state", "available") if connection else "available",
                })

    source_changed = any(item["state"] not in ("available", "connected", "ready") for item in dependencies)
    is_current_value = bool(value and value.valid and value.display_value is not None and not is_draft and not source_changed)
    if is_draft:
        status = "draft"
    elif source_changed:
        status = "source_unavailable"
    elif not current_result or value is None:
        status = "pending"
    elif not is_current_value:
        status = "invalid"
    else:
        status = "valid"

    direct = path.calculation_mode.value == "direct_difference"
    expression = (node.expression.draft_text if node.expression.draft_text is not None
                  else render_expression(node.expression, project.alias_bindings))
    diagnostics = []
    if node.expression.draft_error:
        diagnostics.append(node.expression.draft_error.code)
    if value and status in ("invalid", "source_unavailable"):
        diagnostics.extend(item.code for item in value.diagnostics)
        if result:
            diagnostics.extend(item.code for item in result.diagnostics)
    return {
        "project_id": project.id,
        "revision": project.revision,
        "path_id": path.id,
        "entry_id": entry.id,
        "node_id": node.id,
        "path_label": path.label,
        "node_label": node.label,
        "role": node.role.value,
        "step": entry.position + 1,
        "mode": path.calculation_mode.value,
        "unit": path.unit.value,
        "status": status,
        "expression": expression,
        "value": value.display_value if is_current_value else None,
        "absolute_hartree": value.absolute_hartree if is_current_value and not direct else None,
        "reference_hartree": value.reference_hartree if is_current_value and path.calculation_mode.value == "relative" else None,
        "direct_difference": direct,
        "diagnostics": tuple(dict.fromkeys(diagnostics)),
        "sources": tuple(dependencies),
    }


class PlotInspector(QWidget):
    """Read-only scientific summary, source trace, and compact 2D path overview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("plotInspector")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("section")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setObjectName("inspectorSummary")
        layout.addWidget(self.summary)
        self.energy = QLabel("—")
        self.energy.setObjectName("inspectorEnergy")
        self.energy.setTextFormat(Qt.TextFormat.PlainText)
        self.energy.setWordWrap(True)
        layout.addWidget(self.energy)
        self.preview_title = QLabel()
        self.preview_title.setObjectName("muted")
        layout.addWidget(self.preview_title)
        self.preview = ProfilePreview()
        self.preview.setMinimumHeight(180)
        self.preview.setMaximumHeight(220)
        self.preview.setAccessibleName("2D energy profile overview / 二维能量剖面概览")
        layout.addWidget(self.preview)
        self.source_title = QLabel()
        self.source_title.setObjectName("muted")
        layout.addWidget(self.source_title)
        self.sources = QPlainTextEdit()
        self.sources.setObjectName("inspectorSources")
        self.sources.setReadOnly(True)
        self.sources.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.sources.setMaximumHeight(116)
        self.sources.setPlaceholderText("—")
        layout.addWidget(self.sources)
        layout.addStretch(1)
        self._snapshot = None
        self.set_language("zh_CN")

    @property
    def snapshot(self):
        return self._snapshot

    def set_language(self, language):
        self.language = language
        self.title.setText(translate("选中节点摘要", language))
        self.source_title.setText(translate("来源证据", language))
        self.preview_title.setText(translate("能量概览", language))
        self.preview.set_language(language)
        self._render()

    def set_theme(self, dark):
        self.preview.set_theme(dark)

    def set_snapshot(self, snapshot, project=None, path=None, result=None):
        self._snapshot = snapshot
        self.preview.set_data(project, path, result, snapshot.get("node_id") if snapshot else None)
        self._render()

    def _render(self):
        snapshot = self._snapshot
        if not snapshot:
            self.energy.setText("—")
            self.energy.setToolTip("")
            self.summary.setText(translate("选择图表节点以查看摘要", self.language))
            self.sources.setPlainText(translate("尚无来源证据", self.language))
            return
        en = self.language == "en"
        status = {
            "valid": "有效" if not en else "Valid",
            "invalid": "无效" if not en else "Invalid",
            "draft": "草稿未验证" if not en else "Unvalidated draft",
            "source_unavailable": "来源已变化或不可用" if not en else "Source changed or unavailable",
            "pending": "等待当前计算" if not en else "Waiting for current calculation",
        }.get(snapshot["status"], snapshot["status"])
        role_key = {"unspecified": "未指定", "reactant": "反应物", "intermediate": "中间体",
                    "transition_state": "过渡态", "product": "产物"}.get(snapshot["role"], snapshot["role"])
        role = translate(role_key, self.language)
        lines = [
            f"{snapshot['path_label']} · {snapshot['node_label']}  [{role}]",
            f"{translate('步骤', self.language)} {snapshot['step']} · {status}",
        ]
        if snapshot["value"] is not None:
            label = "Direct difference" if en and snapshot["direct_difference"] else "直接差值" if snapshot["direct_difference"] else "Energy"
            if not en and not snapshot["direct_difference"]:
                label = "当前能量"
            self.energy.setText(f"{snapshot['value']:+.3f} {UNIT_LABELS[snapshot['unit']]}")
            self.energy.setToolTip(f"{label}: {snapshot['value']:+.10g} {UNIT_LABELS[snapshot['unit']]}")
            if snapshot["absolute_hartree"] is not None:
                lines.append(f"{translate('体系能量', self.language)}: {snapshot['absolute_hartree']:.10f} Eh")
            if snapshot["reference_hartree"] is not None:
                lines.append(f"{translate('参考能量', self.language)}: {snapshot['reference_hartree']:.10f} Eh")
        else:
            self.energy.setText("—")
            self.energy.setToolTip("")
            if snapshot["diagnostics"]:
                lines.append(("Diagnostics: " if en else "诊断：") + " · ".join(snapshot["diagnostics"]))
        self.summary.setText("\n".join(lines))
        source_lines = []
        for source in snapshot["sources"]:
            role = ("reference" if en else "参考") if source["role"] == "reference" else ("value" if en else "数值")
            ordinal = f" · job {source['job_ordinal']}" if en and source["job_ordinal"] else f" · 作业 {source['job_ordinal']}" if source["job_ordinal"] else f" · {source['job_id'][:8]}"
            name = Path(source["source_path"]).name
            source_lines.append(f"{role} · {name}{ordinal} · line {source['line']}" if en
                                else f"{role} · {name}{ordinal} · 第 {source['line']} 行")
        self.sources.setToolTip("\n".join(dict.fromkeys(source["source_path"] for source in snapshot["sources"])))
        self.sources.setPlainText("\n".join(dict.fromkeys(source_lines)) if source_lines
                                  else translate("此节点没有可定位的来源依赖", self.language))
