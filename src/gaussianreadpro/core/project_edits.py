"""Pure, reviewable project edits. Preview first; applying checks the base revision."""
from dataclasses import dataclass, replace
from collections.abc import Mapping

from .calculations import calculate_path
from .expressions import (draft_references, expression_from_ast, expression_references, ref_ast)
from .models import (CalculationMode, EnergyRef, ExpressionDocument, Project,
                     canonical_uuid, finite_number)


@dataclass(frozen=True)
class SourceUsage:
    node_ids: tuple[str, ...]
    reference_path_ids: tuple[str, ...]

    @property
    def in_use(self):
        return bool(self.node_ids or self.reference_path_ids)


class ReferencedSourceError(ValueError):
    def __init__(self, usage):
        self.usage = usage
        super().__init__("Source is referenced; inspect usage or explicitly request cascade")


@dataclass(frozen=True)
class ProjectChange:
    project_id: str
    base_revision: int
    project: Project
    affected_node_ids: tuple[str, ...]
    affected_path_ids: tuple[str, ...]
    removed_node_ids: tuple[str, ...] = ()
    removed_path_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if (self.project_id != self.project.id or isinstance(self.base_revision, bool)
                or not isinstance(self.base_revision, int) or self.base_revision < 0
                or self.project.revision != self.base_revision + 1):
            raise ValueError("Preview must describe one revision of the same project")
        for name in ("affected_node_ids", "affected_path_ids", "removed_node_ids", "removed_path_ids"):
            object.__setattr__(self, name, tuple(canonical_uuid(item) for item in getattr(self, name)))

    def apply(self, current):
        if current.id != self.project_id or current.revision != self.base_revision:
            raise ValueError("Project changed since preview; regenerate preview")
        return self.project

    def calculate_preview(self):
        return tuple(calculate_path(self.project, path.id) for path in self.project.paths
                     if path.id in self.affected_path_ids)


def _ids(selected, known):
    identifiers = {canonical_uuid(item) for item in selected}
    if not identifiers <= known:
        raise ValueError("Selection contains unknown identities")
    if not identifiers:
        raise ValueError("Selection must not be empty")
    return identifiers


def _change(before, after, node_ids=(), path_ids=(), removed_nodes=(), removed_paths=()):
    return ProjectChange(before.id, before.revision, replace(after, revision=before.revision + 1),
                         tuple(node_ids), tuple(path_ids), tuple(removed_nodes), tuple(removed_paths))


def _edit_nodes(project, node_ids, transform):
    selected = _ids(node_ids, {node.id for node in project.nodes})
    updated = []
    for node in project.nodes:
        if node.id in selected:
            if node.expression.draft_error is not None:
                raise ValueError("Resolve invalid drafts before a batch formula change")
            node = replace(node, expression=transform(node.expression))
        updated.append(node)
    affected_paths = [p.id for p in project.paths if any(e.node_id in selected for e in p.entries)]
    return _change(project, replace(project, nodes=tuple(updated)),
                   [n.id for n in project.nodes if n.id in selected], affected_paths)


def add_component_to_nodes(project, node_ids, ref, coefficient=1, aliases=None):
    coefficient = finite_number(coefficient)
    if not isinstance(ref, EnergyRef):
        raise TypeError("Component requires a stable EnergyRef")
    def transform(expression):
        term = ref_ast(ref) if coefficient == 1 else {"type": "binary", "op": "mul",
                "left": {"type": "scalar", "value": coefficient}, "right": ref_ast(ref)}
        return expression_from_ast({"type": "binary", "op": "add", "left": expression.ast, "right": term},
                                   aliases, purpose=expression.purpose, combination_mode=expression.combination_mode)
    return _edit_nodes(project, node_ids, transform)


