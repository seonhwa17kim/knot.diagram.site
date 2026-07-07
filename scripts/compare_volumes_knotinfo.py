#!/usr/bin/env python3
"""Compare local parabolic JSON complex volumes with KnotInfo volumes."""

from __future__ import annotations

import argparse
import csv
import html.parser
import json
import math
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from compare_parabolic_json import complex_volume_values, filename_info, normalize_record


KNOTINFO_RESULTS_URL = "https://knotinfo.org/results.php"


class KnotInfoVolumeParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_results = False
        self.in_row = False
        self.in_cell = False
        self.current_cells: list[str] = []
        self.current_text: list[str] = []
        self.rows: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "table" and attr.get("id") == "results":
            self.in_results = True
        elif self.in_results and tag == "tr":
            self.in_row = True
            self.current_cells = []
        elif self.in_row and tag == "td":
            self.in_cell = True
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.in_cell:
            self.current_cells.append(" ".join("".join(self.current_text).split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if len(self.current_cells) >= 2 and self.current_cells[0] != "Name":
                self.rows.append(
                    {
                        "name": self.current_cells[0],
                        "volume": parse_float(self.current_cells[1]),
                        "chern_simons": parse_float(self.current_cells[2]) if len(self.current_cells) >= 3 else None,
                    }
                )
            self.in_row = False
        elif tag == "table" and self.in_results:
            self.in_results = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-dir", type=Path, default=Path("parabolic/data/json"))
    parser.add_argument("--new-dir", type=Path, default=Path("parabolic/data/~12-crossings"))
    parser.add_argument("--thirteen-dir", type=Path, default=Path("parabolic/data/13-crossings"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/parabolic_volume_validation"))
    parser.add_argument("--cache", type=Path, default=Path("reports/parabolic_volume_validation/knotinfo_complex_volume_le13.json"))
    parser.add_argument("--refresh-knotinfo", action="store_true")
    parser.add_argument("--tolerance", type=float, default=1.0e-4)
    return parser.parse_args()


def parse_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    match = re.search(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value)
    if not match:
        return None
    return float(match.group(0))


def canonical_knot_name(value: Any, fallback_filename: str | None = None) -> str:
    if isinstance(value, str) and value:
        name = value
    elif fallback_filename:
        name = filename_info(fallback_filename)[0] or Path(fallback_filename).stem
    else:
        name = ""
    name = re.sub(r"\(\d+\)$", "", name)
    match = re.match(r"^(\d+)([an])_?0*(\d+)$", name)
    if match:
        crossing, family, number = match.groups()
        return f"{crossing}{family}_{int(number)}"
    return name


def geometric_marker(value: Any) -> bool:
    if value in (None, False, 0, "0", "{0}", "", []):
        return False
    return True


def ideal_volume_values(ideal: dict[str, Any]) -> list[float]:
    return [abs(z.imag) for z in complex_volume_values(ideal.get("ComplexVolumeN"))]


def fetch_knotinfo_volumes() -> dict[str, dict[str, float | None]]:
    query = urllib.parse.urlencode(
        {
            "searchmode": "selectknot",
            "category[]": "le13",
            "name": "=1",
            "volume": "=1",
            "chern_simons_invariant": "=1",
            "submittype": "selectknot",
            "startrow": "0",
            "rows": "12965",
        }
    )
    request = urllib.request.Request(
        f"{KNOTINFO_RESULTS_URL}?{query}",
        headers={"User-Agent": "knot.diagram.site volume validation"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        html = response.read().decode("utf-8", errors="replace")
    parser = KnotInfoVolumeParser()
    parser.feed(html)
    return {canonical_knot_name(row["name"]): {"volume": row["volume"], "chern_simons": row["chern_simons"]} for row in parser.rows}


def load_knotinfo_volumes(cache: Path, refresh: bool) -> dict[str, dict[str, float | None]]:
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    cache.parent.mkdir(parents=True, exist_ok=True)
    data = fetch_knotinfo_volumes()
    cache.write_text(json.dumps(data, indent=2, sort_keys=True))
    return data


def read_record(path: Path) -> Any:
    with path.open() as f:
        return normalize_record(path.name, json.load(f))


def closest(values: list[float], target: float | None) -> tuple[float | None, float | None]:
    positive = [v for v in values if v > 1.0e-10]
    if target is None or not positive:
        return None, None
    value = min(positive, key=lambda v: abs(v - target))
    return value, abs(value - target)


def normalized_chern_simons(value: complex) -> float:
    return -value.real / (2.0 * math.pi * math.pi)


def mod_half_delta(left: float, right: float) -> float:
    return min(abs(left - right - 0.5 * shift) for shift in range(-3, 4))


def closest_complex(values: list[complex], target_volume: float | None, target_cs: float | None) -> dict[str, float | None]:
    candidates = [z for z in values if abs(z.imag) > 1.0e-10]
    if target_volume is None or not candidates:
        return {"volume": None, "volume_delta": None, "chern_simons": None, "chern_simons_delta_mod_half": None}
    if target_cs is None:
        best = min(candidates, key=lambda z: abs(abs(z.imag) - target_volume))
    else:
        best = min(candidates, key=lambda z: (abs(abs(z.imag) - target_volume), mod_half_delta(normalized_chern_simons(z), target_cs)))
    local_cs = normalized_chern_simons(best)
    return {
        "volume": abs(best.imag),
        "volume_delta": abs(abs(best.imag) - target_volume),
        "chern_simons": local_cs,
        "chern_simons_delta_mod_half": mod_half_delta(local_cs, target_cs) if target_cs is not None else None,
    }


def compare_record(path: Path, dataset: str, knotinfo_volumes: dict[str, dict[str, float | None]], tolerance: float) -> dict[str, Any]:
    try:
        record = read_record(path)
    except Exception as exc:  # noqa: BLE001
        return {
            "dataset": dataset,
            "filename": path.name,
            "name": canonical_knot_name(None, path.name),
            "status": "READ_ERROR",
            "note": f"{type(exc).__name__}: {exc}",
        }

    name = canonical_knot_name(record.name, path.name)
    knotinfo_entry = knotinfo_volumes.get(name)
    knotinfo_volume = knotinfo_entry.get("volume") if knotinfo_entry else None
    knotinfo_chern_simons = knotinfo_entry.get("chern_simons") if knotinfo_entry else None
    all_values: list[float] = []
    geometric_values: list[float] = []
    all_complex_values: list[complex] = []
    geometric_complex_values: list[complex] = []
    geometric_ideal_names: list[str] = []
    for ideal in record.primary_ideals:
        complex_values = complex_volume_values(ideal.get("ComplexVolumeN"))
        values = [abs(z.imag) for z in complex_values]
        all_values.extend(values)
        all_complex_values.extend(complex_values)
        if geometric_marker(ideal.get("GeometricComponent")):
            geometric_values.extend(values)
            geometric_complex_values.extend(complex_values)
            geometric_ideal_names.append(str(ideal.get("IdealName")))

    closest_any, closest_any_delta = closest(all_values, knotinfo_volume)
    closest_geo, closest_geo_delta = closest(geometric_values, knotinfo_volume)
    closest_any_complex = closest_complex(all_complex_values, knotinfo_volume, knotinfo_chern_simons)
    closest_geo_complex = closest_complex(geometric_complex_values, knotinfo_volume, knotinfo_chern_simons)
    positive_all = sorted(round(v, 10) for v in all_values if v > 1.0e-10)
    positive_geo = sorted(round(v, 10) for v in geometric_values if v > 1.0e-10)

    if name not in knotinfo_volumes:
        status = "NO_KNOTINFO"
        note = "knot is absent from fetched KnotInfo table"
    elif knotinfo_volume is None:
        status = "NO_KNOTINFO_VOLUME"
        note = "KnotInfo volume did not parse as a number"
    elif knotinfo_volume <= tolerance:
        if positive_all and max(positive_all) > tolerance:
            status = "FAIL_POSITIVE_FOR_ZERO"
            note = "KnotInfo volume is zero but local data has positive imaginary complex volume"
        else:
            status = "ZERO_OK"
            note = "KnotInfo volume is zero"
    elif closest_geo_delta is not None and closest_geo_delta <= tolerance:
        status = "OK"
        note = "geometric component volume matches KnotInfo"
    elif closest_any_delta is not None and closest_any_delta <= tolerance:
        status = "OK_ANY"
        note = "some component matches KnotInfo, but no marked geometric component did"
    else:
        status = "FAIL"
        note = "no local complex-volume imaginary part matches KnotInfo"

    return {
        "dataset": dataset,
        "filename": path.name,
        "index": record.index,
        "name": name,
        "json_name": record.name,
        "hyperbolic": record.hyperbolic,
        "knotinfo_volume": knotinfo_volume,
        "knotinfo_chern_simons": knotinfo_chern_simons,
        "status": status,
        "note": note,
        "geometric_ideal_names": ";".join(geometric_ideal_names),
        "closest_geometric_volume": closest_geo,
        "closest_geometric_delta": closest_geo_delta,
        "closest_geometric_chern_simons": closest_geo_complex["chern_simons"],
        "closest_geometric_chern_simons_delta_mod_half": closest_geo_complex["chern_simons_delta_mod_half"],
        "closest_any_volume": closest_any,
        "closest_any_delta": closest_any_delta,
        "closest_any_chern_simons": closest_any_complex["chern_simons"],
        "closest_any_chern_simons_delta_mod_half": closest_any_complex["chern_simons_delta_mod_half"],
        "geometric_positive_volume_values": json.dumps(positive_geo),
        "all_positive_volume_values": json.dumps(positive_all),
    }


def compare_dir(json_dir: Path, dataset: str, knotinfo_volumes: dict[str, dict[str, float | None]], tolerance: float) -> list[dict[str, Any]]:
    return [compare_record(path, dataset, knotinfo_volumes, tolerance) for path in sorted(json_dir.glob("*.json"))]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "dataset",
        "filename",
        "index",
        "name",
        "json_name",
        "hyperbolic",
        "knotinfo_volume",
        "knotinfo_chern_simons",
        "status",
        "note",
        "geometric_ideal_names",
        "closest_geometric_volume",
        "closest_geometric_delta",
        "closest_geometric_chern_simons",
        "closest_geometric_chern_simons_delta_mod_half",
        "closest_any_volume",
        "closest_any_delta",
        "closest_any_chern_simons",
        "closest_any_chern_simons_delta_mod_half",
        "geometric_positive_volume_values",
        "all_positive_volume_values",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, Any]], tolerance: float, knotinfo_count: int) -> None:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("dataset")), str(row.get("status")))
        counts[key] = counts.get(key, 0) + 1

    lines = [
        "# KnotInfo Volume Comparison",
        "",
        f"Tolerance: `{tolerance}`",
        f"KnotInfo rows fetched: `{knotinfo_count}`",
        "Chern-Simons comparison uses `-Re(ComplexVolumeN)/(2*pi^2)` modulo `1/2`.",
        "",
        "## Status Counts",
        "",
    ]
    for (dataset, status), count in sorted(counts.items()):
        lines.append(f"- {dataset} / {status}: {count}")

    interesting = [row for row in rows if row.get("status") not in {"OK", "ZERO_OK"}]
    interesting.sort(key=lambda row: (str(row.get("dataset")), int(row.get("index")) if str(row.get("index")).isdigit() else math.inf))
    lines.extend(["", "## Candidate Problems", ""])
    for row in interesting[:400]:
        lines.append(f"### {row.get('dataset')} / {row.get('filename')} [{row.get('status')}]")
        lines.append(f"- KnotInfo volume / Chern-Simons: `{row.get('knotinfo_volume')}` / `{row.get('knotinfo_chern_simons')}`")
        lines.append(f"- Note: {row.get('note')}")
        lines.append(f"- Geometric ideals: `{row.get('geometric_ideal_names')}`")
        lines.append(f"- Closest geometric volume/delta: `{row.get('closest_geometric_volume')}` / `{row.get('closest_geometric_delta')}`")
        lines.append(
            f"- Closest geometric Chern-Simons/delta mod 1/2: `{row.get('closest_geometric_chern_simons')}` / "
            f"`{row.get('closest_geometric_chern_simons_delta_mod_half')}`"
        )
        lines.append(f"- Closest any volume/delta: `{row.get('closest_any_volume')}` / `{row.get('closest_any_delta')}`")
        lines.append(
            f"- Closest any Chern-Simons/delta mod 1/2: `{row.get('closest_any_chern_simons')}` / "
            f"`{row.get('closest_any_chern_simons_delta_mod_half')}`"
        )
        lines.append("")
    if len(interesting) > 400:
        lines.append(f"_Only first 400 candidate rows shown. See CSV/JSON for all {len(interesting)} rows._")

    cs_issues = []
    for row in rows:
        if row.get("status") == "OK":
            delta = row.get("closest_geometric_chern_simons_delta_mod_half")
        elif row.get("status") == "OK_ANY":
            delta = row.get("closest_any_chern_simons_delta_mod_half")
        else:
            delta = None
        if delta not in (None, "") and float(delta) > 1.0e-5:
            cs_issues.append(row)
    lines.extend(["", "## Chern-Simons Candidate Problems", ""])
    if not cs_issues:
        lines.append("No Chern-Simons discrepancies above `1e-5` among volume-matching rows.")
    for row in cs_issues[:200]:
        lines.append(f"### {row.get('dataset')} / {row.get('filename')}")
        lines.append(f"- KnotInfo Chern-Simons: `{row.get('knotinfo_chern_simons')}`")
        lines.append(f"- Closest geometric Chern-Simons/delta mod 1/2: `{row.get('closest_geometric_chern_simons')}` / `{row.get('closest_geometric_chern_simons_delta_mod_half')}`")
        lines.append(f"- Closest any Chern-Simons/delta mod 1/2: `{row.get('closest_any_chern_simons')}` / `{row.get('closest_any_chern_simons_delta_mod_half')}`")
        lines.append("")
    path.write_text("\n".join(lines))


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    knotinfo_volumes = load_knotinfo_volumes(args.cache, args.refresh_knotinfo)
    rows: list[dict[str, Any]] = []
    rows.extend(compare_dir(args.old_dir, "old-json", knotinfo_volumes, args.tolerance))
    rows.extend(compare_dir(args.new_dir, "new-~12-crossings", knotinfo_volumes, args.tolerance))
    rows.extend(compare_dir(args.thirteen_dir, "13-crossings", knotinfo_volumes, args.tolerance))

    write_csv(args.out_dir / "knotinfo_volume_comparison.csv", rows)
    (args.out_dir / "knotinfo_volume_comparison.json").write_text(json.dumps(rows, indent=2, sort_keys=True))
    write_markdown(args.out_dir / "knotinfo_volume_comparison.md", rows, args.tolerance, len(knotinfo_volumes))

    status_counts: dict[str, int] = {}
    dataset_counts: dict[str, dict[str, int]] = {}
    for row in rows:
        status = str(row.get("status"))
        dataset = str(row.get("dataset"))
        status_counts[status] = status_counts.get(status, 0) + 1
        dataset_counts.setdefault(dataset, {})
        dataset_counts[dataset][status] = dataset_counts[dataset].get(status, 0) + 1
    print(json.dumps({"rows": len(rows), "knotinfo_rows": len(knotinfo_volumes), "status_counts": status_counts, "dataset_counts": dataset_counts}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
