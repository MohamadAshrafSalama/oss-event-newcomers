#!/usr/bin/env python3
"""
Validate contributor journey CSV outputs against progress.json and schema.

Checks:
- Each completed contributor has a CSV file
- CSV header matches expected schema
- CSV is readable and (optionally) sorted by created_at
- Reports missing/extra files and parse issues
"""

import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path


def resolve_path(base_dir: Path, project_root: Path, path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    base_path = base_dir / path
    if base_path.exists():
        return base_path
    return project_root / path


def load_config(config_path: Path) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_date(value: str, date_format: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, date_format)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def validate_csv(
    csv_path: Path,
    expected_columns: list[str],
    date_format: str,
    check_order: bool,
) -> dict:
    result = {
        "exists": csv_path.exists(),
        "header_ok": False,
        "rows": 0,
        "empty": False,
        "date_parse_errors": 0,
        "out_of_order": 0,
        "read_error": None,
    }

    if not csv_path.exists():
        return result

    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                result["empty"] = True
                return result
            result["header_ok"] = header == expected_columns

            last_dt = None
            for row in reader:
                result["rows"] += 1
                if not check_order:
                    continue
                if len(row) <= expected_columns.index("created_at"):
                    continue
                dt = parse_date(
                    row[expected_columns.index("created_at")], date_format
                )
                if dt is None:
                    result["date_parse_errors"] += 1
                    continue
                if last_dt and dt < last_dt:
                    result["out_of_order"] += 1
                last_dt = dt
    except Exception as exc:  # noqa: BLE001 - surface error in report
        result["read_error"] = str(exc)

    if result["rows"] == 0:
        result["empty"] = True

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate contributor journey CSV outputs."
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config.json (default: config.json)",
    )
    parser.add_argument(
        "--check-order",
        action="store_true",
        help="Validate created_at chronological order (slower)",
    )
    parser.add_argument(
        "--max-contributors",
        type=int,
        default=0,
        help="Only check first N contributors (0 = all)",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Optional path to write a text report",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    project_root = Path(config["paths"]["project_root"])
    base_dir = config_path.parent
    contributors_dir = resolve_path(
        base_dir, project_root, config["paths"]["contributors_output_dir"]
    )
    progress_path = resolve_path(
        base_dir, project_root, config["paths"]["progress_file"]
    )

    expected_columns = config["csv_schema"]["columns"]
    date_format = config["validation"]["date_format"]

    with open(progress_path, "r", encoding="utf-8") as f:
        progress = json.load(f)

    completed = progress.get("completed", [])
    if args.max_contributors > 0:
        completed = completed[: args.max_contributors]

    existing_files = {
        p.stem: p for p in contributors_dir.glob("*.csv") if p.is_file()
    }

    def normalized_username(stem: str) -> str:
        if stem.endswith("_journey"):
            return stem[: -len("_journey")]
        return stem

    missing = []
    extra = []
    header_mismatch = []
    empty_files = []
    read_errors = []
    date_errors = 0
    out_of_order = 0

    for username in completed:
        csv_path = contributors_dir / f"{username}.csv"
        alt_path = contributors_dir / f"{username}_journey.csv"
        result = validate_csv(
            csv_path, expected_columns, date_format, args.check_order
        )
        if not result["exists"]:
            result = validate_csv(
                alt_path, expected_columns, date_format, args.check_order
            )
        if not result["exists"]:
            missing.append(username)
            continue
        if not result["header_ok"]:
            header_mismatch.append(username)
        if result["empty"]:
            empty_files.append(username)
        if result["read_error"]:
            read_errors.append((username, result["read_error"]))
        date_errors += result["date_parse_errors"]
        out_of_order += result["out_of_order"]

    completed_set = set(progress.get("completed", []))
    for stem in existing_files:
        normalized = normalized_username(stem)
        if normalized not in completed_set:
            extra.append(stem)

    total_checked = len(completed)
    lines = []
    lines.append("=== CONTRIBUTOR OUTPUT VALIDATION ===")
    lines.append(f"Contributors checked: {total_checked}")
    lines.append(f"Output directory: {contributors_dir}")
    lines.append(f"Missing CSVs: {len(missing)}")
    lines.append(f"Extra CSVs: {len(extra)}")
    lines.append(f"Header mismatches: {len(header_mismatch)}")
    lines.append(f"Empty CSVs: {len(empty_files)}")
    lines.append(f"Read errors: {len(read_errors)}")
    if args.check_order:
        lines.append(f"Date parse errors: {date_errors}")
        lines.append(f"Out-of-order rows: {out_of_order}")

    if missing:
        lines.append("")
        lines.append("Missing CSVs (first 20):")
        for name in missing[:20]:
            lines.append(f"  - {name}")
    if header_mismatch:
        lines.append("")
        lines.append("Header mismatches (first 20):")
        for name in header_mismatch[:20]:
            lines.append(f"  - {name}")
    if empty_files:
        lines.append("")
        lines.append("Empty CSVs (first 20):")
        for name in empty_files[:20]:
            lines.append(f"  - {name}")
    if read_errors:
        lines.append("")
        lines.append("Read errors (first 5):")
        for name, err in read_errors[:5]:
            lines.append(f"  - {name}: {err}")
    if extra:
        lines.append("")
        lines.append("Extra CSVs not in progress (first 20):")
        for name in extra[:20]:
            lines.append(f"  - {name}")

    report_text = "\n".join(lines)
    print(report_text)
    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_text + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
