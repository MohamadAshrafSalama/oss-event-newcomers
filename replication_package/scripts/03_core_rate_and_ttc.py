#!/usr/bin/env python3
"""
================================================================================
Script 03: Core Contributor Rates and Time-to-Core (RQ2)
================================================================================
Paper Section: Section 3.5 "Outcome Analysis (RQ2)",
               Section 4.2.1 "Core Contributor Rates",
               Table 2 (top rows)

Purpose:
  1. Compare core emergence rate: Event vs Organic
  2. Compare core emergence rate: Mentorship vs Non-Mentorship
  3. Compare time-to-core: Event vs Organic
  4. All with chi-squared (proportions), Mann-Whitney U (continuous),
     odds ratios, Cliff's delta

Core Definition (Paper Section 3.4):
  Pareto 80/20 rule -- smallest set responsible for 80% of cumulative
  commits, computed monthly, skipping first 12 months.
  Requires >= 10 commits and >= 5 contributors per evaluation month.

Expected Results (Table 2):
  - Event vs Organic core rate:    12.1% vs 9.6%, chi2 p < 0.001, OR = 1.31
  - Mentorship vs Non-Ment. rate:  14.0% vs 10.6%, chi2 p = 0.012, OR = 1.37
  - Event vs Organic TTC:          7.5 vs 9.0 months, MW p = 0.008, d = -0.18

References:
  - Mockus, Fielding, Herbsleb (2002): 80/20 Pareto core definition
  - Yamashita et al. (2015): Pareto on GitHub projects
  - Xiao et al. (2023): Skip first 12 months (founder-dominated)
================================================================================
"""

import csv
import os
import sys

import numpy as np
from scipy import stats

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")


