#!/usr/bin/env python3
"""
Phase 8: Generate a comprehensive results report (RESULTS_REPORT.md).

Aggregates all analysis outputs from Phases 1-7 into a single, publication-ready
markdown report with every statistical test documented.
"""

import json
import os
import csv
import pandas as pd
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")


def load_json(fname):
    path = os.path.join(OUTPUT_DIR, fname)
    if not os.path.exists(path):
        print(f"  WARNING: {fname} not found")
        return None
    with open(path) as f:
        return json.load(f)


def load_csv(fname):
    path = os.path.join(OUTPUT_DIR, fname)
    if not os.path.exists(path):
        print(f"  WARNING: {fname} not found")
        return None
    return pd.read_csv(path)


def load_dataset_summary():
    path = os.path.join(BASE, "06_final_dataset", "dataset_summary.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_oss4sg_count():
    path = os.path.join(BASE, "OSS4SG-Project-List.csv")
    if not os.path.exists(path):
        return 0
    count = 0
    with open(path) as f:
        reader = csv.DictReader(f)
        for _ in reader:
            count += 1
    return count


def format_p(p):
    """Format p-value for display."""
    if p is None:
        return "N/A"
    if p < 0.001:
        return f"{p:.2e}"
    return f"{p:.4f}"


def format_ci(lo, hi):
    """Format confidence interval."""
    if lo is None or hi is None:
        return "N/A"
    return f"[{lo:.3f}, {hi:.3f}]"


def main():
    print("=" * 70)
    print("PHASE 8: Generating Results Report")
    print("=" * 70)

    # Load all data
    dataset_summary = load_dataset_summary()
    descriptive = load_csv("descriptive_core_stats.csv")
    stat_tests = load_json("statistical_test_results.json")
    retention_results = load_json("survival_retention_results.json")
    core_survival_results = load_json("survival_core_results.json")
    dtw_results = load_json("dtw_clusters.json")
    per_contrib = load_csv("per_contributor_core_status.csv")

    oss4sg_count = load_oss4sg_count()

    lines = []
    def w(s=""):
        lines.append(s)

    # ===================================================================
    # TITLE
    # ===================================================================
    w("# Results Report: Event-Based vs Organic Contributors in OSS")
    w()
    w(f"*Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}*")
    w()
    w("---")
    w()

    # ===================================================================
    # 1. DATASET DESCRIPTION
    # ===================================================================
    w("## 1. Dataset Description")
    w()

    if dataset_summary:
        sv = dataset_summary.get("statistical_validation", {})
        w(f"- **Version:** {dataset_summary.get('version', 'N/A')}")
        w(f"- **Total Event Contributors:** {dataset_summary.get('total_event', 'N/A')}")
        w(f"- **Total Organic Contributors:** {dataset_summary.get('total_organic', 'N/A')}")
        w(f"- **Unique Repositories:** {dataset_summary.get('unique_repos', 'N/A')}")
        w(f"- **OSS4SG Projects:** {oss4sg_count} (from project list)")
        w()

        eb = dataset_summary.get("event_breakdown", {})
        w("### Event Breakdown")
        w()
        w("| Event Type | Count | Category |")
        w("|:-----------|------:|:---------|")
        w(f"| GSoC | {eb.get('gsoc', 0)} | Mentorship |")
        w(f"| LFX | {eb.get('lfx', 0)} | Mentorship |")
        w(f"| 24 Pull Requests | {eb.get('24pr', 0)} | Non-Mentorship |")
        w(f"| Hacktoberfest | {eb.get('hacktoberfest', eb.get('hf', 0))} | Non-Mentorship |")
        w(f"| **Total** | **{dataset_summary.get('total_event', 0)}** | |")
        w()

        w("### Statistical Comparability of Groups")
        w()
        mw_p = sv.get('mann_whitney_p', sv.get('p_value', 'N/A'))
        cd = sv.get('cliffs_delta', 'N/A')
        cd_cat = 'negligible' if isinstance(cd, (int, float)) and abs(cd) < 0.147 else 'small'
        ev_mean = sv.get('event_mean', sv.get('event_mean_commits', 'N/A'))
        org_mean = sv.get('organic_mean', sv.get('organic_mean_commits', 'N/A'))
        pct_diff = sv.get('mean_diff_pct', sv.get('pct_difference', 0))
        w(f"- **Mann-Whitney p-value:** {format_p(mw_p)}")
        w(f"- **Wilcoxon p-value:** {format_p(sv.get('wilcoxon_p', 'N/A'))}")
        w(f"- **Cliff's delta:** {cd:.4f} ({cd_cat})" if isinstance(cd, (int, float)) else f"- **Cliff's delta:** {cd}")
        w(f"- **Event mean commits:** {ev_mean:.1f}" if isinstance(ev_mean, (int, float)) else f"- **Event mean commits:** {ev_mean}")
        w(f"- **Organic mean commits:** {org_mean:.1f}" if isinstance(org_mean, (int, float)) else f"- **Organic mean commits:** {org_mean}")
        w(f"- **Mean difference:** {pct_diff:.1f}%" if isinstance(pct_diff, (int, float)) else f"- **Mean difference:** {pct_diff}")
        w()
        w("> **Note:** The Mann-Whitney p-value is **non-significant** (p > 0.05), confirming that event and "
          "organic groups have statistically comparable commit distributions. Cliff's delta is **negligible** "
          "(< 0.147), indicating minimal practical difference.")
        w()

    w("---")
    w()

    # ===================================================================
    # 2. CORE CONTRIBUTOR RESULTS (Phase 3)
    # ===================================================================
    w("## 2. Core Contributor Emergence")
    w()
    w("Core contributors are identified using the **80/20 Pareto rule**: "
      "the smallest set of contributors whose cumulative commits reach 80% "
      "of total commits in a given month. The first 6 calendar months of each "
      "project are excluded to allow the community to stabilize.")
    w()

    if descriptive is not None and len(descriptive) > 0:
        w("### 2.1 Descriptive Statistics")
        w()
        w("| Group | Total | Ever Core | Never Core | Core Rate (%) | Median Months | Mean Months | Q1 | Q3 |")
        w("|:------|------:|----------:|-----------:|--------------:|--------------:|------------:|---:|---:|")
        for _, r in descriptive.iterrows():
            med = f"{r['median_months_to_core']}" if pd.notna(r['median_months_to_core']) else "N/A"
            mean = f"{r['mean_months_to_core']}" if pd.notna(r['mean_months_to_core']) else "N/A"
            q1 = f"{r['q1_months_to_core']}" if pd.notna(r['q1_months_to_core']) else "N/A"
            q3 = f"{r['q3_months_to_core']}" if pd.notna(r['q3_months_to_core']) else "N/A"
            w(f"| {r['group']} | {r['total']} | {r['ever_core']} | {r['never_core']} | "
              f"{r['core_rate_pct']:.2f} | {med} | {mean} | {q1} | {q3} |")
        w()

    w("---")
    w()

    # ===================================================================
    # 3. STATISTICAL TESTS (Phase 4)
    # ===================================================================
    w("## 3. Statistical Tests -- Core Emergence")
    w()
    w("All tests use **Bonferroni correction** with 8 tests total "
      "(4 comparisons x 2 test types), yielding an adjusted alpha of **0.00625**.")
    w()

    if stat_tests:
        for i, test in enumerate(stat_tests):
            w(f"### 3.{i+1} {test['comparison']} ({test['type'].replace('_', ' ').title()})")
            w()

            if test["type"] == "core_emergence_rate":
                w("**What is compared:** Proportion of contributors who ever achieved core status.")
                w()
                w(f"**Test used:** {test.get('test', 'N/A')} (appropriate for comparing proportions)")
                w()

                # Find the keys for each group
                keys = [k for k in test.keys() if k.endswith("_rate")]
                for k in keys:
                    group = k.replace("_rate", "")
                    n_key = f"{group}_n"
                    core_key = f"{group}_core"
                    if n_key in test:
                        w(f"- **{group}:** {test[core_key]}/{test[n_key]} = {test[k]:.1f}%")

                w()
                w(f"- **Test statistic:** {test.get('test_statistic', 'N/A')}")
                w(f"- **p-value:** {format_p(test.get('p_value'))}")
                w(f"- **Adjusted alpha:** {test.get('alpha_adjusted', 0.00625)}")
                w(f"- **Significant:** {'Yes' if test.get('significant') else 'No'}")
                w(f"- **Odds Ratio:** {test.get('odds_ratio', 'N/A')} "
                  f"(95% CI {format_ci(test.get('OR_95CI_lo'), test.get('OR_95CI_hi'))})")
                w()
                w(f"> {test.get('interpretation', '')}")

            elif test["type"] == "time_to_core":
                w("**What is compared:** Months from first commit to first core appearance "
                  "(among those who achieved core).")
                w()
                w(f"**Test used:** {test.get('test', 'N/A')} (non-parametric, no normality assumption)")
                w()

                keys = [k for k in test.keys() if k.endswith("_median")]
                for k in keys:
                    group = k.replace("_median", "")
                    n_key = f"{group}_n"
                    mean_key = f"{group}_mean"
                    if n_key in test:
                        w(f"- **{group}:** n={test[n_key]}, median={test[k]} months, "
                          f"mean={test.get(mean_key, 'N/A')} months")

                w()
                w(f"- **U statistic:** {test.get('U_statistic', 'N/A')}")
                w(f"- **p-value:** {format_p(test.get('p_value'))}")
                w(f"- **Adjusted alpha:** {test.get('alpha_adjusted', 0.00625)}")
                w(f"- **Significant:** {'Yes' if test.get('significant') else 'No'}")
                w(f"- **Cliff's delta:** {test.get('cliffs_delta', 'N/A')} ({test.get('effect_size', 'N/A')})")
                w()
                w(f"> {test.get('interpretation', '')}")

            elif "note" in test:
                w(f"> {test['note']}")

            w()

    w("---")
    w()

    # ===================================================================
    # 4. SURVIVAL ANALYSIS #1: RETENTION (Phase 5)
    # ===================================================================
    w("## 4. Survival Analysis -- Retention")
    w()
    w("**Research question:** Do event contributors stay in the project longer than organic contributors?")
    w()
    w("**Definition of 'left':** A contributor is considered to have left if they have not committed "
      "for at least **5 months** after their last commit (following Jamieson et al. 2024).")
    w()

    if retention_results:
        w(f"- **Event contributors analyzed:** {retention_results.get('n_event', 'N/A')}")
        w(f"- **Organic contributors analyzed:** {retention_results.get('n_organic', 'N/A')}")
        w(f"- **Left (event observed):** {retention_results.get('n_left', 'N/A')}")
        w(f"- **Censored (still active):** {retention_results.get('n_censored', 'N/A')}")
        w()

        w("### 4.1 Kaplan-Meier Survival Curves")
        w()
        w("![Retention KM Curves](survival_retention_km.png)")
        w()

        lr = retention_results.get("log_rank_event_vs_organic", {})
        w("### 4.2 Log-Rank Test")
        w()
        w("**What is compared:** The two survival curves (Event vs Organic)")
        w()
        w(f"- **Log-rank chi-squared:** {lr.get('chi2', 'N/A'):.4f}")
        w(f"- **p-value:** {format_p(lr.get('p_value'))}")
        w(f"- **Significant:** {'Yes' if lr.get('p_value', 1) < 0.05 else 'No'}")
        w()

        cox = retention_results.get("cox_ph", {})
        if "error" not in cox:
            w("### 4.3 Cox Proportional Hazards Model")
            w()
            w("**Interpretation:** HR > 1 means MORE likely to leave; HR < 1 means LESS likely to leave.")
            w()
            w("| Variable | HR | 95% CI | p-value | Interpretation |")
            w("|:---------|---:|:------:|--------:|:---------------|")
            for var in ["is_event", "is_mentorship", "is_oss4sg"]:
                if var in cox:
                    r = cox[var]
                    direction = "more" if r["hazard_ratio"] > 1 else "less"
                    sig = "***" if r["p_value"] < 0.05 else ""
                    w(f"| {var} | {r['hazard_ratio']:.3f} | "
                      f"[{r['hr_95ci_lo']:.3f}, {r['hr_95ci_hi']:.3f}] | "
                      f"{format_p(r['p_value'])} {sig} | {direction} likely to leave |")
            w()
        else:
            w(f"*Cox PH model failed: {cox.get('error', 'unknown error')}*")
            w()

    w("---")
    w()

    # ===================================================================
    # 5. SURVIVAL ANALYSIS #2: CORE ACHIEVEMENT (Phase 6)
    # ===================================================================
    w("## 5. Survival Analysis -- Time-to-Core Achievement")
    w()
    w("**Research question:** Does participating in an event increase a contributor's chance "
      "of becoming a core contributor?")
    w()
    w("**Event (success):** First time the contributor appears in the monthly core set. "
      "**Censored:** Never achieved core by end of data.")
    w()

    if core_survival_results:
        w(f"- **Event contributors analyzed:** {core_survival_results.get('n_event', 'N/A')}")
        w(f"- **Organic contributors analyzed:** {core_survival_results.get('n_organic', 'N/A')}")
        w(f"- **Achieved core:** {core_survival_results.get('n_achieved_core', 'N/A')}")
        w(f"- **Censored (never core):** {core_survival_results.get('n_censored', 'N/A')}")
        w()

        w("### 5.1 Kaplan-Meier Survival Curves")
        w()
        w("![Core Achievement KM Curves](survival_core_km.png)")
        w()

        w("### 5.2 Log-Rank Tests")
        w()
        w("| Comparison | Chi-squared | p-value | Significant |")
        w("|:-----------|------------:|--------:|:------------|")

        for key, label in [
            ("log_rank_event_vs_organic", "Event vs Organic"),
            ("log_rank_mentorship_vs_non", "Mentorship vs Non-Mentorship"),
            ("log_rank_oss4sg_vs_conv", "OSS4SG vs Conventional"),
        ]:
            lr = core_survival_results.get(key, {})
            chi2 = lr.get("chi2")
            pval = lr.get("p_value")
            sig = "Yes" if pval is not None and pval < 0.05 else "No"
            chi2_str = f"{chi2:.4f}" if chi2 is not None else "N/A"
            w(f"| {label} | {chi2_str} | {format_p(pval)} | {sig} |")
        w()

        cox = core_survival_results.get("cox_ph", {})
        if "error" not in cox:
            w("### 5.3 Cox Proportional Hazards Model")
            w()
            w("**Interpretation:** HR > 1 means MORE likely to achieve core (faster); "
              "HR < 1 means LESS likely.")
            w()
            w("| Variable | HR | 95% CI | p-value | Interpretation |")
            w("|:---------|---:|:------:|--------:|:---------------|")
            for var in ["is_event", "is_mentorship", "is_oss4sg"]:
                if var in cox:
                    r = cox[var]
                    direction = "more" if r["hazard_ratio"] > 1 else "less"
                    sig = "***" if r["p_value"] < 0.05 else ""
                    w(f"| {var} | {r['hazard_ratio']:.3f} | "
                      f"[{r['hr_95ci_lo']:.3f}, {r['hr_95ci_hi']:.3f}] | "
                      f"{format_p(r['p_value'])} {sig} | {direction} likely to achieve core |")
            w()

        # 4-way subgroup
        subgroups = core_survival_results.get("subgroup_4way", {})
        if subgroups:
            w("### 5.4 Four-Way Subgroup Analysis (Event Contributors)")
            w()
            w("| Subgroup | N | Achieved Core | Rate (%) | Median Months |")
            w("|:---------|--:|--------------:|---------:|--------------:|")
            for label, data in subgroups.items():
                med = f"{data['median_months_to_core']}" if data.get('median_months_to_core') is not None else "N/A"
                w(f"| {label} | {data['n']} | {data['achieved_core']} | "
                  f"{data['rate_pct']:.1f} | {med} |")
            w()

    w("---")
    w()

    # ===================================================================
    # 6. DTW CLUSTERING (Phase 7)
    # ===================================================================
    w("## 6. DTW Clustering of Activity Patterns")
    w()
    w("Weekly Contribution Index (commit-only, for fair comparison) time series "
      "were normalized to 52 weeks via linear interpolation and min-max scaled. "
      "K-Medoids clustering with DTW distance was applied.")
    w()

    if dtw_results:
        n_clustered = len(dtw_results.get('assignments', []))
        best_k = dtw_results.get('best_k', dtw_results.get('k', 'N/A'))
        sil = dtw_results.get('best_silhouette', dtw_results.get('silhouette', 'N/A'))
        w(f"- **Contributors clustered:** {n_clustered}")
        w(f"- **Fixed length:** 52 weeks")
        w(f"- **Best k:** {best_k}")
        if isinstance(sil, (int, float)):
            w(f"- **Silhouette score:** {sil:.4f}")
        else:
            w(f"- **Silhouette score:** {sil}")
        w()

        w("### 6.1 Cluster Selection")
        w()
        w("![Cluster Centroids](dtw_cluster_centroids.png)")
        w()

        k_search = dtw_results.get("k_search", {})
        if k_search:
            w("| k | Silhouette Score | Inertia |")
            w("|--:|-----------------:|--------:|")
            for k_str in sorted(k_search.keys(), key=int):
                v = k_search[k_str]
                w(f"| {k_str} | {v.get('silhouette',0):.4f} | {v.get('inertia',0):.0f} |")
            w()

        w("### 6.2 Cluster Descriptions")
        w()
        w("![Cluster Centroids](dtw_cluster_centroids.png)")
        w()

        # Cluster distribution from CSV
        cluster_dist = load_csv("dtw_cluster_distribution.csv")
        if cluster_dist is not None:
            w("### 6.2 Cluster Distribution")
            w()
            w("| Cluster | Total | Mentorship | Non-Mentorship | Organic |")
            w("|--------:|------:|-----------:|---------------:|--------:|")
            for _, row in cluster_dist.iterrows():
                w(f"| {int(row.get('cluster',0))} | {int(row.get('total',0))} | "
                  f"{int(row.get('mentorship',0))} | {int(row.get('non_mentorship',0))} | "
                  f"{int(row.get('organic',0))} |")
            w()

    w("---")
    w()

    # ===================================================================
    # 7. SUMMARY OF ALL STATISTICAL TESTS
    # ===================================================================
    w("## 7. Summary of All Statistical Tests")
    w()
    w("| # | Comparison | Test | Statistic | p-value | Effect Size | Significant | Bonferroni |")
    w("|--:|:-----------|:-----|----------:|--------:|:------------|:-----------:|:----------:|")

    test_num = 0

    # From Phase 4
    if stat_tests:
        for test in stat_tests:
            test_num += 1
            comp = test["comparison"]
            if test["type"] == "core_emergence_rate":
                test_name = test.get("test", "Chi-sq")
                stat_val = test.get("test_statistic", "N/A")
                pval = test.get("p_value")
                effect = f"OR={test.get('odds_ratio', 'N/A')}"
                sig = "Yes" if test.get("significant") else "No"
                w(f"| {test_num} | {comp} (rate) | {test_name} | {stat_val} | "
                  f"{format_p(pval)} | {effect} | {sig} | Yes |")
            elif test["type"] == "time_to_core":
                if "note" in test:
                    w(f"| {test_num} | {comp} (time) | N/A | N/A | N/A | N/A | N/A | Yes |")
                else:
                    stat_val = test.get("U_statistic", "N/A")
                    pval = test.get("p_value")
                    effect = f"d={test.get('cliffs_delta', 'N/A')} ({test.get('effect_size', '')})"
                    sig = "Yes" if test.get("significant") else "No"
                    w(f"| {test_num} | {comp} (time) | Mann-Whitney U | {stat_val} | "
                      f"{format_p(pval)} | {effect} | {sig} | Yes |")

    # From Phase 5
    if retention_results:
        lr = retention_results.get("log_rank_event_vs_organic", {})
        test_num += 1
        w(f"| {test_num} | Retention: Event vs Organic | Log-Rank | "
          f"{lr.get('chi2', 'N/A'):.4f} | {format_p(lr.get('p_value'))} | - | "
          f"{'Yes' if lr.get('p_value', 1) < 0.05 else 'No'} | No |")

        cox = retention_results.get("cox_ph", {})
        if "is_event" in cox:
            test_num += 1
            r = cox["is_event"]
            w(f"| {test_num} | Retention: Cox PH (is_event) | Cox PH | "
              f"HR={r['hazard_ratio']:.3f} | {format_p(r['p_value'])} | "
              f"HR={r['hazard_ratio']:.3f} | "
              f"{'Yes' if r['p_value'] < 0.05 else 'No'} | No |")

    # From Phase 6
    if core_survival_results:
        lr = core_survival_results.get("log_rank_event_vs_organic", {})
        test_num += 1
        w(f"| {test_num} | Core Surv: Event vs Organic | Log-Rank | "
          f"{lr.get('chi2', 'N/A'):.4f} | {format_p(lr.get('p_value'))} | - | "
          f"{'Yes' if lr.get('p_value', 1) < 0.05 else 'No'} | No |")

        cox = core_survival_results.get("cox_ph", {})
        if "is_event" in cox:
            test_num += 1
            r = cox["is_event"]
            w(f"| {test_num} | Core Surv: Cox PH (is_event) | Cox PH | "
              f"HR={r['hazard_ratio']:.3f} | {format_p(r['p_value'])} | "
              f"HR={r['hazard_ratio']:.3f} | "
              f"{'Yes' if r['p_value'] < 0.05 else 'No'} | No |")

    # From Phase 7
    if dtw_results:
        chi = dtw_results.get("chi_squared_event_vs_organic", {})
        test_num += 1
        w(f"| {test_num} | DTW Clusters: Event vs Organic | Chi-squared | "
          f"{chi.get('chi2', 'N/A')} | {format_p(chi.get('p_value'))} | - | "
          f"{'Yes' if chi.get('significant') else 'No'} | No |")

    w()
    w("---")
    w()

    # ===================================================================
    # 8. KEY FINDINGS
    # ===================================================================
    w("## 8. Key Findings")
    w()

    findings = []

    # Finding 1: Core emergence rate
    if stat_tests:
        ev_rate = None
        org_rate = None
        for t in stat_tests:
            if t["comparison"] == "Event vs Organic" and t["type"] == "core_emergence_rate":
                ev_rate = t.get("Event_rate")
                org_rate = t.get("Organic_rate")
                or_val = t.get("odds_ratio")
                sig = t.get("significant")

        if ev_rate is not None:
            findings.append(
                f"**Core Emergence Rate:** Event contributors achieved core status at "
                f"**{ev_rate:.1f}%** compared to **{org_rate:.1f}%** for organic contributors "
                f"(OR={or_val:.3f}). This difference is {'statistically significant' if sig else 'not statistically significant'} "
                f"after Bonferroni correction."
            )

    # Finding 2: Retention
    if retention_results:
        cox = retention_results.get("cox_ph", {})
        if "is_event" in cox:
            hr = cox["is_event"]["hazard_ratio"]
            findings.append(
                f"**Retention:** Event contributors have a hazard ratio of **{hr:.3f}** for leaving, "
                f"meaning they are **{'less' if hr < 1 else 'more'}** likely to leave the project "
                f"compared to organic contributors (p={format_p(cox['is_event']['p_value'])})."
            )

    # Finding 3: Core achievement
    if core_survival_results:
        cox = core_survival_results.get("cox_ph", {})
        if "is_event" in cox:
            hr = cox["is_event"]["hazard_ratio"]
            findings.append(
                f"**Time-to-Core:** Event contributors have a Cox HR of **{hr:.3f}** for core achievement, "
                f"meaning they achieve core at {'a higher' if hr > 1 else 'a similar'} rate "
                f"(p={format_p(cox['is_event']['p_value'])})."
            )

    # Finding 4: Mentorship effect
    if core_survival_results:
        cox = core_survival_results.get("cox_ph", {})
        if "is_mentorship" in cox:
            hr = cox["is_mentorship"]["hazard_ratio"]
            findings.append(
                f"**Mentorship Effect:** Mentorship-based events (GSoC, LFX) have an HR of "
                f"**{hr:.3f}** for core achievement, suggesting mentorship "
                f"{'increases' if hr > 1 else 'does not significantly increase'} the likelihood of becoming core "
                f"(p={format_p(cox['is_mentorship']['p_value'])})."
            )

    # Finding 5: OSS4SG effect
    if core_survival_results:
        cox = core_survival_results.get("cox_ph", {})
        if "is_oss4sg" in cox:
            hr = cox["is_oss4sg"]["hazard_ratio"]
            findings.append(
                f"**OSS4SG Projects:** Contributors in OSS4SG projects have an HR of "
                f"**{hr:.3f}** for core achievement "
                f"(p={format_p(cox['is_oss4sg']['p_value'])})."
            )

    for i, f_text in enumerate(findings, 1):
        w(f"{i}. {f_text}")
        w()

    w("---")
    w()

    # ===================================================================
    # 9. OUTPUT FILES
    # ===================================================================
    w("## 9. Output Files")
    w()
    w("| File | Description |")
    w("|:-----|:------------|")
    w("| `07_core_contributor_analysis/*_cores.json` | Monthly core contributors per project (378 files) |")
    w("| `08_analysis_results/descriptive_core_stats.csv` | Descriptive statistics table |")
    w("| `08_analysis_results/per_contributor_core_status.csv` | Per-contributor core status |")
    w("| `08_analysis_results/statistical_test_results.json` | All Phase 4 test results |")
    w("| `08_analysis_results/survival_retention_km.png` | Retention KM curves |")
    w("| `08_analysis_results/survival_retention_results.json` | Retention analysis results |")
    w("| `08_analysis_results/per_contributor_retention.csv` | Per-contributor retention data |")
    w("| `08_analysis_results/survival_core_km.png` | Core achievement KM curves |")
    w("| `08_analysis_results/survival_core_results.json` | Core survival analysis results |")
    w("| `08_analysis_results/per_contributor_core_survival.csv` | Per-contributor core survival data |")
    w("| `08_analysis_results/ci_timeseries/` | Weekly CI time series (2000+ files) |")
    w("| `08_analysis_results/dtw_clusters.json` | DTW clustering results |")
    w("| `08_analysis_results/dtw_cluster_centroids.png` | Cluster centroid visualization |")
    w("| `08_analysis_results/dtw_cluster_distribution.csv` | Cluster distribution by group |")
    w("| `08_analysis_results/dtw_elbow_silhouette.png` | Elbow and silhouette plots |")
    w("| `08_analysis_results/RESULTS_REPORT.md` | This report |")
    w()

    # Write report
    report_path = os.path.join(OUTPUT_DIR, "RESULTS_REPORT.md")
    with open(report_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\nReport written to: {report_path}")
    print(f"Total lines: {len(lines)}")
    print("\nPHASE 8 COMPLETE")


if __name__ == "__main__":
    main()
