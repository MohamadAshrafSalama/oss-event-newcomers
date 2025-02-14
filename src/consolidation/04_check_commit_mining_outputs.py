#!/usr/bin/env python3
"""
Validate commit mining outputs against progress.json.

Checks:
- Each repo with status=done has an extracted CSV
- CSV files are non-empty
- Reports error/pending repos
- Warns about macOS "._" metadata files
"""

import argparse
import json
import os
from pathlib import Path


def load_progress(progress_path: Path) -> dict:
    with open(progress_path, "r", encoding="utf-8") as f:
        return json.load(f)


def repo_to_filename(repo_full_name: str) -> str:
    return repo_full_name.replace("/", "__") + ".csv"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate commit mining outputs."
    )
    parser.add_argument(
        "--progress",
        default="/Volumes/T7/Event based OSS4SG/progress.json",
        help="Path to progress.json on the T7 drive",
    )
    parser.add_argument(
        "--extracted-dir",
        default="/Volumes/T7/Event based OSS4SG/extracted",
        help="Extracted CSV directory on the T7 drive",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Optional path to write a text report",
    )
    args = parser.parse_args()

    progress_path = Path(args.progress)
    extracted_dir = Path(args.extracted_dir)

    progress = load_progress(progress_path)
    repos = progress.get("repos", {})

    missing_csv = []
    empty_csv = []
    done_count = 0
    error_repos = []
    pending_repos = []

    for repo_name, info in repos.items():
        status = info.get("status", "unknown")
        if status == "done":
            done_count += 1
            csv_path = extracted_dir / repo_to_filename(repo_name)
            if not csv_path.exists():
                missing_csv.append(repo_name)
            else:
                if csv_path.stat().st_size == 0:
                    empty_csv.append(repo_name)
        elif status == "error":
            error_repos.append((repo_name, info.get("error", "Unknown error")))
        else:
            pending_repos.append(repo_name)

    metadata_files = [
        p for p in extracted_dir.glob("._*") if p.is_file()
    ]

    total_repos = len(repos)
    lines = []
    lines.append("=== COMMIT MINING OUTPUT VALIDATION ===")
    lines.append(f"Total repos: {total_repos}")
    lines.append(f"Done repos: {done_count}")
    lines.append(f"Error repos: {len(error_repos)}")
    lines.append(f"Pending repos: {len(pending_repos)}")
    lines.append(f"Missing CSVs for done repos: {len(missing_csv)}")
    lines.append(f"Empty CSVs for done repos: {len(empty_csv)}")
    lines.append(f"macOS metadata files (._*): {len(metadata_files)}")

    if error_repos:
        lines.append("")
        lines.append("Error repos (first 10):")
        for name, err in error_repos[:10]:
            lines.append(f"  - {name}")
            lines.append(f"    Error: {err}")
    if pending_repos:
        lines.append("")
        lines.append("Pending repos (first 10):")
        for name in pending_repos[:10]:
            lines.append(f"  - {name}")
    if missing_csv:
        lines.append("")
        lines.append("Missing CSVs for done repos (first 10):")
        for name in missing_csv[:10]:
            lines.append(f"  - {name}")
    if empty_csv:
        lines.append("")
        lines.append("Empty CSVs for done repos (first 10):")
        for name in empty_csv[:10]:
            lines.append(f"  - {name}")
    if metadata_files:
        lines.append("")
        lines.append("Sample metadata files (first 5):")
        for path in metadata_files[:5]:
            lines.append(f"  - {path.name}")

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
