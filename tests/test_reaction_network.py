from copy import deepcopy
import pytest

from gaussianreadpro.core import EnergyKind, Project, ReactionPath, calculate_path, parse_log
from gaussianreadpro.core.models import new_id
from gaussianreadpro.core.reaction_network import (apply_path_recipe, empty_network,
    normalize_path_graph, parse_molecular_formula, read_reaction_network, validate_network)
from gaussianreadpro.storage import ProjectRepository


def _source(tmp_path, name, gibbs):
    path = tmp_path / f"{name}.log"
    scf = gibbs - .03
    path.write_text("SYNTHETIC REACTION NETWORK\nEntering Gaussian System\n"
        f" SCF Done: E(RB3LYP) = {scf:.12f} A.U.\n"
        " Thermal correction to Gibbs Free Energy= 0.030000000000\n"
        f" Sum of electronic and thermal Free Energies= {gibbs + .0000004:.12f}\n"
        " Normal termination of Gaussian 16\n", encoding="utf-8")
    return parse_log(path).source


def test_gibbs_total_is_same_job_scf_plus_correction_and_keeps_both_sources(tmp_path):
    source = _source(tmp_path, "reactant", -10.0)
    project = Project(new_id(), source_files=(source,))
    from gaussianreadpro.core import EnergyRef, compile_expression, evaluate_expression, EnergyContext
    from gaussianreadpro.core.models import KindPolicy
    ref = EnergyRef(source.id, source.jobs[0].id, KindPolicy.FIXED, EnergyKind.GIBBS_TOTAL)
    expr = compile_expression("@{r}", {"r": ref}).expression
    result = evaluate_expression(expr, EnergyContext({source.id: source}, EnergyKind.GIBBS_TOTAL))
    assert result.value_hartree == pytest.approx(-10.0 - .03 + .03)
    assert {(d.kind, d.source_line) for d in result.dependencies} == {
        (EnergyKind.SCF, source.jobs[0].energies[EnergyKind.SCF].source_line),
        (EnergyKind.GIBBS_CORRECTION, source.jobs[0].energies[EnergyKind.GIBBS_CORRECTION].source_line)}
    assert not any(d.code == "gaussian_gibbs_total_mismatch" for d in result.diagnostics)


def test_gibbs_total_is_unavailable_without_either_addend(tmp_path):
    path = tmp_path / "scf_and_printed_total.log"
    path.write_text("Entering Gaussian System\nSCF Done: E(RHF) = -1.0 A.U.\n"
                    "Sum of electronic and thermal Free Energies= -0.9\n"
                    "Normal termination of Gaussian 16\n", encoding="utf-8")
    source = parse_log(path).source
    from gaussianreadpro.core import select_job
    assert not select_job(source, EnergyKind.GIBBS_TOTAL).available


def test_gibbs_total_mismatch_blocks_automatic_path_value(tmp_path):
    from gaussianreadpro.core import EnergyRef, compile_expression, evaluate_expression, EnergyContext
    from gaussianreadpro.core.models import KindPolicy

    path = tmp_path / "mismatch.log"
    path.write_text("Entering Gaussian System\n SCF Done: E(RHF) = -1.000000 A.U.\n"
                    " Thermal correction to Gibbs Free Energy= 0.100000\n"
                    " Sum of electronic and thermal Free Energies= -0.890000\n"
                    " Normal termination of Gaussian 16\n", encoding="utf-8")
    source = parse_log(path).source
    ref = EnergyRef(source.id, source.jobs[0].id, KindPolicy.FIXED, EnergyKind.GIBBS_TOTAL)
    expression = compile_expression("@{a}", {"a": ref}).expression
    result = evaluate_expression(expression, EnergyContext({source.id: source}, EnergyKind.GIBBS_TOTAL))
    assert result.value_hartree is None
    assert any(d.code == "gaussian_gibbs_total_mismatch" and d.severity.value == "error"
               for d in result.diagnostics)