def load_csv(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


def cliffs_delta(x, y):
    """Cliff's delta effect size."""
    nx, ny = len(x), len(y)
    more = sum(1 for xi in x for yi in y if xi > yi)
    less = sum(1 for xi in x for yi in y if xi < yi)
    return (more - less) / (nx * ny)


def effect_magnitude(d):
    d = abs(d)
    if d < 0.147:
        return "negligible"
    elif d < 0.33:
        return "small"
    elif d < 0.474:
        return "medium"
    return "large"


def odds_ratio_ci(a, b, c, d, alpha=0.05):
    """Odds ratio and 95% CI for 2x2 table [[a,b],[c,d]]."""
    if b == 0 or c == 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    OR = (a * d) / (b * c)
    se = np.sqrt(1/a + 1/b + 1/c + 1/d)
    z = stats.norm.ppf(1 - alpha / 2)
    return OR, np.exp(np.log(OR) - z * se), np.exp(np.log(OR) + z * se)


def test_core_rate(group_a, group_b, label_a, label_b):
    """Chi-squared test on core emergence rate between two groups."""
    a_core = sum(1 for r in group_a if r["ever_core"] == "True")
    a_not = len(group_a) - a_core
    b_core = sum(1 for r in group_b if r["ever_core"] == "True")
    b_not = len(group_b) - b_core

    rate_a = a_core / len(group_a) * 100
    rate_b = b_core / len(group_b) * 100

    table = np.array([[a_core, a_not], [b_core, b_not]])
    chi2, p, dof, expected = stats.chi2_contingency(table, correction=True)
    OR, ci_lo, ci_hi = odds_ratio_ci(a_core, a_not, b_core, b_not)

    print(f"\n  {label_a} vs {label_b} -- CORE RATE")
    print(f"    {label_a}: {a_core}/{len(group_a)} = {rate_a:.1f}%")
    print(f"    {label_b}: {b_core}/{len(group_b)} = {rate_b:.1f}%")
    print(f"    Chi-squared = {chi2:.3f}, p = {p:.6f}")
    print(f"    Odds Ratio = {OR:.2f} [{ci_lo:.2f}, {ci_hi:.2f}]")
    print(f"    Significant (p < 0.05): {'YES' if p < 0.05 else 'NO'}")


def test_ttc(group_a, group_b, label_a, label_b):
    """Mann-Whitney U test on time-to-core between two groups (core only)."""
    ttc_a = [float(r["time_to_core_months"]) for r in group_a
             if r["ever_core"] == "True" and r["time_to_core_months"]]
    ttc_b = [float(r["time_to_core_months"]) for r in group_b
             if r["ever_core"] == "True" and r["time_to_core_months"]]

    if len(ttc_a) < 2 or len(ttc_b) < 2:
        print(f"\n  {label_a} vs {label_b} -- TIME-TO-CORE: insufficient data")
        return

    stat, p = stats.mannwhitneyu(ttc_a, ttc_b, alternative="two-sided")
    d = cliffs_delta(ttc_a, ttc_b)

    print(f"\n  {label_a} vs {label_b} -- TIME-TO-CORE (months)")
    print(f"    {label_a}: n={len(ttc_a)}, median={np.median(ttc_a):.1f}")
    print(f"    {label_b}: n={len(ttc_b)}, median={np.median(ttc_b):.1f}")
    print(f"    Mann-Whitney U = {stat:.1f}, p = {p:.6f}")
    print(f"    Cliff's delta = {d:.4f} ({effect_magnitude(d)})")
    print(f"    Significant (p < 0.05): {'YES' if p < 0.05 else 'NO'}")


def main():
    print("=" * 70)
    print("SCRIPT 03: CORE RATE AND TIME-TO-CORE (RQ2)")
    print("Paper: Section 3.5, Section 4.2.1, Table 2")
    print("=" * 70)

    core = load_csv("per_contributor_core_status.csv")
    print(f"\nLoaded {len(core)} contributor records")

    event = [r for r in core if r["contributor_type"] == "event"]
    organic = [r for r in core if r["contributor_type"] == "organic"]
    mentorship = [r for r in event if r["is_mentorship"] == "True"]
    non_mentorship = [r for r in event if r["is_mentorship"] == "False"]

    print(f"  Event: {len(event)}, Organic: {len(organic)}")
    print(f"  Mentorship: {len(mentorship)}, Non-Mentorship: {len(non_mentorship)}")

    # ── Test 1: Event vs Organic core rate ────────────────────────────
    print("\n" + "─" * 60)
    print("TEST 1: Core Emergence Rate")
    print("Paper: Event 12.1% vs Organic 9.6%, p < 0.001, OR = 1.31")
    print("─" * 60)
    test_core_rate(event, organic, "Event", "Organic")

    # ── Test 2: Mentorship vs Non-Mentorship core rate ────────────────
    print("\n" + "─" * 60)
    print("TEST 2: Mentorship vs Non-Mentorship Core Rate")
    print("Paper: Mentorship 14.0% vs Non-Ment. 10.6%, p = 0.012, OR = 1.37")
    print("─" * 60)
    test_core_rate(mentorship, non_mentorship, "Mentorship", "Non-Mentorship")

    # ── Test 3: Event vs Organic TTC ──────────────────────────────────
    print("\n" + "─" * 60)
    print("TEST 3: Time-to-Core")
    print("Paper: Event median 7.5 vs Organic 9.0, MW p = 0.008, d = -0.18")
    print("─" * 60)
    test_ttc(event, organic, "Event", "Organic")

    # ── Test 4: Mentorship vs Non-Mentorship TTC ─────────────────────
    print("\n" + "─" * 60)
    print("TEST 4: Mentorship vs Non-Mentorship TTC")
    print("─" * 60)
    test_ttc(mentorship, non_mentorship, "Mentorship", "Non-Mentorship")

    print("\n── Finding (RQ2 - Core Rates) ──")
    print("  Event contributors have higher odds of becoming core (OR = 1.31)")
    print("  Event reach core 1.5 months faster (median 7.5 vs 9.0)")
    print("  Mentorship > Non-Mentorship core rate (14.0% vs 10.6%)")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
