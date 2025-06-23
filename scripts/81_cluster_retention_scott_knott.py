#!/usr/bin/env python3
"""
Cluster-Retention Scott-Knott Analysis.

Connects the 3 activity pattern clusters (from script 77) to retention and
core achievement outcomes. Uses Scott-Knott ESD test to rank clusters.

Methodology follows:
  - Tantithamthavorn et al. (TSE 2017): Scott-Knott ESD algorithm
  - Ouf et al. (ICSE 2026): Scott-Knott for retention ranking
  - Lin et al. (CHASE 2017): Retention survival analysis

Steps:
  1. Join cluster assignments (2,508 contributors) to core/retention data
  2. Scott-Knott rankings: clusters by retention, time-to-core, core rate
  3. Cross-tabulation: cluster x event type
  4. Kaplan-Meier survival curves by cluster

Usage:
  python3 scripts/81_cluster_retention_scott_knott.py --test   # 10 contributors
  python3 scripts/81_cluster_retention_scott_knott.py           # all
"""

import argparse
import csv
import json
import os
import sys
import time

import numpy as np

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")

CLUSTERING_PATH = os.path.join(OUTPUT_DIR, "clustering_results.json")
CORE_STATUS_PATH = os.path.join(OUTPUT_DIR, "per_contributor_core_status.csv")
CORE_TTC_PATH = os.path.join(OUTPUT_DIR, "per_contributor_core_status_with_ttc.csv")
RETENTION_PATH = os.path.join(OUTPUT_DIR, "per_contributor_retention.csv")
JOURNEY_PATH = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")
CI_PATH = os.path.join(OUTPUT_DIR, "contribution_index_timeseries.json")

OUTPUT_JSON = os.path.join(OUTPUT_DIR, "cluster_retention_results.json")
OUTPUT_PNG = os.path.join(OUTPUT_DIR, "cluster_retention_survival.png")


# ── Scott-Knott ESD Implementation ──────────────────────────────

def cliffs_delta(x, y):
    """Cliff's delta effect size (non-parametric)."""
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return 0.0
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    count = 0.0
    for xi in x_arr:
        count += np.sum(xi > y_arr) - np.sum(xi < y_arr)
    return count / (nx * ny)


def scott_knott_esd(data_dict, alpha=0.05, delta_threshold=0.147):
    """
    Scott-Knott ESD test.
    data_dict: {group_name: [values]}
    Returns: {group_name: rank}
    """
    from scipy.stats import mannwhitneyu

    sorted_groups = sorted(data_dict.keys(), key=lambda g: np.median(data_dict[g]))
    ranks = {}
    _rank_counter = [1]

    def recurse(groups):
        if len(groups) <= 1:
            for g in groups:
                ranks[g] = _rank_counter[0]
            return

        best_split = None
        best_delta = 0.0

        for i in range(1, len(groups)):
            left = np.concatenate([data_dict[g] for g in groups[:i]])
            right = np.concatenate([data_dict[g] for g in groups[i:]])

            if len(left) < 3 or len(right) < 3:
                continue

            _, p_val = mannwhitneyu(left, right, alternative="two-sided")
            d = abs(cliffs_delta(left, right))

            if p_val < alpha and d >= delta_threshold and d > best_delta:
                best_delta = d
                best_split = i

        if best_split is not None:
            recurse(groups[:best_split])
            _rank_counter[0] += 1
            recurse(groups[best_split:])
        else:
            for g in groups:
                ranks[g] = _rank_counter[0]

    recurse(sorted_groups)
    return ranks


# ── Data Loading ────────────────────────────────────────────────

def load_core_status():
    """Load core status CSV into dict keyed by (username_lower, repo, type).
    For organic contributors, also index by (github_username, repo, organic) from journey data."""
    rows = {}
    with open(CORE_STATUS_PATH) as f:
        for r in csv.DictReader(f):
            key = (r["username_or_email"].lower(), r["repo"].lower(), r["contributor_type"])
            rows[key] = r
    return rows


def load_ttc():
    """Load TTC CSV keyed by (username_lower, repo, type)."""
    rows = {}
    with open(CORE_TTC_PATH) as f:
        for r in csv.DictReader(f):
            key = (r["username_or_email"].lower(), r["repo"].lower(), r["contributor_type"])
            rows[key] = r
    return rows


