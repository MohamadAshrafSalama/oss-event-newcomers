#!/usr/bin/env python3
"""
Phase 4: Statistical Testing -- Event vs Organic Core Emergence.

Tests:
1. Core emergence rate: Chi-squared / Fisher's exact
2. Time-to-core: Mann-Whitney U + Cliff's delta
3. Mentorship vs Non-mentorship
4. OSS4SG vs Conventional OSS
All with Bonferroni correction.
"""

import json
import os
import pandas as pd
import numpy as np
from scipy import stats
from collections import OrderedDict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")


def cliffs_delta(x, y):
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
    return "large"

def odds_ratio_ci(a, b, c, d, alpha=0.05):
    """Compute odds ratio and 95% CI for 2x2 table [[a,b],[c,d]]."""
    if b == 0 or c == 0:
        # Add 0.5 continuity correction
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    OR = (a * d) / (b * c)
    log_or = np.log(OR)
    se = np.sqrt(1/a + 1/b + 1/c + 1/d)
    z = stats.norm.ppf(1 - alpha/2)
    ci_lo = np.exp(log_or - z * se)
    ci_hi = np.exp(log_or + z * se)
    return OR, ci_lo, ci_hi


def run_rate_comparison(df_a, df_b, label_a, label_b, alpha):
    """Compare core emergence rates between two groups."""
    a_core = int(df_a["ever_core"].sum())
    a_not = len(df_a) - a_core
    b_core = int(df_b["ever_core"].sum())
    b_not = len(df_b) - b_core
    
    rate_a = a_core / len(df_a) * 100 if len(df_a) > 0 else 0
    rate_b = b_core / len(df_b) * 100 if len(df_b) > 0 else 0
    
    # 2x2 table: [[a_core, a_not], [b_core, b_not]]
    table = np.array([[a_core, a_not], [b_core, b_not]])
    
    # Chi-squared or Fisher's exact
    min_expected = min(a_core, a_not, b_core, b_not)
    if min_expected < 5:
        odds, p = stats.fisher_exact(table)
        test_name = "Fisher's exact"
        stat_value = odds
    else:
        chi2, p, dof, expected = stats.chi2_contingency(table, correction=True)
        test_name = "Chi-squared (Yates)"
        stat_value = chi2
    
    # Odds ratio
    OR, ci_lo, ci_hi = odds_ratio_ci(a_core, a_not, b_core, b_not)
    
    significant = p < alpha
    
    result = {
        "comparison": f"{label_a} vs {label_b}",
        "type": "core_emergence_rate",
        f"{label_a}_n": len(df_a),
        f"{label_a}_core": a_core,
        f"{label_a}_rate": round(rate_a, 2),
        f"{label_b}_n": len(df_b),
        f"{label_b}_core": b_core,
        f"{label_b}_rate": round(rate_b, 2),
        "test": test_name,
        "test_statistic": round(float(stat_value), 4),
        "p_value": float(p),
        "alpha_adjusted": alpha,
        "significant": significant,
        "odds_ratio": round(float(OR), 4),
        "OR_95CI_lo": round(float(ci_lo), 4),
        "OR_95CI_hi": round(float(ci_hi), 4),
        "interpretation": (
            f"{label_a} contributors achieved core at {rate_a:.1f}% vs {rate_b:.1f}% "
            f"for {label_b} ({test_name}, p={p:.4e}, OR={OR:.3f}, 95% CI [{ci_lo:.3f}, {ci_hi:.3f}]). "
            f"{'Significant' if significant else 'Not significant'} at alpha={alpha:.4f}."
        )
    }
    return result


def run_time_comparison(df_a, df_b, label_a, label_b, alpha):
    """Compare time-to-core between two groups (those who became core)."""
    a_times = df_a[df_a["ever_core"] & df_a["months_to_core"].notna()]["months_to_core"].values.astype(float)
    b_times = df_b[df_b["ever_core"] & df_b["months_to_core"].notna()]["months_to_core"].values.astype(float)
    
    if len(a_times) < 2 or len(b_times) < 2:
        return {
            "comparison": f"{label_a} vs {label_b}",
            "type": "time_to_core",
            "note": "Insufficient data for test",
        }
    
    # Mann-Whitney U
    stat, p = stats.mannwhitneyu(a_times, b_times, alternative="two-sided")
    delta = cliffs_delta(a_times, b_times)
    cat = effect_size_category(delta)
    significant = p < alpha
    
    result = {
        "comparison": f"{label_a} vs {label_b}",
        "type": "time_to_core",
        f"{label_a}_n": len(a_times),
        f"{label_a}_median": round(float(np.median(a_times)), 1),
        f"{label_a}_mean": round(float(np.mean(a_times)), 1),
        f"{label_b}_n": len(b_times),
        f"{label_b}_median": round(float(np.median(b_times)), 1),
        f"{label_b}_mean": round(float(np.mean(b_times)), 1),
        "test": "Mann-Whitney U",
        "U_statistic": float(stat),
        "p_value": float(p),
        "alpha_adjusted": alpha,
        "significant": significant,
        "cliffs_delta": round(float(delta), 4),
        "effect_size": cat,
        "interpretation": (
            f"Among core contributors, {label_a} achieved core in median {np.median(a_times):.1f} months "
            f"vs {np.median(b_times):.1f} months for {label_b} (Mann-Whitney U={stat:.0f}, p={p:.4e}, "
            f"Cliff's delta={delta:.4f} [{cat}]). "
            f"{'Significant' if significant else 'Not significant'} at alpha={alpha:.4f}."
        )
    }
    return result