def test_recipe_materializes_absolute_nodes_with_one_shared_zero_and_roundtrips(tmp_path):
    sources = tuple(_source(tmp_path, name, energy) for name, energy in
                    (("R", -10.0), ("TS", -9.98), ("P", -10.02)))
    path_id = new_id()
    path = ReactionPath(path_id, "A → TS → P", ())
    project = Project(new_id(), source_files=sources, paths=(path,))
    species = [{"id": new_id(), "name": name, "starred": False,
                "bindings": [{"source_file_id": source.id, "job_id": source.jobs[0].id, "historical": False}]}
               for name, source in zip(("A", "TS", "P"), sources)]
    stages = []
    for role, label, material, source in zip(("reactant", "transition_state", "product"),
            ("A", "TS", "P"), species, sources):
        stages.append({"id": new_id(), "role": role, "label": label,
            "predecessor_stage_id": stages[-1]["id"] if stages else None,
            "species": [{"species_id": material["id"], "coefficient": 1.0}],
            "terms": [{"species_id": material["id"], "source_file_id": source.id,
                "job_id": source.jobs[0].id, "energy_kind": "gibbs_total", "coefficient": 1.0,
                "system_mode": "complete_system", "reason": "已选择完整体系作业", "historical": False}],
            "confirm_additional_terms": False, "node_id": None, "entry_id": None, "historical": False})
        stages[-1]["normalization_confirmed"] = True
        stages[-1]["normalization_note"] = "受控夹具：各阶段为同一反应清单"
    network = empty_network()
    network["species"] = species
    network["path_reactions"] = [{"path_id": path_id, "stages": stages,
        "zero_point": {"kind": "reactant", "stage_id": stages[0]["id"]},
        "preset": "relative_energy", "energy_kind": "gibbs_total", "historical": False}]
    built = apply_path_recipe(project, network, path_id)
    assert built.revision == project.revision + 1
    result = calculate_path(built, path_id)
    assert [node.relative_hartree for node in result.nodes] == pytest.approx((0, .02, -.02), abs=1e-12)
    persisted_network = read_reaction_network(built)
    assert all(stage["node_id"] and stage["entry_id"] for stage in persisted_network["path_reactions"][0]["stages"])
    target = tmp_path / "network.grproj"
    with ProjectRepository(target, create=True) as repository:
        repository.save(built)
    with ProjectRepository(target, read_only=True) as repository:
        reopened = repository.load()
    assert read_reaction_network(reopened) == persisted_network
    assert calculate_path(reopened, path_id).nodes == result.nodes

    # Element vectors are checked on every explicitly connected stage pair.
    formula_network = read_reaction_network(built)
    for item in formula_network["species"]:
        item["formula"] = "C6H5NO2"
    validate_network(formula_network, built)
    product_species = formula_network["species"][-1]
    product_species["formula"] = "C6H5NO"
    with pytest.raises(ValueError, match="Unbalanced stage connection"):
        validate_network(formula_network, built)


def test_molecular_formula_parser_supports_nested_groups_and_rejects_bad_syntax():
    assert parse_molecular_formula("C6H5(B(OH)2)") == {"C": 6, "H": 7, "B": 1, "O": 2}
    with pytest.raises(ValueError):
        parse_molecular_formula("C6H5(OH")


def test_graph_energy_normalizer_expands_f58_recursion_and_checks_reconvergence():
    first, second = "F50", "F58"
    delta_58_50 = -0.048504
    normalized = normalize_path_graph([first, second],
        [{"source_stage_id": first, "target_stage_id": second}],
        {first: 0.007441}, {(first, second): delta_58_50})
    assert normalized["relative_energies"][second] == pytest.approx(-0.041063, abs=1e-12)

    graph = ["root", "left", "right", "join"]
    edges = [{"source_stage_id": "root", "target_stage_id": "left"},
             {"source_stage_id": "root", "target_stage_id": "right"},
             {"source_stage_id": "left", "target_stage_id": "join"},
             {"source_stage_id": "right", "target_stage_id": "join"}]
    deltas = {("root", "left"): .1, ("root", "right"): .2,
              ("left", "join"): .2, ("right", "join"): .1}
    assert normalize_path_graph(graph, edges, {"root": 0.0}, deltas)["relative_energies"]["join"] == pytest.approx(.3)
    deltas[("right", "join")] += .01
    with pytest.raises(ValueError, match="Reconvergent routes"):
        normalize_path_graph(graph, edges, {"root": 0.0}, deltas)


