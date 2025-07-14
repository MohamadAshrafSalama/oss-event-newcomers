#!/usr/bin/env python3
"""
Normalize repo metrics by project size (NCLOC).

Without normalization you can't fairly compare a project like Firefox
(millions of lines) to a small project (a few thousand). Dividing each
metric by code size (per 1000 lines) makes the numbers comparable.

Formula: metric_per_kloc = metric / (code_lines / 1000)

Raw and normalized values are both kept in the output so nothing is lost.

Input:  repo_metadata.csv (from 01) + project_size_metrics.csv (from 04)
Output: repo_metrics_normalized.csv with added *_per_kloc columns.

Usage:
  python 05_normalize_metrics.py \
    --metadata repo_metadata.csv \
    --size project_size_metrics.csv \
    --out repo_metrics_normalized.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def to_float(value: str) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def per_kloc(metric: float, code_lines: float) -> float:
    if code_lines <= 0:
        return 0.0
    return metric / (code_lines / 1000.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize metrics by project size.")
    parser.add_argument("--metadata", required=True, help="Metadata CSV from script 01.")
    parser.add_argument("--size", required=True, help="Size CSV from script 04.")
    parser.add_argument("--out", required=True, help="Output normalized CSV.")
    args = parser.parse_args()

    metadata = read_csv(Path(args.metadata))
    size_rows = read_csv(Path(args.size))
    size_by_repo = {row["repo"]: row for row in size_rows if row.get("repo")}

    out_rows: List[Dict[str, object]] = []
    for row in metadata:
        repo = row.get("repo", "")
        size = size_by_repo.get(repo, {})
        code_lines = to_float(size.get("code_lines", "0"))
        ncloc_proxy = to_float(size.get("ncloc_proxy", "0"))

        commit_count = to_float(row.get("commit_count", "0"))
        pr_count = to_float(row.get("pr_count", "0"))
        issue_count = to_float(row.get("issue_count", "0"))
        contributor_count = to_float(row.get("contributor_count", "0"))

        out_rows.append(
            {
                "repo": repo,
                "stars": row.get("stars", ""),
                "forks": row.get("forks", ""),
                "open_issues": row.get("open_issues", ""),
                "commit_count": commit_count,
                "pr_count": pr_count,
                "issue_count": issue_count,
                "contributor_count": contributor_count,
                "code_lines": code_lines,
                "ncloc_proxy": ncloc_proxy,
                "commit_per_kloc": per_kloc(commit_count, code_lines),
                "pr_per_kloc": per_kloc(pr_count, code_lines),
                "issue_per_kloc": per_kloc(issue_count, code_lines),
                "contributors_per_kloc": per_kloc(contributor_count, code_lines),
                "status": row.get("status", "ok"),
            }
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "repo",
        "stars",
        "forks",
        "open_issues",
        "commit_count",
        "pr_count",
        "issue_count",
        "contributor_count",
        "code_lines",
        "ncloc_proxy",
        "commit_per_kloc",
        "pr_per_kloc",
        "issue_per_kloc",
        "contributors_per_kloc",
        "status",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"Saved normalized table ({len(out_rows)} rows) -> {args.out}")


if __name__ == "__main__":
    main()