def build_organic_username_map():
    """Build (github_username.lower(), repo) -> organic_email for organic contributors."""
    mapping = {}
    with open(JOURNEY_PATH) as f:
        journeys = json.load(f)
    for j in journeys.get("organic_journeys", []):
        username = (j.get("github_username") or "").lower()
        email = (j.get("organic_email") or "").lower()
        repo = (j.get("repo") or "").lower()
        if username and email and repo:
            mapping[(username, repo)] = email
    return mapping


def compute_retention_from_ci(ci_data):
    """Compute retention (months of activity) from CI timeseries."""
    retention = {}
    for ctype in ["event", "organic"]:
        for entry in ci_data.get(ctype, []):
            username = (entry.get("username") or "").lower()
            repo = (entry.get("repo") or "").lower()
            contrib_type = "event" if ctype == "event" else "organic"
            if not username or not repo:
                continue
            key = (username, repo, contrib_type)
            length = entry.get("length", 0)
            retention[key] = length
    return retention


def build_merged_dataset(assignments, core_status, ttc_data, retention_data, organic_map, test_n=None):
    """Join cluster assignments with outcome data."""
    merged = []
    matched = 0
    unmatched = 0

    items = assignments[:test_n] if test_n else assignments

    for a in items:
        username = (a.get("username") or "").lower()
        repo = (a.get("repo") or "").lower()
        ctype = a.get("type", "")
        cluster = a.get("cluster", -1)
        event_type_cluster = a.get("event_type", "")

        if not username or not repo:
            unmatched += 1
            continue

        key = (username, repo, ctype)

        core_row = core_status.get(key) or ttc_data.get(key)

        # For organic contributors, cluster assignments use github_username
        # but core status uses email. Use the mapping.
        if core_row is None and ctype == "organic":
            email = organic_map.get((username, repo))
            if email:
                alt_key = (email, repo, "organic")
                core_row = core_status.get(alt_key) or ttc_data.get(alt_key)
        if core_row is None:
            unmatched += 1
            continue

        matched += 1

        is_core = core_row.get("ever_core", "False") == "True"

        ttc_val = None
        ttc_row = ttc_data.get(key)
        if ttc_row and ttc_row.get("real_ttc_months"):
            try:
                ttc_val = float(ttc_row["real_ttc_months"])
            except (ValueError, TypeError):
                pass

        ret_months = retention_data.get(key, 0)
        if ret_months == 0 and ctype == "organic":
            email = organic_map.get((username, repo))
            if email:
                ret_months = retention_data.get((email, repo, "organic"), 0)

        is_mentorship = core_row.get("is_mentorship", "False") == "True"
        actual_event_type = core_row.get("event_type", event_type_cluster)

        merged.append({
            "username": a["username"],
            "repo": a["repo"],
            "cluster": cluster,
            "contributor_type": ctype,
            "event_type": actual_event_type,
            "is_mentorship": is_mentorship,
            "is_core": is_core,
            "time_to_core": ttc_val,
            "retention_months": ret_months,
        })

    return merged, matched, unmatched


# ── Analysis Functions ──────────────────────────────────────────

CLUSTER_NAMES = {0: "Concentrated Burst", 1: "Declining", 2: "Growing"}


