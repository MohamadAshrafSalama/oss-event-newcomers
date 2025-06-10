#!/usr/bin/env python3
"""
Phase 7b: Clustering of Contribution Index Time Series.

Strategy (laptop-friendly, 16 GB RAM):
  1. All time series are already interpolated to a fixed 52-week length
     with min-max scaling per contributor  →  perfectly aligned arrays.
  2. Primary method: Euclidean K-Means (scikit-learn) – fast, <1 min.
  3. Secondary validation: k-Shape (tslearn) – shape-aware cross-correlation,
     still fast (~2-5 min), no DTW needed.
  4. Optimal k via silhouette score + elbow method.
  5. Compare cluster distributions between event and organic groups.

Usage:
  python3 scripts/71_dtw_clustering.py              # full run
  python3 scripts/71_dtw_clustering.py --limit 200  # quick test
  python3 scripts/71_dtw_clustering.py --method kshape  # use k-Shape instead
"""

import json
import os
import sys
import argparse
import time
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CI_DIR = os.path.join(BASE, "08_analysis_results", "ci_timeseries")
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")
FIXED_LENGTH = 52  # 52 weeks = 1 year
SEED = 42

os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_all_timeseries(limit=0):
    """Load all CI time series from the index file."""
    index_path = os.path.join(CI_DIR, "ci_timeseries_index.json")
    with open(index_path) as f:
        index_data = json.load(f)

    entries = index_data["entries"]
    if limit > 0:
        entries = entries[:limit]

    print(f"Loading {len(entries)} time series...")

    data = []
    skipped = 0

    for entry in entries:
        fpath = os.path.join(CI_DIR, entry["file"])
        if not os.path.exists(fpath):
            skipped += 1
            continue
        try:
            with open(fpath) as f:
                ci_data = json.load(f)
        except Exception:
            skipped += 1
            continue

        commit_ci = ci_data.get("commit_ci", [])
        if not commit_ci or len(commit_ci) < 1:
            skipped += 1
            continue

        data.append({
            "contribution_id": entry["contribution_id"],
            "contributor_type": entry["contributor_type"],
            "event_type": entry["event_type"],
            "is_mentorship": entry["is_mentorship"],
            "repo": entry["repo"],
            "n_weeks": len(commit_ci),
            "total_commits": ci_data.get("total_commits", 0),
            "commit_ci": commit_ci,
        })

    print(f"  Loaded: {len(data)}, Skipped: {skipped}")
    return data


def normalize_to_fixed_length(series_list, target_length=52):
    """Interpolate all time series to target_length and min-max scale per series.
    Every output series is guaranteed to be in [0, 1]."""
    normalized = []

    for ts in series_list:
        arr = np.array(ts, dtype=float)

        if len(arr) == 0:
            normalized.append(np.zeros(target_length))
            continue

        # Linear interpolation to target_length (handles len=1 fine -- constant)
        x_old = np.linspace(0, 1, max(len(arr), 2))
        if len(arr) == 1:
            arr = np.array([arr[0], arr[0]])  # duplicate for interp
        x_new = np.linspace(0, 1, target_length)
        interpolated = np.interp(x_new, x_old, arr)

        # Min-max scaling per contributor → [0, 1]
        val_min = interpolated.min()
        val_max = interpolated.max()
        if val_max > val_min:
            interpolated = (interpolated - val_min) / (val_max - val_min)
        else:
            # Constant series → flat at 0 (no activity variation)
            interpolated = np.zeros(target_length)

        normalized.append(interpolated)

    return np.array(normalized)


