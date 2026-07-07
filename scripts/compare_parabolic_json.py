#!/usr/bin/env python3
"""Compare old and new parabolic JSON data.

The script normalizes the old schema

    Diagrams[0], ParabolicReps[0]

and the new schema

    Diagram, Diagram.ParabolicReps.Comps

into one record shape, then emits reports for structural defects and changed
mathematical invariants.  It intentionally treats timing fields as metadata.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LIST_RE = re.compile(r"^\{\s*(-?\d+(?:\s*,\s*-?\d+)*)?\s*\}$")
NAME_CROSSING_RE = re.compile(r"^(\d+)")
FILENAME_RE = re.compile(r"^(?P<name>.+)\((?P<index>\d+)\)\.json$")
NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
COMPLEX_I_RE = re.compile(rf"^\s*({NUM})?\s*([+-])\s*({NUM})\*?I\s*$")
PURE_IMAG_RE = re.compile(rf"^\s*({NUM})\*?I\s*$")
REAL_RE = re.compile(rf"^\s*{NUM}\s*$")
PRECISION_MARK_RE = re.compile(r"`[0-9.]*")


@dataclass(frozen=True)
class CanonicalRecord:
    filename: str
    index: Any
    name: Any
    hyperbolic: Any
    torus: Any
    satellite: Any
    diagram: dict[str, Any]
    solving_seq: Any
    solving_seq_idx: Any
    u_check_eq: list[Any]
    v_check_eq: list[Any]
    primary_ideals: list[dict[str, Any]]
    u_poly_c: list[Any]
    riley_poly_c: list[Any]
    raw: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-dir", type=Path, default=Path("parabolic/data/json260706"))
    parser.add_argument("--new-dir", type=Path, default=Path("parabolic/data/json"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/parabolic_json_validation"))
    parser.add_argument("--volume-tolerance", type=float, default=1.0e-4)
    return parser.parse_args()


def read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with path.open() as f:
            return json.load(f), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_int_brace_list(value: Any) -> list[int] | None:
    if isinstance(value, list) and all(isinstance(x, int) for x in value):
        return value
    if not isinstance(value, str):
        return None
    match = LIST_RE.match(value)
    if not match:
        return None
    body = match.group(1)
    if not body:
        return []
    return [int(x.strip()) for x in body.split(",")]


def crossing_number_from_name(name: Any) -> int | None:
    if not isinstance(name, str):
        return None
    match = NAME_CROSSING_RE.match(name)
    if not match:
        return None
    return int(match.group(1))


def filename_info(filename: str) -> tuple[str | None, int | None]:
    match = FILENAME_RE.match(filename)
    if not match:
        return None, None
    return match.group("name"), int(match.group("index"))


def knot_name_key(name: Any) -> Any:
    if not isinstance(name, str):
        return name
    # Old files use names like 11a1, while filenames and newer files use 11a_1.
    match = re.match(r"^(\d+)([an])_?(\d+)$", name)
    if match:
        crossing, family, number = match.groups()
        return f"{crossing}{family}{int(number)}"
    return name


def normalize_record(filename: str, data: dict[str, Any]) -> CanonicalRecord:
    if "Diagrams" in data:
        diagrams = as_list(data.get("Diagrams"))
        diagram = diagrams[0] if diagrams and isinstance(diagrams[0], dict) else {}
        par_reps = as_list(data.get("ParabolicReps"))
        par_rep = par_reps[0] if par_reps and isinstance(par_reps[0], dict) else {}
        comps = par_rep
    else:
        diagram = data.get("Diagram") if isinstance(data.get("Diagram"), dict) else {}
        par_rep_raw = diagram.get("ParabolicReps")
        if isinstance(par_rep_raw, list):
            par_rep = par_rep_raw[0] if par_rep_raw and isinstance(par_rep_raw[0], dict) else {}
        else:
            par_rep = par_rep_raw if isinstance(par_rep_raw, dict) else {}
        comps = par_rep.get("Comps") if isinstance(par_rep.get("Comps"), dict) else {}

    u = comps.get("u") if isinstance(comps.get("u"), dict) else {}
    v = comps.get("v") if isinstance(comps.get("v"), dict) else {}
    primary_ideals = comps.get("PrimaryIdeals") if isinstance(comps.get("PrimaryIdeals"), list) else []

    return CanonicalRecord(
        filename=filename,
        index=data.get("Index"),
        name=data.get("Name"),
        hyperbolic=data.get("Hyperbolic"),
        torus=data.get("Torus"),
        satellite=data.get("Satellite"),
        diagram=diagram,
        solving_seq=par_rep.get("SolvingSeq", diagram.get("SolvingSeqs", [None])[0] if diagram.get("SolvingSeqs") else None),
        solving_seq_idx=par_rep.get("SolvingSeqIdx"),
        u_check_eq=as_list(u.get("CheckEq")),
        v_check_eq=as_list(v.get("CheckEq")),
        primary_ideals=primary_ideals,
        u_poly_c=as_list(par_rep.get("uPolyC")),
        riley_poly_c=as_list(par_rep.get("RileyPolyC")),
        raw=data,
    )


def stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: stable_value(v) for k, v in sorted(value.items()) if not is_timing_key(k)}
    if isinstance(value, list):
        return [stable_value(v) for v in value]
    return value


def is_timing_key(key: str) -> bool:
    return key.startswith("Timing") or key == "Timings" or key == "TimingForPrimaryIdeals"


def normalize_poly_text(poly: Any) -> str:
    if not isinstance(poly, str):
        return json.dumps(poly, sort_keys=True)
    return re.sub(r"\s+", "", poly)


def normalized_poly_list(polys: list[Any]) -> list[str]:
    return sorted(normalize_poly_text(p) for p in polys)


def parse_pdcode(pdcode: Any) -> list[tuple[int, int, int, int]] | None:
    tuples = []
    for entry in as_list(pdcode):
        parsed = parse_int_brace_list(entry)
        if parsed is None or len(parsed) != 4:
            return None
        tuples.append(tuple(parsed))
    return tuples


def relabel_pd_tuple(tup: tuple[int, int, int, int], sign: int, shift: int, modulus: int) -> tuple[int, int, int, int]:
    return tuple(((sign * (x - 1) + shift) % modulus) + 1 for x in tup)  # type: ignore[return-value]


def canonical_pd_crossing(tup: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    rotations = [tup[i:] + tup[:i] for i in range(4)]
    return min(rotations)


def canonical_pd_under_relabeling(pdcode: Any) -> tuple[tuple[tuple[int, int, int, int], ...], int, int] | None:
    tuples = parse_pdcode(pdcode)
    if tuples is None:
        return None
    if not tuples:
        return tuple(), 1, 0
    modulus = max(max(tup) for tup in tuples)
    candidates = []
    for sign in (1, -1):
        for shift in range(modulus):
            relabeled = tuple(sorted(canonical_pd_crossing(relabel_pd_tuple(tup, sign, shift, modulus)) for tup in tuples))
            candidates.append((relabeled, sign, shift))
    return min(candidates, key=lambda item: item[0])


def pdcode_equivalence(old_pd: Any, new_pd: Any) -> tuple[bool, str | None]:
    old_canon = canonical_pd_under_relabeling(old_pd)
    new_canon = canonical_pd_under_relabeling(new_pd)
    if old_canon is None or new_canon is None:
        return old_pd == new_pd, None
    same = old_canon[0] == new_canon[0]
    if not same:
        return False, None
    sign_changed = old_canon[1] != new_canon[1]
    shift = (new_canon[2] - old_canon[2]) % (max(max(tup) for tup in parse_pdcode(new_pd) or [(0, 0, 0, 0)]) or 1)
    if old_pd == new_pd:
        return True, None
    if sign_changed:
        return True, f"PDcode differs only by dihedral edge relabeling/crossing rotation/permutation; canonical shift delta={shift}"
    return True, f"PDcode differs only by cyclic edge relabeling/crossing rotation/permutation; canonical shift delta={shift}"


def pdcode_status(old_pd: Any, new_pd: Any) -> str:
    if old_pd == new_pd:
        return "exact"
    same, note = pdcode_equivalence(old_pd, new_pd)
    if same and note:
        return "equivalent_by_relabeling"
    if same:
        return "equivalent"
    return "changed"


def multiset(values: list[Any]) -> dict[str, int]:
    return dict(Counter(json.dumps(stable_value(v), sort_keys=True) for v in values))


def ideal_signature(ideal: dict[str, Any]) -> dict[str, Any]:
    cvol_count, cvol_max_abs_imag = complex_volume_summary(ideal.get("ComplexVolumeN"))
    return {
        "abelian": ideal.get("Abelian"),
        "dimension": ideal.get("IdealDimension"),
        "is_zero_dim": ideal.get("IsZeroDim"),
        "obstruction": ideal.get("Obstruction"),
        "cvol_count": cvol_count,
        "cvol_max_abs_imag": round(cvol_max_abs_imag, 6) if cvol_max_abs_imag is not None else None,
        "geometric": bool(ideal.get("GeometricComponent")),
    }


def ideal_invariant_summary(record: CanonicalRecord) -> dict[str, Any]:
    signatures = [ideal_signature(ideal) for ideal in record.primary_ideals]
    dims = Counter(str(ideal.get("IdealDimension")) for ideal in record.primary_ideals)
    sols = Counter(str(ideal.get("NumberOfSols")) for ideal in record.primary_ideals)
    obstructions = Counter(str(ideal.get("Obstruction")) for ideal in record.primary_ideals)
    abelian = Counter(str(ideal.get("Abelian")) for ideal in record.primary_ideals)
    zero_dim_mismatch = sum(
        1
        for ideal in record.primary_ideals
        if ("IsZeroDim" in ideal and "IdealDimension" in ideal and bool(ideal.get("IsZeroDim")) != (ideal.get("IdealDimension") == 0))
    )
    return {
        "primary_count": len(record.primary_ideals),
        "dimension_multiset": dict(dims),
        "number_of_sols_multiset": dict(sols),
        "obstruction_multiset": dict(obstructions),
        "abelian_multiset": dict(abelian),
        "geometric_count": sum(1 for ideal in record.primary_ideals if ideal.get("GeometricComponent")),
        "zero_dim_mismatch_count": zero_dim_mismatch,
        "signature_multiset": multiset(signatures),
    }


def complex_value(value: Any) -> complex | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return complex(float(value), 0.0)
    if isinstance(value, str):
        stripped = PRECISION_MARK_RE.sub("", value.strip())
        if stripped in {"{0}", "0"}:
            return 0j
        if REAL_RE.match(stripped):
            return complex(float(stripped), 0.0)
        pure_imag = PURE_IMAG_RE.match(stripped)
        if pure_imag:
            return complex(0.0, float(pure_imag.group(1)))
        match = COMPLEX_I_RE.match(stripped)
        if match:
            real_s, sign, imag_s = match.groups()
            real = float(real_s) if real_s else 0.0
            imag = float(imag_s)
            if sign == "-":
                imag = -imag
            return complex(real, imag)
    return None


def complex_volume_values(value: Any) -> list[complex]:
    values = []
    for item in as_list(value):
        parsed = complex_value(item)
        if parsed is not None:
            values.append(parsed)
    return values


def complex_volume_summary(value: Any) -> tuple[int, float | None]:
    values = complex_volume_values(value)
    if not values:
        return 0, None
    return len(values), max(abs(z.imag) for z in values)


def validate_diagram(record: CanonicalRecord) -> list[str]:
    issues = []
    name_from_file, index_from_file = filename_info(record.filename)
    if name_from_file is not None and knot_name_key(record.name) != knot_name_key(name_from_file):
        issues.append(f"filename name {name_from_file!r} != JSON Name {record.name!r}")
    if index_from_file is not None and record.index != index_from_file:
        issues.append(f"filename index {index_from_file!r} != JSON Index {record.index!r}")

    crossing = crossing_number_from_name(record.name)
    pdcode = as_list(record.diagram.get("PDcode"))
    acode = parse_int_brace_list(record.diagram.get("Acode"))
    scode = parse_int_brace_list(record.diagram.get("Scode"))
    if crossing is not None:
        if len(pdcode) != crossing:
            issues.append(f"PDcode length {len(pdcode)} != crossing number {crossing}")
        if acode is not None and len(acode) != crossing:
            issues.append(f"Acode length {len(acode)} != crossing number {crossing}")
        if scode is not None and len(scode) != crossing:
            issues.append(f"Scode length {len(scode)} != crossing number {crossing}")
    for i, pd in enumerate(pdcode, start=1):
        parsed = parse_int_brace_list(pd)
        if parsed is None or len(parsed) != 4:
            issues.append(f"PDcode entry {i} is not a 4-tuple: {pd!r}")
    return issues


def validate_solving_seq(record: CanonicalRecord) -> tuple[int | None, list[str]]:
    issues = []
    seq = record.solving_seq
    if not isinstance(seq, list) or len(seq) < 6:
        return None, ["SolvingSeq is missing or has unexpected shape"]
    crossing = crossing_number_from_name(record.name)
    starts = parse_int_brace_list(seq[0])
    generated_steps = seq[2] if isinstance(seq[2], list) else []
    defining_crossings = parse_int_brace_list(seq[3])
    redundant_crossings = parse_int_brace_list(seq[4])
    final_crossing = seq[5]
    if starts is None:
        issues.append(f"starting arcs are not a brace list: {seq[0]!r}")
        starts = []
    if len(starts) != len(set(starts)):
        issues.append("starting arcs contain repetitions")
    generated = []
    for i, step in enumerate(generated_steps, start=1):
        parsed = parse_int_brace_list(step)
        if parsed is None or len(parsed) != 4:
            issues.append(f"generated step {i} is not a 4-tuple: {step!r}")
            continue
        if parsed[3] not in {1, 2, -1, -2}:
            issues.append(f"generated step {i} has unexpected crossing type {parsed[3]}")
        generated.append(parsed[2])
    if crossing is not None:
        all_arcs = set(abs(x) for x in starts + generated)
        expected = set(range(1, crossing + 1))
        missing = sorted(expected - all_arcs)
        extra = sorted(all_arcs - expected)
        if missing:
            issues.append(f"SolvingSeq does not generate arcs {missing}")
        if extra:
            issues.append(f"SolvingSeq uses out-of-range arcs {extra}")
        for label_name, labels in (("defining crossings", defining_crossings), ("redundant crossings", redundant_crossings)):
            if labels is None:
                issues.append(f"{label_name} are not a brace list")
            else:
                bad = [x for x in labels if abs(x) < 1 or abs(x) > crossing]
                if bad:
                    issues.append(f"{label_name} contain out-of-range labels {bad}")
        if isinstance(final_crossing, int) and (final_crossing < 1 or final_crossing > crossing):
            issues.append(f"final SolvingSeq index {final_crossing} out of range")
    return len(starts), issues


def validate_primary_ideals(record: CanonicalRecord, volume_tolerance: float) -> list[str]:
    issues = []
    crossing = crossing_number_from_name(record.name)
    for idx, ideal in enumerate(record.primary_ideals, start=1):
        label = ideal.get("IdealName", f"ideal #{idx}")
        obstruction = ideal.get("Obstruction")
        if obstruction is not None and obstruction not in {-1, 1}:
            issues.append(f"{label}: obstruction is {obstruction!r}, expected -1 or 1")
        if "IsZeroDim" in ideal and "IdealDimension" in ideal:
            if bool(ideal.get("IsZeroDim")) != (ideal.get("IdealDimension") == 0):
                issues.append(f"{label}: IsZeroDim does not agree with IdealDimension")
        if crossing is not None and "ArcColoring" in ideal:
            arc_coloring = as_list(ideal.get("ArcColoring"))
            if len(arc_coloring) != crossing:
                issues.append(f"{label}: ArcColoring length {len(arc_coloring)} != crossing number {crossing}")
        if ideal.get("Abelian") is True:
            _, max_abs_imag = complex_volume_summary(ideal.get("ComplexVolumeN"))
            if max_abs_imag is not None and max_abs_imag > volume_tolerance:
                issues.append(f"{label}: abelian component has nonzero imaginary complex volume {max_abs_imag}")
        if ideal.get("IsZeroDim") is True and "NumberOfSols" in ideal and "RepresentationsN" in ideal:
            reps = as_list(ideal.get("RepresentationsN"))
            if len(reps) != int(ideal.get("NumberOfSols")):
                issues.append(f"{label}: NumberOfSols {ideal.get('NumberOfSols')} != len(RepresentationsN) {len(reps)}")
    if record.hyperbolic is True:
        geometric_ideals = [ideal for ideal in record.primary_ideals if ideal.get("GeometricComponent")]
        if len(geometric_ideals) == 0:
            issues.append("hyperbolic knot has no marked GeometricComponent")
        if len(geometric_ideals) > 1:
            issues.append(f"hyperbolic knot has {len(geometric_ideals)} marked GeometricComponent ideals")
        if geometric_ideals:
            _, max_abs_imag = complex_volume_summary(geometric_ideals[0].get("ComplexVolumeN"))
            if max_abs_imag is None or max_abs_imag <= volume_tolerance:
                issues.append("marked GeometricComponent has no positive imaginary complex volume")
    if record.hyperbolic is False:
        if any(ideal.get("GeometricComponent") for ideal in record.primary_ideals):
            issues.append("non-hyperbolic knot has a marked GeometricComponent")
    return issues


def compare_records(old: CanonicalRecord, new: CanonicalRecord) -> tuple[list[str], list[str]]:
    differences = []
    warnings = []
    for field in ("index", "name", "hyperbolic"):
        old_value = knot_name_key(getattr(old, field)) if field == "name" else getattr(old, field)
        new_value = knot_name_key(getattr(new, field)) if field == "name" else getattr(new, field)
        if old_value != new_value:
            differences.append(f"{field}: old={getattr(old, field)!r}, new={getattr(new, field)!r}")
    for field in ("torus", "satellite"):
        if getattr(old, field) != getattr(new, field):
            if getattr(new, field) is None:
                warnings.append(f"{field}: present in old as {getattr(old, field)!r}, missing in new")
            else:
                differences.append(f"{field}: old={getattr(old, field)!r}, new={getattr(new, field)!r}")

    for field in ("Scode", "Acode", "CBtype"):
        if old.diagram.get(field) != new.diagram.get(field):
            differences.append(f"Diagram.{field} changed")
    pd_same, pd_note = pdcode_equivalence(old.diagram.get("PDcode"), new.diagram.get("PDcode"))
    if not pd_same:
        differences.append("Diagram.PDcode changed")
    elif pd_note:
        warnings.append(pd_note)

    old_starts, _ = validate_solving_seq(old)
    new_starts, _ = validate_solving_seq(new)
    if old_starts != new_starts:
        differences.append(f"starting_arc_count: old={old_starts!r}, new={new_starts!r}")
    if stable_value(old.solving_seq) != stable_value(new.solving_seq):
        differences.append("SolvingSeq changed")

    if normalized_poly_list(old.u_check_eq) != normalized_poly_list(new.u_check_eq):
        differences.append("u.CheckEq changed")
    if normalized_poly_list(old.v_check_eq) != normalized_poly_list(new.v_check_eq):
        differences.append("v.CheckEq changed")
    if normalized_poly_list(old.u_poly_c) != normalized_poly_list(new.u_poly_c):
        differences.append("uPolyC changed")
    if normalized_poly_list(old.riley_poly_c) != normalized_poly_list(new.riley_poly_c):
        differences.append("RileyPolyC changed")

    old_summary = ideal_invariant_summary(old)
    new_summary = ideal_invariant_summary(new)
    for key in (
        "primary_count",
        "dimension_multiset",
        "obstruction_multiset",
        "abelian_multiset",
        "geometric_count",
        "zero_dim_mismatch_count",
    ):
        if old_summary[key] != new_summary[key]:
            differences.append(f"{key}: old={old_summary[key]!r}, new={new_summary[key]!r}")
    if old_summary["number_of_sols_multiset"] != new_summary["number_of_sols_multiset"]:
        if "None" in old_summary["number_of_sols_multiset"] or "None" in new_summary["number_of_sols_multiset"]:
            warnings.append(f"number_of_sols availability differs: old={old_summary['number_of_sols_multiset']!r}, new={new_summary['number_of_sols_multiset']!r}")
        else:
            differences.append(f"number_of_sols_multiset: old={old_summary['number_of_sols_multiset']!r}, new={new_summary['number_of_sols_multiset']!r}")
    if old_summary["signature_multiset"] != new_summary["signature_multiset"]:
        differences.append("primary_ideal_signature_multiset changed")
    return differences, warnings


def severity_for_issues(defects: list[str], differences: list[str], warnings: list[str]) -> str:
    if any("invalid JSON" in x or "missing paired" in x or "filename" in x for x in defects):
        return "P0"
    if any("SolvingSeq" in x or "PDcode" in x or "GeometricComponent" in x for x in defects):
        return "P1"
    if defects:
        return "P2"
    if any(
        token in x
        for x in differences
        for token in (
            "primary_count",
            "dimension_multiset",
            "number_of_sols_multiset",
            "obstruction_multiset",
            "abelian_multiset",
            "geometric_count",
            "hyperbolic",
        )
    ):
        return "P2"
    if differences:
        return "P3"
    if warnings:
        return "WARN"
    return "OK"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "filename",
        "index",
        "name",
        "severity",
        "pdcode_status",
        "old_primary_count",
        "new_primary_count",
        "old_starting_arc_count",
        "new_starting_arc_count",
        "defect_count",
        "difference_count",
        "warning_count",
        "defects",
        "differences",
        "warnings",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    by_severity = Counter(row["severity"] for row in rows)
    severity_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "WARN": 4, "OK": 5}
    interesting = sorted(
        (row for row in rows if row["severity"] not in {"OK"}),
        key=lambda row: (severity_rank.get(row["severity"], 99), int(row["index"]) if str(row["index"]).isdigit() else math.inf, row["filename"]),
    )
    lines = [
        "# Parabolic JSON Validation Report",
        "",
        "## Summary",
        "",
        f"- Compared files: {summary['compared_files']}",
        f"- Old-only files: {summary['old_only_files']}",
        f"- New-only files: {summary['new_only_files']}",
        f"- Rows with defects: {summary['rows_with_defects']}",
        f"- Rows with mathematical differences: {summary['rows_with_differences']}",
        f"- Rows with warnings only or also warnings: {summary['rows_with_warnings']}",
        "",
        "## Severity Counts",
        "",
    ]
    for severity in sorted(by_severity):
        lines.append(f"- {severity}: {by_severity[severity]}")
    lines.extend(["", "## Highest-Priority Rows", ""])
    for row in interesting[:200]:
        lines.append(f"### {row['filename']} [{row['severity']}]")
        if row["defects"]:
            lines.append(f"- Defects: {row['defects']}")
        if row["differences"]:
            lines.append(f"- Differences: {row['differences']}")
        if row["warnings"]:
            lines.append(f"- Warnings: {row['warnings']}")
        lines.append("")
    if len(interesting) > 200:
        lines.append(f"_Only the first 200 non-OK rows are shown here. See summary.csv and differences.json for all {len(interesting)} rows._")
        lines.append("")
    path.write_text("\n".join(lines))


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    old_files = {p.name: p for p in args.old_dir.glob("*.json")}
    new_files = {p.name: p for p in args.new_dir.glob("*.json")}
    all_names = sorted(set(old_files) | set(new_files), key=lambda name: (filename_info(name)[1] or math.inf, name))
    rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}

    for filename in all_names:
        defects: list[str] = []
        differences: list[str] = []
        warnings: list[str] = []
        old_record = None
        new_record = None

        if filename not in old_files:
            defects.append("missing paired old file")
        else:
            old_data, error = read_json(old_files[filename])
            if error:
                defects.append(f"old invalid JSON: {error}")
            else:
                old_record = normalize_record(filename, old_data or {})
                defects.extend(f"old: {issue}" for issue in validate_diagram(old_record))
                _, old_solving_issues = validate_solving_seq(old_record)
                defects.extend(f"old: {issue}" for issue in old_solving_issues)
                defects.extend(f"old: {issue}" for issue in validate_primary_ideals(old_record, args.volume_tolerance))

        if filename not in new_files:
            defects.append("missing paired new file")
        else:
            new_data, error = read_json(new_files[filename])
            if error:
                defects.append(f"new invalid JSON: {error}")
            else:
                new_record = normalize_record(filename, new_data or {})
                defects.extend(f"new: {issue}" for issue in validate_diagram(new_record))
                _, new_solving_issues = validate_solving_seq(new_record)
                defects.extend(f"new: {issue}" for issue in new_solving_issues)
                defects.extend(f"new: {issue}" for issue in validate_primary_ideals(new_record, args.volume_tolerance))

        if old_record is not None and new_record is not None:
            differences, warnings = compare_records(old_record, new_record)

        old_starts = validate_solving_seq(old_record)[0] if old_record else None
        new_starts = validate_solving_seq(new_record)[0] if new_record else None
        old_primary_count = len(old_record.primary_ideals) if old_record else None
        new_primary_count = len(new_record.primary_ideals) if new_record else None
        pd_status = pdcode_status(old_record.diagram.get("PDcode"), new_record.diagram.get("PDcode")) if old_record and new_record else None
        severity = severity_for_issues(defects, differences, warnings)
        row = {
            "filename": filename,
            "index": new_record.index if new_record else (old_record.index if old_record else None),
            "name": new_record.name if new_record else (old_record.name if old_record else None),
            "severity": severity,
            "pdcode_status": pd_status,
            "old_primary_count": old_primary_count,
            "new_primary_count": new_primary_count,
            "old_starting_arc_count": old_starts,
            "new_starting_arc_count": new_starts,
            "defect_count": len(defects),
            "difference_count": len(differences),
            "warning_count": len(warnings),
            "defects": " | ".join(defects),
            "differences": " | ".join(differences),
            "warnings": " | ".join(warnings),
        }
        rows.append(row)
        if defects or differences or warnings:
            details[filename] = {
                "severity": severity,
                "index": row["index"],
                "name": row["name"],
                "defects": defects,
                "differences": differences,
                "warnings": warnings,
                "old_ideal_summary": ideal_invariant_summary(old_record) if old_record else None,
                "new_ideal_summary": ideal_invariant_summary(new_record) if new_record else None,
            }

    summary = {
        "old_dir": str(args.old_dir),
        "new_dir": str(args.new_dir),
        "compared_files": sum(1 for name in all_names if name in old_files and name in new_files),
        "old_only_files": len(set(old_files) - set(new_files)),
        "new_only_files": len(set(new_files) - set(old_files)),
        "rows_total": len(rows),
        "rows_with_defects": sum(1 for row in rows if row["defect_count"]),
        "rows_with_differences": sum(1 for row in rows if row["difference_count"]),
        "rows_with_warnings": sum(1 for row in rows if row["warning_count"]),
        "severity_counts": dict(Counter(row["severity"] for row in rows)),
    }

    write_csv(args.out_dir / "summary.csv", rows)
    (args.out_dir / "differences.json").write_text(json.dumps({"summary": summary, "details": details}, indent=2, sort_keys=True))
    write_markdown(args.out_dir / "defects.md", summary, rows)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