def test_edge_recursive_f58_ledger_materializes_as_one_shared_zero(tmp_path):
    energies = {"E50": -100.0, "E36": -40.0, "E3": -60.007441,
                "E58": -100.048504}
    sources = {name: _source(tmp_path, name, value) for name, value in energies.items()}
    path_id = new_id()
    path = ReactionPath(path_id, "F50 → F58 (recursive)", ())
    project = Project(new_id(), source_files=tuple(sources.values()), paths=(path,))
    species = []
    for name, source in sources.items():
        species.append({"id": new_id(), "name": name, "starred": False,
            "bindings": [{"source_file_id": source.id, "job_id": source.jobs[0].id, "historical": False}]})
    by_name = {item["name"]: item for item in species}
    root_id, product_id, edge_id = new_id(), new_id(), new_id()

    def term(name, coefficient, mode="component"):
        source = sources[name]
        return {"species_id": by_name[name]["id"], "source_file_id": source.id,
            "job_id": source.jobs[0].id, "energy_kind": "gibbs_total", "coefficient": coefficient,
            "system_mode": mode, "reason": "工作簿公式的受控递推夹具", "historical": False}

    stages = [
        {"id": root_id, "role": "reactant", "label": "F50", "predecessor_stage_id": None,
         "species": [{"species_id": by_name["E50"]["id"], "coefficient": 1}],
         "terms": [term("E50", 1)],
         "confirm_additional_terms": False, "node_id": None, "entry_id": None,
         "historical": False, "normalization_confirmed": True,
         "normalization_note": "绝对阶段值取 E50；全路径统一零点为 E36 + E3"},
        {"id": product_id, "role": "product", "label": "F58", "predecessor_stage_id": root_id,
         "species": [{"species_id": by_name["E58"]["id"], "coefficient": 1}], "terms": [],
         "confirm_additional_terms": False, "node_id": None, "entry_id": None,
         "historical": False, "normalization_confirmed": True,
         "normalization_note": "F58 = E58 − E50 + F50"}]
    network = empty_network()
    network["species"] = species
    network["path_reactions"] = [{"path_id": path_id, "stages": stages,
        "connections": [{"id": edge_id, "source_stage_id": root_id,
            "target_stage_id": product_id, "confirmed": True,
            "note": "F58 递推式已按工作簿公式逐项核对",
            "terms": [term("E58", 1, "complete_system"), term("E50", -1, "complete_system")]}],
        "zero_point": {"kind": "manual", "value": -100.007441, "unit": "hartree"}, "preset": "relative_energy",
        "energy_kind": "gibbs_total", "energy_mode": "edge_recursive", "historical": False}]
    built = apply_path_recipe(project, network, path_id)
    result = calculate_path(built, path_id)
    assert [node.relative_hartree for node in result.nodes] == pytest.approx([0.007441, -0.041063], abs=1e-10)
    saved_recipe = read_reaction_network(built)["path_reactions"][0]
    assert saved_recipe["energy_mode"] == "edge_recursive"
    assert saved_recipe["connections"][0]["terms"] == network["path_reactions"][0]["connections"][0]["terms"]


def test_workbook_f15_f22_ledger_formulas_run_through_path_calculator(tmp_path):
    cases = [
        ("F15", {"E15": 5.043120, "E13": 3.0, "E11": 4.0, "E12": 2.0},
         [("E15", 1), ("E13", -1), ("E11", -1), ("E12", 1)], .043120),
        ("F22", {"E22": 9.040207, "E13": 3.0, "E11": 4.0, "E12": 2.0, "E10": 8.0, "E3": 12.0},
         [("E22", 1), ("E13", -1), ("E11", -1), ("E12", 1), ("E10", 1), ("E3", -1)], .040207),
    ]
    sources, species, cases_terms = [], [], []
    for label, values, terms, expected in cases:
        resolved_terms = []
        for name, energy in values.items():
            source = _source(tmp_path, f"{label}_{name}", energy)
            sources.append(source)
            card = {"id": new_id(), "name": name, "starred": False,
                    "bindings": [{"source_file_id": source.id, "job_id": source.jobs[0].id,
                                  "historical": False}]}
            species.append(card)
            resolved_terms.append((card, source, dict((term_name, coefficient) for term_name, coefficient in terms)[name]))
        cases_terms.append((label, resolved_terms, expected))

    path_id = new_id()
    path = ReactionPath(path_id, "F15 / F22 workbook ledger", ())
    project = Project(new_id(), source_files=tuple(sources), paths=(path,))
    stages = []
    for label, resolved_terms, _ in cases_terms:
        ledger = [{"species_id": card["id"], "source_file_id": source.id, "job_id": source.jobs[0].id,
                   "energy_kind": "gibbs_total", "coefficient": coefficient, "system_mode": "component",
                   "reason": f"Synthetic workbook formula term for {label}", "historical": False}
                  for card, source, coefficient in resolved_terms]
        stages.append({"id": new_id(), "role": "intermediate", "label": label,
            "predecessor_stage_id": None, "species": [{"species_id": resolved_terms[0][0]["id"], "coefficient": 1}],
            "terms": ledger, "confirm_additional_terms": False, "node_id": None, "entry_id": None,
            "historical": False, "normalization_confirmed": True,
            "normalization_note": "受控账本夹具；逐项映射自工作簿公式"})
    network = empty_network()
    network["species"] = species
    network["path_reactions"] = [{"path_id": path_id, "stages": stages,
        "zero_point": {"kind": "manual", "value": 0, "unit": "hartree"},
        "preset": "relative_energy", "energy_kind": "gibbs_total", "historical": False}]
    built = apply_path_recipe(project, network, path_id)
    values = [node.relative_hartree for node in calculate_path(built, path_id).nodes]
    assert values == pytest.approx([case[2] for case in cases_terms], abs=1e-10)


