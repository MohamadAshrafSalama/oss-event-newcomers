#!/usr/bin/env python3
"""
================================================================================
Script 00: Dataset Validation and Summary Statistics
================================================================================
Paper Section: Section 3.1 (Project Corpus), 3.2 (Event Contributor
               Identification), 3.3 (Organic Contributor Matching),
               Table 1 (Dataset Overview)

Purpose:
  - Validate the matched-cohort design
  - Reproduce Table 1 (dataset breakdown by event type)
  - Confirm matching quality: Mann-Whitney U test on commit counts
    between event and organic groups (paper: p = 0.21, Cliff's d = -0.02)

References:
  - Munaiah et al. (2017): Project selection criteria
  - Pinto et al. (2016): >= 3 commits threshold for casual contributors
  - Zhou & Mockus (2012): Proportional matching [0.5x, 1.5x]
  - Zhu et al. (2019): Identity resolution (username-email merging)
================================================================================
"""

import csv
import os
import sys
from collections import Counter

import numpy as np
from scipy.stats import mannwhitneyu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "figures")
os.makedirs(OUT, exist_ok=True)


def cliffs_delta(x, y):
    """Cliff's delta effect size for two independent samples."""
    nx, ny = len(x), len(y)
    more = sum(1 for xi in x for yi in y if xi > yi)
    less = sum(1 for xi in x for yi in y if xi < yi)
    return (more - less) / (nx * ny)


def load_csv(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


def main():
    print("=" * 70)
    print("SCRIPT 00: DATASET VALIDATION")
    print("Paper: Section 3.1-3.3, Table 1")
    print("=" * 70)

    event = load_csv("event_contributors.csv")
    organic = load_csv("organic_contributors.csv")
    core = load_csv("per_contributor_core_status.csv")

    # ── Table 1: Dataset Overview ──────────────────────────────────────
    print("\n── TABLE 1: Dataset Overview ──")
    print(f"{'Category':<25} {'Event/Source':<25} {'n':>6} {'%':>7}")
    print("-" * 65)

    mentorship_events = {"gsoc": "Google Summer of Code", "lfx": "Linux Foundation (LFX)"}
    nonmentorship_events = {"24pr": "24 Pull Requests", "hacktoberfest": "Hacktoberfest"}

    event_counts = Counter(e["event"] for e in event)
    ment_total = sum(event_counts[k] for k in mentorship_events)
    nonm_total = sum(event_counts[k] for k in nonmentorship_events)
    total = len(event) + len(organic)

    for key, label in mentorship_events.items():
        n = event_counts[key]
        print(f"{'Mentorship':<25} {label:<25} {n:>6} {n/total*100:>6.1f}")
    print(f"{'':<25} {'Subtotal':<25} {ment_total:>6} {ment_total/total*100:>6.1f}")
    print("-" * 65)

    for key, label in nonmentorship_events.items():
        n = event_counts[key]
        print(f"{'Non-Mentorship':<25} {label:<25} {n:>6} {n/total*100:>6.1f}")
    print(f"{'':<25} {'Subtotal':<25} {nonm_total:>6} {nonm_total/total*100:>6.1f}")
    print("-" * 65)

    print(f"{'Organic (matched)':<25} {'Same project, no event':<25} {len(organic):>6} "
          f"{len(organic)/total*100:>6.1f}")
    print("-" * 65)
    print(f"{'TOTAL':<25} {'':<25} {total:>6} {'100.0':>7}")

    # ── Matching Validation ────────────────────────────────────────────
    print("\n── MATCHING VALIDATION ──")
    print("Paper: Mann-Whitney p = 0.21, Cliff's delta = -0.02")

    event_commits = np.array([int(e["commit_count"]) for e in event])
    organic_commits = np.array([int(o["commit_count"]) for o in organic])

    stat, p = mannwhitneyu(event_commits, organic_commits, alternative="two-sided")
    d = cliffs_delta(event_commits.tolist(), organic_commits.tolist())

    print(f"\n  Event commits:   median={np.median(event_commits):.0f}, "
          f"mean={np.mean(event_commits):.1f}, n={len(event_commits)}")
    print(f"  Organic commits: median={np.median(organic_commits):.0f}, "
          f"mean={np.mean(organic_commits):.1f}, n={len(organic_commits)}")
    print(f"\n  Mann-Whitney U = {stat:.1f}")
    print(f"  p-value = {p:.4f}")
    print(f"  Cliff's delta = {d:.4f}")
    print(f"  Groups comparable: {'YES' if p > 0.05 else 'NO'}")

    # ── Core Status Summary ────────────────────────────────────────────
    print("\n── CORE STATUS SUMMARY ──")
    for ctype in ["event", "organic"]:
        subset = [r for r in core if r["contributor_type"] == ctype]
        n_core = sum(1 for r in subset if r["ever_core"] == "True")
        print(f"  {ctype.title()}: {len(subset)} total, {n_core} core "
              f"({n_core/len(subset)*100:.1f}%)")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