def analyze_scott_knott(merged):
    """Run Scott-Knott on clusters for retention, TTC, and core rate."""
    results = {}

    # Group by cluster
    cluster_groups = {}
    for m in merged:
        cl = CLUSTER_NAMES.get(m["cluster"], f"Cluster_{m['cluster']}")
        cluster_groups.setdefault(cl, []).append(m)

    # 1. Retention duration
    retention_data = {}
    for cl, members in cluster_groups.items():
        vals = [m["retention_months"] for m in members if m["retention_months"] > 0]
        if vals:
            retention_data[cl] = np.array(vals)

    if len(retention_data) >= 2:
        retention_ranks = scott_knott_esd(retention_data)
        results["retention_ranking"] = {
            cl: {
                "rank": retention_ranks.get(cl, 0),
                "n": len(retention_data.get(cl, [])),
                "median": float(np.median(retention_data[cl])) if cl in retention_data else 0,
                "mean": float(np.mean(retention_data[cl])) if cl in retention_data else 0,
            }
            for cl in cluster_groups
        }
        print(f"\n  Retention ranking (Scott-Knott):")
        for cl in sorted(results["retention_ranking"], key=lambda x: results["retention_ranking"][x]["rank"]):
            r = results["retention_ranking"][cl]
            print(f"    Rank {r['rank']}: {cl:25s} | n={r['n']:4d} | median={r['median']:5.1f} | mean={r['mean']:5.1f} months")

    # 2. Time-to-core (among core only)
    ttc_data = {}
    for cl, members in cluster_groups.items():
        vals = [m["time_to_core"] for m in members if m["is_core"] and m["time_to_core"] is not None]
        if vals:
            ttc_data[cl] = np.array(vals)

    if len(ttc_data) >= 2:
        ttc_ranks = scott_knott_esd(ttc_data)
        results["ttc_ranking"] = {
            cl: {
                "rank": ttc_ranks.get(cl, 0),
                "n": len(ttc_data.get(cl, [])),
                "median": float(np.median(ttc_data[cl])) if cl in ttc_data else 0,
                "mean": float(np.mean(ttc_data[cl])) if cl in ttc_data else 0,
            }
            for cl in ttc_data
        }
        print(f"\n  Time-to-core ranking (Scott-Knott):")
        for cl in sorted(results["ttc_ranking"], key=lambda x: results["ttc_ranking"][x]["rank"]):
            r = results["ttc_ranking"][cl]
            print(f"    Rank {r['rank']}: {cl:25s} | n={r['n']:4d} | median={r['median']:5.1f} | mean={r['mean']:5.1f} months")

    # 3. Core achievement rate
    core_rate_data = {}
    for cl, members in cluster_groups.items():
        vals = np.array([1.0 if m["is_core"] else 0.0 for m in members])
        if len(vals) >= 3:
            core_rate_data[cl] = vals

    if len(core_rate_data) >= 2:
        core_ranks = scott_knott_esd(core_rate_data)
        results["core_rate_ranking"] = {
            cl: {
                "rank": core_ranks.get(cl, 0),
                "n": int(len(core_rate_data.get(cl, []))),
                "core_count": int(np.sum(core_rate_data[cl])) if cl in core_rate_data else 0,
                "core_rate": float(np.mean(core_rate_data[cl])) if cl in core_rate_data else 0,
            }
            for cl in cluster_groups
        }
        print(f"\n  Core achievement rate ranking (Scott-Knott):")
        for cl in sorted(results["core_rate_ranking"], key=lambda x: results["core_rate_ranking"][x]["rank"]):
            r = results["core_rate_ranking"][cl]
            print(f"    Rank {r['rank']}: {cl:25s} | n={r['n']:4d} | core={r['core_count']:3d} ({r['core_rate']*100:.1f}%)")

    return results


