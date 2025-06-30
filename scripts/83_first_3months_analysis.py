#!/usr/bin/env python3
"""
First 3 Months Activity Analysis.

Analyzes contributor activity patterns and personas specifically in the first
3 months of engagement (typical mentorship event duration: GSoC, LFX).

Parts:
  1. First 3 months CI patterns - cluster and compare distributions
  2. First 3 months activity profiles (6 dimensions) - spider/radar plots
  3. Predictive value - Scott-Knott ranking by eventual core rate

Backed by:
  - Xiao et al. (FSE 2023): Early participation predicts sustained engagement
  - Zhou & Mockus (ICSE 2012): Early environment predicts long-term engagement
  - Ouf et al. (ICSE 2026): Temporal patterns and newcomer-to-core transitions

Usage:
  python3 scripts/83_first_3months_analysis.py --test   # 10 contributors
  python3 scripts/83_first_3months_analysis.py           # all
"""

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime

import numpy as np
from scipy import stats as scipy_stats
from scipy.stats import mannwhitneyu, chi2_contingency
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")
SPIDER_DIR = os.path.join(OUTPUT_DIR, "spider_plots")

JOURNEY_PATH = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")
CI_PATH = os.path.join(OUTPUT_DIR, "contribution_index_timeseries.json")
CORE_PATH = os.path.join(OUTPUT_DIR, "per_contributor_core_status.csv")
CORE_TTC_PATH = os.path.join(OUTPUT_DIR, "per_contributor_core_status_with_ttc.csv")

OUTPUT_JSON = os.path.join(OUTPUT_DIR, "first_3months_results.json")
OUTPUT_PATTERNS_PNG = os.path.join(OUTPUT_DIR, "first_3months_patterns.png")
OUTPUT_SPIDER_PNG = os.path.join(SPIDER_DIR, "first_3months_spider.png")

os.makedirs(SPIDER_DIR, exist_ok=True)

DIMENSION_NAMES = [
    "Commit Frequency",
    "PR Success Rate",
    "Issue Activity",
    "Discussion Depth",
    "Activity Duration",
    "Contribution Breadth",
]
N_DIMS = len(DIMENSION_NAMES)


# ── Scott-Knott ESD ────────────────────────────────────────────

def cliffs_delta(x, y):
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


# ── Part 1: First 3 Months CI Patterns ─────────────────────────

def extract_first_3months_ci(ci_data):
    """Extract first 3 months of CI timeseries for each contributor."""
    entries = []
    for ctype in ["event", "organic"]:
        for entry in ci_data.get(ctype, []):
            username = (entry.get("username") or "").lower()
            repo = (entry.get("repo") or "").lower()
            ci_series = entry.get("ci", [])

            if not username or not repo or not ci_series:
                continue

            # Take first 3 months (or fewer if shorter)
            first_3 = ci_series[:3]
            length = len(ci_series)

            entries.append({
                "username": entry.get("username", ""),
                "repo": entry.get("repo", ""),
                "contributor_type": ctype,
                "event_type": entry.get("event_type", ctype),
                "first_3_ci": first_3,
                "full_length": length,
            })
    return entries


def normalize_to_fixed_length(series, target_len=3):
    """Normalize a time series to a fixed length via interpolation."""
    if len(series) == 0:
        return [0.0] * target_len
    if len(series) == target_len:
        return list(series)
    if len(series) == 1:
        return [series[0]] * target_len
    x_old = np.linspace(0, 1, len(series))
    x_new = np.linspace(0, 1, target_len)
    return list(np.interp(x_new, x_old, series))


def extract_3month_features(series):
    """Extract shape features from a 3-month CI series."""
    s = np.array(series, dtype=float)
    total = s.sum()
    if total == 0:
        return [0.5, 0.0, 1.0, 1.0, 0.0]

    # 1. Peak position (early=0, late=1)
    peak_pos = np.argmax(s) / max(len(s) - 1, 1)

    # 2. Trend (slope of linear fit)
    x = np.arange(len(s))
    slope = np.polyfit(x, s, 1)[0]
    trend = slope / max(np.std(s), 1e-6)
    trend = np.clip(trend, -3, 3) / 6 + 0.5  # Normalize to [0, 1]

    # 3. Concentration (Gini-like)
    sorted_s = np.sort(s)
    n = len(sorted_s)
    cumsum = np.cumsum(sorted_s)
    concentration = 1.0 - 2.0 * cumsum.sum() / (n * total)
    concentration = np.clip(concentration, 0, 1)

    # 4. Balance (std / mean)
    mean_s = np.mean(s)
    balance = np.std(s) / mean_s if mean_s > 0 else 0
    balance = min(balance, 3.0) / 3.0

    # 5. Active ratio
    active_ratio = np.sum(s > 0) / len(s)

    return [peak_pos, trend, concentration, balance, active_ratio]


