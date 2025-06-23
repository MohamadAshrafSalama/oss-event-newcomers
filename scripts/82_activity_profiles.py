#!/usr/bin/env python3
"""
Contributor Activity Profiles and Personas.

Computes 6 non-overlapping activity dimensions per contributor, normalizes
via percentile rank, identifies personas through K-means clustering, and
generates spider/radar plots for each group.

Dimensions (each backed by citation):
  1. Commit Frequency   - commits / active_months         [Zhou & Mockus 2012]
  2. PR Success Rate    - merged_PRs / total_PRs          [Gousios et al. 2016]
  3. Issue Activity     - issues / active_months           [Cheng & Guo 2019]
  4. Discussion Depth   - issue_comments / max(issues, 1)  [Constantinou & Mens 2017]
  5. Activity Duration  - months from first to last        [Lin et al. 2017]
  6. Contribution Breadth - non-zero {commits,PRs,issues,comments}/4  [Anderson & Sindt 2025]

Normalization: Percentile rank across all contributors (Anderson & Sindt 2025).
Persona identification: K-means on standardized dimensions, K=2..6, silhouette.

Usage:
  python3 scripts/82_activity_profiles.py --test    # 10 contributors
  python3 scripts/82_activity_profiles.py            # all 4,002 contributors
"""

import argparse
import json
import os
import sys
import time

import numpy as np
from scipy import stats as scipy_stats
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

OUTPUT_PROFILES = os.path.join(OUTPUT_DIR, "activity_profiles.json")
OUTPUT_PERSONAS = os.path.join(OUTPUT_DIR, "persona_results.json")

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


# ── Compute Activity Dimensions ────────────────────────────────

def compute_profiles(journeys, ci_data):
    """Compute 6 activity dimensions for each contributor."""
    # Build CI lookup: (username.lower(), repo.lower(), type) -> entry
    ci_lookup = {}
    for ctype in ["event", "organic"]:
        for entry in ci_data.get(ctype, []):
            username = (entry.get("username") or "").lower()
            repo = (entry.get("repo") or "").lower()
            if username and repo:
                ci_lookup[(username, repo, ctype)] = entry

    profiles = []

    # Event contributors
    for j in journeys.get("event_journeys", []):
        username = (j.get("github_username") or "").lower()
        repo = (j.get("repo") or "").lower()
        event_type = j.get("event", "")
        cid = j.get("contribution_id", f"ev_{username}_{repo}")

        ci_entry = ci_lookup.get((username, repo, "event"))
        active_months = ci_entry["length"] if ci_entry else 1

        profile = compute_single_profile(j, active_months)
        profile["contributor_id"] = cid
        profile["username"] = j.get("github_username", "")
        profile["repo"] = j.get("repo", "")
        profile["contributor_type"] = "event"
        profile["event_type"] = event_type
        profile["active_months"] = active_months
        profiles.append(profile)

    # Organic contributors
    for j in journeys.get("organic_journeys", []):
        username = (j.get("github_username") or "").lower()
        repo = (j.get("repo") or "").lower()
        cid = j.get("matched_event_contribution_id", "") + "__organic"

        ci_entry = ci_lookup.get((username, repo, "organic"))
        active_months = ci_entry["length"] if ci_entry else 1

        profile = compute_single_profile(j, active_months)
        profile["contributor_id"] = cid
        profile["username"] = j.get("github_username", "")
        profile["repo"] = j.get("repo", "")
        profile["contributor_type"] = "organic"
        profile["event_type"] = "organic"
        profile["active_months"] = active_months
        profiles.append(profile)

    return profiles


