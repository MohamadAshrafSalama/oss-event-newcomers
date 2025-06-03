#!/usr/bin/env python3
"""
Phase 6: Survival Analysis #2 -- Contributor Perspective (Time-to-Core).

Does participating in an event increase a contributor's chance of becoming
a core contributor?
- "Event" (success) = achieved core status
- "Censored" = never achieved core by data end
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
CORE_DIR = os.path.join(BASE, "07_core_contributor_analysis")
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")
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
    """Load author dates and build index: email_lower -> (first_date, last_date).
    Also returns data_end (max date in repo) and name_emails mapping."""
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


def load_core_data(repo):
    """Load monthly core contributor data for a repo."""
    fname = repo.replace("/", "__") + "_cores.json"
    path = os.path.join(CORE_DIR, fname)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def find_first_core_month(core_data, email=None, username=None, resolved_info=None):
    """Find the first month a contributor appears in the core set.
    Returns first_core_month (int) or None."""
    if not core_data:
        return None

    search_emails = set()
    search_names = set()
    if email:
        search_emails.add(email.lower())
    if username and len(username) > 3:
        search_names.add(username.lower())
    if resolved_info:
        if resolved_info.get("email"):
            search_emails.add(resolved_info["email"].lower())
        if resolved_info.get("name"):
            search_names.add(resolved_info["name"].lower())
        if resolved_info.get("t7_match", {}).get("matched_email"):
            search_emails.add(resolved_info["t7_match"]["matched_email"].lower())

    last_eval = core_data.get("last_evaluation")
    if not last_eval or not last_eval.get("core_contributors"):
        return None

    is_core = False
    matched_email = None
    for cc in last_eval.get("core_contributors", []):
        ce = str(cc.get("email", "") or "").lower()
        cn = str(cc.get("name", "") or "").lower()
        for se in search_emails:
            if se and ce and (se in ce or ce in se):
                is_core = True
                matched_email = ce
                break
        if is_core:
            break
        for sn in search_names:
            if sn and len(sn) > 3 and ((ce and sn in ce) or (cn and sn in cn)):
                is_core = True
                matched_email = ce
                break
        if is_core:
            break

    if not is_core:
        return None

    fcm = core_data.get("first_core_month", {})
    if matched_email and matched_email in fcm:
        return fcm[matched_email]
    for se in search_emails:
        for fcm_email, month in fcm.items():
            if se and fcm_email and (se in fcm_email or fcm_email in se):
                return month
    for sn in search_names:
        if sn and len(sn) > 3:
            for fcm_email, month in fcm.items():
                if sn in fcm_email:
                    return month
    return None


def extract_milestones(kmf, milestones=MILESTONES):
    """Extract survival probabilities at specified month milestones.
    For time-to-core, the survival function shows P(not yet core).
    We return P(became core) = 1 - survival."""
    results = {}
    sf = kmf.survival_function_
    for m in milestones:
        valid = sf.index[sf.index <= m]
        if len(valid) > 0:
            prob_not_core = float(sf.loc[valid[-1]].iloc[0])
        else:
            prob_not_core = 1.0
        results[m] = round((1 - prob_not_core) * 100, 1)  # % who became core
    return results


def main():
    print("=" * 70)
    print("PHASE 6: Survival Analysis -- Time-to-Core Achievement")
    print("=" * 70)

    oss4sg_repos = load_oss4sg_repos()
    print(f"OSS4SG repos: {len(oss4sg_repos)}")

    # Load resolved emails for better matching
    resolved_path = os.path.join(BASE, "05_contributor_journey_extraction",
                                 "resolved_emails.json")
    resolved_emails = {}
    if os.path.exists(resolved_path):
        with open(resolved_path) as f:
            resolved_emails = json.load(f)
        print(f"Loaded {len(resolved_emails)} resolved emails")

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
            "contribution_id": ec["contribution_id"],
        })

    for om in organic_matches:
        repo_contributors[om["repo"]].append({
            "contributor_type": "organic",
            "event_type": om["event_type"],
            "username": None,
            "email": om["organic_email"],
            "is_mentorship": False,
            "contribution_id": om["event_contribution_id"] + "__organic",
        })

    print(f"Processing {len(repo_contributors)} repos...")

    survival_records = []
    skipped_no_csv = 0
    skipped_no_dates = 0
    found = 0

    for ri, (repo, contribs) in enumerate(repo_contributors.items()):
        if (ri + 1) % 50 == 0:
            print(f"  Repo {ri+1}/{len(repo_contributors)}: {repo}")

        csv_path = os.path.join(T7_EXTRACTED, repo.replace("/", "__") + ".csv")
        email_index, name_emails, data_end = load_repo_author_dates(csv_path)

        if data_end is None:
            skipped_no_csv += 1
            continue

        core_data = load_core_data(repo)
        is_oss4sg = repo.lower() in oss4sg_repos

        project_start = None
        if core_data and core_data.get("project_start"):
            try:
                project_start = pd.Timestamp(core_data["project_start"], tz="UTC")
            except Exception:
                pass

        for c in contribs:
            first_commit, last_commit = find_dates(
                email_index, name_emails, c["email"], c["username"])

            if first_commit is None:
                skipped_no_dates += 1
                continue

            resolved_info = None
            key = c["username"] or c["email"] or ""
            if key in resolved_emails:
                resolved_info = resolved_emails[key]

            first_core_month_num = find_first_core_month(
                core_data, c["email"], c["username"], resolved_info)

            if first_core_month_num is not None:
                if project_start is not None:
                    first_core_date = project_start + pd.DateOffset(months=int(first_core_month_num))
                    months_to_core = max(0, (first_core_date - first_commit).days / 30.44)
                else:
                    months_to_core = max(0, float(first_core_month_num))
                achieved_core = 1
                survival_months = round(months_to_core, 2)
            else:
                achieved_core = 0
                survival_months = max(0, (data_end - first_commit).days / 30.44)

            found += 1
            survival_records.append({
                "contributor_type": c["contributor_type"],
                "event_type": c["event_type"],
                "is_mentorship": c["is_mentorship"],
                "is_oss4sg": is_oss4sg,
                "repo": repo,
                "survival_months": round(survival_months, 2),
                "achieved_core": achieved_core,
                "is_event": 1 if c["contributor_type"] == "event" else 0,
                "first_core_month": first_core_month_num,
            })

    df = pd.DataFrame(survival_records)
    csv_out = os.path.join(OUTPUT_DIR, "per_contributor_core_survival.csv")
    df.to_csv(csv_out, index=False)
    print(f"\nSurvival records: {len(df)}")
    print(f"  Event: {(df['is_event']==1).sum()}, Organic: {(df['is_event']==0).sum()}")
    print(f"  Achieved core (achieved_core=1): {df['achieved_core'].sum()}")
    print(f"  Censored (never core): {(df['achieved_core']==0).sum()}")
    print(f"  Skipped (no CSV): {skipped_no_csv}, no dates: {skipped_no_dates}")

    # ── Collect all log-rank tests for Bonferroni correction ──
    logrank_results = []
    N_LOGRANK_TESTS = 3  # Event vs Organic, Mentorship vs Non-Mentorship, OSS4SG vs Conv
    BONFERRONI_ALPHA = 0.05 / N_LOGRANK_TESTS

    # --- Kaplan-Meier ---
    print("\n" + "-" * 50)
    print("KAPLAN-MEIER SURVIVAL CURVES (Time-to-Core)")
    print(f"  Bonferroni correction: {N_LOGRANK_TESTS} tests, adjusted alpha = {BONFERRONI_ALPHA:.4f}")
    print("  Y-axis: Prob. of NOT yet having achieved core (1 = never core)")
    print("-" * 50)

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # ── Plot 1: Event vs Organic ──
    ax = axes[0, 0]
    event_data = df[df["is_event"] == 1]
    organic_data = df[df["is_event"] == 0]

    kmf_event = KaplanMeierFitter()
    kmf_event.fit(event_data["survival_months"], event_data["achieved_core"], label="Event")
    kmf_event.plot_survival_function(ax=ax)

    kmf_organic = KaplanMeierFitter()
    kmf_organic.fit(organic_data["survival_months"], organic_data["achieved_core"], label="Organic")
    kmf_organic.plot_survival_function(ax=ax)

    ax.set_title("Time-to-Core: Event vs Organic")
    ax.set_xlabel("Months since first commit")
    ax.set_ylabel("Prob. of not yet achieving core")
    ax.set_xlim(0, 60)

    lr = logrank_test(
        event_data["survival_months"], organic_data["survival_months"],
        event_data["achieved_core"], organic_data["achieved_core"])
    sig_label = "SIGNIFICANT" if lr.p_value < BONFERRONI_ALPHA else "not significant"
    logrank_results.append(("Event vs Organic", float(lr.test_statistic), float(lr.p_value), sig_label))
    print(f"\n  Event vs Organic:")
    print(f"    Log-rank chi2={lr.test_statistic:.4f}, p={lr.p_value:.4e} ({sig_label} at alpha={BONFERRONI_ALPHA:.4f})")

    # Extract milestones (% who became core by month M)
    event_milestones = extract_milestones(kmf_event)
    organic_milestones = extract_milestones(kmf_organic)

    print(f"\n  Milestone table (% who became core by month M):")
    print(f"    {'Month':>6}  {'Event':>8}  {'Organic':>8}")
    for m in MILESTONES:
        print(f"    {m:>6}  {event_milestones[m]:>7.1f}%  {organic_milestones[m]:>7.1f}%")

    # ── Plot 2: Mentorship vs Non-Mentorship ──
    ax = axes[0, 1]
    mentor_data = df[(df["is_event"] == 1) & (df["is_mentorship"] == True)]
    non_mentor_data = df[(df["is_event"] == 1) & (df["is_mentorship"] == False)]

    mentor_milestones = {}
    nonmentor_milestones = {}
    lr_mentor = None

    if len(mentor_data) > 10 and len(non_mentor_data) > 10:
        kmf1 = KaplanMeierFitter()
        kmf1.fit(mentor_data["survival_months"], mentor_data["achieved_core"],
                 label="Mentorship (GSoC+LFX)")
        kmf1.plot_survival_function(ax=ax)

        kmf2 = KaplanMeierFitter()
        kmf2.fit(non_mentor_data["survival_months"], non_mentor_data["achieved_core"],
                 label="Non-Mentorship (24PR+HF)")
        kmf2.plot_survival_function(ax=ax)

        lr_mentor = logrank_test(
            mentor_data["survival_months"], non_mentor_data["survival_months"],
            mentor_data["achieved_core"], non_mentor_data["achieved_core"])
        sig_label2 = "SIGNIFICANT" if lr_mentor.p_value < BONFERRONI_ALPHA else "not significant"
        logrank_results.append(("Mentorship vs Non-Mentorship", float(lr_mentor.test_statistic), float(lr_mentor.p_value), sig_label2))
        print(f"\n  Mentorship vs Non-Mentorship:")
        print(f"    Log-rank chi2={lr_mentor.test_statistic:.4f}, p={lr_mentor.p_value:.4e} ({sig_label2})")

        mentor_milestones = extract_milestones(kmf1)
        nonmentor_milestones = extract_milestones(kmf2)

        print(f"\n  Milestone table (% who became core by month M):")
        print(f"    {'Month':>6}  {'Mentorship':>12}  {'Non-Mentorship':>16}")
        for m in MILESTONES:
            print(f"    {m:>6}  {mentor_milestones[m]:>11.1f}%  {nonmentor_milestones[m]:>15.1f}%")

    ax.set_title("Time-to-Core: Mentorship vs Non-Mentorship")
    ax.set_xlabel("Months since first commit")
    ax.set_ylabel("Prob. of not yet achieving core")
    ax.set_xlim(0, 60)

    # ── Plot 3: Per event type ──
    ax = axes[1, 0]
    event_type_milestones = {}
    for et in ["gsoc", "lfx", "24pr", "hacktoberfest"]:
        et_data = df[(df["is_event"] == 1) & (df["event_type"] == et)]
        if len(et_data) > 10:
            kmf = KaplanMeierFitter()
            kmf.fit(et_data["survival_months"], et_data["achieved_core"], label=et.upper())
            kmf.plot_survival_function(ax=ax)
            event_type_milestones[et.upper()] = extract_milestones(kmf)

    # Also plot organic for reference
    kmf_ref = KaplanMeierFitter()
    kmf_ref.fit(organic_data["survival_months"], organic_data["achieved_core"], label="Organic")
    kmf_ref.plot_survival_function(ax=ax, ci_show=False, ls="--", color="gray")

    ax.set_title("Time-to-Core by Event Type")
    ax.set_xlabel("Months since first commit")
    ax.set_ylabel("Prob. of not yet achieving core")
    ax.set_xlim(0, 60)

    # ── Plot 4: OSS4SG vs Conventional ──
    ax = axes[1, 1]
    oss4sg_data = df[df["is_oss4sg"] == True]
    conv_data = df[df["is_oss4sg"] == False]

    lr_oss4sg = None
    if len(oss4sg_data) > 10 and len(conv_data) > 10:
        kmf1 = KaplanMeierFitter()
        kmf1.fit(oss4sg_data["survival_months"], oss4sg_data["achieved_core"], label="OSS4SG")
        kmf1.plot_survival_function(ax=ax)

        kmf2 = KaplanMeierFitter()
        kmf2.fit(conv_data["survival_months"], conv_data["achieved_core"], label="Conventional OSS")
        kmf2.plot_survival_function(ax=ax)

        lr_oss4sg = logrank_test(
            oss4sg_data["survival_months"], conv_data["survival_months"],
            oss4sg_data["achieved_core"], conv_data["achieved_core"])
        sig_label3 = "SIGNIFICANT" if lr_oss4sg.p_value < BONFERRONI_ALPHA else "not significant"
        logrank_results.append(("OSS4SG vs Conventional", float(lr_oss4sg.test_statistic), float(lr_oss4sg.p_value), sig_label3))
        print(f"\n  OSS4SG vs Conventional:")
        print(f"    Log-rank chi2={lr_oss4sg.test_statistic:.4f}, p={lr_oss4sg.p_value:.4e} ({sig_label3})")

    ax.set_title("Time-to-Core: OSS4SG vs Conventional")
    ax.set_xlabel("Months since first commit")
    ax.set_ylabel("Prob. of not yet achieving core")
    ax.set_xlim(0, 60)

    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "survival_core_km.png"), dpi=150, bbox_inches="tight")
    print(f"\n  Saved KM plot: survival_core_km.png")

    # ── Log-rank summary with Bonferroni ──
    print("\n" + "-" * 50)
    print(f"LOG-RANK SUMMARY (Bonferroni-corrected, alpha={BONFERRONI_ALPHA:.4f})")
    print("-" * 50)
    for label, chi2, pval, sig in logrank_results:
        print(f"  {label:35s}: chi2={chi2:.4f}, p={pval:.4e} -> {sig}")

    # --- Cox Proportional Hazards ---
    print("\n" + "-" * 50)
    print("COX PROPORTIONAL HAZARDS MODEL (Time-to-Core)")
    print("-" * 50)
    print("  HR > 1 => MORE likely to achieve core (faster)")
    print("  HR < 1 => LESS likely to achieve core (slower)")

    cox_df = df[["survival_months", "achieved_core", "is_event",
                 "is_mentorship", "is_oss4sg"]].copy()
    cox_df["is_mentorship"] = cox_df["is_mentorship"].astype(int)
    cox_df["is_oss4sg"] = cox_df["is_oss4sg"].astype(int)

    mask_ok = (cox_df["survival_months"] > 0) | (cox_df["achieved_core"] == 1)
    removed = len(cox_df) - mask_ok.sum()
    cox_df = cox_df[mask_ok]
    cox_df.loc[(cox_df["survival_months"] == 0) & (cox_df["achieved_core"] == 1),
               "survival_months"] = 0.5
    cox_df.loc[cox_df["survival_months"] == 0, "survival_months"] = 0.5
    print(f"  Records for Cox: {len(cox_df)} (removed {removed} zero-duration censored)")

    cph = CoxPHFitter()
    cox_results = {}
    try:
        cph.fit(cox_df, duration_col="survival_months", event_col="achieved_core")
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
                  f"p={r['p_value']:.4e} -> {direction} likely to achieve core")
    except Exception as e:
        print(f"  Cox PH failed: {e}")
        cox_results = {"error": str(e)}

    # --- 4-way subgroup analysis ---
    print("\n" + "-" * 50)
    print("4-WAY SUBGROUP ANALYSIS")
    print("-" * 50)

    subgroups = {}
    for is_mentor, mentor_label in [(True, "Mentorship"), (False, "Non-Mentorship")]:
        for is_oss, oss_label in [(True, "OSS4SG"), (False, "ConvOSS")]:
            subset = df[(df["is_event"] == 1) &
                        (df["is_mentorship"] == is_mentor) &
                        (df["is_oss4sg"] == is_oss)]
            label = f"{mentor_label}-{oss_label}"
            n_achieved = int(subset["achieved_core"].sum())
            n_total = len(subset)
            rate = (n_achieved / n_total * 100) if n_total > 0 else 0
            median_time = float(subset[subset["achieved_core"] == 1]["survival_months"].median()) \
                if n_achieved > 0 else None
            subgroups[label] = {
                "n": n_total,
                "achieved_core": n_achieved,
                "rate_pct": round(rate, 2),
                "median_months_to_core": round(median_time, 1) if median_time is not None else None,
            }
            print(f"  {label}: n={n_total}, core={n_achieved} ({rate:.1f}%), "
                  f"median months={median_time}")

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
    milestone_df.to_csv(os.path.join(OUTPUT_DIR, "core_achievement_milestones.csv"), index=False)
    print(f"\nSaved: core_achievement_milestones.csv")

    # Save results
    results = {
        "log_rank_tests": [
            {"comparison": label, "chi2": chi2, "p_value": pval,
             "bonferroni_alpha": BONFERRONI_ALPHA,
             "significant_after_correction": pval < BONFERRONI_ALPHA}
            for label, chi2, pval, sig in logrank_results
        ],
        "cox_ph": cox_results,
        "subgroup_4way": subgroups,
        "milestones_pct_core": {
            "months": MILESTONES,
            "event": [event_milestones.get(m) for m in MILESTONES],
            "organic": [organic_milestones.get(m) for m in MILESTONES],
            "mentorship": [mentor_milestones.get(m) for m in MILESTONES] if mentor_milestones else None,
            "non_mentorship": [nonmentor_milestones.get(m) for m in MILESTONES] if nonmentor_milestones else None,
        },
        "n_event": int((df["is_event"] == 1).sum()),
        "n_organic": int((df["is_event"] == 0).sum()),
        "n_achieved_core": int(df["achieved_core"].sum()),
        "n_censored": int((df["achieved_core"] == 0).sum()),
        "bonferroni_n_tests": N_LOGRANK_TESTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
    }

    with open(os.path.join(OUTPUT_DIR, "survival_core_results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"Saved: survival_core_results.json")
    print(f"Saved: per_contributor_core_survival.csv")
    print(f"Saved: survival_core_km.png")
    print("\nPHASE 6 COMPLETE")


if __name__ == "__main__":
    main()