def cluster_3month_patterns(entries, test_n=None):
    """Cluster first-3-month CI patterns."""
    if test_n:
        entries = entries[:test_n]

    # Filter: need at least 1 month of data
    valid = [e for e in entries if len(e["first_3_ci"]) >= 1]
    print(f"  Valid entries (>=1 month): {len(valid)}")

    # Normalize to 3 months
    for e in valid:
        e["norm_3"] = normalize_to_fixed_length(e["first_3_ci"], 3)

    # Extract features
    features = np.array([extract_3month_features(e["norm_3"]) for e in valid])
    print(f"  Feature matrix shape: {features.shape}")

    # Scale and cluster
    scaler = StandardScaler()
    X = scaler.fit_transform(features)

    results = {}
    for k in range(2, 6):
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = km.fit_predict(X)
        sil = silhouette_score(X, labels) if len(set(labels)) > 1 else 0
        results[k] = {"labels": labels, "silhouette": sil}
        print(f"    K={k}: silhouette={sil:.3f}")

    # Force K=3 for interpretability (matching full-timeline analysis)
    best_k = 3
    print(f"  Using K={best_k} (silhouette={results[best_k]['silhouette']:.3f})")

    labels = results[best_k]["labels"]
    for i, e in enumerate(valid):
        e["pattern_cluster"] = int(labels[i])

    # Compute mean patterns for each cluster
    cluster_means = {}
    for cl in range(best_k):
        mask = labels == cl
        cluster_series = np.array([e["norm_3"] for e in valid])[mask]
        cluster_means[cl] = cluster_series.mean(axis=0).tolist()

    return valid, labels, cluster_means, best_k, results[best_k]["silhouette"]


def name_3month_pattern(mean_series, existing_names=None):
    """Name a 3-month pattern based on its shape, ensuring uniqueness."""
    if existing_names is None:
        existing_names = set()

    s = np.array(mean_series)
    if len(s) < 3:
        base = "Short"
    elif s[2] < 0.1 * max(s[0], 1e-6):
        base = "Sharp Dropout"
    elif s[0] > s[1] and s[1] > s[2] and s[0] > 2 * s[2]:
        base = "Front-Loading"
    elif s[0] > s[1] and s[1] > s[2]:
        base = "Gradual Decline"
    elif s[0] < s[1] and s[1] < s[2]:
        base = "Accelerating"
    elif s[1] > s[0] and s[1] > s[2]:
        base = "Mid-Peak"
    elif abs(s[0] - s[2]) < 0.15 * max(np.mean(s), 1e-6):
        base = "Steady High" if np.mean(s) > 2 else "Steady Low"
    elif s[0] > s[2]:
        base = "Tapering"
    else:
        base = "Rising"

    # Ensure uniqueness
    name = base
    counter = 2
    while name in existing_names:
        name = f"{base} ({counter})"
        counter += 1
    existing_names.add(name)
    return name


# ── Part 2: First 3 Months Activity Profiles ───────────────────