def name_cluster(centroid):
    """Name a cluster based on its centroid shape."""
    n = len(centroid)
    q1 = centroid[:n // 4].mean()
    q2 = centroid[n // 4:n // 2].mean()
    q3 = centroid[n // 2:3 * n // 4].mean()
    q4 = centroid[3 * n // 4:].mean()
    overall = centroid.mean()
    peak_idx = int(np.argmax(centroid))
    peak_pos = peak_idx / n  # 0=start, 1=end

    if overall < 0.15:
        return "Low/Inactive"
    elif q1 > max(q3, q4) * 1.5 and q1 > 0.3:
        return "Early Spike"
    elif q4 > max(q1, q2) * 1.5 and q4 > 0.3:
        return "Late Riser"
    elif q2 > q1 * 1.3 and q2 > q4 * 1.3 and q2 > 0.3:
        return "Mid Peak"
    elif q1 > 0.3 and q4 < q1 * 0.5:
        return "Early then Decline"
    elif abs(q1 - q4) < 0.15 and overall > 0.35:
        return "Sustained High"
    elif abs(q1 - q4) < 0.12 and 0.15 <= overall <= 0.35:
        return "Steady Low"
    elif peak_pos < 0.3:
        return "Front-loaded"
    elif peak_pos > 0.7:
        return "Back-loaded"
    elif overall < 0.3:
        return "Low/Gradual"
    else:
        return "Moderate/Mixed"


def run_euclidean_kmeans(X, k_range, seed=42):
    """Run K-Means with Euclidean distance for each k. Returns models, labels, metrics."""
    results = {}
    for k in k_range:
        t0 = time.time()
        model = KMeans(n_clusters=k, n_init=10, max_iter=300, random_state=seed)
        labels = model.fit_predict(X)
        inertia = model.inertia_

        sil = silhouette_score(X, labels) if len(set(labels)) > 1 else -1.0
        elapsed = time.time() - t0

        results[k] = {
            "model": model,
            "labels": labels,
            "inertia": inertia,
            "silhouette": sil,
            "elapsed": elapsed,
        }
        print(f"    k={k}: inertia={inertia:.2f}, silhouette={sil:.4f} ({elapsed:.1f}s)")

    return results


def run_kshape(X, k_range, seed=42):
    """Run k-Shape clustering (shape-based, cross-correlation). Optional validation."""
    from tslearn.clustering import KShape
    from tslearn.utils import to_time_series_dataset

    X_ts = to_time_series_dataset(X)
    results = {}

    for k in k_range:
        t0 = time.time()
        model = KShape(n_clusters=k, n_init=3, max_iter=50, random_state=seed, verbose=0)
        labels = model.fit_predict(X_ts)
        elapsed = time.time() - t0

        sil = silhouette_score(X, labels) if len(set(labels)) > 1 else -1.0

        results[k] = {
            "model": model,
            "labels": labels,
            "inertia": float(model.inertia_),
            "silhouette": sil,
            "elapsed": elapsed,
        }
        print(f"    k={k}: inertia={model.inertia_:.2f}, silhouette={sil:.4f} ({elapsed:.1f}s)")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit number of time series (0=all)")
    parser.add_argument("--max-k", type=int, default=10,
                        help="Maximum k to try")
    parser.add_argument("--min-k", type=int, default=2,
                        help="Minimum k to try")
    parser.add_argument("--method", choices=["kmeans", "kshape", "both"],
                        default="both",
                        help="Clustering method: kmeans, kshape, or both")
    args = parser.parse_args()

    print("=" * 70)
    print("PHASE 7b: Time Series Clustering (Euclidean K-Means + k-Shape)")
    print("=" * 70)

    start_time = time.time()

    # ---- Step 1: Load data ----
    all_data = load_all_timeseries(limit=args.limit)

    if len(all_data) < 20:
        print("ERROR: Too few time series. Need at least 20.")
        sys.exit(1)

    raw_series = [d["commit_ci"] for d in all_data]
    lengths = [len(s) for s in raw_series]
    print(f"\n  Raw lengths: min={min(lengths)}, max={max(lengths)}, "
          f"median={int(np.median(lengths))}, mean={np.mean(lengths):.0f}")

    # ---- Step 2: Normalize to fixed-length ----
    print(f"\nInterpolating to {FIXED_LENGTH} weeks + min-max scaling...")
    X = normalize_to_fixed_length(raw_series, FIXED_LENGTH)
    print(f"  Shape: {X.shape}  ({X.nbytes / 1024:.0f} KB in memory)")

    # Filter out flat-zero series (constant all-zero = contributors with no activity
    # variation). These are always a single blob and hide real patterns.
    row_variance = X.var(axis=1)
    active_mask = row_variance > 1e-6  # keep series with any variation
    n_flat = (~active_mask).sum()
    X_active = X[active_mask]
    active_indices = np.where(active_mask)[0]
    flat_indices = np.where(~active_mask)[0]

    print(f"  Active (non-flat) series: {len(X_active)}  |  Flat/constant: {n_flat}")

    if len(X_active) < 20:
        print("  WARNING: Very few active series. Using all data including flat ones.")
        X_active = X
        active_indices = np.arange(len(X))
        flat_indices = np.array([], dtype=int)

    k_range = list(range(args.min_k, args.max_k + 1))

    # ---- Step 3: Euclidean K-Means ----
    kmeans_results = None
    if args.method in ("kmeans", "both"):
        print(f"\n--- Euclidean K-Means (k={args.min_k}..{args.max_k}) ---")
        kmeans_results = run_euclidean_kmeans(X_active, k_range, seed=SEED)

    # ---- Step 4: k-Shape (optional) ----
    kshape_results = None
    if args.method in ("kshape", "both"):
        print(f"\n--- k-Shape (k={args.min_k}..{args.max_k}) ---")
        kshape_results = run_kshape(X_active, k_range, seed=SEED)

    # ---- Step 5: Pick best k using elbow heuristic ----
    # Pure silhouette often picks k=2. Instead, find the elbow (biggest
    # second-derivative of inertia), but fall back to silhouette if unclear.
    best_method = "kmeans"
    primary = kmeans_results if kmeans_results else kshape_results

    inertias_arr = np.array([primary[k]["inertia"] for k in k_range])
    sil_arr = np.array([primary[k]["silhouette"] for k in k_range])

    # Elbow detection: find k where the rate of decrease slows the most
    if len(k_range) >= 4:
        diffs = -np.diff(inertias_arr)            # positive drops
        diffs2 = np.diff(diffs)                    # how much the drop slows
        # Elbow = k where the drop slows most (largest positive second derivative)
        elbow_idx = int(np.argmax(diffs2)) + 2     # +2 because of double diff offset
        elbow_k = k_range[elbow_idx] if elbow_idx < len(k_range) else k_range[-1]
    else:
        elbow_k = k_range[int(np.argmax(sil_arr))]

    # Among k >= 3 (skip trivial k=2 unless it's the only option), pick
    # the one with the best silhouette
    candidate_ks = [k for k in k_range if k >= 3]
    if not candidate_ks:
        candidate_ks = k_range

    best_k = max(candidate_ks, key=lambda k: primary[k]["silhouette"])
    best_sil = primary[best_k]["silhouette"]

    # If the elbow k has a similar silhouette (within 0.05), prefer the elbow
    if elbow_k in [k for k in k_range] and elbow_k >= 3:
        elbow_sil = primary[elbow_k]["silhouette"]
        if elbow_sil > best_sil - 0.05:
            best_k = elbow_k
            best_sil = elbow_sil

    if kmeans_results:
        best_method = "kmeans"
    else:
        best_method = "kshape"

    # Check if k-Shape beats KMeans at the chosen k
    if kshape_results and best_k in kshape_results:
        if kshape_results[best_k]["silhouette"] > best_sil:
            best_method = "kshape"
            best_sil = kshape_results[best_k]["silhouette"]

    print(f"\n  Elbow at k={elbow_k}")
    print(f"  BEST: method={best_method}, k={best_k}, silhouette={best_sil:.4f}")

    # Get the final labels and centroids for active series
    if best_method == "kmeans":
        chosen_results = kmeans_results
    else:
        chosen_results = kshape_results

    chosen = chosen_results[best_k]
    active_labels = chosen["labels"]

    if best_method == "kmeans":
        centroids = chosen["model"].cluster_centers_  # shape (k, 52)
    else:
        centroids = chosen["model"].cluster_centers_.squeeze()  # shape (k, 52)

    # Build full label array: active series get their cluster,
    # flat series get an extra "Low/Inactive" cluster
    flat_cluster_id = best_k  # one extra cluster
    total_k = best_k + (1 if len(flat_indices) > 0 else 0)

    final_labels = np.full(len(all_data), -1, dtype=int)
    for i, orig_idx in enumerate(active_indices):
        final_labels[orig_idx] = int(active_labels[i])
    for orig_idx in flat_indices:
        final_labels[orig_idx] = flat_cluster_id

    # Add a flat centroid (zeros)
    if len(flat_indices) > 0:
        flat_centroid = np.zeros((1, FIXED_LENGTH))
        centroids = np.vstack([centroids.reshape(best_k, -1), flat_centroid])
        best_k = total_k  # now includes the flat cluster

    # ---- Step 6: Plot elbow + silhouette for primary method ----
    primary_name = "K-Means" if kmeans_results else "k-Shape"

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    inertias_plot = inertias_arr.tolist()
    sil_plot = sil_arr.tolist()

    ax1.plot(k_range, inertias_plot, "bo-", linewidth=2, markersize=8)
    # Mark the chosen k (subtract flat cluster if present)
    chosen_k_plot = best_k - (1 if len(flat_indices) > 0 else 0)
    ax1.axvline(x=chosen_k_plot, color="red", linestyle="--", alpha=0.6,
                label=f"Chosen k={chosen_k_plot} (+1 flat)")
    ax1.set_xlabel("Number of Clusters (k)", fontsize=12)
    ax1.set_ylabel("Inertia", fontsize=12)
    ax1.set_title(f"Elbow Method ({primary_name})", fontsize=13)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.plot(k_range, sil_plot, "ro-", linewidth=2, markersize=8)
    ax2.axvline(x=chosen_k_plot, color="red", linestyle="--", alpha=0.6,
                label=f"Chosen k={chosen_k_plot} (+1 flat)")
    ax2.set_xlabel("Number of Clusters (k)", fontsize=12)
    ax2.set_ylabel("Silhouette Score", fontsize=12)
    ax2.set_title(f"Silhouette Score ({primary_name})", fontsize=13)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "dtw_elbow_silhouette.png"),
                dpi=150, bbox_inches="tight")
    print(f"\n  Saved: dtw_elbow_silhouette.png")

    # If we ran both methods, also plot a comparison
    if kmeans_results and kshape_results:
        fig2, ax = plt.subplots(figsize=(8, 5))
        km_sil = [kmeans_results[k]["silhouette"] for k in k_range]
        ks_sil = [kshape_results[k]["silhouette"] for k in k_range]
        ax.plot(k_range, km_sil, "bo-", label="K-Means (Euclidean)", linewidth=2)
        ax.plot(k_range, ks_sil, "rs-", label="k-Shape (SBD)", linewidth=2)
        ax.set_xlabel("k")
        ax.set_ylabel("Silhouette Score")
        ax.set_title("K-Means vs k-Shape: Silhouette Comparison")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        fig2.savefig(os.path.join(OUTPUT_DIR, "clustering_method_comparison.png"),
                     dpi=150, bbox_inches="tight")
        print(f"  Saved: clustering_method_comparison.png")

    # ---- Step 7: Name clusters, analyze ----
    print(f"\n{'='*60}")
    print(f"CLUSTER ANALYSIS (method={best_method}, k={best_k})")
    print(f"{'='*60}")

    cluster_names = {}
    cluster_sizes = defaultdict(int)
    for label in final_labels:
        cluster_sizes[int(label)] += 1

    for ci in range(best_k):
        centroid = centroids[ci].flatten()
        name = name_cluster(centroid)
        cluster_names[ci] = name
        print(f"  Cluster {ci}: {name} (n={cluster_sizes[ci]}, "
              f"centroid: mean={centroid.mean():.3f}, "
              f"peak@week{int(np.argmax(centroid))})")

    # ---- Step 8: Plot centroids ----
    n_cols = min(best_k, 4)
    n_rows = (best_k + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows),
                              sharey=True, squeeze=False)

    for ci in range(best_k):
        row, col = divmod(ci, n_cols)
        ax = axes[row][col]
        centroid = centroids[ci].flatten()
        ax.plot(centroid, linewidth=2.5, color="red", zorder=10)

        # Plot up to 30 sample members
        members = np.where(final_labels == ci)[0]
        for idx in members[:30]:
            ax.plot(X[idx], alpha=0.1, color="steelblue")

        ax.set_title(f"C{ci}: {cluster_names[ci]}\n(n={cluster_sizes[ci]})",
                      fontsize=11)
        ax.set_xlabel("Week")
        if col == 0:
            ax.set_ylabel("Norm. CI")
        ax.set_ylim(-0.05, 1.05)
        ax.grid(True, alpha=0.2)

    # Hide unused axes
    for ci in range(best_k, n_rows * n_cols):
        row, col = divmod(ci, n_cols)
        axes[row][col].set_visible(False)

    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "dtw_cluster_centroids.png"),
                dpi=150, bbox_inches="tight")
    print(f"  Saved: dtw_cluster_centroids.png")

    # ---- Step 9: Distribution table ----
    print(f"\n{'-'*60}")
    print("CLUSTER DISTRIBUTION: Event vs Organic")
    print(f"{'-'*60}")

    assignments = []
    for i, d in enumerate(all_data):
        label = int(final_labels[i])
        assignments.append({
            "contribution_id": d["contribution_id"],
            "contributor_type": d["contributor_type"],
            "event_type": d["event_type"],
            "is_mentorship": d["is_mentorship"],
            "repo": d["repo"],
            "cluster": label,
            "cluster_name": cluster_names[label],
            "n_weeks_original": d["n_weeks"],
            "total_commits": d["total_commits"],
        })

    adf = pd.DataFrame(assignments)
    n_event_total = len(adf[adf["contributor_type"] == "event"])
    n_organic_total = len(adf[adf["contributor_type"] == "organic"])

    dist_data = []
    for ci in range(best_k):
        row = {"cluster": ci, "cluster_name": cluster_names[ci]}
        cl = adf[adf["cluster"] == ci]
        row["total"] = len(cl)
        row["event"] = len(cl[cl["contributor_type"] == "event"])
        row["organic"] = len(cl[cl["contributor_type"] == "organic"])
        row["event_pct"] = round(row["event"] / max(1, n_event_total) * 100, 2)
        row["organic_pct"] = round(row["organic"] / max(1, n_organic_total) * 100, 2)
        row["mentorship"] = len(cl[(cl["contributor_type"] == "event") &
                                    (cl["is_mentorship"] == True)])
        row["non_mentorship"] = len(cl[(cl["contributor_type"] == "event") &
                                        (cl["is_mentorship"] == False)])
        for et in ["gsoc", "lfx", "24pr", "hacktoberfest"]:
            row[et] = len(cl[(cl["contributor_type"] == "event") &
                              (cl["event_type"] == et)])
        dist_data.append(row)

    dist_df = pd.DataFrame(dist_data)

    header = (f"{'Cluster':<22} {'N':>5} {'Ev':>5} {'Org':>5} "
              f"{'Ev%':>6} {'Org%':>6} {'GSoC':>5} {'LFX':>4} {'24PR':>5} {'HF':>4}")
    print(f"\n{header}")
    print("-" * len(header))
    for _, r in dist_df.iterrows():
        print(f"{r['cluster_name']:<22} {r['total']:>5} {r['event']:>5} {r['organic']:>5} "
              f"{r['event_pct']:>6.1f} {r['organic_pct']:>6.1f} "
              f"{r['gsoc']:>5} {r['lfx']:>4} {r['24pr']:>5} {r.get('hacktoberfest', 0):>4}")

    # ---- Step 10: Chi-squared tests ----
    print(f"\n{'-'*60}")
    print("STATISTICAL TESTS ON CLUSTER DISTRIBUTIONS")
    print(f"{'-'*60}")

    event_counts = dist_df["event"].values
    organic_counts = dist_df["organic"].values
    contingency = np.array([event_counts, organic_counts])

    # Remove zero-sum columns
    col_sums = contingency.sum(axis=0)
    contingency_clean = contingency[:, col_sums > 0]

    if contingency_clean.shape[1] >= 2:
        chi2, p_chi2, dof, _ = stats.chi2_contingency(contingency_clean)
        print(f"\n  Event vs Organic: chi2={chi2:.4f}, df={dof}, p={p_chi2:.6e}")
        print(f"    {'*** Significant ***' if p_chi2 < 0.05 else 'Not significant'}")
    else:
        chi2, p_chi2, dof = 0.0, 1.0, 0
        print("\n  Cannot run chi-squared (insufficient cluster diversity)")

    # Mentorship vs Non-mentorship
    mentor_counts = dist_df["mentorship"].values
    non_mentor_counts = dist_df["non_mentorship"].values
    cont2 = np.array([mentor_counts, non_mentor_counts])
    col_sums2 = cont2.sum(axis=0)
    cont2_clean = cont2[:, col_sums2 > 0]

    chi2_m, p_m, dof_m = None, None, None
    if cont2_clean.shape[1] >= 2 and cont2_clean.sum(axis=1).min() > 0:
        chi2_m, p_m, dof_m, _ = stats.chi2_contingency(cont2_clean)
        print(f"\n  Mentorship vs Non-Mentorship: chi2={chi2_m:.4f}, df={dof_m}, p={p_m:.6e}")
        print(f"    {'*** Significant ***' if p_m < 0.05 else 'Not significant'}")

    # ---- Step 11: Distribution visualisation ----
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Bar: Event vs Organic
    x_pos = np.arange(best_k)
    width = 0.35
    ax = axes[0]
    ax.bar(x_pos - width / 2, event_counts, width, label="Event", color="#2196F3")
    ax.bar(x_pos + width / 2, organic_counts, width, label="Organic", color="#FF9800")
    ax.set_xticks(x_pos)
    ax.set_xticklabels([cluster_names[i] for i in range(best_k)],
                        rotation=30, ha="right", fontsize=9)
    ax.set_ylabel("Count")
    ax.set_title("Cluster Distribution: Event vs Organic")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    # Stacked: event types within clusters
    ax = axes[1]
    event_only = adf[adf["contributor_type"] == "event"]
    if len(event_only) > 0:
        cross = event_only.groupby(["cluster", "event_type"]).size().unstack(fill_value=0)
        cross_pct = cross.div(cross.sum(axis=1), axis=0) * 100
        colors = {"gsoc": "#4CAF50", "lfx": "#2196F3", "24pr": "#FF9800", "hf": "#F44336"}
        cross_pct.plot(kind="bar", stacked=True, ax=ax,
                       color=[colors.get(c, "#999") for c in cross_pct.columns])
        ax.set_xticklabels([cluster_names[i] for i in cross_pct.index],
                            rotation=30, ha="right", fontsize=9)
    ax.set_ylabel("Percentage")
    ax.set_title("Event Type Mix per Cluster (%)")
    ax.legend(title="Event")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "dtw_cluster_distribution.png"),
                dpi=150, bbox_inches="tight")
    print(f"\n  Saved: dtw_cluster_distribution.png")

    dist_df.to_csv(os.path.join(OUTPUT_DIR, "dtw_cluster_distribution.csv"), index=False)
    print(f"  Saved: dtw_cluster_distribution.csv")

    # ---- Step 12: Save full results JSON ----
    # Collect both methods' metrics for the report
    method_metrics = {}
    if kmeans_results:
        method_metrics["kmeans"] = {
            str(k): {"inertia": float(r["inertia"]),
                     "silhouette": float(r["silhouette"]),
                     "elapsed_s": round(r["elapsed"], 2)}
            for k, r in kmeans_results.items()
        }
    if kshape_results:
        method_metrics["kshape"] = {
            str(k): {"inertia": float(r["inertia"]),
                     "silhouette": float(r["silhouette"]),
                     "elapsed_s": round(r["elapsed"], 2)}
            for k, r in kshape_results.items()
        }

    results = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "n_contributors": len(all_data),
        "fixed_length_weeks": FIXED_LENGTH,
        "clustering_method": best_method,
        "methods_tested": list(method_metrics.keys()),
        "method_metrics": method_metrics,
        "k_range_tested": k_range,
        "inertias": [float(primary[k]["inertia"]) for k in k_range],
        "silhouette_scores": [float(primary[k]["silhouette"]) for k in k_range],
        "best_k": best_k,
        "best_silhouette": float(best_sil),
        "clusters": {},
        "chi_squared_event_vs_organic": {
            "chi2": float(chi2),
            "dof": int(dof),
            "p_value": float(p_chi2),
            "significant": bool(p_chi2 < 0.05),
        },
        "chi_squared_mentorship_vs_non": {
            "chi2": float(chi2_m) if chi2_m is not None else None,
            "dof": int(dof_m) if dof_m is not None else None,
            "p_value": float(p_m) if p_m is not None else None,
            "significant": bool(p_m < 0.05) if p_m is not None else None,
        },
        "assignments": assignments,
    }

    for ci in range(best_k):
        centroid = centroids[ci].flatten().tolist()
        results["clusters"][str(ci)] = {
            "name": cluster_names[ci],
            "size": int(cluster_sizes[ci]),
            "centroid": centroid,
        }

    with open(os.path.join(OUTPUT_DIR, "dtw_clusters.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Saved: dtw_clusters.json")

    elapsed = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"PHASE 7b COMPLETE ({elapsed:.0f}s / {elapsed / 60:.1f} min)")
    print(f"  Method: {best_method}")
    print(f"  Best k: {best_k}  (silhouette={best_sil:.4f})")
    print(f"  Chi-sq event vs organic: p={p_chi2:.4e}")
    if chi2_m is not None:
        print(f"  Chi-sq mentorship vs non: p={p_m:.4e}")
    print(f"  Peak RAM: ~{X.nbytes * 3 / 1024**2:.0f} MB (well within 16 GB)")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
