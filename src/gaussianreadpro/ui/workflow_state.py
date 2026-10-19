"""Pure UX state helpers for project naming and save feedback."""
from dataclasses import dataclass
from pathlib import Path
import unicodedata
from collections.abc import Mapping
from types import MappingProxyType

from ..core.models import EnergyKind
from ..core.parser import select_job


_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_WINDOWS_ILLEGAL = set('<>:"/\\|?*')


def normalize_project_name(raw: str) -> str:
    """Return a safe filename stem, accepting one optional ``.grproj`` suffix."""
    if not isinstance(raw, str):
        raise ValueError("项目名称必须是文本。")
    name = raw.strip()
    if name.casefold().endswith(".grproj"):
        name = name[:-7]
        if name.casefold().endswith(".grproj"):
            raise ValueError("项目名称只能包含一个 .grproj 后缀。")
    if not name:
        raise ValueError("项目名称不能为空。")
    if len(name) > 120:
        raise ValueError("项目名称不能超过 120 个字符。")
    if any(unicodedata.category(char) == "Cc" for char in name):
        raise ValueError("项目名称不能包含控制字符。")
    if any(char in _WINDOWS_ILLEGAL for char in name):
        raise ValueError('项目名称不能包含 < > : " / \\ | ? *。')
    if name.endswith((" ", ".")):
        raise ValueError("项目名称不能以空格或句点结尾。")
    device = name.split(".", 1)[0].casefold()
    if device in _WINDOWS_RESERVED:
        raise ValueError("该名称是 Windows 保留设备名。")
    return name


@dataclass(frozen=True)
class SaveFeedback:
    state: str
    recovery_hint: str = ""


@dataclass(frozen=True)
class WorkflowStep:
    key: str
    state: str
    count: int = 0


@dataclass(frozen=True)
class ActionAvailability:
    enabled: bool
    reason_code: str | None
    reason_text: str


@dataclass(frozen=True)
class WorkflowSummary:
    steps: tuple[WorkflowStep, ...]
    next_action: str | None
    issue_count: int
    save_state: str
    action_availability: Mapping[str, ActionAvailability]


@dataclass(frozen=True)
class ImportSummary:
    source_count: int
    job_count: int
    energy_counts: tuple[tuple[str, int], ...]

    def available(self, energy_kind):
        return dict(self.energy_counts).get(EnergyKind(energy_kind).value, 0)


@dataclass(frozen=True)
class JobCandidate:
    source_file_id: str
    job_id: str
    source_label: str
    source_path: str
    job_ordinal: int
    termination: str
    available_energy_kinds: tuple[str, ...]


def derive_import_summary(project, *, source_ids=None) -> ImportSummary:
    """Count imported source/job and usable energy choices without reading files."""
    allowed = set(source_ids) if source_ids is not None else None
    sources = [source for source in project.source_files if allowed is None or source.id in allowed]
    jobs = [(source, job) for source in sources for job in source.jobs]
    counts = {}
    for kind in EnergyKind:
        counts[kind.value] = sum(select_job(source, kind, job_id=job.id).available
                                 for source, job in jobs)
    return ImportSummary(len(sources), len(jobs), tuple(counts.items()))


def derive_job_candidates(project):
    """Return stable, UUID-addressed job rows for an explicit candidate table."""
    rows = []
    for source in project.source_files:
        for job in source.jobs:
            kinds = tuple(kind.value for kind in EnergyKind
                          if select_job(source, kind, job_id=job.id).available)
            rows.append(JobCandidate(source.id, job.id, source.display_name,
                                     source.relative_path or source.original_path, job.ordinal,
                                     job.termination.value, kinds))
    return tuple(rows)


