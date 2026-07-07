#!/usr/bin/env python3
"""Compare JSON complex-volume data with SnapPy hyperbolic volumes."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

import snappy

from compare_parabolic_json import complex_volume_values, normalize_record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-dir", type=Path, default=Path("parabolic/data/json"))
    parser.add_argument("--old-json-dir", type=Path, default=Path("parabolic/data/json260706"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/parabolic_volume_validation"))
    parser.add_argument("--tolerance", type=float, default=1.0e-4)
    parser.add_argument("--include-old", action="store_true")
    return parser.parse_args()


def snappy_name_candidates(name: str) -> list[str]:
    candidates = [name]
    match = re.match(r"^(\d+)([an])_?0*(\d+)$", name)
    if match:
        crossing, family, number = match.groups()
        ht_name = f"{crossing}{family}{int(number)}"
        candidates.extend([ht_name, f"K{ht_name}"])
    return list(dict.fromkeys(candidates))


def snappy_volume(name: str) -> tuple[float | None, str | None, str | None]:
    errors = []
    for candidate in snappy_name_candidates(name):
        try:
            manifold = snappy.Manifold(candidate)
            return float(manifold.volume()), candidate, None
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate}: {type(exc).__name__}")
    return None, None, "; ".join(errors)


def ideal_volume_values(ideal: dict[str, Any]) -> list[float]:
    return [abs(z.imag) for z in complex_volume_values(ideal.get("ComplexVolumeN"))]


def volume_summary(record: Any, snappy_vol: float | None) -> dict[str, Any]:
    all_values: list[float] = []
    geometric_values: list[float] = []
    geometric_ideal_names = []
    for ideal in record.primary_ideals:
        values = ideal_volume_values(ideal)
        all_values.extend(values)
        if ideal.get("GeometricComponent"):
            geometric_values.extend(values)
            geometric_ideal_names.append(ideal.get("IdealName"))

    positive_all = [v for v in all_values if v > 0]
    positive_geo = [v for v in geometric_values if v > 0]

    def closest(values: list[float]) -> tuple[float | None, float | None]:
        if snappy_vol is None or not values:
            return None, None
        value = min(values, key=lambda v: abs(v - snappy_vol))
        return value, abs(value - snappy_vol)

    closest_any, any_delta = closest(positive_all)
    closest_geo, geo_delta = closest(positive_geo)
    return {
        "all_positive_volume_values": sorted(round(v, 10) for v in positive_all),
        "geometric_positive_volume_values": sorted(round(v, 10) for v in positive_geo),
        "geometric_ideal_names": geometric_ideal_names,
        "closest_any_volume": closest_any,
        "closest_any_delta": any_delta,
        "closest_geometric_volume": closest_geo,
        "closest_geometric_delta": geo_delta,
    }


def classify(record: Any, snappy_vol: float | None, summary: dict[str, Any], tolerance: float, snappy_error: str | None) -> tuple[str, str]:
    if record.hyperbolic is not True:
        if snappy_vol is not None and snappy_vol > tolerance:
            return "WARN", "JSON says non-hyperbolic but SnapPy returned positive volume"
        return "SKIP", "non-hyperbolic in JSON"
    if snappy_vol is None:
        return "NO_SNAPPY", snappy_error or "SnapPy lookup failed"
    if snappy_vol <= tolerance:
        return "FAIL", "JSON says hyperbolic but SnapPy volume is zero"
    if summary["closest_geometric_delta"] is not None and summary["closest_geometric_delta"] <= tolerance:
        return "OK", "geometric component volume matches SnapPy"
    if summary["closest_any_delta"] is not None and summary["closest_any_delta"] <= tolerance:
        return "GEOM_MISMATCH", "some component matches SnapPy, but marked geometric component does not"
    if not summary["geometric_ideal_names"]:
        return "NO_GEOM", "no marked geometric component"
    return "FAIL", "no computed volume matches SnapPy within tolerance"


def read_record(path: Path) -> Any:
    with path.open() as f:
        return normalize_record(path.name, json.load(f))


def compare_dir(json_dir: Path, dataset: str, tolerance: float) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(json_dir.glob("*.json")):
        record = read_record(path)
        vol, snappy_name, snappy_error = snappy_volume(str(record.name))
        summary = volume_summary(record, vol)
        status, note = classify(record, vol, summary, tolerance, snappy_error)
        rows.append(
            {
                "dataset": dataset,
                "filename": path.name,
                "index": record.index,
                "name": record.name,
                "hyperbolic": record.hyperbolic,
                "snappy_name": snappy_name,
                "snappy_volume": vol,
                "status": status,
                "note": note,
                "geometric_ideal_names": ";".join(str(x) for x in summary["geometric_ideal_names"]),
                "closest_geometric_volume": summary["closest_geometric_volume"],
                "closest_geometric_delta": summary["closest_geometric_delta"],
                "closest_any_volume": summary["closest_any_volume"],
                "closest_any_delta": summary["closest_any_delta"],
                "geometric_positive_volume_values": json.dumps(summary["geometric_positive_volume_values"]),
                "all_positive_volume_values": json.dumps(summary["all_positive_volume_values"]),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "dataset",
        "filename",
        "index",
        "name",
        "hyperbolic",
        "snappy_name",
        "snappy_volume",
        "status",
        "note",
        "geometric_ideal_names",
        "closest_geometric_volume",
        "closest_geometric_delta",
        "closest_any_volume",
        "closest_any_delta",
        "nearest_snappy_name_to_computed",
        "nearest_snappy_delta_to_computed",
        "geometric_positive_volume_values",
        "all_positive_volume_values",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, Any]], tolerance: float) -> None:
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    interesting = [row for row in rows if row["status"] not in {"OK", "SKIP"}]
    interesting.sort(key=lambda row: (row["dataset"], int(row["index"]) if str(row["index"]).isdigit() else math.inf))
    lines = [
        "# SnapPy Volume Comparison",
        "",
        f"Tolerance: `{tolerance}`",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in sorted(by_status.items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Candidate Problems", ""])
    for row in interesting[:300]:
        lines.append(f"### {row['dataset']} / {row['filename']} [{row['status']}]")
        lines.append(f"- Note: {row['note']}")
        lines.append(f"- SnapPy: `{row['snappy_name']}` volume `{row['snappy_volume']}`")
        lines.append(f"- Geometric ideals: `{row['geometric_ideal_names']}`")
        lines.append(f"- Closest geometric delta: `{row['closest_geometric_delta']}`")
        lines.append(f"- Closest any delta: `{row['closest_any_delta']}`")
        lines.append(f"- Nearest SnapPy volume to computed value: `{row.get('nearest_snappy_name_to_computed')}` delta `{row.get('nearest_snappy_delta_to_computed')}`")
        lines.append("")
    if len(interesting) > 300:
        lines.append(f"_Only first 300 candidate rows shown. See CSV/JSON for all {len(interesting)} rows._")
    path.write_text("\n".join(lines))


def annotate_nearest_snappy(rows: list[dict[str, Any]]) -> None:
    snappy_rows = [
        row
        for row in rows
        if row.get("snappy_volume") is not None and row.get("snappy_name") is not None and str(row.get("snappy_volume")) not in {"", "None"}
    ]
    for row in rows:
        computed = row.get("closest_any_volume")
        if computed is None:
            row["nearest_snappy_name_to_computed"] = None
            row["nearest_snappy_delta_to_computed"] = None
            continue
        computed_float = float(computed)
        nearest = min(snappy_rows, key=lambda candidate: abs(float(candidate["snappy_volume"]) - computed_float))
        row["nearest_snappy_name_to_computed"] = nearest["snappy_name"]
        row["nearest_snappy_delta_to_computed"] = abs(float(nearest["snappy_volume"]) - computed_float)


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = compare_dir(args.json_dir, "new", args.tolerance)
    if args.include_old:
        rows.extend(compare_dir(args.old_json_dir, "old", args.tolerance))
    annotate_nearest_snappy(rows)
    write_csv(args.out_dir / "snappy_volume_comparison.csv", rows)
    (args.out_dir / "snappy_volume_comparison.json").write_text(json.dumps(rows, indent=2, sort_keys=True))
    write_markdown(args.out_dir / "snappy_volume_comparison.md", rows, args.tolerance)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(json.dumps({"rows": len(rows), "status_counts": counts}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