def compute_single_profile(journey, active_months):
    """Compute 6 raw dimension values for a single contributor."""
    commit_count = journey.get("commit_count", 0) or 0
    prs = journey.get("pull_requests", []) or []
    issues = journey.get("issues", []) or []
    pr_count = len(prs)
    issue_count = len(issues)

    # Count merged PRs
    merged_prs = sum(1 for pr in prs if pr.get("merged_at"))

    # Sum issue comments from issue.comments field (integer count)
    total_issue_comments = sum(
        (issue.get("comments", 0) or 0) for issue in issues
    )

    # Active months (at least 1 to avoid division by zero)
    am = max(active_months, 1)

    # 1. Commit Frequency: commits / active_months
    commit_freq = commit_count / am

    # 2. PR Success Rate: merged / total (0 if no PRs)
    pr_success = merged_prs / pr_count if pr_count > 0 else 0.0

    # 3. Issue Activity: issues / active_months
    issue_activity = issue_count / am

    # 4. Discussion Depth: total_issue_comments / max(issues, 1)
    discussion_depth = total_issue_comments / max(issue_count, 1)

    # 5. Activity Duration: direct months value
    activity_duration = active_months

    # 6. Contribution Breadth: fraction of {commits, PRs, issues, comments} > 0
    types_active = sum([
        commit_count > 0,
        pr_count > 0,
        issue_count > 0,
        total_issue_comments > 0,
    ])
    contribution_breadth = types_active / 4.0

    return {
        "raw_dims": [
            commit_freq,
            pr_success,
            issue_activity,
            discussion_depth,
            activity_duration,
            contribution_breadth,
        ],
        "raw_counts": {
            "commits": commit_count,
            "prs": pr_count,
            "merged_prs": merged_prs,
            "issues": issue_count,
            "issue_comments": total_issue_comments,
        },
    }


# ── Normalization ──────────────────────────────────────────────

def percentile_rank_normalize(profiles):
    """Normalize each dimension to percentile rank [0, 1]."""
    raw_matrix = np.array([p["raw_dims"] for p in profiles])
    n = raw_matrix.shape[0]

    pct_matrix = np.zeros_like(raw_matrix)
    for dim in range(N_DIMS):
        col = raw_matrix[:, dim]
        ranks = scipy_stats.rankdata(col, method="average")
        pct_matrix[:, dim] = (ranks - 1) / max(n - 1, 1)

    for i, p in enumerate(profiles):
        p["percentile_dims"] = pct_matrix[i].tolist()

    return pct_matrix


# ── Persona Clustering ─────────────────────────────────────────

def cluster_personas(pct_matrix, k_range=(2, 7)):
    """K-means clustering on percentile-ranked dimensions."""
    scaler = StandardScaler()
    X = scaler.fit_transform(pct_matrix)

    results = {}
    for k in range(k_range[0], k_range[1]):
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = km.fit_predict(X)
        sil = silhouette_score(X, labels)
        results[k] = {"labels": labels, "silhouette": sil, "model": km}
        print(f"    K={k}: silhouette={sil:.3f}")

    best_k = max(results, key=lambda k: results[k]["silhouette"])
    print(f"  Best K={best_k} (silhouette={results[best_k]['silhouette']:.3f})")

    best = results[best_k]
    labels = best["labels"]

    # Compute centroid profiles (in percentile space)
    centroids = {}
    for cl in range(best_k):
        mask = labels == cl
        centroid = pct_matrix[mask].mean(axis=0).tolist()
        centroids[cl] = centroid

    return labels, centroids, best_k, results[best_k]["silhouette"]


def name_persona(centroid):
    """Name a persona based on its dominant dimensions."""
    dim_values = list(zip(DIMENSION_NAMES, centroid))
    sorted_dims = sorted(dim_values, key=lambda x: x[1], reverse=True)

    top = sorted_dims[0]
    second = sorted_dims[1]

    # Descriptive naming
    name_map = {
        "Commit Frequency": "Code-Focused",
        "PR Success Rate": "Effective Contributor",
        "Issue Activity": "Issue-Driven",
        "Discussion Depth": "Discussion-Oriented",
        "Activity Duration": "Long-Term",
        "Contribution Breadth": "Versatile",
    }

    primary = name_map.get(top[0], top[0])

    # If top dimension is very dominant (>0.7), use single name
    if top[1] > 0.7:
        return primary

    return f"{primary} {name_map.get(second[0], second[0])}"