def test_stage_dag_branch_merge_materializes_topologically_and_keeps_all_plot_edges(tmp_path):
    from gaussianreadpro.core.plot_spec import build_plot_spec, plot_payload

    sources = tuple(_source(tmp_path, name, energy) for name, energy in
                    (("A", -10), ("B", -9.9), ("C", -9.8), ("D", -9.7)))
    path_id = new_id()
    path = ReactionPath(path_id, "A → {B, C} → D", ())
    project = Project(new_id(), source_files=sources, paths=(path,))
    species, stages = [], []
    identifiers = [new_id() for _ in sources]
    for index, (source, label) in enumerate(zip(sources, "ABCD")):
        species.append({"id": identifiers[index], "name": label, "formula": "C2H6", "starred": False,
                        "bindings": [{"source_file_id": source.id, "job_id": source.jobs[0].id, "historical": False}]})
        parent_ids = ([stages[0]["id"]] if index in (1, 2) else
                      [stages[1]["id"], stages[2]["id"]] if index == 3 else [])
        stages.append({"id": new_id(), "role": "intermediate", "label": label,
            "predecessor_stage_id": parent_ids[0] if parent_ids else None,
            "predecessor_stage_ids": parent_ids,
            "species": [{"species_id": identifiers[index], "coefficient": 1}],
            "terms": [{"species_id": identifiers[index], "source_file_id": source.id,
                "job_id": source.jobs[0].id, "energy_kind": "gibbs_total", "coefficient": 1,
                "system_mode": "complete_system", "reason": "verified fixture system", "historical": False}],
            "confirm_additional_terms": False, "node_id": None, "entry_id": None, "historical": False,
            "normalization_confirmed": True, "normalization_note": "same atom vector"})
    network = empty_network()
    network["species"] = species
    connections = []
    for stage in stages:
        for parent in stage["predecessor_stage_ids"]:
            connections.append({"id": new_id(), "source_stage_id": parent,
                "target_stage_id": stage["id"], "confirmed": True,
                "note": "each graph edge reviewed in the fixture"})
    network["path_reactions"] = [{"path_id": path_id, "stages": stages,
        "connections": connections,
        "zero_point": {"kind": "stage", "stage_id": stages[0]["id"]}, "preset": "relative_energy",
        "energy_kind": "gibbs_total", "historical": False}]
    built = apply_path_recipe(project, network, path_id)
    normalized = read_reaction_network(built)["path_reactions"][0]["stages"]
    assert [item["label"] for item in normalized] == ["A", "B", "C", "D"]
    result = calculate_path(built, path_id)
    spec = build_plot_spec(built, (result,))
    payload = plot_payload(spec, path_id)
    points = payload["paths"][0]["points"]
    assert len(points[-1]["predecessor_entry_ids"]) == 2
    assert len(payload["paths"][0]["curve_runs"]) == 4

    stoich_network = deepcopy(network)
    first_edge = stoich_network["path_reactions"][0]["connections"][0]
    first_edge["reactants"] = [{"species_id": identifiers[0], "coefficient": 2}]
    first_edge["products"] = [{"species_id": identifiers[1], "coefficient": 2}]
    normalized_stoich = validate_network(stoich_network, project, allow_unmaterialized=True)
    saved_edge = normalized_stoich["path_reactions"][0]["connections"][0]
    assert saved_edge["reactants"][0]["coefficient"] == 2
    first_edge["products"][0]["coefficient"] = 1
    with pytest.raises(ValueError, match="Unbalanced reaction edge"):
        validate_network(stoich_network, project, allow_unmaterialized=True)

    unchecked = deepcopy(network)
    unchecked["path_reactions"][0]["connections"][0]["confirmed"] = False
    with pytest.raises(ValueError, match="explicitly confirmed"):
        apply_path_recipe(project, unchecked, path_id)

    cyclic = read_reaction_network(built)
    recipe = cyclic["path_reactions"][0]
    recipe["stages"][0]["predecessor_stage_id"] = recipe["stages"][3]["id"]
    recipe["stages"][0]["predecessor_stage_ids"] = [recipe["stages"][3]["id"]]
    with pytest.raises(ValueError, match="cycle"):
        validate_network(cyclic, built)


