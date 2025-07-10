#!/usr/bin/env python3
"""
================================================================================
Script 01: Activity Profiling (RQ1)
================================================================================
Paper Section: Section 3.5 "Activity Profiling (RQ1)", Section 4.1.1
               "Activity Profiles", Figure 1 (Spider/Radar Plot)

Purpose:
  Compute and visualize six non-overlapping activity dimensions for
  three groups: Mentorship, Non-Mentorship, and Organic.

Six Dimensions (all percentile-rank normalized to [0, 1]):
  1. Commit Frequency   -- avg commits per active month  [Zhou & Mockus 2012]
  2. PR Success Rate    -- proportion of PRs merged       [Gousios et al. 2016]
  3. Issue Activity     -- avg issues opened per month    [Cheng & Guo 2019]
  4. Discussion Depth   -- avg comment turns per thread   [Constantinou 2017]
  5. Activity Duration  -- months from first to last      [Lin et al. 2017]
  6. Contribution Breadth -- fraction of 4 activity types [Anderson et al. 2025]

Expected Result (Paper):
  - Mentorship: highest on Discussion Depth and Issue Activity
  - Non-Mentorship: highest on Commit Frequency
  - Organic: highest on Activity Duration
  - Key insight: the TYPE of engagement differs, not the AMOUNT

References:
  - Cheng & Guo (2019): Activity dimensions for OSS contributors
  - Anderson et al. (2025): Percentile-rank normalization, contribution breadth
================================================================================
"""

import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "figures")
os.makedirs(OUT, exist_ok=True)

DIMENSION_NAMES = [
    "Commit\nFrequency",
    "PR Success\nRate",
    "Issue\nActivity",
    "Discussion\nDepth",
    "Activity\nDuration",
    "Contribution\nBreadth",
]

MENTORSHIP_EVENTS = {"gsoc", "lfx"}
NON_MENTORSHIP_EVENTS = {"hacktoberfest", "24pr"}


def load_profiles():
    with open(os.path.join(DATA, "activity_profiles.json")) as f:
        return json.load(f)


def assign_group(profile):
    """Map a profile to one of three paper groups."""
    if profile["contributor_type"] == "organic":
        return "Organic"
    if profile["event_type"] in MENTORSHIP_EVENTS:
        return "Mentorship"
    return "Non-Mentorship"


def compute_group_means(profiles):
    """Compute mean percentile-rank per dimension per group."""
    groups = {"Mentorship": [], "Non-Mentorship": [], "Organic": []}
    for p in profiles:
        g = assign_group(p)
        groups[g].append(p["percentile_dims"])

    means = {}
    for g, dims_list in groups.items():
        arr = np.array(dims_list)
        means[g] = arr.mean(axis=0).tolist()
        print(f"  {g}: n={len(dims_list)}, mean dims={[round(x,3) for x in means[g]]}")
    return means


def plot_spider(group_means, output_path):
    """Generate spider/radar plot (Figure 1 in paper)."""
    n_dims = len(DIMENSION_NAMES)
    angles = np.linspace(0, 2 * np.pi, n_dims, endpoint=False).tolist()
    angles += angles[:1]

    colors = {"Mentorship": "#2ecc71", "Non-Mentorship": "#e74c3c", "Organic": "#3498db"}
    markers = {"Mentorship": "o", "Non-Mentorship": "s", "Organic": "D"}

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))

    for label, values in group_means.items():
        vals = list(values) + [values[0]]
        ax.plot(angles, vals, markers[label] + "-", linewidth=2.2,
                label=label, color=colors[label], alpha=0.85, markersize=7)
        ax.fill(angles, vals, alpha=0.08, color=colors[label])

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(DIMENSION_NAMES, size=11, fontweight="medium")
    ax.set_ylim(0, 1)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8"], color="grey", size=8)

    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3,
              fontsize=10, frameon=True, fancybox=True, edgecolor="#cccccc")
    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\n  Saved: {output_path}")


def main():
    print("=" * 70)
    print("SCRIPT 01: ACTIVITY PROFILING (RQ1)")
    print("Paper: Section 3.5, Section 4.1.1, Figure 1")
    print("=" * 70)

    profiles = load_profiles()
    print(f"\nLoaded {len(profiles)} contributor profiles")

    # ── Step 1: Compute group means ────────────────────────────────────
    print("\n── Step 1: Percentile-rank means per group ──")
    group_means = compute_group_means(profiles)

    # ── Step 2: Generate spider plot (Figure 1) ───────────────────────
    print("\n── Step 2: Spider plot (Figure 1) ──")
    plot_spider(group_means, os.path.join(OUT, "spider_plot.png"))

    # ── Step 3: Report per-dimension highlights ───────────────────────
    print("\n── Step 3: Dimension highlights ──")
    dim_short = ["Commit Freq", "PR Success", "Issue Activity",
                 "Discussion Depth", "Activity Duration", "Contrib Breadth"]
    for i, dim in enumerate(dim_short):
        vals = {g: group_means[g][i] for g in group_means}
        top = max(vals, key=vals.get)
        print(f"  {dim:22s}: highest = {top} ({vals[top]:.3f})")

    print("\n── Finding (RQ1 - Activity Profiles) ──")
    print("  Mentorship  -> community-engaged (discussion depth, issue activity)")
    print("  Non-Ment.   -> code-focused (commit frequency)")
    print("  Organic     -> balanced generalists (activity duration)")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