def compute_first_3months_profiles(journeys, ci_data):
    """Compute 6-dimension profiles using only first 3 months of activity."""
    # Build CI lookup with start dates
    ci_lookup = {}
    for ctype in ["event", "organic"]:
        for entry in ci_data.get(ctype, []):
            username = (entry.get("username") or "").lower()
            repo = (entry.get("repo") or "").lower()
            if username and repo:
                ci_lookup[(username, repo, ctype)] = entry

    profiles = []

    def process_contributor(j, ctype):
        username = (j.get("github_username") or "").lower()
        repo = (j.get("repo") or "").lower()

        ci_entry = ci_lookup.get((username, repo, ctype))
        if not ci_entry:
            return None

        start_str = ci_entry.get("start", "")
        if not start_str:
            return None

        # Parse start month
        try:
            start_date = datetime.strptime(start_str, "%Y-%m")
        except ValueError:
            return None

        # End of first 3 months
        # month 0 = start, month 1 = start+1, month 2 = start+2
        from dateutil.relativedelta import relativedelta
        end_3months = start_date + relativedelta(months=3)

        # Filter PRs to first 3 months
        prs = j.get("pull_requests", []) or []
        prs_3m = []
        for pr in prs:
            created = pr.get("created_at", "")
            if created:
                try:
                    pr_date = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if pr_date.replace(tzinfo=None) < end_3months:
                        prs_3m.append(pr)
                except (ValueError, TypeError):
                    pass

        # Filter issues to first 3 months
        issues = j.get("issues", []) or []
        issues_3m = []
        for issue in issues:
            created = issue.get("created_at", "")
            if created:
                try:
                    issue_date = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if issue_date.replace(tzinfo=None) < end_3months:
                        issues_3m.append(issue)
                except (ValueError, TypeError):
                    pass

        # Commits in first 3 months from CI series
        ci_series = ci_entry.get("ci", [])
        ci_3m = ci_series[:3] if ci_series else []
        # Approximate commit count from CI (commits ~= CI * active_months / 0.35)
        # Actually use commit proportion: if full has N commits over L months,
        # first 3 months ~= (sum of first 3 CI / total CI) * total commits
        total_ci = sum(ci_series)
        ci_3m_sum = sum(ci_3m)
        total_commits = j.get("commit_count", 0) or 0
        if total_ci > 0:
            commits_3m = round(total_commits * ci_3m_sum / total_ci)
        else:
            commits_3m = 0

        # Active months in first 3 months (how many of the 3 have activity)
        active_months_3m = min(len(ci_series), 3)
        am = max(active_months_3m, 1)

        # Merged PRs in first 3 months
        merged_3m = sum(1 for pr in prs_3m if pr.get("merged_at"))

        # Issue comments in first 3 months
        comments_3m = sum((issue.get("comments", 0) or 0) for issue in issues_3m)

        # 6 dimensions (same as full profile but scoped to first 3 months)
        commit_freq = commits_3m / am
        pr_success = merged_3m / len(prs_3m) if prs_3m else 0.0
        issue_activity = len(issues_3m) / am
        discussion_depth = comments_3m / max(len(issues_3m), 1)
        activity_duration = active_months_3m
        types_active = sum([
            commits_3m > 0,
            len(prs_3m) > 0,
            len(issues_3m) > 0,
            comments_3m > 0,
        ])
        contribution_breadth = types_active / 4.0

        event_type = j.get("event", ctype)
        cid = j.get("contribution_id", "") or j.get("matched_event_contribution_id", "")
        if ctype == "organic":
            cid = cid + "__organic"

        return {
            "contributor_id": cid,
            "username": j.get("github_username", ""),
            "repo": j.get("repo", ""),
            "contributor_type": ctype,
            "event_type": event_type,
            "raw_dims": [commit_freq, pr_success, issue_activity, discussion_depth,
                         activity_duration, contribution_breadth],
            "raw_counts_3m": {
                "commits": commits_3m,
                "prs": len(prs_3m),
                "merged_prs": merged_3m,
                "issues": len(issues_3m),
                "comments": comments_3m,
            },
        }

    for j in journeys.get("event_journeys", []):
        p = process_contributor(j, "event")
        if p:
            profiles.append(p)

    for j in journeys.get("organic_journeys", []):
        p = process_contributor(j, "organic")
        if p:
            profiles.append(p)

    return profiles


# ── Part 3: Predictive Value ───────────────────────────────────

def load_core_data():
    """Load core status keyed by (username, repo, type)."""
    core = {}
    organic_map = {}

    # Load journey data for organic email->username mapping
    with open(JOURNEY_PATH) as f:
        journeys = json.load(f)
    for j in journeys.get("organic_journeys", []):
        username = (j.get("github_username") or "").lower()
        email = (j.get("organic_email") or "").lower()
        repo = (j.get("repo") or "").lower()
        if username and email and repo:
            organic_map[(username, repo)] = email

    with open(CORE_PATH) as f:
        for r in csv.DictReader(f):
            uname = r["username_or_email"].lower()
            repo = r["repo"].lower()
            ctype = r["contributor_type"]
            core[(uname, repo, ctype)] = r["ever_core"] == "True"

    ttc = {}
    if os.path.exists(CORE_TTC_PATH):
        with open(CORE_TTC_PATH) as f:
            for r in csv.DictReader(f):
                uname = r["username_or_email"].lower()
                repo = r["repo"].lower()
                ctype = r["contributor_type"]
                try:
                    ttc[(uname, repo, ctype)] = float(r["real_ttc_months"])
                except (ValueError, TypeError):
                    pass

    return core, ttc, organic_map