def test_network_rejects_dangling_live_bindings_and_invalid_coefficients():
    project = Project(new_id())
    network = empty_network()
    network["species"] = [{"id": new_id(), "name": "A", "starred": False,
                           "bindings": [{"source_file_id": new_id(), "job_id": new_id(), "historical": False}]}]
    with pytest.raises(ValueError):
        validate_network(network, project)


def test_builder_window_previews_whole_path_and_preserves_draft_links(tmp_path):
    from PySide6.QtCore import QObject, Signal, Qt
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog

    class Controller(QObject):
        busyChanged = Signal(bool, str)
        failed = Signal(str)

    app = QApplication.instance() or QApplication([])
    sources = tuple(_source(tmp_path, name, value) for name, value in
                    (("A", -5), ("B", -5), ("TS_AB", -9.98), ("C", -5.01), ("D", -5.01)))
    first_path, second_path = ReactionPath(new_id(), "unrelated", ()), ReactionPath(new_id(), "reaction", ())
    controller = Controller()
    controller.project = Project(new_id(), source_files=sources, paths=(first_path, second_path))
    dialog = ReactionBuilderDialog(controller, path_id=second_path.id)
    dialog._ask_draft_exit = lambda _reason: "discard"
    assert dialog.path_combo.currentData() == second_path.id
    assert callable(dialog._new_path)
    for source in sources:
        dialog.source_combo.setCurrentIndex(dialog.source_combo.findData(source.id))
        dialog.species_name.setText(source.display_name.removesuffix(".log"))
        dialog._add_species()
    species_ids = [item["id"] for item in dialog.network["species"]]
    for role, ids in (("reactant", species_ids[:2]), ("transition_state", species_ids[2:3]),
                      ("product", species_ids[3:])):
        dialog.stage_role.setCurrentIndex(dialog.stage_role.findData(role))
        if role == "transition_state":
            dialog.predecessor_combo.setCurrentIndex(dialog.predecessor_combo.findData(
                dialog._current_recipe()["stages"][0]["id"]))
        elif role == "product":
            dialog.predecessor_combo.setCurrentIndex(dialog.predecessor_combo.findData(
                dialog._current_recipe()["stages"][-1]["id"]))
        dialog._add_stage(ids)
        if role == "product":
            dialog.additional_predecessor_combo.setCurrentIndex(dialog.additional_predecessor_combo.findData(
                dialog._current_recipe()["stages"][0]["id"]))
            dialog._add_stage_predecessor()
        dialog.species_list.clearSelection()
        for index in range(dialog.species_list.count()):
            item = dialog.species_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) in ids:
                item.setSelected(True)
        dialog.system_mode.setCurrentIndex(dialog.system_mode.findData(
            "complete_system" if role == "transition_state" else "component"))
        dialog._add_terms()
        assert dialog._current_stage()["terms"], dialog.preview.text()
        dialog.normalization_confirmed.setChecked(True)
        dialog.normalization_note.setText("受控夹具：已核对本阶段与统一零点的物质清单")
        dialog._update_stage()
        for row in range(dialog.connection_list.count()):
            edge_item = dialog.connection_list.item(row)
            edge = next(value for value in dialog._current_recipe()["connections"]
                        if value["id"] == edge_item.data(Qt.ItemDataRole.UserRole))
            dialog.connection_list.setCurrentRow(row)
            dialog.connection_confirmed.setChecked(True)
            dialog.connection_note.setText("受控夹具：逐边核对元素组成与共同参考")
            dialog._confirm_connection()
    assert all(edge["confirmed"] and edge["note"] for edge in dialog._current_recipe()["connections"]), dialog._current_recipe()["connections"]
    prepared = apply_path_recipe(dialog.project, dialog.network, second_path.id)
    assert all(stage["node_id"] is None for stage in dialog._current_recipe()["stages"])
    assert [node.relative_hartree for node in calculate_path(prepared, second_path.id).nodes] == pytest.approx(
        (0, .02, -.02), abs=1e-12)
    assert read_reaction_network(prepared)["path_reactions"][0]["zero_point"]["kind"] == "reactant"
    from gaussianreadpro.core.plot_spec import build_plot_spec, compare_points
    spec = build_plot_spec(prepared, (calculate_path(prepared, second_path.id),))
    first_entry, ts_entry = spec.paths[1].points[:2]
    assert ts_entry.predecessor_entry_id == first_entry.entry_id
    assert len(spec.paths[1].points[-1].predecessor_entry_ids) == 2
    assert compare_points(spec, [(second_path.id, first_entry.entry_id),
                                 (second_path.id, ts_entry.entry_id)], "hartree")["barrier_eligible"]
    wanted_zero = ("stage", dialog._current_recipe()["stages"][-1]["id"])
    zero_index = next((i for i in range(dialog.zero_combo.count())
                       if dialog.zero_combo.itemData(i) == wanted_zero), -1)
    assert zero_index >= 0, [dialog.zero_combo.itemData(i) for i in range(dialog.zero_combo.count())]
    dialog.zero_combo.setCurrentIndex(zero_index)
    assert not any(edge["confirmed"] for edge in dialog._current_recipe()["connections"])
    assert not any(stage["normalization_confirmed"] for stage in dialog._current_recipe()["stages"])
    for stage in dialog._current_recipe()["stages"]:
        row = next(index for index in range(dialog.stage_list.count())
                   if dialog.stage_list.item(index).data(Qt.ItemDataRole.UserRole) == stage["id"])
        dialog.stage_list.setCurrentRow(row)
        dialog.normalization_confirmed.setChecked(True)
        dialog.normalization_note.setText("受控夹具：切换零点后重新核对本阶段")
        dialog._update_stage()
        for edge_row in range(dialog.connection_list.count()):
            edge_item = dialog.connection_list.item(edge_row)
            dialog.connection_list.setCurrentRow(edge_row)
            dialog.connection_confirmed.setChecked(True)
            dialog.connection_note.setText("受控夹具：切换零点后重新核对该边")
            dialog._confirm_connection()
    shifted = apply_path_recipe(dialog.project, dialog.network, second_path.id)
    assert [node.relative_hartree for node in calculate_path(shifted, second_path.id).nodes] == pytest.approx(
        (.02, .04, 0), abs=1e-12)
    assert [node.absolute_hartree for node in calculate_path(shifted, second_path.id).nodes] == pytest.approx(
        (-10, -9.98, -10.02), abs=1e-12)
    dialog.stage_role.setCurrentIndex(dialog.stage_role.findData("transition_state"))
    dialog.missing_transition.setChecked(True)
    dialog.species_name.setText("TS_NOT_FOUND")
    dialog._add_placeholder_species()
    dialog._add_stage([dialog.network["species"][-1]["id"]])
    dialog.connection_confirmed.setChecked(True)
    dialog.connection_note.setText("受控夹具：缺值 TS 的相邻反应边已逐边确认")
    dialog._confirm_connection()
    assert dialog._current_recipe()["energy_mode"] == "absolute", dialog._current_recipe()
    assert all(stage["missing"] or stage["terms"] for stage in dialog._current_recipe()["stages"]), [
        (stage["label"], stage["missing"], stage["terms"], stage["predecessor_stage_ids"])
        for stage in dialog._current_recipe()["stages"]]
    with_missing = apply_path_recipe(dialog.project, dialog.network, second_path.id)
    assert calculate_path(with_missing, second_path.id).nodes[-1].relative_hartree is None
    missing_plot = build_plot_spec(with_missing, (calculate_path(with_missing, second_path.id),))
    assert missing_plot.paths[1].points[-1].missing_transition_state
    dialog.close()
    app.processEvents()