def main():
    print("=" * 70)
    print("PHASE 4: Statistical Testing -- Core Emergence")
    print("=" * 70)
    
    # Load data from Phase 3
    df = pd.read_csv(os.path.join(OUTPUT_DIR, "per_contributor_core_status.csv"))
    print(f"Total contributors: {len(df)}")
    
    event_df = df[df["contributor_type"] == "event"]
    organic_df = df[df["contributor_type"] == "organic"]
    
    # Define comparisons (4 main x 2 tests = 8 total)
    # Bonferroni: alpha = 0.05 / 8 = 0.00625
    num_tests = 8
    alpha_adjusted = 0.05 / num_tests
    
    print(f"Bonferroni correction: {num_tests} tests, alpha={alpha_adjusted:.4f}")
    
    all_results = []
    
    # --- Test 1: Event vs Organic ---
    print("\n" + "-" * 50)
    print("TEST 1: Event vs Organic")
    print("-" * 50)
    
    r1a = run_rate_comparison(event_df, organic_df, "Event", "Organic", alpha_adjusted)
    r1b = run_time_comparison(event_df, organic_df, "Event", "Organic", alpha_adjusted)
    all_results.extend([r1a, r1b])
    print(f"  Rate: {r1a['interpretation']}")
    print(f"  Time: {r1b['interpretation']}")
    
    # --- Test 2: Mentorship vs Non-Mentorship ---
    print("\n" + "-" * 50)
    print("TEST 2: Mentorship vs Non-Mentorship (within event)")
    print("-" * 50)
    
    mentorship = event_df[event_df["is_mentorship"] == True]
    non_mentorship = event_df[event_df["is_mentorship"] == False]
    
    r2a = run_rate_comparison(mentorship, non_mentorship, "Mentorship", "Non-Mentorship", alpha_adjusted)
    r2b = run_time_comparison(mentorship, non_mentorship, "Mentorship", "Non-Mentorship", alpha_adjusted)
    all_results.extend([r2a, r2b])
    print(f"  Rate: {r2a['interpretation']}")
    print(f"  Time: {r2b['interpretation']}")
    
    # --- Test 3: OSS4SG vs Conventional OSS (event contributors) ---
    print("\n" + "-" * 50)
    print("TEST 3: OSS4SG vs Conventional OSS (event contributors)")
    print("-" * 50)
    
    oss4sg_event = event_df[event_df["is_oss4sg"] == True]
    oss_event = event_df[event_df["is_oss4sg"] == False]
    
    r3a = run_rate_comparison(oss4sg_event, oss_event, "OSS4SG-Event", "ConvOSS-Event", alpha_adjusted)
    r3b = run_time_comparison(oss4sg_event, oss_event, "OSS4SG-Event", "ConvOSS-Event", alpha_adjusted)
    all_results.extend([r3a, r3b])
    print(f"  Rate: {r3a['interpretation']}")
    print(f"  Time: {r3b['interpretation']}")
    
    # --- Test 4: OSS4SG vs Conventional OSS (organic contributors) ---
    print("\n" + "-" * 50)
    print("TEST 4: OSS4SG vs Conventional OSS (organic contributors)")
    print("-" * 50)
    
    oss4sg_org = organic_df[organic_df["is_oss4sg"] == True]
    oss_org = organic_df[organic_df["is_oss4sg"] == False]
    
    r4a = run_rate_comparison(oss4sg_org, oss_org, "OSS4SG-Organic", "ConvOSS-Organic", alpha_adjusted)
    r4b = run_time_comparison(oss4sg_org, oss_org, "OSS4SG-Organic", "ConvOSS-Organic", alpha_adjusted)
    all_results.extend([r4a, r4b])
    print(f"  Rate: {r4a['interpretation']}")
    print(f"  Time: {r4b['interpretation']}")
    
    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY OF ALL STATISTICAL TESTS")
    print("=" * 70)
    
    for r in all_results:
        sig = "***" if r.get("significant") else "   "
        p = r.get("p_value", "N/A")
        p_str = f"{p:.4e}" if isinstance(p, float) else str(p)
        print(f"  {sig} {r['comparison']:>35} ({r['type']:>20}): p={p_str}")
    
    # Save results
    output_path = os.path.join(OUTPUT_DIR, "statistical_test_results.json")
    
    # Convert numpy types for JSON
    def convert(obj):
        if isinstance(obj, (np.integer, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64)):
            return float(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return obj
    
    clean_results = []
    for r in all_results:
        clean = {}
        for k, v in r.items():
            clean[k] = convert(v)
        clean_results.append(clean)
    
    with open(output_path, "w") as f:
        json.dump(clean_results, f, indent=2, default=str)
    
    print(f"\nSaved: {output_path}")
    print("\nPHASE 4 COMPLETE")


if __name__ == "__main__":
    main()
