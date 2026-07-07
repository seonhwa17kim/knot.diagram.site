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


def repository_json_path(source_path):
    repo_json = ROOT / "parabolic" / "data" / "json" / source_path.name
    if repo_json.exists():
        return rel(repo_json)
    return rel(source_path)


class DisjointSet:
    def __init__(self, values):
        self.parent = {value: value for value in values}

    def find(self, value):
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left, right):
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def parse_pd_entry(value):
    numbers = [int(part) for part in re.findall(r"-?\d+", str(value))]
    return numbers if len(numbers) == 4 else None


def pd_code_from_data(data):
    diagram = data.get("Diagram")
    if isinstance(diagram, dict) and isinstance(diagram.get("PDcode"), list):
        return [entry for entry in (parse_pd_entry(item) for item in diagram["PDcode"]) if entry]

    diagrams = data.get("Diagrams")
    if isinstance(diagrams, list):
        for item in diagrams:
            if isinstance(item, dict) and isinstance(item.get("PDcode"), list):
                return [entry for entry in (parse_pd_entry(code) for code in item["PDcode"]) if entry]
    return []


def bareiss_determinant(matrix):
    if not matrix:
        return 1

    values = [row[:] for row in matrix]
    size = len(values)
    sign = 1
    previous = 1

    for pivot_index in range(size - 1):
        pivot_row = next((row for row in range(pivot_index, size) if values[row][pivot_index]), None)
        if pivot_row is None:
            return 0
        if pivot_row != pivot_index:
            values[pivot_index], values[pivot_row] = values[pivot_row], values[pivot_index]
            sign = -sign

        pivot = values[pivot_index][pivot_index]
        for row in range(pivot_index + 1, size):
            for col in range(pivot_index + 1, size):
                values[row][col] = (
                    values[row][col] * pivot - values[row][pivot_index] * values[pivot_index][col]
                ) // previous
        previous = pivot

        for row in range(pivot_index + 1, size):
            values[row][pivot_index] = 0
        for col in range(pivot_index + 1, size):
            values[pivot_index][col] = 0

    return abs(sign * values[-1][-1])


def determinant_from_pd(pd_code):
    if not pd_code:
        return None

    labels = sorted({label for crossing in pd_code for label in crossing})
    over_pair = (0, 2)
    under_positions = [1, 3]
    disjoint_set = DisjointSet(labels)

    for crossing in pd_code:
        disjoint_set.union(crossing[over_pair[0]], crossing[over_pair[1]])

    roots = sorted({disjoint_set.find(label) for label in labels})
    root_index = {root: index for index, root in enumerate(roots)}
    matrix = []
    for crossing in pd_code:
        row = [0] * len(roots)
        over_index = root_index[disjoint_set.find(crossing[over_pair[0]])]
        row[over_index] += 2
        for position in under_positions:
            row[root_index[disjoint_set.find(crossing[position])]] -= 1
        matrix.append(row)

    if len(matrix) < 2 or len(roots) < 2:
        return 1
    cofactor = [row[1:] for row in matrix[1:]]
    return bareiss_determinant(cofactor)


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            inner = stripped[1:-1].strip()
            if not inner:
                return []
            return [part.strip() for part in inner.split(",")]
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

    complex_volumes = as_list(ideal.get("ComplexVolumeN"))
    if complex_volumes:
        return len(complex_volumes)

    number_of_sols = ideal.get("NumberOfSols")
    if number_of_sols is not None:
        return number_of_sols

    return None


def has_positive_dimension(ideal):
    if ideal.get("IsZeroDim") is False:
        return True
    dimension = ideal.get("IdealDimension")
    return isinstance(dimension, int) and dimension > 0


def is_abelian_ideal(ideal):
    name = str(ideal.get("IdealName") or "")
    return name.lower().startswith("ab")


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
    determinant = determinant_from_pd(pd_code_from_data(data))

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
    has_positive_dimensional_ideal = False

    for idx, ideal in enumerate(primary_ideals, start=1):
        geometric_indices = parse_geometric_indices(ideal.get("GeometricComponent"))
        geometric = bool(geometric_indices)
        positive_dimensional = has_positive_dimension(ideal)
        has_positive_dimensional_ideal = has_positive_dimensional_ideal or positive_dimensional
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
                "positiveDimensional": positive_dimensional,
                "abelian": is_abelian_ideal(ideal),
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
        "hasPositiveDimensionalIdeal": has_positive_dimensional_ideal,
        "determinant": determinant,
        "solutionCounts": [component["solutions"] for component in components],
        "components": components,
        "obstructions": obstructions,
        "diagram": diagram_path,
        "html": html_path,
        "pdf": pdf_path,
        "repoJson": repository_json_path(path),
        "newJson": rel(path),
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