def analyze_cross_tabulation(merged):
    """Cross-tabulate cluster x event/organic for retention and core rate."""
    from scipy.stats import mannwhitneyu

    results = {}

    for cluster_id, cluster_name in CLUSTER_NAMES.items():
        cluster_members = [m for m in merged if m["cluster"] == cluster_id]
        event_members = [m for m in cluster_members if m["contributor_type"] == "event"]
        organic_members = [m for m in cluster_members if m["contributor_type"] == "organic"]

        if len(event_members) < 3 or len(organic_members) < 3:
            continue

        cross = {"cluster": cluster_name, "event_n": len(event_members), "organic_n": len(organic_members)}

        # Retention
        ev_ret = [m["retention_months"] for m in event_members if m["retention_months"] > 0]
        org_ret = [m["retention_months"] for m in organic_members if m["retention_months"] > 0]

        if len(ev_ret) >= 3 and len(org_ret) >= 3:
            stat, p = mannwhitneyu(ev_ret, org_ret, alternative="two-sided")
            d = cliffs_delta(ev_ret, org_ret)
            cross["retention"] = {
                "event_median": float(np.median(ev_ret)),
                "organic_median": float(np.median(org_ret)),
                "mann_whitney_p": float(p),
                "cliffs_delta": float(d),
                "significant": p < 0.05 and abs(d) >= 0.147,
            }

        # Core rate
        ev_core = [1.0 if m["is_core"] else 0.0 for m in event_members]
        org_core = [1.0 if m["is_core"] else 0.0 for m in organic_members]

        if len(ev_core) >= 3 and len(org_core) >= 3:
            stat, p = mannwhitneyu(ev_core, org_core, alternative="two-sided")
            d = cliffs_delta(ev_core, org_core)
            cross["core_rate"] = {
                "event_rate": float(np.mean(ev_core)),
                "organic_rate": float(np.mean(org_core)),
                "mann_whitney_p": float(p),
                "cliffs_delta": float(d),
                "significant": p < 0.05 and abs(d) >= 0.147,
            }

        results[cluster_name] = cross

    print(f"\n  Cross-tabulation (cluster x event/organic):")
    for cl_name, cross in results.items():
        print(f"\n    {cl_name} (event={cross['event_n']}, organic={cross['organic_n']}):")
        if "retention" in cross:
            r = cross["retention"]
            sig = "***" if r["significant"] else "ns"
            print(f"      Retention: event median={r['event_median']:.1f}m, organic={r['organic_median']:.1f}m | p={r['mann_whitney_p']:.4f}, d={r['cliffs_delta']:.3f} {sig}")
        if "core_rate" in cross:
            r = cross["core_rate"]
            sig = "***" if r["significant"] else "ns"
            print(f"      Core rate: event={r['event_rate']*100:.1f}%, organic={r['organic_rate']*100:.1f}% | p={r['mann_whitney_p']:.4f}, d={r['cliffs_delta']:.3f} {sig}")

    return results


def generate_survival_plots(merged):
    """Generate Kaplan-Meier survival curves by cluster."""
    try:
        from lifelines import KaplanMeierFitter
        from lifelines.statistics import logrank_test
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  WARNING: lifelines or matplotlib not installed, skipping plots")
        return {}

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    colors = ["#e74c3c", "#3498db", "#2ecc71"]
    log_rank_results = {}

    # Plot 1: Survival by cluster
    ax = axes[0]
    cluster_data = {}
    for cl_id, cl_name in CLUSTER_NAMES.items():
        members = [m for m in merged if m["cluster"] == cl_id and m["retention_months"] > 0]
        if not members:
            continue
        durations = [m["retention_months"] for m in members]
        events = [1] * len(durations)  # all observed (conservative)
        cluster_data[cl_name] = (durations, events)

        kmf = KaplanMeierFitter()
        kmf.fit(durations, events, label=f"{cl_name} (n={len(members)})")
        kmf.plot_survival_function(ax=ax, color=colors[cl_id % len(colors)], ci_show=True, alpha=0.7)

    ax.set_title("Retention Survival by Activity Pattern Cluster", fontsize=13, fontweight="bold")
    ax.set_xlabel("Months Active")
    ax.set_ylabel("Survival Probability")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Log-rank tests between clusters
    cluster_names_list = list(cluster_data.keys())
    for i in range(len(cluster_names_list)):
        for j in range(i + 1, len(cluster_names_list)):
            n1, n2 = cluster_names_list[i], cluster_names_list[j]
            d1, e1 = cluster_data[n1]
            d2, e2 = cluster_data[n2]
            result = logrank_test(d1, d2, event_observed_A=e1, event_observed_B=e2)
            log_rank_results[f"{n1} vs {n2}"] = {
                "test_statistic": float(result.test_statistic),
                "p_value": float(result.p_value),
                "significant": result.p_value < 0.05,
            }

    # Plot 2: Within Growing cluster - event vs organic
    ax = axes[1]
    for ctype, color, label_prefix in [("event", "#e74c3c", "Event"), ("organic", "#3498db", "Organic")]:
        members = [m for m in merged if m["cluster"] == 2 and m["contributor_type"] == ctype and m["retention_months"] > 0]
        if not members:
            continue
        durations = [m["retention_months"] for m in members]
        events = [1] * len(durations)
        kmf = KaplanMeierFitter()
        kmf.fit(durations, events, label=f"{label_prefix} Growing (n={len(members)})")
        kmf.plot_survival_function(ax=ax, color=color, ci_show=True, alpha=0.7)

    ax.set_title("Growing Pattern: Event vs Organic Retention", fontsize=13, fontweight="bold")
    ax.set_xlabel("Months Active")
    ax.set_ylabel("Survival Probability")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n  Saved survival plot: {OUTPUT_PNG}")

    print(f"\n  Log-rank tests:")
    for pair, r in log_rank_results.items():
        sig = "***" if r["significant"] else "ns"
        print(f"    {pair}: stat={r['test_statistic']:.2f}, p={r['p_value']:.4f} {sig}")

    return log_rank_results