def replace_node_references(project, node_ids, replacements: Mapping[EnergyRef, EnergyRef], aliases=None):
    if not replacements or any(not isinstance(a, EnergyRef) or not isinstance(b, EnergyRef)
                               for a, b in replacements.items()):
        raise ValueError("Provide exact EnergyRef replacements")
    def transform(expression):
        def visit(node):
            if node["type"] == "ref":
                original = EnergyRef(node["source_file_id"], node["job_id"], node["kind_policy"], node.get("kind"))
                return ref_ast(replacements.get(original, original))
            tree = {key: value for key, value in node.items() if key != "span"}
            if node["type"] == "binary":
                tree.update(left=visit(node["left"]), right=visit(node["right"]))
            elif node["type"] == "unary":
                tree["operand"] = visit(node["operand"])
            return tree
        return expression_from_ast(visit(expression.ast), aliases, purpose=expression.purpose,
                                   combination_mode=expression.combination_mode)
    return _edit_nodes(project, node_ids, transform)


def set_reference_for_paths(project, path_ids, reference):
    if not isinstance(reference, ExpressionDocument):
        raise TypeError("Reference must be an ExpressionDocument")
    selected = _ids(path_ids, {p.id for p in project.paths})
    for path in project.paths:
        if path.id in selected and path.calculation_mode == CalculationMode.DIRECT_DIFFERENCE:
            raise ValueError("Direct differences cannot acquire another reference")
    paths = tuple(replace(path, calculation_mode=CalculationMode.RELATIVE, reference_expression=reference)
                  if path.id in selected else path for path in project.paths)
    return _change(project, replace(project, paths=paths), path_ids=[p.id for p in project.paths if p.id in selected])


def reorder_path(project, path_id, entry_ids):
    path_id = canonical_uuid(path_id)
    path = next((p for p in project.paths if p.id == path_id), None)
    if path is None:
        raise ValueError("Unknown path")
    ids = tuple(canonical_uuid(item) for item in entry_ids)
    indexed = {entry.id: entry for entry in path.entries}
    if len(ids) != len(indexed) or set(ids) != set(indexed):
        raise ValueError("Reorder must contain each entry exactly once")
    updated = replace(path, entries=tuple(replace(indexed[item], position=i) for i, item in enumerate(ids)))
    return _change(project, replace(project, paths=tuple(updated if p.id == path_id else p for p in project.paths)),
                   path_ids=(path_id,))


def find_source_usage(project, source_ids):
    selected = {canonical_uuid(item) for item in source_ids}
    def uses(expression):
        if expression is None:
            return False
        refs = expression_references(expression) + draft_references(expression, project.alias_bindings)
        return any(ref.source_file_id in selected for ref in refs)
    return SourceUsage(tuple(node.id for node in project.nodes if uses(node.expression)),
                       tuple(path.id for path in project.paths if uses(path.reference_expression)))


def remove_sources(project, source_ids, *, cascade=False):
    selected = _ids(source_ids, {source.id for source in project.source_files})
    usage = find_source_usage(project, selected)
    if usage.in_use and not cascade:
        raise ReferencedSourceError(usage)
    removed_nodes, removed_paths = set(usage.node_ids), set(usage.reference_path_ids)
    paths, affected = [], []
    for path in project.paths:
        if path.id in removed_paths:
            continue
        entries = [e for e in path.entries if e.node_id not in removed_nodes]
        if len(entries) != len(path.entries):
            affected.append(path.id)
            path = replace(path, entries=tuple(replace(e, position=i) for i, e in enumerate(entries)))
        paths.append(path)
    after = replace(project, source_files=tuple(s for s in project.source_files if s.id not in selected),
                    nodes=tuple(n for n in project.nodes if n.id not in removed_nodes), paths=tuple(paths),
                    alias_bindings={name: ref for name, ref in project.alias_bindings.items()
                                    if ref.source_file_id not in selected})
    if "reaction_network_v1" in after.workspace_state:
        from .reaction_network import reconcile_network, write_reaction_network
        after = write_reaction_network(after, reconcile_network(after))
    return _change(project, after, usage.node_ids, affected, usage.node_ids, usage.reference_path_ids)
