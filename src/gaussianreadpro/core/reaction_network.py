"""Versioned, project-local reaction species graph and whole-path recipe.

This is editor metadata only. ProfileNode expressions and ReactionPath references
remain the single source of calculated energies.
"""
from __future__ import annotations

import json
import math
import hashlib
import itertools
import re
import uuid
from collections.abc import Mapping
from .expressions import (EnergyContext, compile_expression, edit_expression,
                          evaluate_expression, expression_from_ast, ref_ast)
from .models import (CalculationMode, EnergyKind, EnergyRef, ExpressionPurpose, KindPolicy,
                     PathEntry, ProfileNode, Project, ReactionPath, canonical_uuid, new_id,
                     snapshot_to_dict)

FORMAT_VERSION = 1
MAX_BYTES = 16 * 1024 * 1024
MAX_SPECIES = 5000
MAX_EDGES = 20000
MAX_NODE_LINKS = 20000
MAX_PATHS = 1000
MAX_STAGES_PER_PATH = 512
MAX_TERMS_PER_STAGE = 2048
ROLES = {"reactant", "intermediate", "transition_state", "product", "unspecified"}
ENERGY_KINDS = {"scf", "gibbs_total", "gibbs_correction"}
SYSTEM_MODES = {"component", "complete_system"}
RELATIONS = {"precursor", "successor"}


def empty_network():
    return {"format_version": FORMAT_VERSION, "species": [], "edges": [], "node_links": [], "path_reactions": []}


def _uuid(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a UUID")
    canonical = canonical_uuid(value)
    if canonical != value:
        raise ValueError(f"{label} must be canonical lowercase UUID")
    return value


def _text(value, label, maximum=512, *, empty=True):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"Invalid {label}")
    return value


def _number(value, label, *, positive=False, nonzero=False):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    value = float(value)
    if positive and value <= 0 or nonzero and value == 0:
        raise ValueError(f"Invalid {label}")
    return value


def _keys(value, expected, label):
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise ValueError(f"Invalid {label} shape")


def parse_molecular_formula(formula):
    """Parse a compact molecular formula (including nested parentheses)."""
    if not isinstance(formula, str) or not formula or len(formula) > 256:
        raise ValueError("A molecular formula is required")
    token = re.compile(r"([A-Z][a-z]?|\(|\)|\d+)")
    parts = token.findall(formula)
    if "".join(parts) != formula:
        raise ValueError(f"Invalid molecular formula: {formula}")
    index = 0
    def group(nested=False):
        nonlocal index
        counts = {}
        while index < len(parts):
            part = parts[index]
            if part == ")":
                if not nested:
                    raise ValueError("Unmatched closing parenthesis in molecular formula")
                index += 1
                return counts
            if part == "(":
                index += 1
                inner = group(True)
                multiplier = 1
                if index < len(parts) and parts[index].isdigit():
                    multiplier = int(parts[index]); index += 1
                if multiplier < 1:
                    raise ValueError("Formula counts must be positive integers")
                for element, number in inner.items():
                    counts[element] = counts.get(element, 0) + number * multiplier
            elif part.isdigit():
                raise ValueError("A formula count must follow an element or parenthesized group")
            else:
                element = part
                index += 1
                number = 1
                if index < len(parts) and parts[index].isdigit():
                    number = int(parts[index]); index += 1
                if number < 1:
                    raise ValueError("Formula counts must be positive integers")
                counts[element] = counts.get(element, 0) + number
        if nested:
            raise ValueError("Unmatched opening parenthesis in molecular formula")
        return counts
    result = group()
    if not result:
        raise ValueError("Molecular formula is empty")
    return result


def _stage_atom_vector(stage, species_by_id):
    result = {}
    for component in stage["species"]:
        formula = species_by_id[component["species_id"]]["formula"]
        if not formula:
            return None
        for element, count in parse_molecular_formula(formula).items():
            result[element] = result.get(element, 0) + count * component["coefficient"]
    return result


def _stage_stoich(stage):
    return [{"species_id": item["species_id"], "coefficient": item["coefficient"]}
            for item in stage["species"]]


def _validate_stoich(raw, species_ids, label):
    if type(raw) is not list or not raw or len(raw) > MAX_TERMS_PER_STAGE:
        raise ValueError(f"Every reaction edge needs an explicit {label} side")
    result, seen = [], set()
    for term in raw:
        _keys(term, ("species_id", "coefficient"), f"edge {label} stoichiometry")
        identifier = _uuid(term["species_id"], f"edge {label} species id")
        if identifier not in species_ids:
            raise ValueError("Edge stoichiometry references an unknown species")
        coefficient = _number(term["coefficient"], f"edge {label} coefficient", positive=True)
        if identifier in seen:
            raise ValueError("Edge stoichiometry contains a duplicate species; combine its coefficient")
        seen.add(identifier)
        result.append({"species_id": identifier, "coefficient": coefficient})
    return result


def _stoich_atom_vector(stoich, species_by_id):
    result = {}
    for component in stoich:
        formula = species_by_id[component["species_id"]]["formula"]
        if not formula:
            return None
        for element, count in parse_molecular_formula(formula).items():
            result[element] = result.get(element, 0) + count * component["coefficient"]
    return result


