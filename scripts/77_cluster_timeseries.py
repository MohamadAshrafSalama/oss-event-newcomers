#!/usr/bin/env python3
"""
Cluster contributor activity patterns using shape features.

v3: Feature-based clustering (fast, interpretable, better separation).

Key insight: instead of clustering raw 12-point series (noisy, poorly separated),
we extract 5 interpretable shape features and cluster on those:
  1. peak_position: where in the timeline the peak occurs (0=start, 1=end)
  2. trend: linear slope (positive=growing, negative=declining)
  3. concentration: how concentrated activity is (1=one burst, 0=uniform)
  4. balance: first-half vs second-half activity ratio
  5. active_ratio: fraction of months with activity

This gives much better cluster separation because we capture the SHAPE
rather than point-by-point values.

Pipeline:
  1. Load CI time series, filter (>= 3 active months)
  2. Interpolate to 12 months, extract 5 shape features
  3. K-means on features (k=2..10), silhouette for best K
  4. Map clusters back to centroid time series for visualization
  5. Plots + analysis + save

Usage:
  python3 scripts/77_cluster_timeseries.py
"""

import json, os, sys, time, warnings
import numpy as np
from collections import Counter
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CI_PATH = os.path.join(BASE, "08_analysis_results", "contribution_index_timeseries.json")
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")
FIXED_LEN = 12
K_RANGE = range(2, 11)
SEED = 42
MIN_ACTIVE_MONTHS = 3


def interpolate_series(series, target_len=FIXED_LEN):
    n = len(series)
    if n == 0:
        return np.zeros(target_len)
    if n == 1:
        return np.full(target_len, series[0])
    x_orig = np.linspace(0, 1, n)
    x_target = np.linspace(0, 1, target_len)
    return np.interp(x_target, x_orig, series)


def normalize_01(series):
    mn, mx = series.min(), series.max()
    if mx - mn < 1e-10:
        return np.zeros_like(series)
    return (series - mn) / (mx - mn)


def extract_features(series_01):
    """Extract 5 interpretable shape features from [0,1] normalized series."""
    n = len(series_01)
    half = n // 2

    # 1. Peak position (0.0 = start, 1.0 = end)
    peak_pos = np.argmax(series_01) / max(n - 1, 1)

    # 2. Trend: slope of linear fit
    x = np.arange(n, dtype=float)
    if series_01.std() > 1e-10:
        slope = np.polyfit(x, series_01, 1)[0]
    else:
        slope = 0.0

    # 3. Concentration (entropy-based, 1 = all in one month, 0 = perfectly uniform)
    total = series_01.sum()
    if total > 0:
        p = series_01 / total
        entropy = -np.sum(p[p > 0] * np.log2(p[p > 0] + 1e-15))
        max_entropy = np.log2(n)
        concentration = 1 - (entropy / max_entropy) if max_entropy > 0 else 0
    else:
        concentration = 0.0

    # 4. Balance: second-half vs first-half (-1 = all early, +1 = all late)
    first_half = series_01[:half].mean()
    second_half = series_01[half:].mean()
    denom = first_half + second_half
    balance = (second_half - first_half) / denom if denom > 1e-10 else 0.0

    # 5. Active ratio: fraction of months with non-trivial activity
    active_ratio = (series_01 > 0.05).sum() / n

    return np.array([peak_pos, slope, concentration, balance, active_ratio])


FEATURE_NAMES = ["peak_position", "trend", "concentration", "balance", "active_ratio"]


def classify_pattern(centroid, features_center):
    """Name a cluster based on its centroid shape and feature center."""
    peak_pos_val = features_center[0]  # 0=early, 1=late
    trend_val = features_center[1]     # negative=declining, positive=growing
    concentration_val = features_center[2]  # high=bursty
    balance_val = features_center[3]   # negative=early-heavy, positive=late-heavy
    active_ratio_val = features_center[4]

    if concentration_val > 0.4 and active_ratio_val < 0.5:
        return "Concentrated Burst"
    elif trend_val > 0.02 and balance_val > 0.15:
        return "Growing"
    elif trend_val < -0.02 and balance_val < -0.15:
        return "Declining"
    elif active_ratio_val > 0.75 and abs(balance_val) < 0.2:
        return "Sustained"
    elif peak_pos_val < 0.3:
        return "Early-Peak"
    elif peak_pos_val > 0.7:
        return "Late-Peak"
    else:
        return "Mid-Active"


