#!/usr/bin/env python3
"""
Phase 5: Survival Analysis #1 -- Event Perspective (Retention).

Does an event contributor stay in the project longer than an organic contributor?
- "Survive" = still active
- "Dead/Left" = no commit for >= 5 months after last commit
- Uses Kaplan-Meier curves, Log-Rank test, Cox Proportional Hazards
- Milestone tables at 6-month increments
- Bonferroni correction for multiple log-rank comparisons
"""

import json
import os
import pandas as pd
import numpy as np
from collections import defaultdict
from lifelines import KaplanMeierFitter, CoxPHFitter
from lifelines.statistics import logrank_test
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7_EXTRACTED = "/Volumes/T7/Event based OSS4SG/extracted"
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")
LEAVE_THRESHOLD_MONTHS = 5
MILESTONES = [6, 12, 18, 24, 30, 36]

os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_oss4sg_repos():
    import csv
    oss4sg = set()
    try:
        with open(os.path.join(BASE, "OSS4SG-Project-List.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                oss4sg.add(row["repo_name_with_owner"].strip().lower())
    except Exception:
        pass
    return oss4sg


def load_repo_author_dates(csv_path):
    """Load author dates and build index: email_lower -> (first_date, last_date, data_end)."""
    if not os.path.exists(csv_path):
        return {}, {}, None
    try:
        df = pd.read_csv(csv_path, usecols=["author_name", "author_email", "author_date"])
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, usecols=["author_name", "author_email", "author_date"],
                        encoding="latin-1")
    except Exception:
        return {}, {}, None

    df["author_date"] = pd.to_datetime(df["author_date"], errors="coerce", utc=True)
    df = df.dropna(subset=["author_date"])

    if df.empty:
        return {}, {}, None

    data_end = df["author_date"].max()

    email_index = {}
    grouped = df.groupby("author_email")["author_date"].agg(["min", "max"])
    for email, row in grouped.iterrows():
        email_index[str(email).lower()] = (row["min"], row["max"])

    name_emails = defaultdict(set)
    for email, name in zip(df["author_email"], df["author_name"]):
        if pd.notna(name):
            name_emails[str(name).lower()].add(str(email).lower())

    return email_index, dict(name_emails), data_end


def find_dates(email_index, name_emails, email=None, username=None):
    """Find (first_commit, last_commit) for contributor."""
    if email:
        e_lower = email.lower()
        if e_lower in email_index:
            return email_index[e_lower]
        for e, dates in email_index.items():
            if e_lower in e or e in e_lower:
                return dates

    if username and len(username) > 3:
        u = username.lower()
        for e, dates in email_index.items():
            if u in e:
                return dates
        for name, emails in name_emails.items():
            if u in name:
                for e in emails:
                    if e in email_index:
                        return email_index[e]
    return None, None


def extract_milestones(kmf, milestones=MILESTONES):
    """Extract survival probabilities at specified month milestones from a KaplanMeierFitter."""
    results = {}
    sf = kmf.survival_function_
    for m in milestones:
        # Find the closest time point <= m in the survival function
        valid = sf.index[sf.index <= m]
        if len(valid) > 0:
            prob = float(sf.loc[valid[-1]].iloc[0])
        else:
            prob = 1.0  # No events before this time
        results[m] = round(prob * 100, 1)  # as percentage
    return results


def main():
    print("=" * 70)
    print("PHASE 5: Survival Analysis -- Retention")
    print("=" * 70)

    oss4sg_repos = load_oss4sg_repos()

    # Load contributors
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "event_contributors_v2.json")) as f:
        event_contribs = json.load(f)["contributions"]

    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "organic_matches_v2.json")) as f:
        organic_matches = json.load(f)["matches"]

    # Group by repo
    repo_contributors = defaultdict(list)

    for ec in event_contribs:
        repo_contributors[ec["repo"]].append({
            "contributor_type": "event",
            "event_type": ec["event"],
            "username": ec["github_username"],
            "email": None,
            "is_mentorship": ec["event"] in ("gsoc", "lfx"),
        })

    for om in organic_matches:
        repo_contributors[om["repo"]].append({
            "contributor_type": "organic",
            "event_type": om["event_type"],
            "username": None,
            "email": om["organic_email"],
            "is_mentorship": False,
        })

    print(f"Processing {len(repo_contributors)} repos...")

    survival_records = []

    for ri, (repo, contribs) in enumerate(repo_contributors.items()):
        if (ri + 1) % 50 == 0:
            print(f"  Repo {ri+1}/{len(repo_contributors)}: {repo}")

        csv_path = os.path.join(T7_EXTRACTED, repo.replace("/", "__") + ".csv")
        email_index, name_emails, data_end = load_repo_author_dates(csv_path)

        if data_end is None:
            continue

        is_oss4sg = repo.lower() in oss4sg_repos

        for c in contribs:
            first_commit, last_commit = find_dates(
                email_index, name_emails, c["email"], c["username"])

            if first_commit is None or last_commit is None:
                continue

            # Determine if "left" (inactive for >= 5 months)
            months_since_last = (data_end - last_commit).days / 30.44

            if months_since_last >= LEAVE_THRESHOLD_MONTHS:
                event_observed = 1  # left
                survival_months = max(0, (last_commit - first_commit).days / 30.44)
            else:
                event_observed = 0  # censored (still active)
                survival_months = max(0, (data_end - first_commit).days / 30.44)

            survival_records.append({
                "contributor_type": c["contributor_type"],
                "event_type": c["event_type"],
                "is_mentorship": c["is_mentorship"],
                "is_oss4sg": is_oss4sg,
                "repo": repo,
                "survival_months": round(survival_months, 2),
                "event_observed": event_observed,
                "is_event": 1 if c["contributor_type"] == "event" else 0,
            })

    df = pd.DataFrame(survival_records)
    df.to_csv(os.path.join(OUTPUT_DIR, "per_contributor_retention.csv"), index=False)
    print(f"\nSurvival records: {len(df)}")
    print(f"  Event: {(df['is_event']==1).sum()}, Organic: {(df['is_event']==0).sum()}")
    print(f"  Left (event_observed=1): {df['event_observed'].sum()}")
    print(f"  Censored: {(df['event_observed']==0).sum()}")

    # ── Collect all log-rank tests for Bonferroni correction ──
    logrank_results = []  # list of (label, chi2, p_value)
    N_LOGRANK_TESTS = 3  # Event vs Organic, Mentorship vs Non-Mentorship, OSS4SG vs Conv
    BONFERRONI_ALPHA = 0.05 / N_LOGRANK_TESTS

    # --- Kaplan-Meier ---
    print("\n" + "-" * 50)
    print("KAPLAN-MEIER SURVIVAL CURVES")
    print(f"  Bonferroni correction: {N_LOGRANK_TESTS} tests, adjusted alpha = {BONFERRONI_ALPHA:.4f}")
    print("-" * 50)

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # ── Plot 1: Event vs Organic ──
    ax = axes[0, 0]
    kmf_event = KaplanMeierFitter()
    event_data = df[df["is_event"] == 1]
    organic_data = df[df["is_event"] == 0]

    kmf_event.fit(event_data["survival_months"], event_data["event_observed"], label="Event")
    kmf_event.plot_survival_function(ax=ax)

    kmf_organic = KaplanMeierFitter()
    kmf_organic.fit(organic_data["survival_months"], organic_data["event_observed"], label="Organic")
    kmf_organic.plot_survival_function(ax=ax)

    ax.set_title("Retention: Event vs Organic")
    ax.set_xlabel("Months since first commit")
    ax.set_ylabel("Probability of still being active")
    ax.set_xlim(0, 120)

    lr = logrank_test(
        event_data["survival_months"], organic_data["survival_months"],
        event_data["event_observed"], organic_data["event_observed"])
    sig_label = "SIGNIFICANT" if lr.p_value < BONFERRONI_ALPHA else "not significant"
    logrank_results.append(("Event vs Organic", float(lr.test_statistic), float(lr.p_value), sig_label))
    print(f"\n  Event vs Organic:")
    print(f"    Log-rank chi2={lr.test_statistic:.4f}, p={lr.p_value:.4e} ({sig_label} at alpha={BONFERRONI_ALPHA:.4f})")
    print(f"    Event median survival: {kmf_event.median_survival_time_:.1f} months")
    print(f"    Organic median survival: {kmf_organic.median_survival_time_:.1f} months")

    # Extract milestones
    event_milestones = extract_milestones(kmf_event)
    organic_milestones = extract_milestones(kmf_organic)

    print(f"\n  Milestone table (% still active):")
    print(f"    {'Month':>6}  {'Event':>8}  {'Organic':>8}")
    for m in MILESTONES:
        print(f"    {m:>6}  {event_milestones[m]:>7.1f}%  {organic_milestones[m]:>7.1f}%")

    # ── Plot 2: Mentorship vs Non-Mentorship ──
    ax = axes[0, 1]
    mentor_data = df[(df["is_event"] == 1) & (df["is_mentorship"] == True)]
    non_mentor_data = df[(df["is_event"] == 1) & (df["is_mentorship"] == False)]

    kmf_mentor = KaplanMeierFitter()
    kmf_nonmentor = KaplanMeierFitter()
    mentor_milestones = {}
    nonmentor_milestones = {}
    lr2 = None

    if len(mentor_data) > 10 and len(non_mentor_data) > 10:
        kmf_mentor.fit(mentor_data["survival_months"], mentor_data["event_observed"], label="Mentorship")
        kmf_mentor.plot_survival_function(ax=ax)

        kmf_nonmentor.fit(non_mentor_data["survival_months"], non_mentor_data["event_observed"], label="Non-Mentorship")
        kmf_nonmentor.plot_survival_function(ax=ax)

        lr2 = logrank_test(
            mentor_data["survival_months"], non_mentor_data["survival_months"],
            mentor_data["event_observed"], non_mentor_data["event_observed"])
        sig_label2 = "SIGNIFICANT" if lr2.p_value < BONFERRONI_ALPHA else "not significant"
        logrank_results.append(("Mentorship vs Non-Mentorship", float(lr2.test_statistic), float(lr2.p_value), sig_label2))
        print(f"\n  Mentorship vs Non-Mentorship:")
        print(f"    Log-rank chi2={lr2.test_statistic:.4f}, p={lr2.p_value:.4e} ({sig_label2})")

        mentor_milestones = extract_milestones(kmf_mentor)
        nonmentor_milestones = extract_milestones(kmf_nonmentor)

        print(f"\n  Milestone table (% still active):")
        print(f"    {'Month':>6}  {'Mentorship':>12}  {'Non-Mentorship':>16}")
        for m in MILESTONES:
            print(f"    {m:>6}  {mentor_milestones[m]:>11.1f}%  {nonmentor_milestones[m]:>15.1f}%")

    ax.set_title("Retention: Mentorship vs Non-Mentorship")
    ax.set_xlabel("Months since first commit")
    ax.set_ylabel("Probability of still being active")
    ax.set_xlim(0, 120)

    # ── Plot 3: Per event type ──
    ax = axes[1, 0]
    event_type_milestones = {}
    for et in ["gsoc", "lfx", "24pr", "hacktoberfest"]:
        et_data = df[(df["is_event"] == 1) & (df["event_type"] == et)]
        if len(et_data) > 10:
            kmf = KaplanMeierFitter()
            kmf.fit(et_data["survival_months"], et_data["event_observed"], label=et.upper())
            kmf.plot_survival_function(ax=ax)
            event_type_milestones[et.upper()] = extract_milestones(kmf)
    ax.set_title("Retention by Event Type")
    ax.set_xlabel("Months since first commit")
    ax.set_ylabel("Probability of still being active")
    ax.set_xlim(0, 120)

    # ── Plot 4: OSS4SG vs Conventional ──
    ax = axes[1, 1]
    oss4sg_data = df[df["is_oss4sg"] == True]
    conv_data = df[df["is_oss4sg"] == False]
    lr3 = None

    if len(oss4sg_data) > 10 and len(conv_data) > 10:
        kmf1 = KaplanMeierFitter()
        kmf1.fit(oss4sg_data["survival_months"], oss4sg_data["event_observed"], label="OSS4SG")
        kmf1.plot_survival_function(ax=ax)

        kmf2 = KaplanMeierFitter()
        kmf2.fit(conv_data["survival_months"], conv_data["event_observed"], label="Conventional OSS")
        kmf2.plot_survival_function(ax=ax)

        lr3 = logrank_test(
            oss4sg_data["survival_months"], conv_data["survival_months"],
            oss4sg_data["event_observed"], conv_data["event_observed"])
        sig_label3 = "SIGNIFICANT" if lr3.p_value < BONFERRONI_ALPHA else "not significant"
        logrank_results.append(("OSS4SG vs Conventional", float(lr3.test_statistic), float(lr3.p_value), sig_label3))
        print(f"\n  OSS4SG vs Conventional:")
        print(f"    Log-rank chi2={lr3.test_statistic:.4f}, p={lr3.p_value:.4e} ({sig_label3})")

    ax.set_title("Retention: OSS4SG vs Conventional")
    ax.set_xlabel("Months since first commit")
    ax.set_ylabel("Probability of still being active")
    ax.set_xlim(0, 120)

    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "survival_retention_km.png"), dpi=150, bbox_inches="tight")
    print(f"\n  Saved KM plot: survival_retention_km.png")

    # ── Log-rank summary with Bonferroni ──
    print("\n" + "-" * 50)
    print(f"LOG-RANK SUMMARY (Bonferroni-corrected, alpha={BONFERRONI_ALPHA:.4f})")
    print("-" * 50)
    for label, chi2, pval, sig in logrank_results:
        print(f"  {label:35s}: chi2={chi2:.4f}, p={pval:.4e} -> {sig}")

    # --- Cox Proportional Hazards ---
    print("\n" + "-" * 50)
    print("COX PROPORTIONAL HAZARDS MODEL")
    print("-" * 50)

    cox_df = df[["survival_months", "event_observed", "is_event", "is_mentorship", "is_oss4sg"]].copy()
    cox_df["is_mentorship"] = cox_df["is_mentorship"].astype(int)
    cox_df["is_oss4sg"] = cox_df["is_oss4sg"].astype(int)

    # Remove zero-duration records (causes issues)
    cox_df = cox_df[cox_df["survival_months"] > 0]

    cph = CoxPHFitter()
    cox_results = {}
    try:
        cph.fit(cox_df, duration_col="survival_months", event_col="event_observed")
        cph.print_summary()

        for var in ["is_event", "is_mentorship", "is_oss4sg"]:
            row = cph.summary.loc[var]
            cox_results[var] = {
                "hazard_ratio": round(float(row["exp(coef)"]), 4),
                "hr_95ci_lo": round(float(row["exp(coef) lower 95%"]), 4),
                "hr_95ci_hi": round(float(row["exp(coef) upper 95%"]), 4),
                "p_value": float(row["p"]),
                "coef": round(float(row["coef"]), 4),
            }

        print(f"\n  Interpretation:")
        for var, r in cox_results.items():
            direction = "more" if r["hazard_ratio"] > 1 else "less"
            print(f"    {var}: HR={r['hazard_ratio']:.3f} "
                  f"(95% CI [{r['hr_95ci_lo']:.3f}, {r['hr_95ci_hi']:.3f}]), "
                  f"p={r['p_value']:.4e} -> {direction} likely to leave")
    except Exception as e:
        print(f"  Cox PH failed: {e}")
        cox_results = {"error": str(e)}

    # ── Save milestone table as CSV ──
    milestone_rows = []
    for m in MILESTONES:
        row = {"month": m, "event": event_milestones.get(m), "organic": organic_milestones.get(m)}
        if mentor_milestones:
            row["mentorship"] = mentor_milestones.get(m)
        if nonmentor_milestones:
            row["non_mentorship"] = nonmentor_milestones.get(m)
        for et_label, et_ms in event_type_milestones.items():
            row[et_label] = et_ms.get(m)
        milestone_rows.append(row)
    milestone_df = pd.DataFrame(milestone_rows)
    milestone_df.to_csv(os.path.join(OUTPUT_DIR, "retention_milestones.csv"), index=False)
    print(f"\nSaved: retention_milestones.csv")

    # Save results
    results = {
        "log_rank_tests": [
            {"comparison": label, "chi2": chi2, "p_value": pval,
             "bonferroni_alpha": BONFERRONI_ALPHA,
             "significant_after_correction": pval < BONFERRONI_ALPHA}
            for label, chi2, pval, sig in logrank_results
        ],
        "cox_ph": cox_results,
        "milestones_pct_active": {
            "months": MILESTONES,
            "event": [event_milestones.get(m) for m in MILESTONES],
            "organic": [organic_milestones.get(m) for m in MILESTONES],
            "mentorship": [mentor_milestones.get(m) for m in MILESTONES] if mentor_milestones else None,
            "non_mentorship": [nonmentor_milestones.get(m) for m in MILESTONES] if nonmentor_milestones else None,
        },
        "n_event": int((df["is_event"] == 1).sum()),
        "n_organic": int((df["is_event"] == 0).sum()),
        "n_left": int(df["event_observed"].sum()),
        "n_censored": int((df["event_observed"] == 0).sum()),
        "bonferroni_n_tests": N_LOGRANK_TESTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
    }

    with open(os.path.join(OUTPUT_DIR, "survival_retention_results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"Saved: survival_retention_results.json")
    print("\nPHASE 5 COMPLETE")


if __name__ == "__main__":
    main()