def connect_patterns_to_outcomes(entries, core_data, ttc_data, organic_map, pattern_names):
    """Connect first-3-month patterns to core achievement and retention."""
    results = {}

    for cl_id, cl_name in pattern_names.items():
        members = [e for e in entries if e.get("pattern_cluster") == cl_id]
        if not members:
            continue

        core_count = 0
        ttc_values = []
        for m in members:
            uname = m["username"].lower()
            repo = m["repo"].lower()
            ctype = m["contributor_type"]

            is_core = core_data.get((uname, repo, ctype), False)
            if not is_core and ctype == "organic":
                email = organic_map.get((uname, repo))
                if email:
                    is_core = core_data.get((email, repo, "organic"), False)

            if is_core:
                core_count += 1
                t = ttc_data.get((uname, repo, ctype))
                if t is None and ctype == "organic":
                    email = organic_map.get((uname, repo))
                    if email:
                        t = ttc_data.get((email, repo, "organic"))
                if t is not None:
                    ttc_values.append(t)

        core_rate = core_count / len(members) if members else 0
        results[cl_name] = {
            "n": len(members),
            "core_count": core_count,
            "core_rate": round(core_rate, 4),
            "median_ttc": round(float(np.median(ttc_values)), 1) if ttc_values else None,
            "mean_ttc": round(float(np.mean(ttc_values)), 1) if ttc_values else None,
        }

    return results


# ── Plotting ───────────────────────────────────────────────────