def test_builder_quick_deploy_previews_selected_relationships_as_parallel_stages(monkeypatch):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication, QMessageBox
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog

    class Controller(QObject):
        busyChanged = Signal(bool, str)
        failed = Signal(str)

    app = QApplication.instance() or QApplication([])
    path = ReactionPath(new_id(), "branch preview", ())
    controller = Controller()
    controller.project = Project(new_id(), paths=(path,))
    dialog = ReactionBuilderDialog(controller, path_id=path.id)
    dialog._ask_draft_exit = lambda _reason: "discard"
    dialog.network["species"] = [{"id": new_id(), "name": name, "starred": False, "bindings": [], "formula": "C2H6"}
                                 for name in ("A", "B", "C")]
    a, b, c = [item["id"] for item in dialog.network["species"]]
    dialog.stage_role.setCurrentIndex(dialog.stage_role.findData("reactant"))
    dialog._add_stage([a])
    root = dialog._current_recipe()["stages"][0]
    dialog.network["edges"] = [{"id": new_id(), "source_species_id": a, "target_species_id": target,
                                "relation": "successor", "note": "fixture"} for target in (b, c)]
    dialog._render_edges()
    dialog.edge_list.item(0).setSelected(True)
    dialog.edge_list.item(1).setSelected(True)
    dialog.predecessor_combo.setCurrentIndex(dialog.predecessor_combo.findData(root["id"]))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    dialog._deploy_edge()
    candidates = dialog._current_recipe()["stages"][1:]
    assert [stage["species"][0]["species_id"] for stage in candidates] == [b, c]
    assert all(stage["predecessor_stage_ids"] == [root["id"]] for stage in candidates)
    assert all({"reactants", "products", "terms"} <= set(edge)
               for edge in dialog._current_recipe()["connections"])
    dialog.close()
    app.processEvents()