def _validate_terms(raw_terms, species_ids, species_bindings, source_jobs, energy_kind):
    if type(raw_terms) is not list or len(raw_terms) > MAX_TERMS_PER_STAGE:
        raise ValueError("Invalid energy ledger")
    terms = []
    for term in raw_terms:
        _keys(term, ("species_id", "source_file_id", "job_id", "energy_kind", "coefficient",
                     "system_mode", "reason", "historical"), "ledger term")
        species_id = _uuid(term["species_id"], "ledger species id")
        source_id = _uuid(term["source_file_id"], "ledger source id")
        job_id = _uuid(term["job_id"], "ledger job id")
        if (species_id not in species_ids or term["energy_kind"] not in ENERGY_KINDS or
                term["energy_kind"] != energy_kind or term["system_mode"] not in SYSTEM_MODES):
            raise ValueError("Ledger references unknown species or energy mode")
        if (source_id, job_id) not in species_bindings[species_id]:
            raise ValueError("Ledger source/job is not bound to its species card")
        if type(term["historical"]) is not bool or (job_id not in source_jobs.get(source_id, set())) != term["historical"]:
            raise ValueError("Ledger history marker conflicts with current project")
        terms.append({"species_id": species_id, "source_file_id": source_id, "job_id": job_id,
            "energy_kind": term["energy_kind"], "coefficient": _number(term["coefficient"], "ledger coefficient", nonzero=True),
            "system_mode": term["system_mode"], "reason": _text(term["reason"], "ledger reason", 512, empty=False),
            "historical": term["historical"]})
    whole_system_terms = [term for term in terms if term["system_mode"] == "complete_system"]
    component_terms = [term for term in terms if term["system_mode"] == "component"]
    if whole_system_terms and component_terms:
        raise ValueError("Full-system and component terms cannot be combined in one ledger")
    return terms


