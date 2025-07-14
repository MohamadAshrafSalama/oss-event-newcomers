#!/usr/bin/env python3
"""
Validate expected output files and required columns for the starter workflow.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "datasets" / "derived"


REQUIRED: Dict[str, List[str]] = {
    "repo_metadata.csv": ["repo", "commit_count", "pr_count", "issue_count", "contributor_count"],
    "project_size_metrics.csv": ["repo", "code_lines", "ncloc_proxy"],
    "repo_metrics_normalized.csv": ["repo", "commit_per_kloc", "contributors_per_kloc"],
    "core_periphery_ratios.csv": ["repo", "core_contributor_ratio", "core_commit_share"],
    "contributor_commit_agg.csv": ["repo", "contributor_id", "commit_count", "is_core"],
    "rq1_project_descriptive.csv": ["repo", "commit_per_kloc", "core_contributor_ratio"],
    "rq1_contributor_summary.csv": ["repo", "contributor_id", "is_core"],
    "rq1_plot_ready_long.csv": ["repo", "metric", "value"],
}


def check_file(path: Path, required_cols: List[str]) -> List[str]:
    errors: List[str] = []
    if not path.exists():
        return [f"Missing file: {path.name}"]
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        for col in required_cols:
            if col not in cols:
                errors.append(f"{path.name}: missing column `{col}`")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate workflow outputs.")
    parser.add_argument("--mode", choices=["sample", "full"], default="sample")
    args = parser.parse_args()

    errors: List[str] = []
    for filename, cols in REQUIRED.items():
        errors.extend(check_file(DERIVED / filename, cols))

    if args.mode == "full":
        commits_all = DERIVED / "commits_all.csv"
        if not commits_all.exists():
            errors.append("Missing file: commits_all.csv (expected in full mode)")

    if errors:
        print("Validation FAILED:")
        for e in errors:
            print(f"- {e}")
        raise SystemExit(1)

    print("Validation passed: all required outputs and columns are present.")


if __name__ == "__main__":
    main()