# ── Spider/Radar Plots ─────────────────────────────────────────

def create_radar_plot(groups, title, filename, dim_names=None):
    """Create a radar/spider plot comparing groups."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if dim_names is None:
        dim_names = DIMENSION_NAMES

    n_dims = len(dim_names)
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
    ax.set_xticklabels(dim_names, size=10)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8"], color="grey", size=8)
    ax.set_title(title, size=14, fontweight="bold", pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.15), fontsize=9)

    plt.tight_layout()
    plt.savefig(os.path.join(SPIDER_DIR, filename), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"    Saved: {filename}")


# ── Statistical Tests ──────────────────────────────────────────

def run_dimension_tests(profiles, alpha=0.05):
    """Mann-Whitney U on each dimension: event vs organic. Bonferroni-corrected."""
    from scipy.stats import mannwhitneyu

    event_list = [p["percentile_dims"] for p in profiles if p["contributor_type"] == "event"]
    organic_list = [p["percentile_dims"] for p in profiles if p["contributor_type"] == "organic"]

    if not event_list or not organic_list:
        print("  Skipping dimension tests (need both event and organic)")
        return {}

    event_matrix = np.array(event_list)
    organic_matrix = np.array(organic_list)

    bonferroni_alpha = alpha / N_DIMS
    results = {}

    print(f"\n  Dimension tests (event vs organic, Bonferroni alpha={bonferroni_alpha:.4f}):")
    for dim in range(N_DIMS):
        ev_vals = event_matrix[:, dim]
        org_vals = organic_matrix[:, dim]
        stat, p = mannwhitneyu(ev_vals, org_vals, alternative="two-sided")

        # Cliff's delta
        nx, ny = len(ev_vals), len(org_vals)
        count = 0.0
        for xi in ev_vals:
            count += np.sum(xi > org_vals) - np.sum(xi < org_vals)
        d = count / (nx * ny)

        sig = "***" if p < bonferroni_alpha else "ns"
        results[DIMENSION_NAMES[dim]] = {
            "event_median": float(np.median(ev_vals)),
            "organic_median": float(np.median(org_vals)),
            "mann_whitney_p": float(p),
            "cliffs_delta": float(d),
            "significant": p < bonferroni_alpha,
        }
        print(f"    {DIMENSION_NAMES[dim]:25s} | ev={np.median(ev_vals):.3f} org={np.median(org_vals):.3f} | p={p:.4f} d={d:.3f} {sig}")

    return results


# ── Main ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Process only 10 contributors")
    args = parser.parse_args()

    t0 = time.time()
    print("=" * 60)
    print("CONTRIBUTOR ACTIVITY PROFILES & PERSONAS")
    print("=" * 60)

    # Load data
    print("\n[1/6] Loading data...")
    with open(JOURNEY_PATH) as f:
        journeys = json.load(f)
    n_ev = len(journeys.get("event_journeys", []))
    n_org = len(journeys.get("organic_journeys", []))
    print(f"  Journeys: {n_ev} event + {n_org} organic = {n_ev + n_org}")

    with open(CI_PATH) as f:
        ci_data = json.load(f)
    print(f"  CI timeseries: {len(ci_data.get('event', []))} event + {len(ci_data.get('organic', []))} organic")

    # Compute profiles
    print("\n[2/6] Computing activity profiles...")
    profiles = compute_profiles(journeys, ci_data)
    print(f"  Profiles computed: {len(profiles)}")

    if args.test:
        profiles = profiles[:10]
        print(f"  TEST MODE: using {len(profiles)} profiles")

    # Sample
    for p in profiles[:3]:
        print(f"    {p['username']:20s} | {p['contributor_type']:8s} | dims={[f'{d:.2f}' for d in p['raw_dims']]}")

    # Normalize
    print("\n[3/6] Percentile rank normalization...")
    pct_matrix = percentile_rank_normalize(profiles)
    print(f"  Shape: {pct_matrix.shape}")

    # Cluster into personas
    print("\n[4/6] Clustering into personas...")
    labels, centroids, best_k, sil = cluster_personas(pct_matrix)

    # Name personas
    persona_names = {}
    for cl, centroid in centroids.items():
        name = name_persona(centroid)
        persona_names[cl] = name
        dims_str = ", ".join(f"{DIMENSION_NAMES[i]}={centroid[i]:.2f}" for i in range(N_DIMS))
        print(f"    Persona {cl} ({name}): {dims_str}")

    # Assign persona labels
    for i, p in enumerate(profiles):
        p["persona"] = int(labels[i])
        p["persona_name"] = persona_names[int(labels[i])]

    # Persona distribution
    print(f"\n  Persona distribution:")
    from collections import Counter
    persona_counts = Counter(p["persona"] for p in profiles)
    for cl in sorted(persona_counts):
        name = persona_names[cl]
        n = persona_counts[cl]
        ev_n = sum(1 for p in profiles if p["persona"] == cl and p["contributor_type"] == "event")
        org_n = sum(1 for p in profiles if p["persona"] == cl and p["contributor_type"] == "organic")
        print(f"    {name:30s} | total={n:5d} | event={ev_n:5d} | organic={org_n:5d}")

    # Spider plots
    print("\n[5/6] Generating spider/radar plots...")

    # Plot 1: Persona centroids
    persona_groups = {persona_names[cl]: centroids[cl] for cl in centroids}
    create_radar_plot(persona_groups, "Contributor Personas", "persona_centroids.png")

    # Plot 2: Event vs Organic
    event_profiles = [p for p in profiles if p["contributor_type"] == "event"]
    organic_profiles = [p for p in profiles if p["contributor_type"] == "organic"]
    if event_profiles and organic_profiles:
        ev_mean = np.mean([p["percentile_dims"] for p in event_profiles], axis=0).tolist()
        org_mean = np.mean([p["percentile_dims"] for p in organic_profiles], axis=0).tolist()
        create_radar_plot(
            {"Event": ev_mean, "Organic": org_mean},
            "Event vs Organic Activity Profiles",
            "event_vs_organic.png",
        )

    # Plot 3: By event type (mentorship vs non-mentorship vs organic)
    mentorship_events = {"gsoc", "lfx"}
    non_mentorship_events = {"hacktoberfest", "24pullrequests"}
    ment_profiles = [p for p in profiles if p["event_type"] in mentorship_events]
    non_ment_profiles = [p for p in profiles if p["event_type"] in non_mentorship_events]
    if ment_profiles and non_ment_profiles and organic_profiles:
        ment_mean = np.mean([p["percentile_dims"] for p in ment_profiles], axis=0).tolist()
        non_ment_mean = np.mean([p["percentile_dims"] for p in non_ment_profiles], axis=0).tolist()
        org_mean = np.mean([p["percentile_dims"] for p in organic_profiles], axis=0).tolist()
        create_radar_plot(
            {"Mentorship": ment_mean, "Non-Mentorship": non_ment_mean, "Organic": org_mean},
            "Mentorship vs Non-Mentorship vs Organic",
            "mentorship_comparison.png",
        )

    # Plot 4: Core vs Non-core
    import csv
    core_set = set()
    if os.path.exists(CORE_PATH):
        with open(CORE_PATH) as f:
            for r in csv.DictReader(f):
                if r["ever_core"] == "True":
                    core_set.add(r["contributor_id"])

    core_profiles = [p for p in profiles if p["contributor_id"] in core_set or p["contributor_id"].rstrip("__organic") in core_set]
    noncore_profiles = [p for p in profiles if p not in core_profiles]

    if core_profiles and noncore_profiles:
        core_mean = np.mean([p["percentile_dims"] for p in core_profiles], axis=0).tolist()
        noncore_mean = np.mean([p["percentile_dims"] for p in noncore_profiles], axis=0).tolist()
        create_radar_plot(
            {"Core Contributors": core_mean, "Non-Core": noncore_mean},
            "Core vs Non-Core Activity Profiles",
            "core_vs_noncore.png",
        )

    # Plot 5: By specific event type
    event_type_groups = {}
    for etype in ["gsoc", "lfx", "hacktoberfest", "24pullrequests", "organic"]:
        ep = [p for p in profiles if p["event_type"] == etype]
        if ep:
            label = etype.upper() if etype in ("gsoc", "lfx") else etype.title()
            event_type_groups[label] = np.mean([p["percentile_dims"] for p in ep], axis=0).tolist()
    if len(event_type_groups) >= 2:
        create_radar_plot(event_type_groups, "Activity Profiles by Event Type", "by_event_type.png")

    # Statistical tests
    print("\n[6/6] Statistical tests...")
    dim_tests = run_dimension_tests(profiles)

    # Chi-squared on persona distribution
    from scipy.stats import chi2_contingency
    persona_dist = {}
    for cl in sorted(persona_counts):
        ev_n = sum(1 for p in profiles if p["persona"] == cl and p["contributor_type"] == "event")
        org_n = sum(1 for p in profiles if p["persona"] == cl and p["contributor_type"] == "organic")
        persona_dist[persona_names[cl]] = {"event": ev_n, "organic": org_n}

    if len(persona_dist) >= 2:
        table = [[v["event"], v["organic"]] for v in persona_dist.values()]
        chi2, p_chi, dof, expected = chi2_contingency(table)
        print(f"\n  Chi-squared (persona x event/organic): chi2={chi2:.2f}, p={p_chi:.4f}, dof={dof}")

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

    # Save profiles (without raw matrix, just the per-contributor data)
    profiles_output = []
    for p in profiles:
        profiles_output.append({
            "contributor_id": p["contributor_id"],
            "username": p["username"],
            "repo": p["repo"],
            "contributor_type": p["contributor_type"],
            "event_type": p["event_type"],
            "raw_dims": p["raw_dims"],
            "percentile_dims": p["percentile_dims"],
            "persona": p["persona"],
            "persona_name": p["persona_name"],
            "raw_counts": p["raw_counts"],
        })

    with open(OUTPUT_PROFILES, "w") as f:
        json.dump(profiles_output, f, indent=2, cls=NumpyEncoder)
    print(f"\n  Saved profiles: {OUTPUT_PROFILES}")

    # Save persona results
    persona_output = {
        "config": {
            "n_contributors": len(profiles),
            "n_dimensions": N_DIMS,
            "dimension_names": DIMENSION_NAMES,
            "best_k": best_k,
            "silhouette": sil,
        },
        "personas": {
            persona_names[cl]: {
                "centroid": centroids[cl],
                "n": persona_counts[cl],
                "event_n": sum(1 for p in profiles if p["persona"] == cl and p["contributor_type"] == "event"),
                "organic_n": sum(1 for p in profiles if p["persona"] == cl and p["contributor_type"] == "organic"),
            }
            for cl in centroids
        },
        "persona_distribution": persona_dist,
        "dimension_tests": dim_tests,
        "chi_squared": {"chi2": chi2, "p_value": p_chi, "dof": dof} if len(persona_dist) >= 2 else None,
    }

    with open(OUTPUT_PERSONAS, "w") as f:
        json.dump(persona_output, f, indent=2, cls=NumpyEncoder)
    print(f"  Saved persona results: {OUTPUT_PERSONAS}")

    elapsed = time.time() - t0
    print(f"\n  Total time: {elapsed:.1f}s")
    print("=" * 60)
    print("DONE!")


if __name__ == "__main__":
    main()
