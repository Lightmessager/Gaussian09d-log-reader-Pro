"""Pure draft and legacy-path adapters used by the reaction builder UI."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from collections.abc import Mapping
import json
import re
from typing import ClassVar

from ..core.expressions import expression_references
from ..core.models import (CalculationMode, CombinationMode, EnergyKind, EnergyRef,
                           ExpressionPurpose, KindPolicy, Unit, canonical_uuid, finite_number, new_id)
from ..core.parser import select_job
from ..core.reaction_network import (empty_network, parse_molecular_formula,
                                     read_reaction_network, reference_signature,
                                     validate_network)


_ROLES = {"reactant", "intermediate", "transition_state", "product", "unspecified"}


@dataclass(frozen=True)
class LegacyConversionPreview:
    """An unapplied, validated network proposal for one supported old path."""

    network: dict
    path_id: str
    source_path_id: str
    identity_policy: str
    reference_policy_changed: bool
    reference_policy_text: str
    zero_stage_id: str


@dataclass
class BuilderDraft:
    """Project snapshot plus a classification of the path the editor opened."""

    base_project_id: str
    base_revision: int
    path_id: str
    network: dict
    layout: dict
    path_options: dict
    legacy_mode: str
    legacy_reason: str = ""
    generation: int = 0
    source_job_ids: frozenset[tuple[str, str]] = field(default_factory=frozenset, repr=False)
    path_energy_kind: str = EnergyKind.GIBBS_TOTAL.value
    _undo_states: list[tuple[dict, dict, dict]] = field(default_factory=list, repr=False)
    _redo_states: list[tuple[dict, dict, dict]] = field(default_factory=list, repr=False)

    _COMMAND_KEYS: ClassVar[dict[str, set[str]]] = {
        "add_species": {"type", "species"},
        "update_species": {"type", "species_id", "fields"},
        "remove_species": {"type", "species_id"},
        "set_star": {"type", "species_id", "starred"},
        "add_stage": {"type", "stage"},
        "update_stage": {"type", "stage_id", "fields"},
        "remove_stage": {"type", "stage_id"},
        "set_composition": {"type", "stage_id", "species"},
        "set_energy_terms": {"type", "stage_id", "terms"},
        "add_connection": {"type", "connection"},
        "update_connection": {"type", "connection_id", "fields"},
        "remove_connection": {"type", "connection_id"},
        "set_zero": {"type", "zero_point"},
        "set_path_options": {"type", "path_options"},
        "move_stage": {"type", "stage_id", "x", "y"},
    }

    @classmethod
    def from_project(cls, project, path_id):
        path = next((item for item in project.paths if item.id == path_id), None)
        if path is None:
            raise ValueError("Builder path does not belong to this project")
        network = deepcopy(read_reaction_network(project))
        recipe = next((item for item in network["path_reactions"]
                       if item["path_id"] == path_id), None)
        ux_v2 = project.workspace_state.get("ux_v2", {})
        layouts = ux_v2.get("builder_layouts", {}) if isinstance(ux_v2, Mapping) else {}
        raw_layout = layouts.get(path_id, {}) if isinstance(layouts, Mapping) else {}
        known_stage_ids = {item["id"] for item in recipe["stages"]} if recipe else set()
        layout = cls._sanitize_layout(raw_layout, known_stage_ids)
        path_options = {"label": path.label, "unit": path.unit.value, "color": path.color}
        source_job_ids = frozenset((source.id, job.id) for source in project.source_files
                                   for job in source.jobs)

        def make_draft(mode, reason=""):
            return cls(project.id, project.revision, path_id, network, deepcopy(layout),
                       deepcopy(path_options), mode, reason, source_job_ids=source_job_ids,
                       path_energy_kind=path.energy_kind.value)

        if recipe is not None:
            return make_draft("existing_recipe")
        if not path.entries:
            return make_draft("empty")
        if path.reference_expression is not None and path.reference_expression.draft_error:
            return make_draft("legacy_invalid", "路径零点包含尚未完成或无效的表达式草稿。")
        if path.calculation_mode == CalculationMode.DIRECT_DIFFERENCE:
            return make_draft("legacy_expert", "该路径使用直接差值，不能转换为体系能量阶段；可继续使用专家表达式，或选择作业另建相对能量路径并明确零点。")
        if path.calculation_mode != CalculationMode.RELATIVE:
            return make_draft("legacy_expert", "该路径使用绝对能量，没有可无损沿用的旧零点；不能原位转换。可继续使用专家表达式，或选择作业另建相对能量路径并明确零点。")
        if len({entry.node_id for entry in path.entries}) != len(path.entries):
            return make_draft("legacy_expert", "同一计算节点在路径中重复引用，不能无损映射为独立阶段；可用专家表达式或另选作业创建新路径。")

        nodes = {node.id: node for node in project.nodes}
        sources = {source.id: source for source in project.source_files}
        for entry in path.entries:
            node = nodes.get(entry.node_id)
            if node is None:
                return make_draft("legacy_invalid", "路径点引用的计算节点不存在。")
            expression = node.expression
            if expression.draft_error or expression.ast is None:
                return make_draft("legacy_invalid", "存在尚未完成或无效的表达式草稿。")
            if (expression.purpose != ExpressionPurpose.SYSTEM or
                    expression.combination_mode != CombinationMode.STANDARD or
                    expression.ast.get("type") != "ref"):
                return make_draft("legacy_expert", "该路径包含直接差值、组合表达式或复杂 AST；请继续使用专家表达式。")
            refs = expression_references(expression)
            if len(refs) != 1 or not isinstance(refs[0], EnergyRef):
                return make_draft("legacy_expert", "表达式无法无损转换为单个来源作业。")
            ref = refs[0]
            source = sources.get(ref.source_file_id)
            job = next((item for item in source.jobs if item.id == ref.job_id), None) if source else None
            if source is None or job is None:
                return make_draft("legacy_expert", "表达式引用了当前项目中不存在的来源或作业。")
            if ref.kind_policy == KindPolicy.FIXED and ref.kind != path.energy_kind:
                return make_draft("legacy_expert", "固定能量类型与当前路径类型不同，无法保证原值语义。")

        return make_draft("legacy_supported")

    @classmethod
    def _sanitize_layout(cls, layout, known_stage_ids):
        if not isinstance(layout, Mapping):
            return {}
        positions = layout.get("stages", {})
        if not isinstance(positions, Mapping):
            return {}
        cleaned = {}
        for identifier, point in positions.items():
            if not isinstance(identifier, str) or identifier not in known_stage_ids:
                continue
            try:
                if canonical_uuid(identifier) != identifier:
                    continue
                if not isinstance(point, Mapping) or set(point) != {"x", "y"}:
                    continue
                x, y = finite_number(point["x"]), finite_number(point["y"])
            except (TypeError, ValueError, AttributeError):
                continue
            if abs(x) <= 100000 and abs(y) <= 100000:
                cleaned[identifier] = {"x": x, "y": y}
        return {"stages": cleaned} if cleaned else {}

    def conversion_preview(self, project, *, roles, confirmed_compositions,
                           accept_reference_policy=False, formulas=None, target_path=None):
        """Build a conversion proposal without changing ``project`` or its network."""
        if project.id != self.base_project_id or project.revision != self.base_revision:
            raise ValueError("Project changed after the legacy path draft was opened")
        if self.legacy_mode != "legacy_supported":
            raise ValueError(self.legacy_reason or "This legacy path cannot be converted in place")
        path = next((item for item in project.paths if item.id == self.path_id), None)
        if path is None:
            raise ValueError("Legacy path no longer exists")
        if target_path is None and path.calculation_mode != CalculationMode.RELATIVE:
            raise ValueError("In-place conversion requires a relative-energy path")
        if target_path is not None:
            if any(item.id == target_path.id for item in project.paths):
                raise ValueError("New conversion path UUID already exists")
            if target_path.energy_kind != path.energy_kind or target_path.calculation_mode != CalculationMode.RELATIVE:
                raise ValueError("A new conversion path must use the legacy energy kind and relative mode")

        nodes = {node.id: node for node in project.nodes}
        refs_by_entry = {}
        for entry in path.entries:
            node = nodes[entry.node_id]
            refs_by_entry[entry.id] = expression_references(node.expression)[0]
        old_node_ids = {entry.node_id for entry in path.entries}
        shared_nodes = {entry.node_id for other in project.paths if other.id != path.id
                        for entry in other.entries}
        if target_path is None and len(old_node_ids) != len(path.entries):
            raise ValueError("Repeated node entries require creating a new path before conversion")
        if target_path is None and old_node_ids & shared_nodes:
            raise ValueError("Shared nodes require creating a new path before conversion")

        matching_zero = [entry for entry in path.entries
                         if path.reference_expression is not None and
                         reference_signature(nodes[entry.node_id].expression) ==
                         reference_signature(path.reference_expression)]
        if len(matching_zero) != 1:
            raise ValueError("In-place conversion requires a zero expression matching exactly one existing node")
        if not accept_reference_policy:
            raise ValueError("Confirm the conversion from the old reference policy to a fixed path energy kind")
        if not isinstance(roles, Mapping) or not isinstance(confirmed_compositions, (set, frozenset, list, tuple)):
            raise ValueError("Select a role and confirm the composition for every old node")

        role_values = dict(roles)
        confirmed = set(confirmed_compositions)
        if set(role_values) != old_node_ids or not old_node_ids <= confirmed:
            raise ValueError("Select a role and confirm the composition for every old node")
        if any(role not in _ROLES for role in role_values.values()):
            raise ValueError("Every legacy stage needs an explicitly selected role")

        formula_values = dict(formulas or {})
        network = deepcopy(self.network)
        stages = []
        refs = list(refs_by_entry.values())
        policy_changed = any(ref.kind_policy == KindPolicy.FOLLOW_PATH for ref in refs)
        for entry in path.entries:
            node = nodes[entry.node_id]
            ref = refs_by_entry[entry.id]
            source = next(source for source in project.source_files if source.id == ref.source_file_id)
            job = next(job for job in source.jobs if job.id == ref.job_id)
            species_id, stage_id = new_id(), new_id()
            formula = formula_values.get(node.id, "").strip()
            if formula:
                parse_molecular_formula(formula)
            network["species"].append({"id": species_id, "name": node.label or f"作业 {job.ordinal + 1}",
                "formula": formula, "starred": False, "bindings": [{
                    "source_file_id": source.id, "job_id": job.id, "historical": False}]})
            kind = path.energy_kind.value
            stages.append({"id": stage_id, "role": role_values[node.id], "label": node.label or f"作业 {job.ordinal + 1}",
                "predecessor_stage_id": None, "predecessor_stage_ids": [],
                "species": [{"species_id": species_id, "coefficient": 1.0}],
                "terms": [{"species_id": species_id, "source_file_id": source.id, "job_id": job.id,
                    "energy_kind": kind, "coefficient": 1.0, "system_mode": "complete_system",
                    "reason": "旧单引用表达式；已确认固定为当前路径能量类型", "historical": False}],
                "confirm_additional_terms": False, "node_id": node.id, "entry_id": entry.id,
                "historical": False, "missing": False, "normalization_confirmed": True,
                "normalization_note": "已逐项核对该旧节点对应的单物质组成"})

        zero_entry = matching_zero[0]
        zero_stage = next(stage for stage in stages if stage["node_id"] == zero_entry.node_id)
        zero_kind = "reactant" if zero_stage["role"] == "reactant" else "stage"
        target_id = target_path.id if target_path is not None else path.id
        if target_path is not None:
            for stage in stages:
                stage["node_id"] = None
                stage["entry_id"] = None
        network["path_reactions"].append({"path_id": target_id, "stages": stages, "connections": [],
            "zero_point": {"kind": zero_kind, "stage_id": zero_stage["id"]},
            "preset": "relative_energy", "energy_kind": path.energy_kind.value,
            "energy_mode": "absolute", "historical": False,
            "reference_signature": reference_signature(path.reference_expression)})
        validation_project = (project if target_path is None else
                              type(project)(project.id, project.source_files, project.nodes,
                                  (*project.paths, target_path), project.schema_version, project.revision,
                                  project.unit_constants_version, project.plot_state, project.workspace_state,
                                  project.alias_bindings))
        network = validate_network(network, validation_project, allow_unmaterialized=True)
        changed = policy_changed
        old_policy = "随路径" if changed else "固定"
        policy_text = f"旧引用策略：{old_policy}；新配方将固定为 {path.energy_kind.value}。"
        return LegacyConversionPreview(network, target_id, path.id,
            "regenerate" if target_path is not None else "preserve_exclusive", changed,
            policy_text, zero_stage["id"])

    def propose_imported_jobs(self, project, candidates):
        """Return a network draft with explicitly selected source/job cards."""
        if project.id != self.base_project_id or project.revision != self.base_revision:
            raise ValueError("Project changed after the builder draft was opened")
        return propose_imported_job_cards(project, self.network, candidates)

    def snapshot(self):
        """Return an isolated, JSON-safe view model for canvas and inspector rendering."""
        snapshot = {
            "project_id": self.base_project_id,
            "base_revision": self.base_revision,
            "path_id": self.path_id,
            "generation": self.generation,
            "network": deepcopy(self.network),
            "layout": deepcopy(self.layout),
            "path_options": deepcopy(self.path_options),
            "legacy_mode": self.legacy_mode,
        }
        json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        return snapshot

    def _state(self):
        return deepcopy((self.network, self.layout, self.path_options))

    def _replace_state(self, state):
        self.network, self.layout, self.path_options = deepcopy(state)

    def undo(self):
        if not self._undo_states:
            return False
        self._redo_states.append(self._state())
        self._replace_state(self._undo_states.pop())
        self.generation += 1
        return True

    def redo(self):
        if not self._redo_states:
            return False
        self._undo_states.append(self._state())
        self._replace_state(self._redo_states.pop())
        self.generation += 1
        return True

    def execute(self, command):
        """Apply one strict, local command atomically and return the new generation."""
        if not isinstance(command, Mapping):
            raise ValueError("Builder command must be an object")
        kind = command.get("type")
        expected = self._COMMAND_KEYS.get(kind)
        valid_keys = expected is not None and set(command) == expected
        if kind == "set_energy_terms" and set(command) == expected | {"confirm_additional_terms"}:
            valid_keys = True
        if expected is None or not valid_keys:
            raise ValueError("Unknown builder command or command fields")
        network, layout, path_options = self._state()
        self._apply_command(network, layout, path_options, dict(command))
        self._validate_local(network, layout, path_options)
        next_state = (network, layout, path_options)
        if next_state == (self.network, self.layout, self.path_options):
            return self.generation
        self._undo_states.append(self._state())
        if len(self._undo_states) > 100:
            del self._undo_states[0]
        self._redo_states.clear()
        self._replace_state(next_state)
        self.generation += 1
        return self.generation

    @staticmethod
    def _require_uuid(value, label):
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a canonical UUID")
        try:
            canonical = canonical_uuid(value)
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"{label} must be a canonical UUID") from error
        if canonical != value:
            raise ValueError(f"{label} must be a canonical UUID")
        return value

    @staticmethod
    def _require_object(value, required, optional=(), label="object"):
        if not isinstance(value, Mapping) or not set(required) <= set(value) or not set(value) <= set(required) | set(optional):
            raise ValueError(f"Invalid {label} shape")
        return dict(value)

    @staticmethod
    def _finite(value, label, *, positive=False, nonzero=False):
        try:
            result = finite_number(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} must be finite") from error
        if positive and result <= 0 or nonzero and result == 0:
            raise ValueError(f"Invalid {label}")
        return result

    def _recipe(self, network, *, create=False):
        recipe = next((item for item in network["path_reactions"] if item.get("path_id") == self.path_id), None)
        if recipe is None and create:
            recipe = {
                "path_id": self.path_id, "stages": [], "connections": [],
                "zero_point": {"kind": "reactant", "stage_id": ""},
                "preset": "relative_energy", "energy_kind": self.path_energy_kind,
                "energy_mode": "absolute", "historical": False,
            }
            network["path_reactions"].append(recipe)
        return recipe

    @staticmethod
    def _parent_ids(stage):
        if "predecessor_stage_ids" in stage:
            return list(stage["predecessor_stage_ids"])
        primary = stage.get("predecessor_stage_id")
        return [primary] if primary else []

    @staticmethod
    def _invalidate_stage(recipe, stage_id):
        affected = {stage_id}
        changed = True
        while changed:
            changed = False
            for candidate in recipe["stages"]:
                if candidate["id"] not in affected and affected.intersection(BuilderDraft._parent_ids(candidate)):
                    affected.add(candidate["id"])
                    changed = True
        for stage in recipe["stages"]:
            if stage["id"] in affected:
                stage["normalization_confirmed"] = False
                stage["normalization_note"] = ""
                stage["confirm_additional_terms"] = False
        for edge in recipe.get("connections", []):
            if edge["source_stage_id"] in affected or edge["target_stage_id"] in affected:
                edge["confirmed"] = False
                edge["note"] = ""

    @staticmethod
    def _invalidate_all(recipe):
        for stage in recipe["stages"]:
            stage["normalization_confirmed"] = False
            stage["normalization_note"] = ""
            stage["confirm_additional_terms"] = False
        for edge in recipe.get("connections", []):
            edge["confirmed"] = False
            edge["note"] = ""

    def _validate_terms(self, terms, network, recipe):
        if not isinstance(terms, list) or len(terms) > 2048:
            raise ValueError("Invalid stage energy terms")
        species_by_id = {item["id"]: item for item in network["species"]}
        energy_kind = recipe["energy_kind"]
        result = []
        required = {"species_id", "source_file_id", "job_id", "energy_kind", "coefficient",
                    "system_mode", "reason", "historical"}
        for term in terms:
            term = self._require_object(term, required, label="energy term")
            species_id = self._require_uuid(term["species_id"], "energy species id")
            source_id = self._require_uuid(term["source_file_id"], "energy source id")
            job_id = self._require_uuid(term["job_id"], "energy job id")
            species = species_by_id.get(species_id)
            if species is None or (source_id, job_id) not in {
                    (binding["source_file_id"], binding["job_id"]) for binding in species["bindings"]}:
                raise ValueError("Energy source/job must be bound to its species")
            if (not term["historical"] and (source_id, job_id) not in self.source_job_ids) or type(term["historical"]) is not bool:
                raise ValueError("Energy source/job is outside this project")
            if term["energy_kind"] != energy_kind or term["system_mode"] not in {"component", "complete_system"}:
                raise ValueError("Energy term does not match the path mode")
            if not isinstance(term["reason"], str) or not term["reason"].strip() or len(term["reason"]) > 512:
                raise ValueError("Energy term needs a reason")
            term["coefficient"] = self._finite(term["coefficient"], "energy coefficient", nonzero=True)
            result.append(term)
        return result

    def _validate_composition(self, values, species_by_id, label, *, require_nonempty=False):
        if not isinstance(values, list) or len(values) > 2048:
            raise ValueError(f"Invalid {label}")
        if require_nonempty and not values:
            raise ValueError(f"{label} needs at least one species")
        normalized, seen = [], set()
        for value in values:
            value = self._require_object(value, {"species_id", "coefficient"}, label=label)
            species_id = self._require_uuid(value["species_id"], f"{label} species id")
            if species_id not in species_by_id or species_id in seen:
                raise ValueError(f"{label} references an unknown or duplicate species")
            seen.add(species_id)
            normalized.append({"species_id": species_id,
                               "coefficient": self._finite(value["coefficient"], f"{label} coefficient", positive=True)})
        return normalized

    def _apply_command(self, network, layout, path_options, command):
        kind = command["type"]
        species_by_id = {item["id"]: item for item in network["species"]}
        recipe = self._recipe(network, create=kind in {"add_stage", "set_zero"})
        stage_by_id = {item["id"]: item for item in recipe["stages"]} if recipe else {}
        edges = recipe.get("connections", []) if recipe else []

        if kind == "add_species":
            item = self._require_object(command["species"],
                {"id", "name", "formula", "starred", "bindings"}, label="species")
            identifier = self._require_uuid(item["id"], "species id")
            if identifier in species_by_id:
                raise ValueError("Duplicate species UUID")
            if not isinstance(item["name"], str) or not item["name"].strip() or len(item["name"].strip()) > 256:
                raise ValueError("Invalid species name")
            if not isinstance(item["formula"], str) or len(item["formula"]) > 256:
                raise ValueError("Invalid molecular formula")
            if item["formula"].strip():
                parse_molecular_formula(item["formula"].strip())
            if type(item["starred"]) is not bool or not isinstance(item["bindings"], list):
                raise ValueError("Invalid species fields")
            bindings, seen = [], set()
            if len(item["bindings"]) > 128:
                raise ValueError("Too many species bindings")
            for binding in item["bindings"]:
                binding = self._require_object(binding,
                    {"source_file_id", "job_id", "historical"}, label="species binding")
                source_id = self._require_uuid(binding["source_file_id"], "source id")
                job_id = self._require_uuid(binding["job_id"], "job id")
                if type(binding["historical"]) is not bool:
                    raise ValueError("Invalid historical marker")
                if not binding["historical"] and (source_id, job_id) not in self.source_job_ids:
                    raise ValueError("Species source/job is outside this project")
                pair = (source_id, job_id)
                if pair in seen:
                    raise ValueError("Duplicate species binding")
                seen.add(pair)
                bindings.append(binding)
            network["species"].append({**item, "id": identifier, "name": item["name"].strip(),
                                       "formula": item["formula"].strip(), "bindings": bindings})
            return

        if kind == "update_species":
            identifier = self._require_uuid(command["species_id"], "species id")
            item = species_by_id.get(identifier)
            fields = command["fields"]
            allowed = {"name", "formula", "bindings"}
            if item is None or not isinstance(fields, Mapping) or not fields or not set(fields) <= allowed:
                raise ValueError("Invalid species update")
            updated = deepcopy(item)
            if "name" in fields:
                if not isinstance(fields["name"], str) or not fields["name"].strip() or len(fields["name"].strip()) > 256:
                    raise ValueError("Invalid species name")
                updated["name"] = fields["name"].strip()
            if "formula" in fields:
                formula = fields["formula"]
                if not isinstance(formula, str) or len(formula) > 256:
                    raise ValueError("Invalid molecular formula")
                if formula.strip():
                    parse_molecular_formula(formula.strip())
                updated["formula"] = formula.strip()
            if "bindings" in fields:
                if not isinstance(fields["bindings"], list) or len(fields["bindings"]) > 128:
                    raise ValueError("Invalid species bindings")
                normalized, seen = [], set()
                for binding in fields["bindings"]:
                    binding = self._require_object(binding,
                        {"source_file_id", "job_id", "historical"}, label="species binding")
                    source_id = self._require_uuid(binding["source_file_id"], "source id")
                    job_id = self._require_uuid(binding["job_id"], "job id")
                    if type(binding["historical"]) is not bool or (
                            not binding["historical"] and (source_id, job_id) not in self.source_job_ids):
                        raise ValueError("Species source/job is outside this project")
                    pair = (source_id, job_id)
                    if pair in seen:
                        raise ValueError("Duplicate species binding")
                    seen.add(pair)
                    normalized.append(binding)
                updated["bindings"] = normalized
            network["species"] = [updated if value["id"] == identifier else value for value in network["species"]]
            if set(fields) & {"formula", "bindings"} and recipe:
                for stage in recipe["stages"]:
                    if any(component["species_id"] == identifier for component in stage["species"]) or any(
                            term["species_id"] == identifier for term in stage["terms"]):
                        self._invalidate_stage(recipe, stage["id"])
            return

        if kind == "remove_species":
            identifier = self._require_uuid(command["species_id"], "species id")
            if identifier not in species_by_id:
                raise ValueError("Unknown species UUID")
            if any(identifier in edge.get("species_ids", []) for edge in network["edges"]):
                raise ValueError("Species is referenced by a material relationship")
            if any(identifier in link.get("species_ids", []) for link in network["node_links"]):
                raise ValueError("Species is referenced by a node association")
            if recipe and (any(any(part["species_id"] == identifier for part in stage["species"])
                                or any(term["species_id"] == identifier for term in stage["terms"])
                                for stage in recipe["stages"]) or any(
                                any(part["species_id"] == identifier for side in ("reactants", "products")
                                    for part in edge.get(side, [])) or any(
                                    term["species_id"] == identifier for term in edge.get("terms", []))
                                for edge in edges)):
                raise ValueError("Species is referenced by the current reaction path")
            network["species"] = [item for item in network["species"] if item["id"] != identifier]
            return

        if kind == "set_star":
            identifier = self._require_uuid(command["species_id"], "species id")
            if identifier not in species_by_id or type(command["starred"]) is not bool:
                raise ValueError("Invalid star command")
            species_by_id[identifier]["starred"] = command["starred"]
            return

        if kind == "add_stage":
            stage = self._require_object(command["stage"],
                {"id", "role", "label", "predecessor_stage_id", "species", "terms",
                 "confirm_additional_terms", "node_id", "entry_id", "historical"},
                {"missing", "normalization_confirmed", "normalization_note", "predecessor_stage_ids"}, "stage")
            recipe = recipe or self._recipe(network, create=True)
            identifier = self._require_uuid(stage["id"], "stage id")
            stage_by_id = {item["id"]: item for item in recipe["stages"]}
            if identifier in stage_by_id:
                raise ValueError("Duplicate stage UUID")
            if stage["role"] not in _ROLES or not isinstance(stage["label"], str) or not stage["label"].strip() or len(stage["label"].strip()) > 256:
                raise ValueError("Invalid stage role or label")
            if type(stage["historical"]) is not bool or stage["historical"]:
                raise ValueError("A new stage cannot be historical")
            if type(stage["confirm_additional_terms"]) is not bool:
                raise ValueError("Invalid additional energy confirmation")
            if "missing" in stage and (type(stage["missing"]) is not bool or
                    stage["missing"] and stage["role"] != "transition_state"):
                raise ValueError("Only a transition state can be marked NOT FOUND")
            parents = self._parent_ids(stage)
            if len(parents) != len(set(parents)) or any(parent not in stage_by_id for parent in parents):
                raise ValueError("Stage predecessor is outside the current path")
            stage = deepcopy(stage)
            stage["label"] = stage["label"].strip()
            stage["species"] = self._validate_composition(stage["species"], species_by_id,
                                                            "stage composition", require_nonempty=True)
            stage["terms"] = self._validate_terms(stage["terms"], network, recipe)
            if stage.get("missing") and stage["terms"]:
                raise ValueError("A NOT FOUND stage cannot have energy terms")
            stage["predecessor_stage_ids"] = parents
            stage["predecessor_stage_id"] = parents[0] if parents else None
            stage["normalization_confirmed"] = False
            stage["normalization_note"] = ""
            recipe["stages"].append(stage)
            if not recipe["stages"][:-1] and stage["role"] == "reactant":
                recipe["zero_point"] = {"kind": "reactant", "stage_id": identifier}
            for parent_id in parents:
                parent = stage_by_id[parent_id]
                recipe["connections"].append({
                    "id": new_id(), "source_stage_id": parent_id, "target_stage_id": identifier,
                    "confirmed": False, "note": "",
                    "reactants": deepcopy(parent["species"]), "products": deepcopy(stage["species"]), "terms": [],
                })
            return

        if kind == "update_stage":
            identifier = self._require_uuid(command["stage_id"], "stage id")
            stage = stage_by_id.get(identifier)
            fields = command["fields"]
            allowed = {"role", "label", "missing", "normalization_confirmed", "normalization_note",
                       "confirm_additional_terms", "predecessor_stage_ids"}
            if stage is None or not isinstance(fields, Mapping) or not fields or not set(fields) <= allowed:
                raise ValueError("Invalid stage update")
            changed_science = False
            parent_values = fields.get("predecessor_stage_ids")
            if parent_values is not None:
                if not isinstance(parent_values, list) or len(parent_values) != len(set(parent_values)):
                    raise ValueError("Invalid stage predecessors")
                parent_values = [self._require_uuid(value, "predecessor stage id") for value in parent_values]
                if identifier in parent_values or any(value not in stage_by_id for value in parent_values):
                    raise ValueError("Stage predecessor is outside the current path")
                old_parents = set(self._parent_ids(stage))
                new_parents = set(parent_values)
                if old_parents != new_parents:
                    changed_science = True
                    recipe["connections"] = [edge for edge in recipe.get("connections", [])
                        if edge["target_stage_id"] != identifier or edge["source_stage_id"] in new_parents]
                    existing_parents = {edge["source_stage_id"] for edge in recipe["connections"]
                                        if edge["target_stage_id"] == identifier}
                    for parent_id in parent_values:
                        if parent_id not in existing_parents:
                            parent = stage_by_id[parent_id]
                            recipe["connections"].append({
                                "id": new_id(), "source_stage_id": parent_id, "target_stage_id": identifier,
                                "confirmed": False, "note": "", "reactants": deepcopy(parent["species"]),
                                "products": deepcopy(stage["species"]), "terms": [],
                            })
                    stage["predecessor_stage_ids"] = parent_values
                    stage["predecessor_stage_id"] = parent_values[0] if parent_values else None
            for key, value in fields.items():
                if key == "predecessor_stage_ids":
                    continue
                if key == "role":
                    if value not in _ROLES:
                        raise ValueError("Invalid stage role")
                    changed_science |= value != stage["role"]
                elif key == "label":
                    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
                        raise ValueError("Invalid stage label")
                    value = value.strip()
                elif key in {"missing", "normalization_confirmed"}:
                    if type(value) is not bool:
                        raise ValueError(f"Invalid {key} value")
                    if key == "missing":
                        changed_science |= value != stage.get("missing", False)
                elif key == "normalization_note":
                    if not isinstance(value, str) or len(value) > 1024:
                        raise ValueError("Invalid normalization note")
                stage[key] = value
            if stage.get("missing") and stage["role"] != "transition_state":
                raise ValueError("Only a transition state can be marked NOT FOUND")
            if stage.get("missing"):
                stage["terms"] = []
            if changed_science:
                self._invalidate_stage(recipe, identifier)
            return

        if kind == "remove_stage":
            identifier = self._require_uuid(command["stage_id"], "stage id")
            if identifier not in stage_by_id:
                raise ValueError("Unknown stage UUID")
            recipe["stages"] = [item for item in recipe["stages"] if item["id"] != identifier]
            recipe["connections"] = [edge for edge in edges if edge["source_stage_id"] != identifier
                                      and edge["target_stage_id"] != identifier]
            for stage in recipe["stages"]:
                parents = [parent for parent in self._parent_ids(stage) if parent != identifier]
                stage["predecessor_stage_ids"] = parents
                stage["predecessor_stage_id"] = parents[0] if parents else None
                self._invalidate_stage(recipe, stage["id"])
            zero = recipe.get("zero_point", {})
            if zero.get("kind") in {"stage", "reactant"} and zero.get("stage_id") == identifier:
                replacement = next((item for item in recipe["stages"] if item["role"] == "reactant"), None)
                recipe["zero_point"] = ({"kind": "reactant", "stage_id": replacement["id"]}
                                         if replacement else {"kind": "reactant", "stage_id": ""})
            return

        if kind == "set_composition":
            identifier = self._require_uuid(command["stage_id"], "stage id")
            stage = stage_by_id.get(identifier)
            values = command["species"]
            if stage is None:
                raise ValueError("Invalid stage composition")
            normalized = self._validate_composition(values, species_by_id, "stage composition",
                                                    require_nonempty=True)
            if stage["species"] != normalized:
                stage["species"] = normalized
                self._invalidate_stage(recipe, identifier)
                for edge in edges:
                    if edge["source_stage_id"] == identifier:
                        edge["reactants"] = deepcopy(normalized)
                    if edge["target_stage_id"] == identifier:
                        edge["products"] = deepcopy(normalized)
            return

        if kind == "set_energy_terms":
            identifier = self._require_uuid(command["stage_id"], "stage id")
            stage = stage_by_id.get(identifier)
            if stage is None or stage.get("missing"):
                raise ValueError("An unresolved or unknown stage cannot receive energy terms")
            values = self._validate_terms(command["terms"], network, recipe)
            if stage["terms"] != values:
                stage["terms"] = values
                self._invalidate_stage(recipe, identifier)
                stage["confirm_additional_terms"] = False
            if "confirm_additional_terms" in command:
                if type(command["confirm_additional_terms"]) is not bool:
                    raise ValueError("Invalid additional energy confirmation")
                stage["confirm_additional_terms"] = command["confirm_additional_terms"]
            return

        if kind == "add_connection":
            if recipe is None:
                raise ValueError("Create a stage before adding a connection")
            connection = self._require_object(command["connection"],
                {"id", "source_stage_id", "target_stage_id", "confirmed", "note"},
                {"reactants", "products", "terms"}, "stage connection")
            connection_id = self._require_uuid(connection["id"], "connection id")
            source_id = self._require_uuid(connection["source_stage_id"], "connection source stage id")
            target_id = self._require_uuid(connection["target_stage_id"], "connection target stage id")
            if source_id not in stage_by_id or target_id not in stage_by_id or source_id == target_id:
                raise ValueError("Connection endpoint is outside the current path")
            if any(edge["id"] == connection_id or
                   (edge["source_stage_id"], edge["target_stage_id"]) == (source_id, target_id) for edge in edges):
                raise ValueError("Duplicate reaction connection")
            connection["confirmed"], connection["note"] = False, ""
            connection.setdefault("reactants", deepcopy(stage_by_id[source_id]["species"]))
            connection.setdefault("products", deepcopy(stage_by_id[target_id]["species"]))
            connection.setdefault("terms", [])
            connection["reactants"] = self._validate_composition(connection["reactants"], species_by_id,
                                                                  "connection reactants")
            connection["products"] = self._validate_composition(connection["products"], species_by_id,
                                                                 "connection products")
            connection["terms"] = self._validate_terms(connection["terms"], network, recipe)
            recipe["connections"].append(connection)
            target = stage_by_id[target_id]
            parents = self._parent_ids(target)
            parents.append(source_id)
            target["predecessor_stage_ids"] = parents
            target["predecessor_stage_id"] = target.get("predecessor_stage_id") or source_id
            self._invalidate_stage(recipe, target_id)
            return

        if kind == "update_connection":
            connection_id = self._require_uuid(command["connection_id"], "connection id")
            edge = next((item for item in edges if item["id"] == connection_id), None)
            fields = command["fields"]
            allowed = {"confirmed", "note", "reactants", "products", "terms"}
            if edge is None or not isinstance(fields, Mapping) or not fields or not set(fields) <= allowed:
                raise ValueError("Invalid connection update")
            science_fields = set(fields) & {"reactants", "products", "terms"}
            if science_fields:
                for key in science_fields:
                    if key in {"reactants", "products"}:
                        edge[key] = self._validate_composition(fields[key], species_by_id,
                                                              f"connection {key}")
                    else:
                        edge[key] = self._validate_terms(fields[key], network, recipe)
                edge["confirmed"], edge["note"] = False, ""
            for key in set(fields) - science_fields:
                if key == "confirmed" and type(fields[key]) is not bool:
                    raise ValueError("Invalid connection confirmation")
                if key == "note" and (not isinstance(fields[key], str) or len(fields[key]) > 1024):
                    raise ValueError("Invalid connection note")
                edge[key] = fields[key]
            if edge["confirmed"] and not edge["note"].strip():
                raise ValueError("A confirmed stage connection needs a review note")
            return

        if kind == "remove_connection":
            connection_id = self._require_uuid(command["connection_id"], "connection id")
            edge = next((item for item in edges if item["id"] == connection_id), None)
            if edge is None:
                raise ValueError("Unknown connection UUID")
            target_id, source_id = edge["target_stage_id"], edge["source_stage_id"]
            recipe["connections"] = [item for item in edges if item["id"] != connection_id]
            target = stage_by_id[target_id]
            parents = [parent for parent in self._parent_ids(target) if parent != source_id]
            target["predecessor_stage_ids"] = parents
            target["predecessor_stage_id"] = parents[0] if parents else None
            self._invalidate_stage(recipe, target_id)
            return

        if kind == "set_zero":
            recipe = recipe or self._recipe(network, create=True)
            zero = command["zero_point"]
            if not isinstance(zero, Mapping) or zero.get("kind") not in {"reactant", "stage", "custom_expression", "manual"}:
                raise ValueError("Invalid zero point")
            mode = zero["kind"]
            if mode in {"reactant", "stage"}:
                zero = self._require_object(zero, {"kind", "stage_id"}, label="zero point")
                stage_id = self._require_uuid(zero["stage_id"], "zero stage id")
                stage = next((item for item in recipe["stages"] if item["id"] == stage_id), None)
                if stage is None or mode == "reactant" and stage["role"] != "reactant":
                    raise ValueError("Zero point stage does not match this path")
            elif mode == "custom_expression":
                zero = self._require_object(zero, {"kind", "expression"}, label="zero point")
                if not isinstance(zero["expression"], str) or not zero["expression"].strip() or len(zero["expression"]) > 8192:
                    raise ValueError("Invalid zero point expression")
            else:
                zero = self._require_object(zero, {"kind", "value", "unit"}, label="zero point")
                zero["value"] = self._finite(zero["value"], "manual reference")
                if zero["unit"] not in {unit.value for unit in Unit}:
                    raise ValueError("Invalid manual reference unit")
            if recipe["zero_point"] != zero:
                recipe["zero_point"] = deepcopy(dict(zero))
                self._invalidate_all(recipe)
            return

        if kind == "set_path_options":
            values = command["path_options"]
            allowed = {"label", "unit", "color", "energy_mode", "energy_kind"}
            if not isinstance(values, Mapping) or not values or not set(values) <= allowed:
                raise ValueError("Invalid path options")
            for key, value in values.items():
                if key == "label" and (not isinstance(value, str) or not value.strip() or len(value.strip()) > 256):
                    raise ValueError("Invalid path label")
                if key == "unit" and value not in {unit.value for unit in Unit}:
                    raise ValueError("Invalid path unit")
                if key == "color" and (not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value)):
                    raise ValueError("Invalid path color")
                if key == "energy_mode" and value not in {"absolute", "edge_recursive"}:
                    raise ValueError("Invalid path energy mode")
                if key == "energy_kind" and value not in {item.value for item in EnergyKind}:
                    raise ValueError("Invalid path energy kind")
            if set(values) & {"energy_mode", "energy_kind"}:
                recipe = recipe or self._recipe(network, create=True)
                for key in ("energy_mode", "energy_kind"):
                    if key in values and recipe.get(key) != values[key]:
                        recipe[key] = values[key]
                        self._invalidate_all(recipe)
            for key, value in values.items():
                if key in {"label", "unit", "color"}:
                    path_options[key] = value.strip() if key == "label" else value
            return

        if kind == "move_stage":
            identifier = self._require_uuid(command["stage_id"], "stage id")
            if identifier not in stage_by_id:
                raise ValueError("Stage is outside the current path")
            x = self._finite(command["x"], "stage x")
            y = self._finite(command["y"], "stage y")
            if abs(x) > 100000 or abs(y) > 100000:
                raise ValueError("Stage layout coordinates must be within ±100000 DIP")
            layout.setdefault("stages", {})[identifier] = {"x": x, "y": y}

    def _validate_local(self, network, layout, path_options):
        species_ids = [self._require_uuid(item.get("id"), "species id") for item in network["species"]]
        if len(species_ids) != len(set(species_ids)):
            raise ValueError("Duplicate species UUID")
        known_species = set(species_ids)
        species_by_id = {item["id"]: item for item in network["species"]}
        recipe = self._recipe(network)
        if recipe is not None:
            stage_ids = [self._require_uuid(item.get("id"), "stage id") for item in recipe["stages"]]
            if len(stage_ids) != len(set(stage_ids)):
                raise ValueError("Duplicate stage UUID")
            known_stages = set(stage_ids)
            expected_pairs = set()
            graph = {identifier: [] for identifier in stage_ids}
            for stage in recipe["stages"]:
                parents = self._parent_ids(stage)
                if len(parents) != len(set(parents)) or any(parent not in known_stages or parent == stage["id"] for parent in parents):
                    raise ValueError("Invalid stage predecessor")
                if stage.get("predecessor_stage_id") is not None and stage["predecessor_stage_id"] not in parents:
                    raise ValueError("Primary predecessor must be included in predecessor list")
                if any(part["species_id"] not in known_species for part in stage.get("species", [])):
                    raise ValueError("Stage composition references unknown species")
                for part in stage.get("species", []):
                    self._finite(part["coefficient"], "stoichiometric coefficient", positive=True)
                self._validate_terms(stage.get("terms", []), network, recipe)
                for parent in parents:
                    graph[parent].append(stage["id"])
                    expected_pairs.add((parent, stage["id"]))
            visiting, visited = set(), set()
            def visit(identifier):
                if identifier in visiting:
                    raise ValueError("Stage graph contains a cycle")
                if identifier in visited:
                    return
                visiting.add(identifier)
                for child in graph[identifier]:
                    visit(child)
                visiting.remove(identifier)
                visited.add(identifier)
            for identifier in stage_ids:
                visit(identifier)
            connections, pairs = set(), set()
            for edge in recipe.get("connections", []):
                edge_id = self._require_uuid(edge["id"], "connection id")
                pair = (edge["source_stage_id"], edge["target_stage_id"])
                if edge_id in connections or pair in pairs or pair not in expected_pairs:
                    raise ValueError("Duplicate or undeclared reaction connection")
                connections.add(edge_id)
                pairs.add(pair)
                if type(edge["confirmed"]) is not bool or not isinstance(edge["note"], str):
                    raise ValueError("Invalid connection review state")
                for side in ("reactants", "products"):
                    edge[side] = self._validate_composition(edge.get(side, []), species_by_id,
                                                            f"connection {side}")
                edge["terms"] = self._validate_terms(edge.get("terms", []), network, recipe)
            if pairs != expected_pairs:
                raise ValueError("Every stage predecessor needs an explicit connection")
        stage_layout = layout.get("stages", {})
        if not isinstance(stage_layout, Mapping):
            raise ValueError("Invalid builder layout")
        for identifier, position in stage_layout.items():
            if identifier not in (set() if recipe is None else {item["id"] for item in recipe["stages"]}):
                raise ValueError("Layout references a stage outside the current path")
            position = self._require_object(position, {"x", "y"}, label="stage position")
            if any(abs(self._finite(position[key], f"stage {key}")) > 100000 for key in ("x", "y")):
                raise ValueError("Stage layout coordinates must be within ±100000 DIP")
        json.dumps((network, layout, path_options), ensure_ascii=False, allow_nan=False)


def propose_imported_job_cards(project, network, candidates):
    """Append validated, explicitly selected job cards without inferring edges."""
    result = deepcopy(network if network else empty_network())
    sources = {source.id: source for source in project.source_files}
    seen_pairs = set()
    for item in candidates:
        if not isinstance(item, Mapping):
            raise ValueError("Job candidate must be an object")
        source_id, job_id = item.get("source_file_id"), item.get("job_id")
        name = item.get("name")
        if not isinstance(source_id, str) or not isinstance(job_id, str):
            raise ValueError("Job candidate needs explicit source and job UUIDs")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 256:
            raise ValueError("Every selected job needs a material card name")
        source = sources.get(source_id)
        job = next((job for job in source.jobs if job.id == job_id), None) if source else None
        if source is None or job is None:
            raise ValueError("Selected source/job UUID is not present in this project")
        if not any(select_job(source, kind, job_id=job.id).available for kind in EnergyKind):
            raise ValueError("Selected job has no available energy and cannot make a bound material card")
        pair = (source_id, job_id)
        if pair in seen_pairs:
            raise ValueError("A source/job pair can only be selected once per candidate batch")
        seen_pairs.add(pair)
        formula = item.get("formula", "")
        if not isinstance(formula, str) or len(formula.strip()) > 256:
            raise ValueError("Invalid candidate molecular formula")
        if formula.strip():
            parse_molecular_formula(formula.strip())
        result["species"].append({"id": new_id(), "name": name.strip(),
            "formula": formula.strip(), "starred": False, "bindings": [{
                "source_file_id": source_id, "job_id": job_id, "historical": False}]})
    result["edges"] = deepcopy(network.get("edges", []))
    result["path_reactions"] = deepcopy(network.get("path_reactions", []))
    return result