def test_starred_species_survives_source_removal_as_historical_and_marks_plot(tmp_path):
    from gaussianreadpro.core.plot_spec import build_plot_spec
    from gaussianreadpro.core.project_edits import remove_sources
    from gaussianreadpro.core.reaction_network import reference_signature

    source = _source(tmp_path, "A", -5)
    path_id, species_id = new_id(), new_id()
    project = Project(new_id(), source_files=(source,), paths=(ReactionPath(path_id, "path", ()),))
    stage_id = new_id()
    network = empty_network()
    network["species"] = [{"id": species_id, "name": "A", "starred": True,
        "bindings": [{"source_file_id": source.id, "job_id": source.jobs[0].id, "historical": False}]}]
    network["path_reactions"] = [{"path_id": path_id, "stages": [{"id": stage_id,
        "role": "reactant", "label": "A", "predecessor_stage_id": None,
        "species": [{"species_id": species_id, "coefficient": 1}],
        "terms": [{"species_id": species_id, "source_file_id": source.id,
            "job_id": source.jobs[0].id, "energy_kind": "gibbs_total", "coefficient": 1,
            "system_mode": "complete_system", "reason": "whole job", "historical": False}],
        "confirm_additional_terms": False, "node_id": None, "entry_id": None,
        "historical": False, "normalization_confirmed": True,
        "normalization_note": "受控夹具：同一反应清单"}], "zero_point": {"kind": "reactant", "stage_id": stage_id},
        "preset": "relative_energy", "energy_kind": "gibbs_total", "historical": False}]
    built = apply_path_recipe(project, network, path_id)
    spec = build_plot_spec(built, (calculate_path(built, path_id),))
    assert spec.paths[0].points[0].starred_species == ("A",)
    saved = read_reaction_network(built)
    assert saved["path_reactions"][0]["reference_signature"] == reference_signature(
        built.paths[0].reference_expression)
    removed = remove_sources(built, [source.id], cascade=True).project
    historical = read_reaction_network(removed)
    assert historical["species"][0]["bindings"][0]["historical"]
    assert historical["species"][0]["starred"]
    assert historical["path_reactions"][0]["stages"][0]["historical"]
