"""RF4 presentation DTO: current core results only; no JS scientific arithmetic."""
from ..core.models import snapshot_to_dict


def inspector_payload(project, payload, state, connections=(), selection=()):
    paths = [p for p in payload["paths"] if p["visible"]]
    # Last selected point is the active detail; other selections remain comparison markers.
    selected = [(p, n) for p in paths for n in p["points"] if n["selected"]]
    last = tuple(selection[-1]) if selection else None
    chosen = next(((p,n) for p,n in selected if (p["id"],n["entry_id"]) == last), selected[-1] if selected else (None,None))
    path, point = chosen
    connection_map = {c.source_file_id: c for c in connections}
    sources = {s.id: s for s in project.source_files}
    dependencies = []
    if point:
        for role, items in (("value",point["dependencies"]), ("reference",point["reference_dependencies"])):
            for dep in items:
                source = sources.get(dep["source_file_id"])
                job = next((j for j in source.jobs if j.id == dep["job_id"]), None) if source else None
                connection = connection_map.get(dep["source_file_id"])
                dependencies.append({"role":role, "source_file_id":dep["source_file_id"], "job_id":dep["job_id"],
                    "source_label": source.original_name if source else dep["source_label"], "source_sha256":dep["source_sha256"],
                    "kind":dep["kind"], "line":dep["source_line"], "job_ordinal":job.ordinal+1 if job else None,
                    "state":connection.state if connection else "unverified"})
    valid = bool(point and point["valid"] and all(d["state"] == "available" for d in dependencies))
    barrier = payload.get("barrier")
    if not (valid and barrier and barrier["path_id"] == path["id"] and barrier["to_entry"] == point["entry_id"]):
        barrier = None
    detail = None if not point else {"path_id":path["id"],"entry_id":point["entry_id"],"node_id":point["node_id"],
        "path_label":path["label"],"label":point["label_short"],"valid":valid,
        "value":point["value"] if valid else None,"value_label":point["value_label"] if valid else "—",
        "absolute_hartree":point["absolute_hartree"] if valid and payload["mode"] != "direct_difference" else None,
        "barrier":barrier,"barrier_label":format(barrier["value"],"+.6f" if payload["unit"] == "hartree" else "+.3f") if barrier else None,
        "sources":dependencies,"diagnostics":point["diagnostics"],"role":point["role"]}
    candidates = []
    if valid:
        seen = set()
        for dep in dependencies:
            # Only node-value dependencies are molecule candidates. Reference molecules
            # remain traceable but are not silently substituted for the current system.
            key = (dep["source_file_id"],dep["job_id"])
            if dep["role"] == "value" and key not in seen:
                candidates.append(dep)
                seen.add(key)
    # Explicit ID groups only. Labels and array positions never establish correspondence.
    lookup = {(p["id"],n["entry_id"]):(p,n) for p in paths for n in p["points"]}
    rows, used = [], set()
    for group in state.get("step_pairs", ()):
        keys = [tuple(k) for k in group if tuple(k) in lookup]
        if keys:
            rows.append(keys)
            used.update(keys)
    for key in lookup:
        if key not in used:
            rows.append([key])
    table = []
    for group in rows:
        members = [lookup[k] for k in group]
        cells = []
        for p in paths:
            found = next((n for path,n in members if path["id"] == p["id"]),None)
            cells.append(None if found is None else {"path_id":p["id"],"entry_id":found["entry_id"],"node_id":found["node_id"],
                "label":found["label_short"],"value_label":found["value_label"],"valid":found["valid"],"selected":found["selected"]})
        names = list(dict.fromkeys(n["label_short"] for _,n in members))
        table.append({"label":" / ".join(names),"paired":len(group)>1,"cells":cells})
    return {"detail":detail,"structure_candidates":candidates,"table_paths":[{"id":p["id"],"label":p["label"],"color":p["color"]} for p in paths],
            "table_rows":table,"pairable":len(selected)==2 and selected[0][0]["id"]!=selected[1][0]["id"]}
