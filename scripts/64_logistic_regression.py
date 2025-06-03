#!/usr/bin/env python3
"""
Experiment 2: Logistic Regression -- Core Contributor Prediction.

Binary logistic regression comparing contributor groups while controlling
for activity level and project characteristics.

Runs THREE models following best practices from SE research:
  Model 0 (base):        group only (no controls)
  Model 1 (controlled):  group + log_commits + is_oss4sg
  Model 2 (full):        group + log_commits + is_oss4sg + log_project_size

DV: ever_core (binary 0/1)
IVs:
  - contributor_group: 3-level (mentorship / non-mentorship / organic)
    Reference = organic
  - Also tested: is_event (binary, event vs organic)
  - log_commits: log-transformed commit count (controls for activity)
  - is_oss4sg: binary (mission-driven context)
  - log_project_size: log-transformed unique contributor count in repo

Following Zhou & Mockus (ICSE 2012; TSE 2015), Sharma et al. (OSS 2012),
Middleton et al. (MSR 2018), Qiu et al. (ICSE 2019) for binary logistic
regression in SE research.
"""

import json
import os
import sys
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7_EXTRACTED = "/Volumes/T7/Event based OSS4SG/extracted"
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_oss4sg_repos():
    """Load set of OSS4SG repo names."""
    oss4sg = set()
    try:
        path = os.path.join(BASE, "OSS4SG-Project-List.csv")
        df = pd.read_csv(path)
        for r in df["repo_name_with_owner"]:
            oss4sg.add(str(r).strip().lower())
    except Exception:
        pass
    return oss4sg


