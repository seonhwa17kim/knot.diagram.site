#!/usr/bin/env python3
"""Compare NumberOfSols component-by-component between two JSON folders."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from compare_parabolic_json import normalize_poly_text, normalize_record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-dir", type=Path, default=Path("parabolic/data/json"))
    parser.add_argument("--new-dir", type=Path, default=Path("parabolic/data/~12-crossings"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/parabolic_number_of_sols"))
    return parser.parse_args()


def stem_key(path: Path) -> str:
    stem = path.stem
    return re.sub(r"\(\d+\)$", "", stem)


def read_record(path: Path) -> Any:
    with path.open() as f:
        return normalize_record(path.name, json.load(f))


def generators_signature(ideal: dict[str, Any]) -> str:
    generators = ideal.get("Generators")
    if not isinstance(generators, list):
        generators = []
    payload = {
        "generators": sorted(normalize_poly_text(g) for g in generators),
        "variable_order": ideal.get("VariableOrder"),
        "dimension": ideal.get("IdealDimension"),
        "abelian": ideal.get("Abelian"),
        "obstruction": ideal.get("Obstruction"),
    }
    return json.dumps(payload, sort_keys=True)


def component_label(ideal: dict[str, Any], idx: int) -> str:
    name = ideal.get("IdealName")
    if not isinstance(name, str) or not name:
        return f"component_{idx}"
    return canonical_ideal_name(name)


def canonical_ideal_name(name: str) -> str:
    return re.sub(r"(\d+[an])_(\d+)_", r"\1\2_", name)


def index_ideals(ideals: list[dict[str, Any]]) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    by_name: dict[str, list[int]] = defaultdict(list)
    by_signature: dict[str, list[int]] = defaultdict(list)
    for idx, ideal in enumerate(ideals):
        by_name[component_label(ideal, idx)].append(idx)
        by_signature[generators_signature(ideal)].append(idx)
    return dict(by_name), dict(by_signature)


def match_components(old_ideals: list[dict[str, Any]], new_ideals: list[dict[str, Any]]) -> list[tuple[int | None, int | None, str]]:
    old_by_name, old_by_sig = index_ideals(old_ideals)
    new_by_name, new_by_sig = index_ideals(new_ideals)
    matched_old: set[int] = set()
    matched_new: set[int] = set()
    matches: list[tuple[int | None, int | None, str]] = []

    for name, old_indices in old_by_name.items():
        new_indices = new_by_name.get(name, [])
        if len(old_indices) == 1 and len(new_indices) == 1:
            old_idx = old_indices[0]
            new_idx = new_indices[0]
            matches.append((old_idx, new_idx, "ideal_name"))
            matched_old.add(old_idx)
            matched_new.add(new_idx)

    for old_idx, old_ideal in enumerate(old_ideals):
        if old_idx in matched_old:
            continue
        signature = generators_signature(old_ideal)
        candidates = [idx for idx in new_by_sig.get(signature, []) if idx not in matched_new]
        old_candidates = [idx for idx in old_by_sig.get(signature, []) if idx not in matched_old]
        if len(old_candidates) == 1 and len(candidates) == 1:
            new_idx = candidates[0]
            matches.append((old_idx, new_idx, "signature"))
            matched_old.add(old_idx)
            matched_new.add(new_idx)

    for old_idx in range(len(old_ideals)):
        if old_idx not in matched_old:
            matches.append((old_idx, None, "old_unmatched"))
    for new_idx in range(len(new_ideals)):
        if new_idx not in matched_new:
            matches.append((None, new_idx, "new_unmatched"))
    return matches


def compare_pair(old_path: Path, new_path: Path) -> list[dict[str, Any]]:
    old_record = read_record(old_path)
    new_record = read_record(new_path)
    rows = []
    for old_idx, new_idx, match_method in match_components(old_record.primary_ideals, new_record.primary_ideals):
        old_ideal = old_record.primary_ideals[old_idx] if old_idx is not None else {}
        new_ideal = new_record.primary_ideals[new_idx] if new_idx is not None else {}
        old_sols = old_ideal.get("NumberOfSols")
        new_sols = new_ideal.get("NumberOfSols")
        if old_idx is None:
            status = "NEW_ONLY"
        elif new_idx is None:
            status = "OLD_ONLY"
        elif old_sols is None and new_sols is None:
            status = "BOTH_MISSING"
        elif old_sols is None:
            status = "OLD_MISSING"
        elif new_sols is None:
            status = "NEW_MISSING"
        elif old_sols == new_sols:
            status = "OK"
        else:
            status = "DIFF"
        rows.append(
            {
                "filename": old_path.name,
                "knot": stem_key(old_path),
                "old_index": old_idx,
                "new_index": new_idx,
                "old_ideal_name": old_ideal.get("IdealName"),
                "new_ideal_name": new_ideal.get("IdealName"),
                "match_method": match_method,
                "old_number_of_sols": old_sols,
                "new_number_of_sols": new_sols,
                "old_dimension": old_ideal.get("IdealDimension"),
                "new_dimension": new_ideal.get("IdealDimension"),
                "old_abelian": old_ideal.get("Abelian"),
                "new_abelian": new_ideal.get("Abelian"),
                "old_obstruction": old_ideal.get("Obstruction"),
                "new_obstruction": new_ideal.get("Obstruction"),
                "status": status,
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "filename",
        "knot",
        "old_index",
        "new_index",
        "old_ideal_name",
        "new_ideal_name",
        "match_method",
        "old_number_of_sols",
        "new_number_of_sols",
        "old_dimension",
        "new_dimension",
        "old_abelian",
        "new_abelian",
        "old_obstruction",
        "new_obstruction",
        "status",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, Any]], missing_pairs: list[str]) -> None:
    counts = Counter(str(row["status"]) for row in rows)
    match_counts = Counter(str(row["match_method"]) for row in rows)
    lines = [
        "# NumberOfSols Comparison",
        "",
        "Old folder: `parabolic/data/json`",
        "New folder: `parabolic/data/~12-crossings`",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Match Method Counts", ""])
    for method, count in sorted(match_counts.items()):
        lines.append(f"- {method}: {count}")
    if missing_pairs:
        lines.extend(["", "## Missing File Pairs", ""])
        for filename in missing_pairs[:200]:
            lines.append(f"- {filename}")
        if len(missing_pairs) > 200:
            lines.append(f"- ... {len(missing_pairs) - 200} more")

    interesting = [row for row in rows if row["status"] not in {"OK"}]
    lines.extend(["", "## Candidate Problems", ""])
    for row in interesting[:500]:
        lines.append(
            f"- `{row['filename']}` {row['old_ideal_name']} -> {row['new_ideal_name']}: "
            f"{row['old_number_of_sols']} vs {row['new_number_of_sols']} [{row['status']}, {row['match_method']}]"
        )
    if len(interesting) > 500:
        lines.append(f"_Only first 500 candidate rows shown. See CSV/JSON for all {len(interesting)} rows._")
    path.write_text("\n".join(lines))


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    old_files = {path.name: path for path in args.old_dir.glob("*.json")}
    new_files = {path.name: path for path in args.new_dir.glob("*.json")}
    missing_pairs = sorted(set(old_files) ^ set(new_files))

    rows: list[dict[str, Any]] = []
    for filename in sorted(set(old_files) & set(new_files)):
        rows.extend(compare_pair(old_files[filename], new_files[filename]))

    write_csv(args.out_dir / "number_of_sols_comparison.csv", rows)
    (args.out_dir / "number_of_sols_comparison.json").write_text(json.dumps(rows, indent=2, sort_keys=True))
    write_markdown(args.out_dir / "number_of_sols_comparison.md", rows, missing_pairs)

    print(
        json.dumps(
            {
                "paired_files": len(set(old_files) & set(new_files)),
                "missing_file_pairs": len(missing_pairs),
                "component_rows": len(rows),
                "status_counts": dict(Counter(str(row["status"]) for row in rows)),
                "match_method_counts": dict(Counter(str(row["match_method"]) for row in rows)),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