# ── Main ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Use only 10 contributors")
    args = parser.parse_args()

    t0 = time.time()
    print("=" * 60)
    print("CLUSTER-RETENTION SCOTT-KNOTT ANALYSIS")
    print("=" * 60)

    # Load data
    print("\n[1/5] Loading data...")
    with open(CLUSTERING_PATH) as f:
        clustering = json.load(f)
    assignments = clustering["assignments"]
    print(f"  Cluster assignments: {len(assignments)}")

    core_status = load_core_status()
    print(f"  Core status entries: {len(core_status)}")

    ttc_data = load_ttc()
    print(f"  TTC entries: {len(ttc_data)}")

    with open(CI_PATH) as f:
        ci_data = json.load(f)
    retention_data = compute_retention_from_ci(ci_data)
    print(f"  Retention (from CI): {len(retention_data)} contributors")

    organic_map = build_organic_username_map()
    print(f"  Organic username->email map: {len(organic_map)} entries")

    # Merge
    print("\n[2/5] Merging datasets...")
    test_n = 10 if args.test else None
    merged, matched, unmatched = build_merged_dataset(
        assignments, core_status, ttc_data, retention_data, organic_map, test_n=test_n
    )
    print(f"  Matched: {matched}, Unmatched: {unmatched}")
    print(f"  Merged dataset: {len(merged)} contributors")

    if args.test:
        print("\n  TEST MODE - sample of merged data:")
        for m in merged[:5]:
            print(f"    {m['username']:20s} | cluster={m['cluster']} | core={m['is_core']} | ttc={m['time_to_core']} | ret={m['retention_months']}")

    # Distribution summary
    from collections import Counter
    cluster_counts = Counter(m["cluster"] for m in merged)
    print(f"\n  Cluster distribution:")
    for cl_id in sorted(cluster_counts):
        name = CLUSTER_NAMES.get(cl_id, f"C{cl_id}")
        print(f"    {name}: {cluster_counts[cl_id]}")

    # Scott-Knott
    print("\n[3/5] Scott-Knott rankings...")
    sk_results = analyze_scott_knott(merged)

    # Cross-tabulation
    print("\n[4/5] Cross-tabulation analysis...")
    cross_results = analyze_cross_tabulation(merged)

    # Survival plots
    print("\n[5/5] Generating survival curves...")
    log_rank_results = generate_survival_plots(merged)

    # Save results
    output = {
        "config": {
            "n_matched": matched,
            "n_unmatched": unmatched,
            "n_merged": len(merged),
            "cluster_names": CLUSTER_NAMES,
        },
        "scott_knott": sk_results,
        "cross_tabulation": cross_results,
        "log_rank_tests": log_rank_results,
        "cluster_distribution": {
            CLUSTER_NAMES.get(cl, f"C{cl}"): {
                "total": sum(1 for m in merged if m["cluster"] == cl),
                "event": sum(1 for m in merged if m["cluster"] == cl and m["contributor_type"] == "event"),
                "organic": sum(1 for m in merged if m["cluster"] == cl and m["contributor_type"] == "organic"),
                "core": sum(1 for m in merged if m["cluster"] == cl and m["is_core"]),
                "core_rate": round(
                    sum(1 for m in merged if m["cluster"] == cl and m["is_core"])
                    / max(sum(1 for m in merged if m["cluster"] == cl), 1),
                    4,
                ),
            }
            for cl in sorted(set(m["cluster"] for m in merged))
        },
    }

    class NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return super().default(obj)

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2, cls=NumpyEncoder)
    print(f"\n  Saved results: {OUTPUT_JSON}")

    elapsed = time.time() - t0
    print(f"\n  Total time: {elapsed:.1f}s")
    print("=" * 60)
    print("DONE!")


if __name__ == "__main__":
    main()