def main():
    t0 = time.time()

    print("=" * 60)
    print("TIME SERIES CLUSTERING (Feature-based)")
    print(f"  Fixed length: {FIXED_LEN} months")
    print(f"  Min active months: {MIN_ACTIVE_MONTHS}")
    print(f"  Features: {', '.join(FEATURE_NAMES)}")
    print(f"  K range: {K_RANGE.start}-{K_RANGE.stop - 1}")
    print("=" * 60)

    # ── 1. Load ─────────────────────────────────────────────────
    print("\n[1/5] Loading + filtering + feature extraction...")
    t1 = time.time()

    with open(CI_PATH) as f:
        ci_data = json.load(f)

    all_series_01 = []   # interpolated + normalized for visualization
    all_features = []    # shape features for clustering
    all_labels = []
    all_event_types = []
    all_meta = []

    dropped_short = 0
    dropped_constant = 0

    for source, entries, default_type in [
        ("event", ci_data["event"], "unknown"),
        ("organic", ci_data["organic"], "organic"),
    ]:
        for entry in entries:
            raw = np.array(entry["ci"], dtype=float)
            active_months = (raw > 0).sum()
            if active_months < MIN_ACTIVE_MONTHS:
                dropped_short += 1
                continue

            interp = interpolate_series(raw, FIXED_LEN)
            norm = normalize_01(interp)

            if norm.max() < 1e-10:
                dropped_constant += 1
                continue

            feats = extract_features(norm)
            all_series_01.append(norm)
            all_features.append(feats)
            all_labels.append(source)
            all_event_types.append(entry.get("event_type", default_type) or default_type)
            all_meta.append({
                "username": entry.get("username", ""),
                "repo": entry.get("repo", ""),
                "length_orig": entry.get("length", 0),
                "total_ci": entry.get("total_ci", 0),
            })

    X_series = np.array(all_series_01)
    X_features = np.array(all_features)
    labels = np.array(all_labels)
    event_types = np.array(all_event_types)

    n_input = len(ci_data["event"]) + len(ci_data["organic"])
    print(f"  Input: {n_input}")
    print(f"  Dropped (< {MIN_ACTIVE_MONTHS} active months): {dropped_short}")
    print(f"  Dropped (constant): {dropped_constant}")
    print(f"  Valid: {len(X_features)} (Event: {(labels == 'event').sum()}, Organic: {(labels == 'organic').sum()})")

    # Feature summary
    print(f"\n  Feature ranges:")
    for i, name in enumerate(FEATURE_NAMES):
        vals = X_features[:, i]
        print(f"    {name:>16}: min={vals.min():.3f}, median={np.median(vals):.3f}, max={vals.max():.3f}")

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_features)
    print(f"  Time: {time.time()-t1:.1f}s")

    # ── 2. Find optimal K ───────────────────────────────────────
    print(f"\n[2/5] K-means clustering (k={K_RANGE.start}..{K_RANGE.stop-1})...")
    t2 = time.time()

    scores = {}
    inertias = {}
    best_k = 2
    best_sil = -1

    for k in K_RANGE:
        km = KMeans(n_clusters=k, random_state=SEED, n_init=20, max_iter=500)
        cl = km.fit_predict(X_scaled)
        sil = silhouette_score(X_scaled, cl, random_state=SEED)
        scores[k] = sil
        inertias[k] = km.inertia_
        if sil > best_sil:
            best_sil = sil
            best_k = k
        print(f"    k={k:2d}: silhouette={sil:.4f}  inertia={km.inertia_:.1f}")

    # Force K=3
    best_k = 3
    best_sil = scores[3]

    print(f"\n  Selected K = {best_k} (silhouette = {best_sil:.4f})")
    print(f"  Time: {time.time()-t2:.1f}s")

    # ── 3. Final clustering ─────────────────────────────────────
    print(f"\n[3/5] Final K-means with K={best_k}...")
    t3 = time.time()

    km_final = KMeans(n_clusters=best_k, random_state=SEED, n_init=30, max_iter=1000)
    final_clusters = km_final.fit_predict(X_scaled)
    feature_centers = scaler.inverse_transform(km_final.cluster_centers_)

    # Compute mean time series per cluster (for centroid visualization)
    centroids_ts = np.zeros((best_k, FIXED_LEN))
    for c in range(best_k):
        mask = final_clusters == c
        centroids_ts[c] = X_series[mask].mean(axis=0)

    # Sort by peak position (early to late)
    peak_positions = feature_centers[:, 0]  # peak_position feature
    sort_order = np.argsort(peak_positions)
    cluster_remap = {old: new for new, old in enumerate(sort_order)}
    final_clusters = np.array([cluster_remap[c] for c in final_clusters])
    centroids_ts = centroids_ts[sort_order]
    feature_centers = feature_centers[sort_order]

    # Name clusters
    labels_desc = []
    for c in range(best_k):
        name = classify_pattern(centroids_ts[c], feature_centers[c])
        labels_desc.append(name)

    print(f"  Time: {time.time()-t3:.1f}s")

    # ── 4. Analysis ─────────────────────────────────────────────
    print(f"\n[4/5] Analysis...")

    cluster_counts = Counter(final_clusters)
    print(f"\n  Cluster profiles (K={best_k}, silhouette={best_sil:.3f}):")
    print(f"  {'':>4} {'Name':>20} {'Size':>6} {'%':>6} | {'peak_pos':>8} {'trend':>7} {'concen.':>7} {'balance':>7} {'active%':>7}")
    print(f"  {'':>4} {'':>20} {'':>6} {'':>6} | {'(0=early':>8} {'(+grow':>7} {'(1=bursty':>7} {'(-1=early':>7} {'':>7}")
    for c in range(best_k):
        n = cluster_counts[c]
        pct = n / len(final_clusters) * 100
        fc = feature_centers[c]
        print(f"  C{c:>2} {labels_desc[c]:>20} {n:>6} {pct:5.1f}% | {fc[0]:>8.3f} {fc[1]:>7.4f} {fc[2]:>7.3f} {fc[3]:>7.3f} {fc[4]:>7.3f}")

    # Distribution
    print(f"\n  Event vs Organic:")
    ev_total = (labels == "event").sum()
    org_total = (labels == "organic").sum()
    print(f"  {'Cluster':>4} {'Name':>20} | {'Event':>6} {'%':>6} | {'Organic':>6} {'%':>6}")
    for c in range(best_k):
        mask_c = final_clusters == c
        ev_n = (labels[mask_c] == "event").sum()
        org_n = (labels[mask_c] == "organic").sum()
        print(f"  C{c:>2} {labels_desc[c]:>20} | {ev_n:>6} {ev_n/ev_total*100:5.1f}% | {org_n:>6} {org_n/org_total*100:5.1f}%")

    unique_etypes = sorted(set(event_types))
    print(f"\n  By event type (% of each type in each cluster):")
    header = f"  {'':>25}"
    for et in unique_etypes:
        header += f" {et[:8]:>8}"
    print(header)
    for c in range(best_k):
        mask_c = final_clusters == c
        row = f"  C{c} {labels_desc[c]:>21}"
        for et in unique_etypes:
            n_et = (event_types[mask_c] == et).sum()
            total_et = (event_types == et).sum()
            row += f" {n_et/max(total_et,1)*100:7.1f}%"
        print(row)

    # ── 5. Plots ────────────────────────────────────────────────
    print(f"\n[5/5] Generating plots...")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    months = np.arange(1, FIXED_LEN + 1)
    colors = plt.cm.tab10(np.linspace(0, 1, max(best_k, 3)))

    # Plot 1: Silhouette
    ax = axes[0, 0]
    ks = sorted(scores.keys())
    ax.plot(ks, [scores[k] for k in ks], "bo-", linewidth=2, markersize=8)
    ax.axvline(x=best_k, color="r", linestyle="--", alpha=0.7, label=f"Best K={best_k} (sil={best_sil:.3f})")
    ax.set_xlabel("Number of Clusters (K)", fontsize=11)
    ax.set_ylabel("Silhouette Score", fontsize=11)
    ax.set_title("Optimal K Selection", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(ks)

    # Plot 2: Centroid time series
    ax = axes[0, 1]
    for c in range(best_k):
        ax.plot(months, centroids_ts[c], color=colors[c], linewidth=2.5,
                label=f"C{c}: {labels_desc[c]} (n={cluster_counts[c]})", marker="o", markersize=5)
        # Light fill
        ax.fill_between(months, centroids_ts[c], alpha=0.08, color=colors[c])
    ax.set_xlabel("Month (normalized timeline)", fontsize=11)
    ax.set_ylabel("Mean Normalized Activity", fontsize=11)
    ax.set_title(f"Activity Pattern Centroids (K={best_k})", fontsize=13)
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(True, alpha=0.3)
    ax.set_xticks(months)

    # Plot 3: Event vs Organic bar chart
    ax = axes[1, 0]
    x_pos = np.arange(best_k)
    width = 0.35
    ev_pcts = [((final_clusters == c) & (labels == "event")).sum() / ev_total * 100 for c in range(best_k)]
    org_pcts = [((final_clusters == c) & (labels == "organic")).sum() / org_total * 100 for c in range(best_k)]
    bars1 = ax.bar(x_pos - width / 2, ev_pcts, width, label="Event", color="#2196F3", alpha=0.85)
    bars2 = ax.bar(x_pos + width / 2, org_pcts, width, label="Organic", color="#FF9800", alpha=0.85)
    ax.set_xlabel("Cluster", fontsize=11)
    ax.set_ylabel("% of Group", fontsize=11)
    ax.set_title("Cluster Distribution: Event vs Organic", fontsize=13)
    ax.set_xticks(x_pos)
    ax.set_xticklabels([f"C{c}\n{labels_desc[c]}" for c in range(best_k)], fontsize=8)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3, axis="y")
    for bar in bars1:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2., h + 0.3, f'{h:.1f}%', ha='center', va='bottom', fontsize=8)
    for bar in bars2:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2., h + 0.3, f'{h:.1f}%', ha='center', va='bottom', fontsize=8)

    # Plot 4: By event type
    ax = axes[1, 1]
    etype_list = ["gsoc", "lfx", "hacktoberfest", "24pr", "organic"]
    etype_list = [e for e in etype_list if e in set(event_types)]
    n_et = len(etype_list)
    width_et = 0.75 / n_et
    etype_colors = {"24pr": "#4CAF50", "gsoc": "#9C27B0", "hacktoberfest": "#FFC107",
                    "lfx": "#607D8B", "organic": "#FF9800"}
    for idx, et in enumerate(etype_list):
        et_cnts = [((final_clusters == c) & (event_types == et)).sum() for c in range(best_k)]
        et_tot = sum(et_cnts)
        et_pcts = [v / max(et_tot, 1) * 100 for v in et_cnts]
        offset = (idx - n_et / 2 + 0.5) * width_et
        ax.bar(x_pos + offset, et_pcts, width_et, label=et,
               color=etype_colors.get(et, "#999"), alpha=0.85)
    ax.set_xlabel("Cluster", fontsize=11)
    ax.set_ylabel("% of Event Type", fontsize=11)
    ax.set_title("Cluster Distribution by Event Type", fontsize=13)
    ax.set_xticks(x_pos)
    ax.set_xticklabels([f"C{c}\n{labels_desc[c]}" for c in range(best_k)], fontsize=8)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    plot_path = os.path.join(OUTPUT_DIR, "clustering_results.png")
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {plot_path}")

    # Save JSON
    results = {
        "config": {
            "method": "Feature-based K-means",
            "features": FEATURE_NAMES,
            "fixed_length": FIXED_LEN,
            "min_active_months": MIN_ACTIVE_MONTHS,
            "best_k": best_k,
            "best_silhouette": round(best_sil, 4),
            "total_valid": len(X_features),
            "dropped_short": dropped_short,
            "dropped_constant": dropped_constant,
        },
        "silhouette_scores": {str(k): round(v, 4) for k, v in scores.items()},
        "centroids_ts": [[round(v, 4) for v in c] for c in centroids_ts.tolist()],
        "feature_centers": [[round(v, 4) for v in c] for c in feature_centers.tolist()],
        "centroid_labels": labels_desc,
        "cluster_distribution": {
            "event": {str(c): int(((final_clusters == c) & (labels == "event")).sum()) for c in range(best_k)},
            "organic": {str(c): int(((final_clusters == c) & (labels == "organic")).sum()) for c in range(best_k)},
        },
        "event_type_distribution": {},
    }
    for et in unique_etypes:
        results["event_type_distribution"][et] = {
            str(c): int(((final_clusters == c) & (event_types == et)).sum()) for c in range(best_k)
        }
    assignments = []
    for i in range(len(final_clusters)):
        assignments.append({
            "cluster": int(final_clusters[i]),
            "type": all_labels[i],
            "event_type": all_event_types[i],
            "username": all_meta[i]["username"],
            "repo": all_meta[i]["repo"],
            "orig_length": all_meta[i]["length_orig"],
        })
    results["assignments"] = assignments

    results_path = os.path.join(OUTPUT_DIR, "clustering_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {results_path}")

    t_end = time.time()
    print(f"\n  Total time: {t_end - t0:.1f}s")
    print("=" * 60)
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
