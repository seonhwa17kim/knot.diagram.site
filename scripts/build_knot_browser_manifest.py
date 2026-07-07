#!/usr/bin/env python3
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSON_SOURCES = [
    {
        "directories": [
            ROOT / "parabolic" / "data" / "~12crossings",
            ROOT / "parabolic" / "data" / "~12-crossings",
        ],
        "max_crossing": 12,
        "r2_prefixes": {
            "~12crossings": "~12crossings",
            "~12-crossings": "~12-crossings",
        },
    },
    {
        "directories": [
            ROOT / "parabolic" / "data" / "13crossings",
            ROOT / "parabolic" / "data" / "13-crossings",
        ],
        "max_crossing": 13,
        "r2_prefixes": {
            "13crossings": "13crossings",
            "13-crossings": "13-crossings",
        },
    },
]
OUT = ROOT / "parabolic" / "data" / "knot-browser-manifest.json"


def rel(path):
    return path.relative_to(ROOT).as_posix()


def resolve_source(source):
    for directory in source["directories"]:
        if directory.exists():
            prefix = source["r2_prefixes"].get(directory.name, directory.name)
            return directory, prefix
    return None, None


def crossing_number(name):
    match = re.match(r"^(\d+)", name)
    return int(match.group(1)) if match else None


def display_name(name):
    match = re.match(r"^(\d+)([an])_(\d+)$", name)
    if match:
        return f"{match.group(1)}{match.group(2)}_{int(match.group(3))}"
    match = re.match(r"^(\d+)([an])(\d+)$", name)
    if match:
        return f"{match.group(1)}{match.group(2)}_{int(match.group(3))}"
    return name


def find_prefixed_file(directory, index, suffix):
    matches = sorted(directory.glob(f"{index}_*{suffix}"))
    return rel(matches[0]) if matches else None


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_geometric_indices(value):
    if value in (None, 0, "0", "{0}", [], ""):
        return []

    if isinstance(value, int):
        return [value] if value > 0 else []

    if isinstance(value, list):
        indices = []
        for item in value:
            if isinstance(item, int) and item > 0:
                indices.append(item)
            elif isinstance(item, str) and item.strip().isdigit() and int(item.strip()) > 0:
                indices.append(int(item.strip()))
        return indices

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            stripped = stripped[1:-1]
        indices = []
        for part in stripped.split(","):
            part = part.strip()
            if part.isdigit() and int(part) > 0:
                indices.append(int(part))
        return indices

    return []


def selected_complex_volumes(value, indices):
    values = as_list(value)
    selected = []
    for index in indices:
        one_based = index - 1
        if 0 <= one_based < len(values):
            selected.append(str(values[one_based]))
    return selected


def primary_ideals_from_parabolic_reps(parabolic_reps):
    if isinstance(parabolic_reps, dict):
        reps = [parabolic_reps]
    elif isinstance(parabolic_reps, list):
        reps = [item for item in parabolic_reps if isinstance(item, dict)]
    else:
        reps = []

    primary_ideals = []
    for rep in reps:
        direct_ideals = rep.get("PrimaryIdeals", [])
        if isinstance(direct_ideals, list):
            primary_ideals.extend(direct_ideals)

        comps = rep.get("Comps", {})
        if not isinstance(comps, dict):
            continue
        ideals = comps.get("PrimaryIdeals", [])
        if isinstance(ideals, list):
            primary_ideals.extend(ideals)
    return primary_ideals


def component_solution_count(ideal):
    if ideal.get("IsZeroDim") is False:
        dimension = ideal.get("IdealDimension")
        if isinstance(dimension, int) and dimension > 0:
            return -dimension
        return "positive-dimensional"

    if ideal.get("IdealDimension") not in (None, 0):
        dimension = ideal.get("IdealDimension")
        if isinstance(dimension, int) and dimension > 0:
            return -dimension

    number_of_sols = ideal.get("NumberOfSols")
    if number_of_sols is not None:
        return number_of_sols

    complex_volumes = as_list(ideal.get("ComplexVolumeN"))
    if complex_volumes:
        return len(complex_volumes)

    return None


def first_available(*values):
    for value in values:
        if value is not None:
            return value
    return None


def summarize_json(path, r2_prefix):
    data = json.loads(path.read_text())
    index = int(data["Index"])
    raw_name = str(data.get("Name") or data.get("RolfsenName") or path.stem)
    name = display_name(raw_name)
    crossing = crossing_number(name)

    diagram = data.get("Diagram", {})
    parabolic_reps = first_available(
        data.get("ParabolicReps"),
        diagram.get("ParabolicReps", {}) if isinstance(diagram, dict) else {},
    )
    primary_ideals = primary_ideals_from_parabolic_reps(parabolic_reps)

    components = []
    geometric_index = None
    geometric_volume = None
    obstructions = []

    for idx, ideal in enumerate(primary_ideals, start=1):
        geometric_indices = parse_geometric_indices(ideal.get("GeometricComponent"))
        geometric = bool(geometric_indices)
        if geometric and geometric_index is None:
            geometric_index = idx
            geometric_volume = selected_complex_volumes(ideal.get("ComplexVolumeN"), geometric_indices)

        obstruction = ideal.get("Obstruction")
        obstructions.append(obstruction if obstruction is not None else "?")

        components.append(
            {
                "index": idx,
                "name": ideal.get("IdealName"),
                "solutions": component_solution_count(ideal),
                "dimension": ideal.get("IdealDimension"),
                "obstruction": obstruction,
                "geometric": geometric,
                "geometricIndices": geometric_indices,
            }
        )

    html_path = find_prefixed_file(ROOT / "parabolic" / "data" / "html", index, ".html")
    pdf_path = find_prefixed_file(ROOT / "parabolic" / "data" / "pdf", index, ".pdf")
    diagram_path = find_prefixed_file(ROOT / "parabolic" / "diagram" / "svg", index, ".svg")
    return {
        "index": index,
        "name": name,
        "rawName": raw_name,
        "crossing": crossing,
        "hyperbolic": data.get("Hyperbolic"),
        "geometricComponent": geometric_index,
        "geometricVolume": geometric_volume,
        "componentCount": len(primary_ideals),
        "solutionCounts": [component["solutions"] for component in components],
        "components": components,
        "obstructions": obstructions,
        "diagram": diagram_path,
        "html": html_path,
        "pdf": pdf_path,
        "repoJson": rel(path),
        "newJsonKey": f"{r2_prefix}/{path.name}",
    }


def main():
    rows = []
    for source in JSON_SOURCES:
        directory, r2_prefix = resolve_source(source)
        if directory is None:
            candidates = ", ".join(rel(path) for path in source["directories"])
            print(f"skipping missing source; expected one of: {candidates}")
            continue
        for path in sorted(directory.glob("*.json")):
            record = summarize_json(path, r2_prefix)
            if record["crossing"] is not None and record["crossing"] <= source["max_crossing"]:
                rows.append(record)

    rows.sort(key=lambda row: row["index"])
    OUT.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"wrote {len(rows)} records to {rel(OUT)}")


if __name__ == "__main__":
    main()
