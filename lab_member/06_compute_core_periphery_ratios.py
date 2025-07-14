#!/usr/bin/env python3
"""
Compute core vs periphery contributor ratios from commit data.

Core definition (Pareto 80/20, per repo):
  Sort contributors by commit count descending. The core is the smallest
  group whose commits sum to >= 80% of all commits in that repo.

Input:  commits CSV. Needs at least a repo column and a contributor column.
        Works with repo_name + author_email (from the consolidated commits file).
Output: two files --
  - ratios CSV: one row per repo with core_contributor_ratio, core_commit_share, etc.
  - contributor CSV: one row per contributor with is_core flag.

Usage:
  python 06_compute_core_periphery_ratios.py \
    --commits 04_contributor_selection_and_organic_matching/outputs/all_commits_consolidated.csv \
    --ratios-out core_periphery_ratios.csv \
    --contributors-out contributor_commit_agg.csv
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def pick_col(row: Dict[str, str], candidates: Iterable[str]) -> str:
    for c in candidates:
        value = (row.get(c) or "").strip()
        if value:
            return value
    return ""


def aggregate_contributor_commits(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str], int]:
    counter: Dict[Tuple[str, str], int] = defaultdict(int)
    for row in rows:
        repo = pick_col(row, ("repo_name", "repo", "repository", "full_name"))
        contributor = pick_col(
            row,
            (
                "author_email",
                "author_name",
                "username",
                "github_username",
                "contributor_id",
                "name",
            ),
        )
        if not repo or not contributor:
            continue
        counter[(repo, contributor)] += 1
    return counter


def compute_core_set(commits_by_contributor: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
    total = sum(c for _, c in commits_by_contributor)
    if total <= 0:
        return []
    threshold = total * 0.8
    cumulative = 0
    core = []
    for contributor, count in commits_by_contributor:
        core.append((contributor, count))
        cumulative += count
        if cumulative >= threshold:
            break
    return core


def safe_div(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return a / b


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute core/periphery contributor ratios.")
    parser.add_argument("--commits", required=True, help="Commit CSV path.")
    parser.add_argument("--ratios-out", required=True, help="Output repo-level ratio CSV.")
    parser.add_argument(
        "--contributors-out", required=True, help="Output contributor aggregation CSV."
    )
    args = parser.parse_args()

    commit_rows = read_csv(Path(args.commits))
    agg = aggregate_contributor_commits(commit_rows)

    by_repo: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for (repo, contributor), commit_count in agg.items():
        by_repo[repo].append((contributor, commit_count))

    contributor_rows: List[Dict[str, object]] = []
    ratio_rows: List[Dict[str, object]] = []

    for repo, pairs in sorted(by_repo.items()):
        pairs_sorted = sorted(pairs, key=lambda x: x[1], reverse=True)
        total_commits = sum(c for _, c in pairs_sorted)
        total_contributors = len(pairs_sorted)
        core_pairs = compute_core_set(pairs_sorted)
        core_names = {name for name, _ in core_pairs}
        core_contributors = len(core_pairs)
        peripheral_contributors = max(total_contributors - core_contributors, 0)
        core_commit_sum = sum(c for _, c in core_pairs)
        peripheral_commit_sum = max(total_commits - core_commit_sum, 0)

        for name, count in pairs_sorted:
            contributor_rows.append(
                {
                    "repo": repo,
                    "contributor_id": name,
                    "commit_count": count,
                    "is_core": name in core_names,
                }
            )

        ratio_rows.append(
            {
                "repo": repo,
                "total_commits": total_commits,
                "total_contributors": total_contributors,
                "core_contributors": core_contributors,
                "peripheral_contributors": peripheral_contributors,
                "core_commit_sum": core_commit_sum,
                "peripheral_commit_sum": peripheral_commit_sum,
                "core_contributor_ratio": safe_div(core_contributors, total_contributors),
                "peripheral_contributor_ratio": safe_div(
                    peripheral_contributors, total_contributors
                ),
                "core_to_peripheral_ratio": safe_div(
                    core_contributors, peripheral_contributors
                ),
                "core_commit_share": safe_div(core_commit_sum, total_commits),
            }
        )

    contrib_out = Path(args.contributors_out)
    contrib_out.parent.mkdir(parents=True, exist_ok=True)
    with contrib_out.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["repo", "contributor_id", "commit_count", "is_core"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(contributor_rows)

    ratios_out = Path(args.ratios_out)
    ratios_out.parent.mkdir(parents=True, exist_ok=True)
    with ratios_out.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "repo",
            "total_commits",
            "total_contributors",
            "core_contributors",
            "peripheral_contributors",
            "core_commit_sum",
            "peripheral_commit_sum",
            "core_contributor_ratio",
            "peripheral_contributor_ratio",
            "core_to_peripheral_ratio",
            "core_commit_share",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(ratio_rows)

    print(f"Saved contributor table ({len(contributor_rows)} rows) -> {args.contributors_out}")
    print(f"Saved ratio table ({len(ratio_rows)} rows) -> {args.ratios_out}")


if __name__ == "__main__":
    main()
