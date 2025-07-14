#!/usr/bin/env python3
"""
Join all outputs into final tables ready for analysis and plotting.

Takes the normalized metrics, core ratios, contributor aggregations, and
optionally the mined PR/issue activity, and produces three output files:

  rq1_project_descriptive.csv  -- one row per repo, all metrics merged
  rq1_contributor_summary.csv  -- one row per contributor with commit + activity counts
  rq1_plot_ready_long.csv      -- long format (repo, metric, value) for easy plotting

Usage:
  python 07_build_analysis_ready_tables.py \
    --normalized repo_metrics_normalized.csv \
    --ratios core_periphery_ratios.csv \
    --contributors contributor_commit_agg.csv \
    --activity contributor_activity.csv \
    --out-dir ./outputs
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build final analysis-ready tables.")
    parser.add_argument("--normalized", required=True, help="Normalized repo metrics CSV.")
    parser.add_argument("--ratios", required=True, help="Core/periphery ratio CSV.")
    parser.add_argument("--contributors", required=True, help="Contributor aggregation CSV.")
    parser.add_argument("--activity", default="", help="Optional activity CSV from script 03.")
    parser.add_argument("--out-dir", required=True, help="Output directory.")
    args = parser.parse_args()

    normalized_rows = read_csv(Path(args.normalized))
    ratio_rows = read_csv(Path(args.ratios))
    contributor_rows = read_csv(Path(args.contributors))
    activity_rows = read_csv(Path(args.activity)) if args.activity else []

    ratio_by_repo = {r.get("repo", ""): r for r in ratio_rows if r.get("repo")}

    # Table 1: repo descriptive + ratio merge
    project_rows: List[Dict[str, object]] = []
    for row in normalized_rows:
        repo = row.get("repo", "")
        ratio = ratio_by_repo.get(repo, {})
        merged = dict(row)
        merged["core_contributors"] = ratio.get("core_contributors", "")
        merged["peripheral_contributors"] = ratio.get("peripheral_contributors", "")
        merged["core_contributor_ratio"] = ratio.get("core_contributor_ratio", "")
        merged["core_commit_share"] = ratio.get("core_commit_share", "")
        project_rows.append(merged)

    # Table 2: contributor summary enriched with activity counts
    activity_counts: Dict[str, Counter] = defaultdict(Counter)
    for row in activity_rows:
        cid = row.get("contributor_id", "")
        kind = row.get("activity_type", "")
        if cid and kind:
            activity_counts[cid][kind] += 1

    contrib_summary_rows: List[Dict[str, object]] = []
    for row in contributor_rows:
        cid = row.get("contributor_id", "")
        counts = activity_counts.get(cid, Counter())
        contrib_summary_rows.append(
            {
                "repo": row.get("repo", ""),
                "contributor_id": cid,
                "commit_count": row.get("commit_count", "0"),
                "is_core": row.get("is_core", "False"),
                "pr_count": counts.get("pr", 0),
                "issue_count": counts.get("issue", 0),
                "total_non_commit_activities": counts.get("pr", 0) + counts.get("issue", 0),
            }
        )

    # Table 3: long format for easy plotting
    long_rows: List[Dict[str, object]] = []
    metrics = [
        "commit_per_kloc",
        "pr_per_kloc",
        "issue_per_kloc",
        "contributors_per_kloc",
        "core_contributor_ratio",
        "core_commit_share",
    ]
    for row in project_rows:
        repo = row.get("repo", "")
        for metric in metrics:
            long_rows.append(
                {
                    "repo": repo,
                    "metric": metric,
                    "value": row.get(metric, ""),
                }
            )

    out_dir = Path(args.out_dir)
    write_csv(
        out_dir / "rq1_project_descriptive.csv",
        project_rows,
        fieldnames=[
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
            "core_contributors",
            "peripheral_contributors",
            "core_contributor_ratio",
            "core_commit_share",
            "status",
        ],
    )
    write_csv(
        out_dir / "rq1_contributor_summary.csv",
        contrib_summary_rows,
        fieldnames=[
            "repo",
            "contributor_id",
            "commit_count",
            "is_core",
            "pr_count",
            "issue_count",
            "total_non_commit_activities",
        ],
    )
    write_csv(
        out_dir / "rq1_plot_ready_long.csv",
        long_rows,
        fieldnames=["repo", "metric", "value"],
    )

    print(f"Saved project rows: {len(project_rows)}")
    print(f"Saved contributor rows: {len(contrib_summary_rows)}")
    print(f"Saved long-format rows: {len(long_rows)}")


if __name__ == "__main__":
    main()