def get_repo_metadata(repos):
    """Get project_size and repo_age for each repo from T7 CSVs.
    Memory-safe: load one at a time."""
    meta = {}
    for repo in repos:
        fname = repo.replace("/", "__") + ".csv"
        csv_path = os.path.join(T7_EXTRACTED, fname)
        if not os.path.exists(csv_path):
            meta[repo] = {"project_size": 0, "repo_age_months": 0}
            continue
        try:
            df = pd.read_csv(csv_path,
                             usecols=["author_email", "author_date"],
                             dtype={"author_email": str})
            df["author_date"] = pd.to_datetime(df["author_date"],
                                                errors="coerce", utc=True)
            df = df.dropna(subset=["author_date"])
            if df.empty:
                meta[repo] = {"project_size": 0, "repo_age_months": 0}
            else:
                n_contribs = df["author_email"].nunique()
                first = df["author_date"].min()
                last = df["author_date"].max()
                age_months = max(1, (last - first).days // 30)
                meta[repo] = {"project_size": n_contribs,
                              "repo_age_months": age_months}
            del df
        except Exception:
            meta[repo] = {"project_size": 0, "repo_age_months": 0}
    return meta


def hosmer_lemeshow(y_true, y_pred, n_groups=10):
    """Compute Hosmer-Lemeshow goodness-of-fit test."""
    from scipy import stats as sp_stats
    df_hl = pd.DataFrame({"actual": y_true.values, "predicted": y_pred})
    df_hl["decile"] = pd.qcut(df_hl["predicted"], n_groups, duplicates="drop")
    groups = df_hl.groupby("decile", observed=True).agg(
        obs_events=("actual", "sum"),
        obs_total=("actual", "count"),
        exp_events=("predicted", "sum"),
    )
    groups["obs_nonevents"] = groups["obs_total"] - groups["obs_events"]
    groups["exp_nonevents"] = groups["obs_total"] - groups["exp_events"]

    # Avoid division by zero
    groups = groups[(groups["exp_events"] > 0) & (groups["exp_nonevents"] > 0)]

    hl_stat = (((groups["obs_events"] - groups["exp_events"])**2
                / groups["exp_events"]).sum()
               + ((groups["obs_nonevents"] - groups["exp_nonevents"])**2
                  / groups["exp_nonevents"]).sum())
    hl_df = len(groups) - 2
    hl_p = 1 - sp_stats.chi2.cdf(hl_stat, max(1, hl_df))
    return float(hl_stat), int(hl_df), float(hl_p)


def fit_and_report(y, X, X_cols, model_name):
    """Fit a logistic regression model and return structured results."""
    import statsmodels.api as sm
    from statsmodels.stats.outliers_influence import variance_inflation_factor

    model = sm.Logit(y, X)
    result = model.fit(disp=0, maxiter=200)

    params = result.params
    conf = result.conf_int()
    odds_ratios = np.exp(params)
    or_ci_low = np.exp(conf[0])
    or_ci_high = np.exp(conf[1])
    pvalues = result.pvalues

    print(f"\n{'='*70}")
    print(f"  {model_name}")
    print(f"{'='*70}")
    print(f"  N = {len(y)}, core = {int(y.sum())}, non-core = {int((y == 0).sum())}")
    print(f"  Pseudo R² (McFadden): {result.prsquared:.4f}")
    print(f"  Log-Likelihood: {result.llf:.2f}")
    print(f"  AIC: {result.aic:.2f}, BIC: {result.bic:.2f}")

    # Classification accuracy
    y_pred_class = (result.predict(X) >= 0.5).astype(int)
    acc = (y_pred_class == y).mean()
    print(f"  Classification accuracy: {acc:.3f}")

    # Hosmer-Lemeshow
    pred_probs = result.predict(X)
    hl_chi2, hl_df, hl_p = hosmer_lemeshow(y, pred_probs)
    hl_ok = "GOOD fit (p > 0.05)" if hl_p > 0.05 else "Poor fit (p <= 0.05)"
    print(f"  Hosmer-Lemeshow: chi2={hl_chi2:.2f}, df={hl_df}, p={hl_p:.4f} -> {hl_ok}")

    # Odds ratios table
    print(f"\n  {'Variable':<25} {'OR':>8} {'95% CI':>22} {'p-value':>12} {'Sig':>5}")
    print(f"  {'-'*72}")
    coefficients = {}
    for var in X.columns:
        if var == "const":
            continue
        or_val = odds_ratios[var]
        ci_lo = or_ci_low[var]
        ci_hi = or_ci_high[var]
        p = pvalues[var]
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        print(f"  {var:<25} {or_val:8.3f}  [{ci_lo:7.3f}, {ci_hi:7.3f}]  {p:12.4e}  {sig}")
        coefficients[var] = {
            "coef": float(params[var]),
            "odds_ratio": float(or_val),
            "ci_lower": float(ci_lo),
            "ci_upper": float(ci_hi),
            "p_value": float(p),
            "significant": bool(p < 0.05),
        }

    # VIF for multicollinearity (skip for base models with only dummies)
    X_no_const = X.drop("const", axis=1)
    vif_results = {}
    if len(X_no_const.columns) > 1:
        print(f"\n  --- Variance Inflation Factors ---")
        for i, col in enumerate(X_no_const.columns):
            vif = variance_inflation_factor(X_no_const.values, i)
            flag = " *** HIGH" if vif > 5 else ""
            print(f"    {col:<25}: VIF = {vif:.2f}{flag}")
            vif_results[col] = float(vif)

    return {
        "model_name": model_name,
        "n": int(len(y)),
        "n_core": int(y.sum()),
        "pseudo_r2_mcfadden": float(result.prsquared),
        "aic": float(result.aic),
        "bic": float(result.bic),
        "log_likelihood": float(result.llf),
        "classification_accuracy": float(acc),
        "hosmer_lemeshow": {"chi2": hl_chi2, "df": hl_df, "p": hl_p},
        "coefficients": coefficients,
        "vif": vif_results,
    }, result


def main():
    print("=" * 70)
    print("EXPERIMENT 2: Logistic Regression -- Core Contributor Prediction")
    print("=" * 70)

    # Load per-contributor core status (from script 60)
    core_path = os.path.join(OUTPUT_DIR, "per_contributor_core_status.csv")
    df = pd.read_csv(core_path)
    print(f"Loaded {len(df)} contributor records from per_contributor_core_status.csv")

    # Load event/organic data to get commit counts
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "event_contributors_v2.json")) as f:
        events = json.load(f)["contributions"]
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "organic_matches_v2.json")) as f:
        matches = json.load(f)["matches"]

    # Build commit count lookup
    event_commits = {}
    for e in events:
        event_commits[e["contribution_id"]] = e.get("effective_commits",
                                                      e.get("activity", 0))
    organic_commits = {}
    for m in matches:
        key = m["event_contribution_id"] + "__organic"
        organic_commits[key] = m["organic_commits"]

    # Assign commit counts
    def get_commits(row):
        cid = row["contributor_id"]
        if cid in event_commits:
            return event_commits[cid]
        if cid in organic_commits:
            return organic_commits[cid]
        return 0

    df["commit_count"] = df.apply(get_commits, axis=1)
    df["log_commits"] = np.log1p(df["commit_count"])  # log(1+x)

    # Assign contributor group (3-level)
    def get_group(row):
        if row["contributor_type"] == "organic":
            return "organic"
        if row.get("is_mentorship", False):
            return "mentorship"
        return "non_mentorship"

    df["contributor_group"] = df.apply(get_group, axis=1)

    # Binary event flag
    df["is_event"] = (df["contributor_type"] == "event").astype(int)

    # OSS4SG flag
    oss4sg = load_oss4sg_repos()
    df["is_oss4sg"] = df["repo"].str.lower().isin(oss4sg).astype(int)

    # Get repo metadata (project_size, repo_age)
    unique_repos = df["repo"].unique().tolist()
    print(f"Loading repo metadata for {len(unique_repos)} repos...")
    meta = get_repo_metadata(unique_repos)
    df["project_size"] = df["repo"].map(lambda r: meta.get(r, {}).get("project_size", 0))
    df["repo_age_months"] = df["repo"].map(lambda r: meta.get(r, {}).get("repo_age_months", 0))
    df["log_project_size"] = np.log1p(df["project_size"])
    df["log_repo_age"] = np.log1p(df["repo_age_months"])

    # Filter out rows with zero commits
    df = df[df["commit_count"] > 0].copy()
    print(f"After filtering zero-commit rows: {len(df)}")

    # ── Descriptive statistics ──
    print("\n" + "=" * 70)
    print("DESCRIPTIVE STATISTICS")
    print("=" * 70)
    y = df["ever_core"].astype(int)
    print(f"Total: N={len(df)}, core={y.sum()} ({y.mean()*100:.1f}%)")
    for grp in ["mentorship", "non_mentorship", "organic"]:
        sub = df[df["contributor_group"] == grp]
        core_rate = sub["ever_core"].mean() * 100
        print(f"  {grp:20s}: n={len(sub):5d}, core_rate={core_rate:.1f}%, "
              f"mean_commits={sub['commit_count'].mean():.1f}, "
              f"median_commits={sub['commit_count'].median():.0f}")

    import statsmodels.api as sm
    from scipy import stats as sp_stats

    # Create dummy variables (organic = reference)
    df["is_mentorship_grp"] = (df["contributor_group"] == "mentorship").astype(int)
    df["is_non_mentorship_grp"] = (df["contributor_group"] == "non_mentorship").astype(int)

    all_results = {}

    # ══════════════════════════════════════════════════════════════════════
    # ANALYSIS A: 3-level group (mentorship / non-mentorship / organic)
    # ══════════════════════════════════════════════════════════════════════
    print("\n\n" + "#" * 70)
    print("# ANALYSIS A: 3-Level Group (Mentorship / Non-Mentorship / Organic)")
    print("#" * 70)

    # --- Model A0: Base (group only, no controls) ---
    X0_cols = ["is_mentorship_grp", "is_non_mentorship_grp"]
    X0 = sm.add_constant(df[X0_cols].copy())
    res_a0, fit_a0 = fit_and_report(y, X0, X0_cols,
        "Model A0: Group Only (no controls)")

    # --- Model A1: Controlled (group + activity + oss4sg) ---
    X1_cols = ["is_mentorship_grp", "is_non_mentorship_grp",
               "log_commits", "is_oss4sg"]
    X1 = sm.add_constant(df[X1_cols].copy())
    res_a1, fit_a1 = fit_and_report(y, X1, X1_cols,
        "Model A1: Group + Activity + OSS4SG (primary model)")

    # --- Model A2: Full (adds project size) ---
    X2_cols = ["is_mentorship_grp", "is_non_mentorship_grp",
               "log_commits", "is_oss4sg", "log_project_size"]
    X2 = sm.add_constant(df[X2_cols].copy())
    res_a2, fit_a2 = fit_and_report(y, X2, X2_cols,
        "Model A2: Full (adds project size)")

    # Likelihood Ratio Tests: A0 vs A1, A1 vs A2
    lr_01 = -2 * (fit_a0.llf - fit_a1.llf)
    lr_01_df = len(X1_cols) - len(X0_cols)
    lr_01_p = 1 - sp_stats.chi2.cdf(lr_01, lr_01_df)

    lr_12 = -2 * (fit_a1.llf - fit_a2.llf)
    lr_12_df = len(X2_cols) - len(X1_cols)
    lr_12_p = 1 - sp_stats.chi2.cdf(lr_12, lr_12_df)

    print(f"\n{'='*70}")
    print(f"LIKELIHOOD RATIO TESTS (3-level)")
    print(f"{'='*70}")
    print(f"  A0 vs A1: LR={lr_01:.2f}, df={lr_01_df}, p={lr_01_p:.4e} "
          f"{'-> A1 significantly better' if lr_01_p < 0.05 else '-> No improvement'}")
    print(f"  A1 vs A2: LR={lr_12:.2f}, df={lr_12_df}, p={lr_12_p:.4e} "
          f"{'-> A2 significantly better' if lr_12_p < 0.05 else '-> No improvement'}")

    all_results["3_level"] = {
        "model_a0_base": res_a0,
        "model_a1_controlled": res_a1,
        "model_a2_full": res_a2,
        "lr_test_a0_vs_a1": {"LR": float(lr_01), "df": lr_01_df, "p": float(lr_01_p)},
        "lr_test_a1_vs_a2": {"LR": float(lr_12), "df": lr_12_df, "p": float(lr_12_p)},
    }

    # ══════════════════════════════════════════════════════════════════════
    # ANALYSIS B: Binary (event vs organic)
    # ══════════════════════════════════════════════════════════════════════
    print("\n\n" + "#" * 70)
    print("# ANALYSIS B: Binary (Event vs Organic)")
    print("#" * 70)

    # --- Model B0: Base ---
    Xb0_cols = ["is_event"]
    Xb0 = sm.add_constant(df[Xb0_cols].copy())
    res_b0, fit_b0 = fit_and_report(y, Xb0, Xb0_cols,
        "Model B0: Event vs Organic (no controls)")

    # --- Model B1: Controlled ---
    Xb1_cols = ["is_event", "log_commits", "is_oss4sg"]
    Xb1 = sm.add_constant(df[Xb1_cols].copy())
    res_b1, fit_b1 = fit_and_report(y, Xb1, Xb1_cols,
        "Model B1: Event + Activity + OSS4SG")

    lr_b = -2 * (fit_b0.llf - fit_b1.llf)
    lr_b_df = len(Xb1_cols) - len(Xb0_cols)
    lr_b_p = 1 - sp_stats.chi2.cdf(lr_b, lr_b_df)

    print(f"\n{'='*70}")
    print(f"LIKELIHOOD RATIO TESTS (binary)")
    print(f"{'='*70}")
    print(f"  B0 vs B1: LR={lr_b:.2f}, df={lr_b_df}, p={lr_b_p:.4e} "
          f"{'-> B1 significantly better' if lr_b_p < 0.05 else '-> No improvement'}")

    all_results["binary"] = {
        "model_b0_base": res_b0,
        "model_b1_controlled": res_b1,
        "lr_test_b0_vs_b1": {"LR": float(lr_b), "df": lr_b_df, "p": float(lr_b_p)},
    }

    # ══════════════════════════════════════════════════════════════════════
    # INTERPRETATION
    # ══════════════════════════════════════════════════════════════════════
    print("\n\n" + "#" * 70)
    print("# INTERPRETATION SUMMARY")
    print("#" * 70)

    print("\n--- Analysis A: 3-level group ---")
    print("  Model A0 (no controls) shows the RAW group effect.")
    print("  Model A1 (with controls) shows the effect AFTER controlling for activity.")
    print("  If the direction flips between A0 and A1, this indicates a suppression")
    print("  effect: the groups differ in activity, and once activity is held constant,")
    print("  the group effect changes. This is informative, not a bug.")

    for label, model_key in [("A0 (base)", "model_a0_base"),
                              ("A1 (controlled)", "model_a1_controlled")]:
        print(f"\n  {label}:")
        for var in ["is_mentorship_grp", "is_non_mentorship_grp"]:
            c = all_results["3_level"][model_key]["coefficients"].get(var)
            if c:
                direction = "more" if c["odds_ratio"] > 1 else "less"
                sig = "significant" if c["significant"] else "NOT significant"
                grp_name = "Mentorship" if "non" not in var else "Non-Mentorship"
                print(f"    {grp_name} vs Organic: OR={c['odds_ratio']:.3f} "
                      f"[{c['ci_lower']:.3f}, {c['ci_upper']:.3f}] "
                      f"p={c['p_value']:.4e} ({sig})")

    print(f"\n--- Analysis B: Binary ---")
    for label, model_key in [("B0 (base)", "model_b0_base"),
                              ("B1 (controlled)", "model_b1_controlled")]:
        c = all_results["binary"][model_key]["coefficients"].get("is_event")
        if c:
            sig = "significant" if c["significant"] else "NOT significant"
            print(f"  {label}: Event vs Organic: OR={c['odds_ratio']:.3f} "
                  f"[{c['ci_lower']:.3f}, {c['ci_upper']:.3f}] "
                  f"p={c['p_value']:.4e} ({sig})")

    # ── Save results ──
    out_path = os.path.join(OUTPUT_DIR, "logistic_regression_results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved: {out_path}")

    print(f"\n{'='*70}")
    print(f"EXPERIMENT 2 COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
