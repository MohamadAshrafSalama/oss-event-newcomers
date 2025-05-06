#!/usr/bin/env python3
"""
Phase 1 - Step 1: Analyze current commit count distributions.
Identifies the exact bias in event vs organic contributor selection.
"""

import pandas as pd
import numpy as np
from scipy import stats
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def cliffs_delta(x, y):
    """Compute Cliff's delta effect size."""
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return 0.0
    more = sum(1 for xi in x for yi in y if xi > yi)
    less = sum(1 for xi in x for yi in y if xi < yi)
    return (more - less) / (nx * ny)

def effect_size_category(d):
    d = abs(d)
    if d < 0.147:
        return "negligible"
    elif d < 0.33:
        return "small"
    elif d < 0.474:
        return "medium"
    else:
        return "large"

def describe(arr, label):
    arr = np.array(arr)
    print(f"\n  {label} (n={len(arr)}):")
    print(f"    Mean={arr.mean():.1f}, Median={np.median(arr):.1f}, Std={arr.std():.1f}")
    print(f"    Min={arr.min()}, Q1={np.percentile(arr,25):.0f}, Q3={np.percentile(arr,75):.0f}, Max={arr.max()}")
    print(f"    P95={np.percentile(arr,95):.0f}, P99={np.percentile(arr,99):.0f}")
    print(f"    >50: {(arr>50).sum()}, >100: {(arr>100).sum()}, >500: {(arr>500).sum()}, >1000: {(arr>1000).sum()}")

def main():
    print("=" * 70)
    print("PHASE 1: Current Distribution Analysis")
    print("=" * 70)

    # Load event contributors
    event_df = pd.read_csv(os.path.join(BASE, "06_final_dataset", "event_contributors_summary.csv"))
    organic_df = pd.read_csv(os.path.join(BASE, "06_final_dataset", "organic_contributors_summary.csv"))

    print(f"\nEvent contributors: {len(event_df)}")
    print(f"Organic contributors: {len(organic_df)}")

    # ---- Per-event breakdown ----
    print("\n" + "-" * 50)
    print("EVENT CONTRIBUTOR DISTRIBUTIONS (by event)")
    print("-" * 50)

    for event_name in ["gsoc", "lfx", "24pr", "hf"]:
        subset = event_df[event_df["event"] == event_name]
        describe(subset["commit_count"].values, f"{event_name.upper()}")

    describe(event_df["commit_count"].values, "ALL EVENT")

    print("\n" + "-" * 50)
    print("ORGANIC CONTRIBUTOR DISTRIBUTION")
    print("-" * 50)
    describe(organic_df["commit_count"].values, "ALL ORGANIC")

    # ---- Statistical comparison ----
    print("\n" + "-" * 50)
    print("STATISTICAL COMPARISON: Event vs Organic (commit_count)")
    print("-" * 50)

    ev_commits = event_df["commit_count"].values
    org_commits = organic_df["commit_count"].values

    stat, p = stats.mannwhitneyu(ev_commits, org_commits, alternative="two-sided")
    delta = cliffs_delta(ev_commits, org_commits)

    print(f"\n  Mann-Whitney U statistic: {stat:.0f}")
    print(f"  p-value: {p:.6e}")
    print(f"  Cliff's delta: {delta:.4f} ({effect_size_category(delta)})")
    print(f"  Event mean / Organic mean: {ev_commits.mean():.1f} / {org_commits.mean():.1f}")
    print(f"  Ratio: event is {((ev_commits.mean()/org_commits.mean())-1)*100:.1f}% higher")

    if p < 0.05:
        print("\n  *** FAIL: Groups are SIGNIFICANTLY different (p < 0.05) ***")
    else:
        print("\n  *** PASS: Groups are NOT significantly different (p > 0.05) ***")

    # ---- Top outliers ----
    print("\n" + "-" * 50)
    print("TOP 20 EVENT CONTRIBUTORS BY COMMIT COUNT")
    print("-" * 50)
    top = event_df.nlargest(20, "commit_count")[["username", "repo", "event", "commit_count"]]
    for _, row in top.iterrows():
        print(f"  {row['commit_count']:>6} commits | {row['event']:>13} | {row['username']} @ {row['repo']}")

    print("\n" + "-" * 50)
    print("TOP 10 ORGANIC CONTRIBUTORS BY COMMIT COUNT")
    print("-" * 50)
    top_org = organic_df.nlargest(10, "commit_count")[["email", "repo", "matched_event_type", "commit_count"]]
    for _, row in top_org.iterrows():
        print(f"  {row['commit_count']:>6} commits | {row['matched_event_type']:>13} | {row['email'][:30]} @ {row['repo']}")

    # ---- Mentorship vs Non-mentorship ----
    print("\n" + "-" * 50)
    print("MENTORSHIP vs NON-MENTORSHIP")
    print("-" * 50)

    mentorship = event_df[event_df["event"].isin(["gsoc", "lfx"])]["commit_count"].values
    non_mentorship = event_df[event_df["event"].isin(["24pr", "hf"])]["commit_count"].values

    describe(mentorship, "Mentorship (GSoC+LFX)")
    describe(non_mentorship, "Non-Mentorship (24PR+HF)")

    stat2, p2 = stats.mannwhitneyu(mentorship, non_mentorship, alternative="two-sided")
    delta2 = cliffs_delta(mentorship, non_mentorship)
    print(f"\n  Mann-Whitney U: stat={stat2:.0f}, p={p2:.6e}")
    print(f"  Cliff's delta: {delta2:.4f} ({effect_size_category(delta2)})")

    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    main()