def plot_3month_patterns(cluster_means, pattern_names, entries, sil_score):
    """Plot first 3-month CI patterns."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Left: Pattern centroids
    ax = axes[0]
    months = [1, 2, 3]
    for cl_id, mean_ts in sorted(cluster_means.items()):
        name = pattern_names.get(cl_id, f"C{cl_id}")
        n = sum(1 for e in entries if e.get("pattern_cluster") == cl_id)
        ax.plot(months, mean_ts, "o-", color=colors[cl_id % len(colors)],
                linewidth=2.5, markersize=8, label=f"{name} (n={n})")
    ax.set_xlabel("Month", fontsize=12)
    ax.set_ylabel("Mean Contribution Index", fontsize=12)
    ax.set_title(f"First 3-Month Activity Patterns\n(silhouette={sil_score:.3f})",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_xticks([1, 2, 3])

    # Right: Pattern distribution by event type
    ax = axes[1]
    event_types = sorted(set(e["event_type"] for e in entries))
    cluster_ids = sorted(cluster_means.keys())
    x = np.arange(len(event_types))
    width = 0.8 / len(cluster_ids)

    for i, cl_id in enumerate(cluster_ids):
        counts = []
        for et in event_types:
            n = sum(1 for e in entries if e.get("pattern_cluster") == cl_id and e["event_type"] == et)
            counts.append(n)
        name = pattern_names.get(cl_id, f"C{cl_id}")
        ax.bar(x + i * width, counts, width, label=name, color=colors[cl_id % len(colors)], alpha=0.8)

    ax.set_xticks(x + width * (len(cluster_ids) - 1) / 2)
    ax.set_xticklabels([et.upper() if et in ("gsoc", "lfx") else et.title() for et in event_types],
                       fontsize=9, rotation=20)
    ax.set_ylabel("Count")
    ax.set_title("Pattern Distribution by Event Type", fontsize=13, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(OUTPUT_PATTERNS_PNG, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {OUTPUT_PATTERNS_PNG}")


def create_radar_plot(groups, title, filename):
    """Create spider/radar plot."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n_dims = len(DIMENSION_NAMES)
    angles = np.linspace(0, 2 * np.pi, n_dims, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c"]

    for i, (label, values) in enumerate(groups.items()):
        vals = list(values) + [values[0]]
        color = colors[i % len(colors)]
        ax.plot(angles, vals, "o-", linewidth=2, label=label, color=color, alpha=0.8)
        ax.fill(angles, vals, alpha=0.1, color=color)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(DIMENSION_NAMES, size=10)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8"], color="grey", size=8)
    ax.set_title(title, size=14, fontweight="bold", pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.15), fontsize=9)

    plt.tight_layout()
    plt.savefig(os.path.join(SPIDER_DIR, filename), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    Saved: {filename}")


# ── Main ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Use only 10 contributors")
    args = parser.parse_args()

    t0 = time.time()
    print("=" * 60)
    print("FIRST 3 MONTHS ACTIVITY ANALYSIS")
    print("=" * 60)

    # Load data
    print("\n[1/6] Loading data...")
    with open(JOURNEY_PATH) as f:
        journeys = json.load(f)
    with open(CI_PATH) as f:
        ci_data = json.load(f)
    core_data, ttc_data, organic_map = load_core_data()
    print(f"  Journeys: {len(journeys.get('event_journeys',[]))} event + {len(journeys.get('organic_journeys',[]))} organic")
    print(f"  Core status: {len(core_data)} entries")

    # Part 1: First 3 months CI patterns
    print("\n[2/6] Part 1: First 3-month CI patterns...")
    ci_entries = extract_first_3months_ci(ci_data)
    print(f"  CI entries: {len(ci_entries)}")

    test_n = 10 if args.test else None
    valid_entries, labels, cluster_means, best_k, sil = cluster_3month_patterns(ci_entries, test_n)

    pattern_names = {}
    used_names = set()
    for cl_id in sorted(cluster_means.keys()):
        mean_ts = cluster_means[cl_id]
        name = name_3month_pattern(mean_ts, used_names)
        pattern_names[cl_id] = name
        print(f"    Pattern {cl_id} ({name}): {[f'{v:.2f}' for v in mean_ts]}")

    # Distribution
    print(f"\n  Pattern distribution:")
    for cl_id in sorted(cluster_means):
        n_total = sum(1 for e in valid_entries if e.get("pattern_cluster") == cl_id)
        n_event = sum(1 for e in valid_entries if e.get("pattern_cluster") == cl_id and e["contributor_type"] == "event")
        n_organic = sum(1 for e in valid_entries if e.get("pattern_cluster") == cl_id and e["contributor_type"] == "organic")
        print(f"    {pattern_names[cl_id]:20s} | total={n_total:5d} | event={n_event:5d} | organic={n_organic:5d}")

    # Part 2: First 3 months activity profiles
    print("\n[3/6] Part 2: First 3-month activity profiles...")
    profiles_3m = compute_first_3months_profiles(journeys, ci_data)
    if args.test:
        profiles_3m = profiles_3m[:test_n]
    print(f"  Profiles computed: {len(profiles_3m)}")

    # Percentile rank normalization
    if profiles_3m:
        raw_matrix = np.array([p["raw_dims"] for p in profiles_3m])
        n = raw_matrix.shape[0]
        pct_matrix = np.zeros_like(raw_matrix)
        for dim in range(N_DIMS):
            col = raw_matrix[:, dim]
            ranks = scipy_stats.rankdata(col, method="average")
            pct_matrix[:, dim] = (ranks - 1) / max(n - 1, 1)
        for i, p in enumerate(profiles_3m):
            p["percentile_dims"] = pct_matrix[i].tolist()

    # Spider plots for first 3 months
    print("\n[4/6] Generating first 3-month spider plots...")
    ev_3m = [p for p in profiles_3m if p["contributor_type"] == "event"]
    org_3m = [p for p in profiles_3m if p["contributor_type"] == "organic"]

    if ev_3m and org_3m:
        ev_mean = np.mean([p["percentile_dims"] for p in ev_3m], axis=0).tolist()
        org_mean = np.mean([p["percentile_dims"] for p in org_3m], axis=0).tolist()
        create_radar_plot(
            {"Event (3m)": ev_mean, "Organic (3m)": org_mean},
            "First 3 Months: Event vs Organic",
            "first_3months_event_vs_organic.png",
        )

    # By event type
    mentorship_events = {"gsoc", "lfx"}
    non_mentorship_events = {"hacktoberfest", "24pullrequests"}
    ment_3m = [p for p in profiles_3m if p["event_type"] in mentorship_events]
    non_ment_3m = [p for p in profiles_3m if p["event_type"] in non_mentorship_events]
    if ment_3m and non_ment_3m and org_3m:
        ment_mean = np.mean([p["percentile_dims"] for p in ment_3m], axis=0).tolist()
        non_ment_mean = np.mean([p["percentile_dims"] for p in non_ment_3m], axis=0).tolist()
        org_mean_3 = np.mean([p["percentile_dims"] for p in org_3m], axis=0).tolist()
        create_radar_plot(
            {"Mentorship (3m)": ment_mean, "Non-Mentorship (3m)": non_ment_mean, "Organic (3m)": org_mean_3},
            "First 3 Months: Mentorship vs Non-Mentorship vs Organic",
            "first_3months_mentorship.png",
        )

    # Part 3: Predictive value
    print("\n[5/6] Part 3: Connecting patterns to outcomes...")
    outcomes = connect_patterns_to_outcomes(valid_entries, core_data, ttc_data, organic_map, pattern_names)

    print(f"\n  Pattern -> Core Achievement:")
    for name, o in sorted(outcomes.items(), key=lambda x: x[1]["core_rate"], reverse=True):
        ttc_str = f"median TTC={o['median_ttc']}m" if o["median_ttc"] else "N/A"
        print(f"    {name:20s} | n={o['n']:5d} | core={o['core_count']:4d} ({o['core_rate']*100:.1f}%) | {ttc_str}")

    # Scott-Knott on core rate by pattern
    core_rate_data = {}
    for name, o in outcomes.items():
        vals = np.array([1.0] * o["core_count"] + [0.0] * (o["n"] - o["core_count"]))
        if len(vals) >= 3:
            core_rate_data[name] = vals

    sk_results = {}
    if len(core_rate_data) >= 2:
        sk_results = scott_knott_esd(core_rate_data)
        print(f"\n  Scott-Knott ranking (core rate):")
        for name in sorted(sk_results, key=lambda x: sk_results[x]):
            print(f"    Rank {sk_results[name]}: {name:20s} | core rate={outcomes[name]['core_rate']*100:.1f}%")

    # Plot patterns
    if not args.test:
        print("\n[6/6] Generating pattern plots...")
        plot_3month_patterns(cluster_means, pattern_names, valid_entries, sil)

    # Dimension tests: event vs organic (first 3 months)
    dim_tests = {}
    if ev_3m and org_3m:
        ev_mat = np.array([p["percentile_dims"] for p in ev_3m])
        org_mat = np.array([p["percentile_dims"] for p in org_3m])
        bonferroni_alpha = 0.05 / N_DIMS
        print(f"\n  Dimension tests (first 3m, event vs organic, Bonferroni alpha={bonferroni_alpha:.4f}):")
        for dim in range(N_DIMS):
            ev_vals = ev_mat[:, dim]
            org_vals = org_mat[:, dim]
            stat, p = mannwhitneyu(ev_vals, org_vals, alternative="two-sided")
            d = cliffs_delta(ev_vals, org_vals)
            sig = "***" if p < bonferroni_alpha else "ns"
            dim_tests[DIMENSION_NAMES[dim]] = {
                "event_median": float(np.median(ev_vals)),
                "organic_median": float(np.median(org_vals)),
                "p_value": float(p),
                "cliffs_delta": float(d),
                "significant": p < bonferroni_alpha,
            }
            print(f"    {DIMENSION_NAMES[dim]:25s} | ev={np.median(ev_vals):.3f} org={np.median(org_vals):.3f} | p={p:.4f} d={d:.3f} {sig}")

    # Save results
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

    output = {
        "config": {
            "n_ci_entries": len(ci_entries),
            "n_valid_entries": len(valid_entries),
            "n_profiles_3m": len(profiles_3m),
            "best_k": best_k,
            "silhouette": sil,
        },
        "patterns": {
            pattern_names[cl]: {
                "mean_ci": cluster_means[cl],
                "n": sum(1 for e in valid_entries if e.get("pattern_cluster") == cl),
            }
            for cl in cluster_means
        },
        "pattern_outcomes": outcomes,
        "scott_knott_core_rate": sk_results,
        "dimension_tests_3m": dim_tests,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2, cls=NumpyEncoder)
    print(f"\n  Saved: {OUTPUT_JSON}")

    elapsed = time.time() - t0
    print(f"\n  Total time: {elapsed:.1f}s")
    print("=" * 60)
    print("DONE!")


if __name__ == "__main__":
    main()