def derive_workflow(project, results, connections, save_status, *, active_path_id,
                    busy, read_only, path=None, workspace_dirty=False, plot_dirty=False,
                    save_failed=False) -> WorkflowSummary:
    """Derive the four stable project-workflow steps from current project state."""
    active_path = next((item for item in project.paths if item.id == active_path_id), None) if project else None
    sources = tuple(project.source_files) if project else ()
    connection_by_source = {item.source_file_id: item for item in (connections or ())}
    unavailable_project_sources = {source.id for source in sources
        if source.id not in connection_by_source or connection_by_source[source.id].state != "available"}
    source_issue_ids = {source.id for source in sources
                        if not source.jobs or source.import_state.value in {"error", "failed"}}
    source_issue_ids.update(unavailable_project_sources)
    source_issues = len(source_issue_ids)
    source_state = "pending" if not sources else "needs_attention" if source_issues else "ready"
    entries = active_path.entries if active_path else ()
    path_state = "pending" if not active_path or not entries else "ready"
    matching = next((result for result in (results or ()) if project and
                     result.project_id == project.id and result.path_id == active_path_id and
                     result.revision == project.revision), None)
    used_source_ids = ({dependency.source_file_id for node in matching.nodes
                        for dependency in (*node.dependencies, *node.reference_dependencies)}
                       if matching else set())
    unavailable_connections = {source_id for source_id in used_source_ids
                               if source_id not in connection_by_source or
                               connection_by_source[source_id].state != "available"}
    if not entries:
        check_state = "pending"
    elif matching is None:
        check_state = "pending"
    else:
        check_state = ("ready" if matching.valid and not unavailable_connections
                       else "needs_attention")
    feedback = derive_save_feedback(path=path, status=save_status,
        project_revision=project.revision if project else None,
        busy_operation="save" if busy else "", workspace_dirty=workspace_dirty,
        plot_dirty=plot_dirty, read_only=read_only, save_failed=save_failed)
    if feedback.state == "已保存":
        save_state = "ready"
    elif feedback.state in {"只读", "保存失败"}:
        save_state = "needs_attention"
    else:
        save_state = "pending"
    steps = (WorkflowStep("sources", source_state, len(sources)),
             WorkflowStep("path", path_state, len(entries)),
             WorkflowStep("check", check_state,
                          ((sum(1 for item in matching.diagnostics if item.severity.value == "error") +
                            len(unavailable_connections)) if matching else 0)),
             WorkflowStep("save", save_state, 0))
    issue_count = source_issues + steps[2].count + int(feedback.state in {"保存失败", "只读"})
    actions = {
        "import_logs": ActionAvailability(not busy and not read_only,
            "busy" if busy else "read_only" if read_only else None,
            "当前操作进行中" if busy else "只读项目不能导入来源" if read_only else ""),
        "edit_reaction_path": ActionAvailability(not busy,
            "busy" if busy else None, "当前操作进行中" if busy else ""),
        "calculate": ActionAvailability(bool(project and entries) and not busy,
            "busy" if busy else "no_path" if not entries else None,
            "当前操作进行中" if busy else "当前路径没有可计算节点" if not entries else ""),
        "show_sources": ActionAvailability(bool(project) and not busy,
            "busy" if busy else "no_project" if not project else None,
            "当前操作进行中" if busy else "尚未创建项目" if not project else ""),
        "reconnect_source": ActionAvailability(
            bool(unavailable_project_sources or unavailable_connections) and not busy and not read_only,
            "busy" if busy else "read_only" if read_only else None,
            "当前操作进行中" if busy else "只读项目不能重新定位来源" if read_only else ""),
        "save_project": ActionAvailability(bool(project) and not busy,
            "busy" if busy else "no_project" if not project else None,
            "当前操作进行中" if busy else "尚未创建项目" if not project else ""),
    }
    if unavailable_project_sources or unavailable_connections:
        next_action = "show_sources" if read_only else "reconnect_source"
    elif source_issues:
        next_action = "show_sources"
    elif not sources:
        next_action = "import_logs"
    elif not active_path or not entries:
        next_action = "edit_reaction_path"
    elif matching is None or check_state != "ready":
        next_action = "calculate"
    elif feedback.state != "已保存":
        next_action = "save_project"
    else:
        next_action = None
    if next_action is not None and not actions[next_action].enabled:
        next_action = None
    return WorkflowSummary(steps, next_action, issue_count, feedback.state,
                           MappingProxyType(actions))


def derive_save_feedback(*, path: str | Path | None, status, project_revision: int | None,
                         busy_operation: str = "", workspace_dirty: bool = False,
                         plot_dirty: bool = False, read_only: bool = False,
                         save_failed: bool = False) -> SaveFeedback:
    """Describe the main project file separately from its recovery copy."""
    revision = project_revision
    recovery_hint = ""
    if status is not None:
        if (status.recovery_error_code is not None):
            recovery_hint = "恢复副本保存失败"
        elif (revision is not None and status.recovery_revision is not None
              and status.recovery_revision >= revision):
            recovery_hint = "已保留恢复副本"

    if read_only:
        return SaveFeedback("只读", recovery_hint)
    if busy_operation == "save" or (status is not None and status.saving and busy_operation == "save_as"):
        return SaveFeedback("保存中", recovery_hint)
    if save_failed:
        return SaveFeedback("保存失败", recovery_hint)
    if path is None:
        return SaveFeedback("尚未保存", recovery_hint)
    if status is None:
        return SaveFeedback("未保存更改", recovery_hint)
    if status.error_code:
        return SaveFeedback("保存失败", recovery_hint)
    clean = not workspace_dirty and not plot_dirty
    if clean and revision is not None and status.saved_revision is not None and status.saved_revision >= revision:
        return SaveFeedback("已保存", recovery_hint)
    return SaveFeedback("未保存更改", recovery_hint)