def normalize_path_graph(stage_ids, connections, root_values, edge_deltas, *, tolerance_hartree=1e-8):
    """Accumulate local edge deltas from one common zero through an acyclic graph.

    ``root_values`` and ``edge_deltas`` are already expressed against the same
    zero. A reconvergent stage is accepted only when every incoming route yields
    the same cumulative energy within the explicit tolerance.
    """
    ids = list(stage_ids)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Path graph needs unique stage IDs")
    known = set(ids)
    if type(root_values) is not dict or not root_values or not set(root_values) <= known:
        raise ValueError("Path graph needs one or more known root values")
    tolerance = _number(tolerance_hartree, "normalization tolerance", positive=True)
    incoming = {identifier: [] for identifier in ids}
    outgoing = {identifier: [] for identifier in ids}
    for edge in connections:
        source, target = edge["source_stage_id"], edge["target_stage_id"]
        if source not in known or target not in known or source == target:
            raise ValueError("Invalid path graph edge")
        if (source, target) not in edge_deltas:
            raise ValueError("Path graph edge is missing its local energy delta")
        delta = _number(edge_deltas[(source, target)], "local edge energy")
        incoming[target].append((source, delta))
        outgoing[source].append(target)
    indegree = {identifier: len(incoming[identifier]) for identifier in ids}
    ready = [identifier for identifier in ids if indegree[identifier] == 0]
    order, emitted = [], set()
    while ready:
        current = ready.pop(0)
        order.append(current); emitted.add(current)
        for child in outgoing[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(order) != len(ids):
        raise ValueError("Path graph contains a cycle")
    values = {identifier: _number(value, "root relative energy") for identifier, value in root_values.items()}
    for identifier in order:
        parents = incoming[identifier]
        if not parents:
            if identifier not in values:
                raise ValueError(f"Path graph stage {identifier} is disconnected from a selected zero-point root")
            continue
        if identifier in values:
            raise ValueError("A stage cannot be both an edge-derived stage and a root")
        candidates = [(source, values[source] + delta) for source, delta in parents if source in values]
        if len(candidates) != len(parents):
            raise ValueError("Path graph contains a route disconnected from the selected zero point")
        baseline = candidates[0][1]
        if any(abs(value - baseline) > tolerance for _, value in candidates[1:]):
            detail = {source: value for source, value in candidates}
            raise ValueError(f"Reconvergent routes do not normalize to one energy: {detail}")
        values[identifier] = baseline
    if set(values) != known:
        raise ValueError("Path graph contains stages unreachable from the selected zero point")
    return {"relative_energies": values,
            "local_deltas": {(source, target): delta for target, parents in incoming.items()
                             for source, delta in parents}}


def reference_signature(expression):
    """Stable content signature for the saved zero-point AST, excluding editor spans."""
    if expression is None:
        return ""
    def clean(value):
        if isinstance(value, Mapping):
            return {key: clean(item) for key, item in value.items() if key != "span"}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value
    canonical = json.dumps(clean(expression.ast), ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_network(raw, project: Project, *, allow_unmaterialized=False):
    """Validate untrusted project JSON and return a plain normalized structure.

    Dangling source/job/node/path links are retained only when explicitly marked
    historical. This prevents silent relinking after source removal or edits.
    """
    raw = snapshot_to_dict(raw)
    if not isinstance(raw, Mapping):
        raise ValueError("Reaction network must be an object")
    _keys(raw, ("format_version", "species", "edges", "node_links", "path_reactions"), "network")
    if type(raw["format_version"]) is not int or raw["format_version"] != FORMAT_VERSION:
        raise ValueError("Unsupported reaction network format")
    for key, maximum in (("species", MAX_SPECIES), ("edges", MAX_EDGES),
                         ("node_links", MAX_NODE_LINKS), ("path_reactions", MAX_PATHS)):
        if type(raw[key]) is not list or len(raw[key]) > maximum:
            raise ValueError(f"Reaction network {key} limit exceeded")
    encoded = json.dumps(raw, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ValueError("Reaction network size limit exceeded")

    species_ids, species_out, species_bindings = set(), [], {}
    source_jobs = {s.id: {j.id for j in s.jobs} for s in project.source_files}
    node_ids = {node.id for node in project.nodes}
    path_ids = {path.id for path in project.paths}
    entry_links = {entry.id: (path.id, entry.node_id) for path in project.paths for entry in path.entries}
    for item in raw["species"]:
        if set(item) not in ({"id", "name", "starred", "bindings"}, {"id", "name", "starred", "bindings", "formula"}):
            raise ValueError("Invalid species shape")
        identifier = _uuid(item["id"], "species id")
        if identifier in species_ids:
            raise ValueError("Duplicate species UUID")
        species_ids.add(identifier)
        name = _text(item["name"], "species name", 256, empty=False).strip()
        if type(item["starred"]) is not bool or type(item["bindings"]) is not list or len(item["bindings"]) > 128:
            raise ValueError("Invalid species fields")
        bindings, seen = [], set()
        for binding in item["bindings"]:
            _keys(binding, ("source_file_id", "job_id", "historical"), "species binding")
            source_id = _uuid(binding["source_file_id"], "source id")
            job_id = _uuid(binding["job_id"], "job id")
            if type(binding["historical"]) is not bool:
                raise ValueError("Invalid historical marker")
            exists = job_id in source_jobs.get(source_id, set())
            if exists == binding["historical"]:
                raise ValueError("Species binding history marker conflicts with current project")
            if (source_id, job_id) in seen:
                raise ValueError("Duplicate species binding")
            seen.add((source_id, job_id))
            bindings.append({"source_file_id": source_id, "job_id": job_id, "historical": binding["historical"]})
        formula = _text(item.get("formula", ""), "molecular formula", 256).strip()
        if formula:
            parse_molecular_formula(formula)
        species_out.append({"id": identifier, "name": name, "starred": item["starred"], "bindings": bindings,
                            "formula": formula})
        species_bindings[identifier] = {(binding["source_file_id"], binding["job_id"])
                                        for binding in bindings}

    edges, edge_ids = [], set()
    for edge in raw["edges"]:
        _keys(edge, ("id", "source_species_id", "target_species_id", "relation", "note"), "edge")
        identifier = _uuid(edge["id"], "edge id")
        source, target = _uuid(edge["source_species_id"], "edge source"), _uuid(edge["target_species_id"], "edge target")
        if identifier in edge_ids or source not in species_ids or target not in species_ids:
            raise ValueError("Duplicate edge or missing species endpoint")
        if edge["relation"] not in RELATIONS:
            raise ValueError("Invalid reaction relation")
        edge_ids.add(identifier)
        edges.append({"id": identifier, "source_species_id": source, "target_species_id": target,
                      "relation": edge["relation"], "note": _text(edge["note"], "edge note", 2048)})

    links, linked_nodes = [], set()
    for link in raw["node_links"]:
        _keys(link, ("node_id", "species_ids", "historical"), "node association")
        node_id = _uuid(link["node_id"], "node id")
        if type(link["historical"]) is not bool or (node_id not in node_ids) != link["historical"]:
            raise ValueError("Node association history marker conflicts with project")
        if node_id in linked_nodes or type(link["species_ids"]) is not list or not link["species_ids"]:
            raise ValueError("Invalid or duplicate node association")
        species = [_uuid(s, "species id") for s in link["species_ids"]]
        if len(species) != len(set(species)) or not set(species) <= species_ids:
            raise ValueError("Node association references unknown species")
        linked_nodes.add(node_id)
        links.append({"node_id": node_id, "species_ids": species, "historical": link["historical"]})

    reactions, reaction_paths = [], set()
    for reaction in raw["path_reactions"]:
        base_reaction_keys = {"path_id", "stages", "zero_point", "preset", "energy_kind", "historical"}
        optional_reaction_keys = {"reference_signature", "connections", "energy_mode"}
        allowed_reaction_keys = {frozenset(base_reaction_keys | set(optional))
                                 for count in range(len(optional_reaction_keys) + 1)
                                 for optional in itertools.combinations(optional_reaction_keys, count)}
        if frozenset(reaction) not in allowed_reaction_keys:
            raise ValueError("Invalid path reaction shape")
        signature = reaction.get("reference_signature", "")
        if not isinstance(signature, str) or (signature and (len(signature) != 64 or
            any(character not in "0123456789abcdef" for character in signature))):
            raise ValueError("Invalid saved zero-point signature")
        energy_mode = reaction.get("energy_mode", "absolute")
        if energy_mode not in {"absolute", "edge_recursive"}:
            raise ValueError("Invalid path energy normalization mode")
        path_id = _uuid(reaction["path_id"], "path id")
        if path_id in reaction_paths or type(reaction["historical"]) is not bool:
            raise ValueError("Invalid path reaction identity")
        if (path_id not in path_ids) != reaction["historical"]:
            raise ValueError("Path history marker conflicts with project")
        if type(reaction["stages"]) is not list or not reaction["stages"] or len(reaction["stages"]) > MAX_STAGES_PER_PATH:
            raise ValueError("Invalid path stages")
        stage_ids, stages = set(), []
        all_species_seen = set()
        for stage in reaction["stages"]:
            stage_keys = {"id", "role", "label", "predecessor_stage_id", "species", "terms", "confirm_additional_terms",
                          "node_id", "entry_id", "historical"}
            allowed_keys = stage_keys | {"missing", "normalization_confirmed", "normalization_note", "predecessor_stage_ids"}
            if not stage_keys <= set(stage) or not set(stage) <= allowed_keys:
                raise ValueError("Invalid stage shape")
            missing = stage.get("missing", False)
            normalized = stage.get("normalization_confirmed", False)
            normalization_note = _text(stage.get("normalization_note", ""), "normalization note", 1024)
            if type(missing) is not bool or missing and stage["role"] != "transition_state":
                raise ValueError("Only a transition state can be marked NOT FOUND")
            if type(normalized) is not bool:
                raise ValueError("Invalid composition normalization confirmation")
            stage_id = _uuid(stage["id"], "stage id")
            predecessor = (_uuid(stage["predecessor_stage_id"], "predecessor stage id")
                           if stage["predecessor_stage_id"] is not None else None)
            if "predecessor_stage_ids" in stage:
                if type(stage["predecessor_stage_ids"]) is not list or len(stage["predecessor_stage_ids"]) > MAX_STAGES_PER_PATH:
                    raise ValueError("Invalid stage predecessor list")
                predecessors_for_stage = [_uuid(value, "predecessor stage id") for value in stage["predecessor_stage_ids"]]
                if predecessor is not None and predecessor not in predecessors_for_stage:
                    raise ValueError("Primary predecessor must be included in predecessor list")
            else:
                predecessors_for_stage = [predecessor] if predecessor else []
            if len(predecessors_for_stage) != len(set(predecessors_for_stage)):
                raise ValueError("Duplicate stage predecessor")
            if predecessor == stage_id:
                raise ValueError("A stage cannot be its own predecessor")
            if stage_id in stage_ids or stage["role"] not in ROLES or type(stage["historical"]) is not bool:
                raise ValueError("Invalid stage identity or role")
            stage_ids.add(stage_id)
            if type(stage["species"]) is not list or not stage["species"] or len(stage["species"]) > MAX_TERMS_PER_STAGE:
                raise ValueError("Every stage needs an explicit species composition")
            composition = []
            for component in stage["species"]:
                _keys(component, ("species_id", "coefficient"), "stage composition")
                species_id = _uuid(component["species_id"], "composition species id")
                if species_id not in species_ids:
                    raise ValueError("Stage composition references unknown species")
                composition.append({"species_id": species_id, "coefficient": _number(component["coefficient"], "stoichiometric coefficient", positive=True)})
                all_species_seen.add(species_id)
            stage_requires_terms = (energy_mode == "absolute" or not predecessors_for_stage)
            if (type(stage["terms"]) is not list or len(stage["terms"]) > MAX_TERMS_PER_STAGE or
                    (not missing and stage_requires_terms and not stage["terms"]) or
                    (energy_mode == "edge_recursive" and predecessors_for_stage and stage["terms"]) or
                    (missing and stage["terms"])):
                raise ValueError("Every stage needs an explicit energy ledger")
            if type(stage["confirm_additional_terms"]) is not bool:
                raise ValueError("Invalid double-count confirmation")
            terms = []
            for term in stage["terms"]:
                _keys(term, ("species_id", "source_file_id", "job_id", "energy_kind", "coefficient", "system_mode", "reason", "historical"), "ledger term")
                species_id = _uuid(term["species_id"], "ledger species id")
                source_id = _uuid(term["source_file_id"], "ledger source id")
                job_id = _uuid(term["job_id"], "ledger job id")
                if species_id not in species_ids or term["energy_kind"] not in ENERGY_KINDS or term["system_mode"] not in SYSTEM_MODES:
                    raise ValueError("Ledger references unknown species or energy mode")
                if (source_id, job_id) not in species_bindings[species_id]:
                    raise ValueError("Ledger source/job is not bound to its species card")
                if type(term["historical"]) is not bool or (job_id not in source_jobs.get(source_id, set())) != term["historical"]:
                    raise ValueError("Ledger history marker conflicts with current project")
                terms.append({"species_id": species_id, "source_file_id": source_id, "job_id": job_id,
                    "energy_kind": term["energy_kind"], "coefficient": _number(term["coefficient"], "ledger coefficient", nonzero=True),
                    "system_mode": term["system_mode"], "reason": _text(term["reason"], "ledger reason", 512, empty=False),
                    "historical": term["historical"]})
            whole_system_terms = [term for term in terms if term["system_mode"] == "complete_system"]
            component_terms = [term for term in terms if term["system_mode"] == "component"]
            if whole_system_terms and (len(whole_system_terms) > 1 or
                                       component_terms and not stage["confirm_additional_terms"]):
                raise ValueError("Full-system plus additional terms require explicit double-count review")
            node_id = _uuid(stage["node_id"], "stage node id") if stage["node_id"] is not None else None
            entry_id = _uuid(stage["entry_id"], "stage entry id") if stage["entry_id"] is not None else None
            if (node_id is None) != (entry_id is None):
                raise ValueError("Stage must link both node and path entry, or neither")
            linked = entry_links.get(entry_id) if entry_id else None
            missing_model_link = (node_id is not None and
                                  (node_id not in node_ids or linked != (path_id, node_id)))
            if node_id is None and not reaction["historical"] and not allow_unmaterialized:
                # Unapplied editor drafts never belong in a saved project.
                raise ValueError("Saved stages must link to a calculation node and path entry")
            if missing_model_link != stage["historical"]:
                raise ValueError("Stage history marker conflicts with project")
            stages.append({"id": stage_id, "role": stage["role"], "label": _text(stage["label"], "stage label", 256, empty=False),
                "predecessor_stage_id": predecessor, "species": composition, "terms": terms, "node_id": node_id, "entry_id": entry_id,
                "confirm_additional_terms": stage["confirm_additional_terms"], "historical": stage["historical"],
                "missing": missing, "normalization_confirmed": normalized,
                "normalization_note": normalization_note, "predecessor_stage_ids": predecessors_for_stage})
        if any(parent not in stage_ids for stage in stages for parent in stage["predecessor_stage_ids"]):
            raise ValueError("Stage predecessor is not part of this reaction")
        by_id = {stage["id"]: stage for stage in stages}
        indegree = {stage["id"]: len(stage["predecessor_stage_ids"]) for stage in stages}
        children = {stage["id"]: [] for stage in stages}
        for stage in stages:
            for parent in stage["predecessor_stage_ids"]:
                if parent == stage["id"]:
                    raise ValueError("A stage cannot be its own predecessor")
                children[parent].append(stage["id"])
        ready = [stage["id"] for stage in stages if indegree[stage["id"]] == 0]
        topo = []
        while ready:
            current = ready.pop(0)
            topo.append(current)
            for child in children[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(topo) != len(stages):
            raise ValueError("Stage graph contains a cycle")
        expected_pairs = {(parent, stage["id"]) for stage in stages for parent in stage["predecessor_stage_ids"]}
        if "connections" not in reaction:
            connections = [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"gaussianreadpro:{path_id}:{source}:{target}")),
                            "source_stage_id": source, "target_stage_id": target,
                            "confirmed": by_id[target]["normalization_confirmed"],
                            "note": by_id[target]["normalization_note"],
                            "reactants": _stage_stoich(by_id[source]),
                            "products": _stage_stoich(by_id[target]), "terms": []}
                           for source, target in sorted(expected_pairs)]
        else:
            if type(reaction["connections"]) is not list or len(reaction["connections"]) > MAX_EDGES:
                raise ValueError("Invalid reaction connection list")
            connections, connection_ids, connection_pairs = [], set(), set()
            for connection in reaction["connections"]:
                base_connection_keys = {"id", "source_stage_id", "target_stage_id", "confirmed", "note"}
                optional_connection_keys = {"terms", "reactants", "products"}
                if (not base_connection_keys <= set(connection) or
                        not set(connection) <= base_connection_keys | optional_connection_keys or
                        ("reactants" in connection) != ("products" in connection)):
                    raise ValueError("Invalid stage connection shape")
                connection_id = _uuid(connection["id"], "stage connection id")
                source_id = _uuid(connection["source_stage_id"], "connection source stage id")
                target_id = _uuid(connection["target_stage_id"], "connection target stage id")
                pair = (source_id, target_id)
                if connection_id in connection_ids or pair in connection_pairs or pair not in expected_pairs:
                    raise ValueError("Duplicate or undeclared stage connection")
                if type(connection["confirmed"]) is not bool:
                    raise ValueError("Invalid stage connection confirmation")
                reactants = _validate_stoich(connection.get("reactants", _stage_stoich(by_id[source_id])),
                                             species_ids, "reactant")
                products = _validate_stoich(connection.get("products", _stage_stoich(by_id[target_id])),
                                            species_ids, "product")
                connection_ids.add(connection_id); connection_pairs.add(pair)
                connections.append({"id": connection_id, "source_stage_id": source_id,
                                    "target_stage_id": target_id, "confirmed": connection["confirmed"],
                                    "note": _text(connection["note"], "stage connection note", 1024),
                                    "reactants": reactants, "products": products,
                                    "terms": (_validate_terms(connection["terms"], species_ids,
                                        species_bindings, source_jobs, reaction["energy_kind"])
                                        if "terms" in connection else [])})
            if connection_pairs != expected_pairs:
                raise ValueError("Every stage predecessor must have exactly one explicit connection")
        species_by_id = {item["id"]: item for item in species_out}
        for stage in stages:
            after = _stage_atom_vector(stage, species_by_id)
            for predecessor_id in stage["predecessor_stage_ids"]:
                predecessor_stage = by_id[predecessor_id]
                before = _stage_atom_vector(predecessor_stage, species_by_id)
                if before is not None and after is not None and any(
                        abs(before.get(element, 0) - after.get(element, 0)) > 1e-8
                        for element in set(before) | set(after)):
                    delta = {element: after.get(element, 0) - before.get(element, 0)
                             for element in set(before) | set(after)
                             if abs(after.get(element, 0) - before.get(element, 0)) > 1e-8}
                    raise ValueError(f"Unbalanced stage connection {predecessor_stage['label']} → {stage['label']}: {delta}")
        connection_by_pair = {(edge["source_stage_id"], edge["target_stage_id"]): edge for edge in connections}
        for edge in connections:
            reactant_atoms = _stoich_atom_vector(edge["reactants"], species_by_id)
            product_atoms = _stoich_atom_vector(edge["products"], species_by_id)
            if reactant_atoms is not None and product_atoms is not None and any(
                    abs(reactant_atoms.get(element, 0) - product_atoms.get(element, 0)) > 1e-8
                    for element in set(reactant_atoms) | set(product_atoms)):
                delta = {element: product_atoms.get(element, 0) - reactant_atoms.get(element, 0)
                         for element in set(reactant_atoms) | set(product_atoms)
                         if abs(product_atoms.get(element, 0) - reactant_atoms.get(element, 0)) > 1e-8}
                raise ValueError(f"Unbalanced reaction edge {by_id[edge['source_stage_id']]['label']} → "
                                 f"{by_id[edge['target_stage_id']]['label']}: {delta}")
        for source_id, target_id in expected_pairs:
            edge = connection_by_pair[(source_id, target_id)]
            if edge["confirmed"] and not edge["note"].strip():
                raise ValueError("A confirmed stage connection needs a review note")
        zero = reaction["zero_point"]
        if not isinstance(zero, Mapping) or zero.get("kind") not in {"reactant", "stage", "custom_expression", "manual"}:
            raise ValueError("Invalid zero point")
        if zero["kind"] in {"reactant", "stage"}:
            _keys(zero, ("kind", "stage_id"), "zero point")
            stage_id = _uuid(zero["stage_id"], "zero point stage id")
            if stage_id not in stage_ids or (zero["kind"] == "reactant" and
                next(s for s in stages if s["id"] == stage_id)["role"] != "reactant"):
                raise ValueError("Zero point stage does not match the selected reaction")
            zero = {"kind": zero["kind"], "stage_id": stage_id}
        elif zero["kind"] == "custom_expression":
            _keys(zero, ("kind", "expression"), "zero point")
            _text(zero["expression"], "zero point expression", 8192, empty=False)
            zero = {"kind": zero["kind"], "expression": zero["expression"]}
        else:
            _keys(zero, ("kind", "value", "unit"), "zero point")
            value = _number(zero["value"], "manual reference")
            if zero["unit"] not in {"hartree", "kcal_mol", "kj_mol"}:
                raise ValueError("Invalid manual reference unit")
            zero = {"kind": "manual", "value": value, "unit": zero["unit"]}
        reaction_paths.add(path_id)
        if reaction["energy_kind"] not in ENERGY_KINDS:
            raise ValueError("Invalid path energy kind")
        if any(term["energy_kind"] != reaction["energy_kind"] for stage in stages for term in stage["terms"]):
            raise ValueError("All path ledger terms must use its selected energy kind")
        reactions.append({"path_id": path_id, "stages": stages, "connections": connections, "zero_point": zero,
                          "preset": _text(reaction["preset"], "calculation preset", 128, empty=False),
                          "energy_kind": reaction["energy_kind"], "historical": reaction["historical"],
                          "reference_signature": signature, "energy_mode": energy_mode})
    result = {"format_version": FORMAT_VERSION, "species": species_out, "edges": edges,
              "node_links": links, "path_reactions": reactions}
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_BYTES:
        raise ValueError("Reaction network size limit exceeded")
    return result


def read_reaction_network(project: Project):
    raw = project.workspace_state.get("reaction_network_v1")
    return validate_network(raw if raw is not None else empty_network(), project)


def write_reaction_network(project: Project, network):
    normalized = validate_network(network, project)
    workspace = dict(project.workspace_state)
    workspace["reaction_network_v1"] = normalized
    return Project(project.id, project.source_files, project.nodes, project.paths, project.schema_version,
                   project.revision, project.unit_constants_version, project.plot_state, workspace,
                   project.alias_bindings)


def _stage_expression(stage, aliases):
    if stage.get("missing"):
        return edit_expression(None, "", aliases, purpose=ExpressionPurpose.SYSTEM)
    return _terms_expression(stage["terms"], aliases)


def _terms_expression(terms, aliases):
    tree = None
    for term in terms:
        if term["historical"]:
            raise ValueError("Historical source links cannot be deployed")
        ref = EnergyRef(term["source_file_id"], term["job_id"], KindPolicy.FIXED,
                        EnergyKind(term["energy_kind"]))
        atom = ref_ast(ref)
        coefficient = term["coefficient"]
        if coefficient != 1:
            atom = {"type": "binary", "op": "mul", "left": {"type": "scalar", "value": coefficient}, "right": atom}
        tree = atom if tree is None else {"type": "binary", "op": "add", "left": tree, "right": atom}
    return expression_from_ast(tree, aliases, purpose=ExpressionPurpose.SYSTEM)


def _sum_asts(left, right):
    return {"type": "binary", "op": "add", "left": left, "right": right}


def apply_path_recipe(project: Project, raw_network, path_id, *, identity_policy="regenerate"):
    """Materialize one confirmed recipe into existing nodes, entries and path math.

    Every stage is generated as an absolute SYSTEM expression. calculate_path()
    performs the one shared-reference subtraction for every plotted point.

    ``regenerate`` preserves the historical behavior. ``preserve_exclusive``
    reuses only a complete node/entry pair from this path when the node is not
    referenced by another path.
    """
    if identity_policy not in {"regenerate", "preserve_exclusive"}:
        raise ValueError("Unknown path materialization identity policy")
    path_id = canonical_uuid(path_id)
    network = validate_network(raw_network, project, allow_unmaterialized=True)
    recipe = next((item for item in network["path_reactions"] if item["path_id"] == path_id), None)
    path = next((item for item in project.paths if item.id == path_id), None)
    if recipe is None or path is None or recipe["historical"]:
        raise ValueError("Recipe must refer to a current project path")
    unconfirmed_edges = [edge for edge in recipe["connections"] if not edge["confirmed"] or not edge["note"].strip()]
    if unconfirmed_edges:
        raise ValueError("Every reaction graph edge must be explicitly confirmed with a review note")
    if recipe["energy_mode"] == "edge_recursive" and any(not edge["terms"] for edge in recipe["connections"]):
        raise ValueError("Every edge-recursive connection needs an explicit local energy ledger")
    remaining = {stage["id"]: stage for stage in recipe["stages"]}
    ordered_stages, emitted = [], set()
    while remaining:
        ready = [stage for stage in remaining.values()
                 if set(stage["predecessor_stage_ids"]) <= emitted]
        if not ready:
            raise ValueError("Stage graph contains a cycle")
        for stage in ready:
            ordered_stages.append(stage)
            emitted.add(stage["id"])
            del remaining[stage["id"]]
    old_nodes = {entry.node_id for entry in path.entries}
    nodes = {node.id: node for node in project.nodes}
    entries_by_pair = {(entry.node_id, entry.id): entry for entry in path.entries}
    other_path_nodes = {entry.node_id for other in project.paths if other.id != path_id
                        for entry in other.entries}
    reused_node_ids, reused_entry_ids = set(), set()
    energy_context = EnergyContext({source.id: source for source in project.source_files},
                                   EnergyKind(recipe["energy_kind"]))
    generated, entries, links = [], [], []
    stages = []
    absolute_asts = {}
    stage_by_id = {stage["id"]: stage for stage in ordered_stages}
    connections_by_target = {}
    for edge in recipe["connections"]:
        connections_by_target.setdefault(edge["target_stage_id"], []).append(edge)
    for index, stage in enumerate(ordered_stages):
        if stage["historical"]:
            raise ValueError("Historical stage cannot be deployed")
        if not stage["missing"] and (not stage["normalization_confirmed"] or
                                     not stage["normalization_note"].strip()):
            raise ValueError(f"Stage {stage['label']} has not confirmed composition and shared-reference comparability")
        if recipe["energy_mode"] == "edge_recursive" and stage["predecessor_stage_ids"]:
            candidates = []
            if stage.get("missing"):
                raise ValueError(f"NOT FOUND stage {stage['label']} has no numeric recursive energy")
            for edge in connections_by_target.get(stage["id"], []):
                parent_ast = absolute_asts.get(edge["source_stage_id"])
                if parent_ast is None:
                    raise ValueError("Cannot recursively normalize a stage after a missing-energy predecessor")
                delta_expression = _terms_expression(edge["terms"], project.alias_bindings)
                if delta_expression.draft_error or delta_expression.ast is None:
                    raise ValueError("Local edge energy expression is invalid")
                candidate_ast = _sum_asts(parent_ast, delta_expression.ast)
                candidate_expression = expression_from_ast(candidate_ast, project.alias_bindings,
                                                           purpose=ExpressionPurpose.SYSTEM)
                candidate_value = evaluate_expression(candidate_expression, energy_context)
                if not candidate_value.valid:
                    raise ValueError(f"Cannot evaluate recursive edge {edge['id']}: {candidate_value.diagnostics}")
                candidates.append((edge, candidate_ast, candidate_value.value_hartree))
            if not candidates:
                raise ValueError(f"Stage {stage['label']} has no usable incoming local-energy ledger")
            baseline = candidates[0][2]
            for edge, _, value in candidates[1:]:
                if abs(value - baseline) > 1e-8:
                    details = ", ".join(f"{item[0]['id'][:8]}={item[2]:.12f} Eh" for item in candidates)
                    raise ValueError(f"Reconvergent routes to {stage['label']} disagree beyond 1e-8 Eh: {details}")
            absolute_asts[stage["id"]] = candidates[0][1]
            expression = expression_from_ast(candidates[0][1], project.alias_bindings,
                                             purpose=ExpressionPurpose.SYSTEM)
        else:
            expression = _stage_expression(stage, project.alias_bindings)
            if recipe["energy_mode"] == "edge_recursive" and not stage.get("missing"):
                absolute_asts[stage["id"]] = expression.ast
        if expression.draft_error and not stage.get("missing"):
            raise ValueError("Stage expression is invalid")
        requested_node_id, requested_entry_id = stage.get("node_id"), stage.get("entry_id")
        if identity_policy == "preserve_exclusive" and (requested_node_id is not None or requested_entry_id is not None):
            if requested_node_id is None or requested_entry_id is None:
                raise ValueError("Preserved stage identity needs both a node and path entry")
            pair = (requested_node_id, requested_entry_id)
            old_entry = entries_by_pair.get(pair)
            old_node = nodes.get(requested_node_id)
            if old_entry is None or old_node is None:
                raise ValueError("Preserved node/entry identity does not match one entry on the target path")
            if requested_node_id in other_path_nodes:
                raise ValueError("Shared nodes require creating a new path before conversion")
            if requested_node_id in reused_node_ids or requested_entry_id in reused_entry_ids:
                raise ValueError("A preserved node or entry identity cannot be mapped more than once")
            node_id, entry_id = requested_node_id, requested_entry_id
            node = ProfileNode(node_id, stage["label"], expression, stage["role"], old_node.display)
            entry = PathEntry(entry_id, node_id, index, old_entry.display_override)
            reused_node_ids.add(node_id)
            reused_entry_ids.add(entry_id)
        else:
            node_id, entry_id = new_id(), new_id()
            node = ProfileNode(node_id, stage["label"], expression, stage["role"])
            entry = PathEntry(entry_id, node_id, index)
        nodes[node_id] = node
        generated.append(node_id)
        entries.append(entry)
        species_ids = list(dict.fromkeys(component["species_id"] for component in stage["species"]))
        links.append({"node_id": node_id, "species_ids": species_ids, "historical": False})
        stages.append({**stage, "node_id": node_id, "entry_id": entry_id, "historical": False})

    by_stage = {stage["id"]: stage for stage in stages}
    zero = recipe["zero_point"]
    if zero["kind"] in {"reactant", "stage"}:
        if by_stage[zero["stage_id"]].get("missing"):
            raise ValueError("A NOT FOUND transition state cannot be the zero point")
        reference = _stage_expression(by_stage[zero["stage_id"]], project.alias_bindings)
    elif zero["kind"] == "custom_expression":
        compiled = compile_expression(zero["expression"], project.alias_bindings, purpose=ExpressionPurpose.SYSTEM)
        if not compiled.valid:
            raise ValueError("Custom zero-point expression is invalid")
        reference = compiled.expression
    else:
        reference = expression_from_ast({"type": "energy_constant", "value": zero["value"], "unit": zero["unit"]},
                                       project.alias_bindings, purpose=ExpressionPurpose.SYSTEM)
    old_other_refs = {entry.node_id for other in project.paths if other.id != path_id for entry in other.entries}
    nodes = tuple(node for node in nodes.values() if node.id not in old_nodes or node.id in old_other_refs or node.id in generated)
    updated_path = ReactionPath(path.id, path.label, tuple(entries), EnergyKind(recipe["energy_kind"]), reference,
                                CalculationMode.RELATIVE, path.unit, path.color, path.visible)
    paths = tuple(updated_path if item.id == path_id else item for item in project.paths)
    used_old = old_nodes & old_other_refs
    network["node_links"] = [link for link in network["node_links"]
                             if link["node_id"] not in old_nodes or link["node_id"] in used_old]
    network["node_links"].extend(links)
    network["path_reactions"] = [{**recipe, "stages": stages,
        "reference_signature": reference_signature(reference)} if item["path_id"] == path_id else item
                                  for item in network["path_reactions"]]
    result = Project(project.id, project.source_files, nodes, paths, project.schema_version,
                     project.revision + 1, project.unit_constants_version, project.plot_state,
                     project.workspace_state, project.alias_bindings)
    return write_reaction_network(result, network)


def reconcile_network(project: Project):
    """Retain removed-source references as marked historical rather than relinking."""
    raw = project.workspace_state.get("reaction_network_v1")
    if raw is None:
        return empty_network()
    network = json.loads(json.dumps(snapshot_to_dict(raw), ensure_ascii=False))
    source_jobs = {s.id: {j.id for j in s.jobs} for s in project.source_files}
    node_ids = {node.id for node in project.nodes}
    path_ids = {path.id for path in project.paths}
    entry_links = {entry.id: (path.id, entry.node_id) for path in project.paths for entry in path.entries}
    for item in network.get("species", []):
        for binding in item.get("bindings", []):
            binding["historical"] = binding.get("job_id") not in source_jobs.get(binding.get("source_file_id"), set())
    for link in network.get("node_links", []):
        link["historical"] = link.get("node_id") not in node_ids
    for reaction in network.get("path_reactions", []):
        reaction["historical"] = reaction.get("path_id") not in path_ids
        for stage in reaction.get("stages", []):
            node_id, entry_id = stage.get("node_id"), stage.get("entry_id")
            stage["historical"] = bool(node_id and
                (node_id not in node_ids or entry_links.get(entry_id) != (reaction.get("path_id"), node_id)))
            for term in stage.get("terms", []):
                term["historical"] = term.get("job_id") not in source_jobs.get(term.get("source_file_id"), set())
        for edge in reaction.get("connections", []):
            for term in edge.get("terms", []):
                term["historical"] = term.get("job_id") not in source_jobs.get(term.get("source_file_id"), set())
    return network
