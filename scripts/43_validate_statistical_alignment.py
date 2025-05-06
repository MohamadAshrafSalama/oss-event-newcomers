#!/usr/bin/env python3
"""
Phase 1 - Step 4: Validate statistical alignment of new event vs organic groups.
Runs Wilcoxon/Mann-Whitney U test, Cliff's delta, and prints detailed results.
Also archives old data and creates the new final dataset.
"""

import json
import os
import shutil
import random
import pandas as pd
import numpy as np
from scipy import stats
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7_EXTRACTED = "/Volumes/T7/Event based OSS4SG/extracted"

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
    arr = np.array(arr, dtype=float)
    print(f"\n  {label} (n={len(arr)}):")
    print(f"    Mean={arr.mean():.1f}, Median={np.median(arr):.1f}, Std={arr.std():.1f}")
    print(f"    Min={arr.min():.0f}, Q1={np.percentile(arr,25):.0f}, Q3={np.percentile(arr,75):.0f}, Max={arr.max():.0f}")

def main():
    print("=" * 70)
    print("PHASE 1 - STEP 4: Validate Statistical Alignment")
    print("=" * 70)
    
    # Load re-selected event contributors
    v2_event_path = os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                                  "outputs", "event_contributors_v2.json")
    with open(v2_event_path) as f:
        event_data = json.load(f)
    
    # Load re-matched organic contributors
    v2_organic_path = os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                                    "outputs", "organic_matches_v2.json")
    with open(v2_organic_path) as f:
        organic_data = json.load(f)
    
    event_contribs = event_data["contributions"]
    organic_matches = organic_data["matches"]
    
    print(f"\nEvent contributors: {len(event_contribs)}")
    print(f"Organic matches: {len(organic_matches)}")
    
    # Build commit count arrays from MATCHED PAIRS only
    # This ensures fair comparison (same number of event vs organic)
    event_commits = [m["event_commits"] for m in organic_matches]
    organic_commits = [m["organic_commits"] for m in organic_matches]
    
    event_commits = np.array(event_commits)
    organic_commits = np.array(organic_commits)
    
    # -- Validation Tests --
    print("\n" + "-" * 50)
    print("DISTRIBUTION COMPARISON")
    print("-" * 50)
    
    describe(event_commits, "Event (all)")
    describe(organic_commits, "Organic (all)")
    
    # Mann-Whitney U test
    stat, p = stats.mannwhitneyu(event_commits, organic_commits, alternative="two-sided")
    delta = cliffs_delta(event_commits, organic_commits)
    
    pct_diff = ((np.mean(event_commits) / np.mean(organic_commits)) - 1) * 100 if np.mean(organic_commits) > 0 else float('inf')
    
    print(f"\n  Mann-Whitney U statistic: {stat:.0f}")
    print(f"  p-value: {p:.6f}")
    print(f"  Cliff's delta: {delta:.4f} ({effect_size_category(delta)})")
    print(f"  Event mean / Organic mean: {np.mean(event_commits):.1f} / {np.mean(organic_commits):.1f}")
    print(f"  Percentage difference: {pct_diff:+.1f}%")
    
    if p > 0.05:
        print("\n  *** PASS: Groups are NOT significantly different (p > 0.05) ***")
    else:
        print("\n  *** WARNING: Groups are still significantly different (p < 0.05) ***")
    
    if abs(delta) < 0.147:
        print("  *** PASS: Cliff's delta is negligible ***")
    else:
        print(f"  *** WARNING: Cliff's delta is {effect_size_category(delta)} ***")
    
    # -- Per-event breakdown (matched pairs only) --
    print("\n" + "-" * 50)
    print("PER-EVENT BREAKDOWN (matched pairs)")
    print("-" * 50)
    
    by_event_ev = defaultdict(list)
    by_event_org = defaultdict(list)
    for m in organic_matches:
        by_event_ev[m["event_type"]].append(m["event_commits"])
        by_event_org[m["event_type"]].append(m["organic_commits"])
    
    for ev_name in ["gsoc", "lfx", "24pr", "hf"]:
        if ev_name in by_event_ev:
            describe(by_event_ev[ev_name], f"{ev_name.upper()} event")
    
    print("\n  Organic matched per event type:")
    for ev_name in ["gsoc", "lfx", "24pr", "hf"]:
        if ev_name in by_event_org:
            vals = by_event_org[ev_name]
            print(f"    {ev_name.upper()}: n={len(vals)}, mean={np.mean(vals):.1f}, median={np.median(vals):.0f}")
    
    # -- Mentorship vs Non-Mentorship --
    print("\n" + "-" * 50)
    print("MENTORSHIP vs NON-MENTORSHIP (within event)")
    print("-" * 50)
    
    mentorship_commits = by_event_ev.get("gsoc", []) + by_event_ev.get("lfx", [])
    non_mentorship_commits = by_event_ev.get("24pr", []) + by_event_ev.get("hf", [])
    
    if mentorship_commits and non_mentorship_commits:
        describe(mentorship_commits, "Mentorship (GSoC+LFX)")
        describe(non_mentorship_commits, "Non-Mentorship (24PR+HF)")
        
        stat2, p2 = stats.mannwhitneyu(mentorship_commits, non_mentorship_commits, alternative="two-sided")
        delta2 = cliffs_delta(mentorship_commits, non_mentorship_commits)
        print(f"\n  Mann-Whitney U: stat={stat2:.0f}, p={p2:.6f}")
        print(f"  Cliff's delta: {delta2:.4f} ({effect_size_category(delta2)})")
    
    # -- Sample 20 random pairs --
    print("\n" + "-" * 50)
    print("SAMPLE 20 RANDOM EVENT-ORGANIC PAIRS")
    print("-" * 50)
    
    random.seed(42)
    sample_indices = random.sample(range(len(organic_matches)), min(20, len(organic_matches)))
    print(f"  {'Event User':<25} {'Event Cmts':>10} | {'Organic Email':<35} {'Org Cmts':>8} | {'Repo'}")
    print(f"  {'-'*25} {'-'*10} | {'-'*35} {'-'*8} | {'-'*30}")
    for idx in sample_indices:
        m = organic_matches[idx]
        print(f"  {m['event_username']:<25} {m['event_commits']:>10} | "
              f"{m['organic_email'][:35]:<35} {m['organic_commits']:>8} | {m['repo'][:30]}")
    
    # -- Archive old data and create new final dataset --
    print("\n" + "-" * 50)
    print("ARCHIVING OLD DATASET & CREATING NEW")
    print("-" * 50)
    
    final_dir = os.path.join(BASE, "06_final_dataset")
    archive_dir = os.path.join(final_dir, "archive_v1")
    os.makedirs(archive_dir, exist_ok=True)
    
    # Move old files to archive
    for fname in ["event_contributors_summary.csv", "organic_contributors_summary.csv",
                   "dataset_summary.json"]:
        src = os.path.join(final_dir, fname)
        dst = os.path.join(archive_dir, fname)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            print(f"  Archived: {fname}")
    
    # Create new event contributors summary CSV (from matched pairs only)
    # Build lookup from contribution_id -> commit count from matches
    event_commit_lookup = {}
    for m in organic_matches:
        event_commit_lookup[m["event_contribution_id"]] = m["event_commits"]
    
    event_rows = []
    for ec in event_contribs:
        cid = ec["contribution_id"]
        c = event_commit_lookup.get(cid, ec.get("t7_commit_count", 0))
        event_rows.append({
            "username": ec["github_username"],
            "repo": ec["repo"],
            "event": ec["event"],
            "commit_count": c,
            "contribution_id": cid,
        })
    event_df = pd.DataFrame(event_rows)
    event_df.to_csv(os.path.join(final_dir, "event_contributors_summary.csv"), index=False)
    print(f"  Created new event_contributors_summary.csv ({len(event_df)} rows)")
    
    # Create new organic contributors summary CSV
    organic_rows = []
    for m in organic_matches:
        organic_rows.append({
            "email": m["organic_email"],
            "name": m["organic_name"],
            "repo": m["repo"],
            "matched_event_type": m["event_type"],
            "commit_count": m["organic_commits"],
            "matched_event_contribution_id": m["event_contribution_id"],
        })
    organic_df = pd.DataFrame(organic_rows)
    organic_df.to_csv(os.path.join(final_dir, "organic_contributors_summary.csv"), index=False)
    print(f"  Created new organic_contributors_summary.csv ({len(organic_df)} rows)")
    
    # Create new dataset summary
    summary = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "version": "v2",
        "description": "Re-selected event contributors (24PR/HF capped 3-50) + activity-band matched organic",
        "total_event": len(event_contribs),
        "total_organic": len(organic_matches),
        "event_breakdown": dict(event_data["by_event"]),
        "unique_repos": len(set(ec["repo"] for ec in event_contribs)),
        "statistical_validation": {
            "mann_whitney_u_statistic": float(stat),
            "p_value": float(p),
            "cliffs_delta": float(delta),
            "cliffs_delta_category": effect_size_category(delta),
            "event_mean_commits": float(np.mean(event_commits)),
            "organic_mean_commits": float(np.mean(organic_commits)),
            "pct_difference": float(pct_diff),
            "groups_comparable": bool(p > 0.05),
        }
    }
    with open(os.path.join(final_dir, "dataset_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Created new dataset_summary.json")
    
    print("\n" + "=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    main()
