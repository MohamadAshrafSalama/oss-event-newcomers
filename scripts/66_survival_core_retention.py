#!/usr/bin/env python3
"""
Phase 7: Survival Analysis #3 -- Core Contributor Retention After Achieving Core.

For contributors who achieved core status, how long do they remain active?
This answers the supervisor's question: "If mentorship helps people become core,
do those core contributors actually stay, or do they leave afterward?"

- Population: Only contributors who achieved core status
- "Survive" = still active after becoming core
- "Left" = no commit for >= 5 months after last commit (post-core)
- Survival time = months from achieving core to leaving (or data end)
- Uses Kaplan-Meier curves, Log-Rank test (Bonferroni corrected), Cox PH
- Milestone tables at 6-month increments
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
    """Load author dates and build index: email_lower -> (first_date, last_date)."""
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
    """Extract survival probabilities at specified month milestones."""
    results = {}
    sf = kmf.survival_function_
    for m in milestones:
        valid = sf.index[sf.index <= m]
        if len(valid) > 0:
            prob = float(sf.loc[valid[-1]].iloc[0])
        else:
            prob = 1.0
        results[m] = round(prob * 100, 1)  # as percentage
    return results


def main():
    print("=" * 70)
    print("PHASE 7: Core Contributor Retention After Achieving Core")
    print("=" * 70)
    print("  Question: Once someone becomes core, do event-based core")
    print("  contributors stay longer than organic core contributors?")

    oss4sg_repos = load_oss4sg_repos()

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

    records = []
    skipped_no_csv = 0
    skipped_no_dates = 0
    skipped_not_core = 0

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

            if first_commit is None or last_commit is None:
                skipped_no_dates += 1
                continue

            resolved_info = None
            key = c["username"] or c["email"] or ""
            if key in resolved_emails:
                resolved_info = resolved_emails[key]

            # Check if this contributor achieved core
            first_core_month_num = find_first_core_month(
                core_data, c["email"], c["username"], resolved_info)

            if first_core_month_num is None:
                skipped_not_core += 1
                continue

            # Calculate the date they achieved core
            if project_start is not None:
                first_core_date = project_start + pd.DateOffset(months=int(first_core_month_num))
            else:
                # Fallback: use first_commit + first_core_month_num months
                first_core_date = first_commit + pd.DateOffset(months=int(first_core_month_num))

            # Post-core survival: from core achievement to leaving (or data end)
            months_since_last = (data_end - last_commit).days / 30.44

            if months_since_last >= LEAVE_THRESHOLD_MONTHS:
                # Left the project
                event_observed = 1
                post_core_months = max(0, (last_commit - first_core_date).days / 30.44)
            else:
                # Still active (censored)
                event_observed = 0
                post_core_months = max(0, (data_end - first_core_date).days / 30.44)

            records.append({
                "contributor_type": c["contributor_type"],
                "event_type": c["event_type"],
                "is_mentorship": c["is_mentorship"],
                "is_oss4sg": is_oss4sg,
                "repo": repo,
                "post_core_months": round(post_core_months, 2),
                "event_observed": event_observed,  # 1 = left after core, 0 = still active
                "is_event": 1 if c["contributor_type"] == "event" else 0,
                "first_core_month": first_core_month_num,
            })

    df = pd.DataFrame(records)
    csv_out = os.path.join(OUTPUT_DIR, "per_core_contributor_post_core_retention.csv")
    df.to_csv(csv_out, index=False)
    print(f"\nCore contributor records: {len(df)}")
    print(f"  Event core contributors: {(df['is_event']==1).sum()}")
    print(f"  Organic core contributors: {(df['is_event']==0).sum()}")
    print(f"  Left after core (event_observed=1): {df['event_observed'].sum()}")
    print(f"  Still active after core (censored): {(df['event_observed']==0).sum()}")
    print(f"  Skipped (no CSV): {skipped_no_csv}, no dates: {skipped_no_dates}, not core: {skipped_not_core}")

    if len(df) < 20:
        print("\nWARNING: Too few core contributors found. Results may not be reliable.")
        # Still proceed but note the warning

    # ── Collect log-rank tests for Bonferroni ──
    logrank_results = []
    N_LOGRANK_TESTS = 3
    BONFERRONI_ALPHA = 0.05 / N_LOGRANK_TESTS

    # --- Kaplan-Meier ---
    print("\n" + "-" * 50)
    print("KAPLAN-MEIER: Post-Core Retention")
    print(f"  Bonferroni correction: {N_LOGRANK_TESTS} tests, adjusted alpha = {BONFERRONI_ALPHA:.4f}")
    print("-" * 50)

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # ── Plot 1: Event vs Organic ──
    ax = axes[0, 0]
    event_data = df[df["is_event"] == 1]
    organic_data = df[df["is_event"] == 0]

    kmf_event = KaplanMeierFitter()
    kmf_organic = KaplanMeierFitter()

    event_milestones = {}
    organic_milestones = {}

    if len(event_data) > 5 and len(organic_data) > 5:
        kmf_event.fit(event_data["post_core_months"], event_data["event_observed"], label="Event (core)")
        kmf_event.plot_survival_function(ax=ax)

        kmf_organic.fit(organic_data["post_core_months"], organic_data["event_observed"], label="Organic (core)")
        kmf_organic.plot_survival_function(ax=ax)

        lr = logrank_test(
            event_data["post_core_months"], organic_data["post_core_months"],
            event_data["event_observed"], organic_data["event_observed"])
        sig_label = "SIGNIFICANT" if lr.p_value < BONFERRONI_ALPHA else "not significant"
        logrank_results.append(("Event vs Organic (core only)", float(lr.test_statistic), float(lr.p_value), sig_label))
        print(f"\n  Event vs Organic (core contributors only):")
        print(f"    Log-rank chi2={lr.test_statistic:.4f}, p={lr.p_value:.4e} ({sig_label})")
        print(f"    Event core median post-core retention: {kmf_event.median_survival_time_:.1f} months")
        print(f"    Organic core median post-core retention: {kmf_organic.median_survival_time_:.1f} months")

        event_milestones = extract_milestones(kmf_event)
        organic_milestones = extract_milestones(kmf_organic)

        print(f"\n  Milestone table (% still active after becoming core):")
        print(f"    {'Month':>6}  {'Event':>8}  {'Organic':>8}")
        for m in MILESTONES:
            print(f"    {m:>6}  {event_milestones[m]:>7.1f}%  {organic_milestones[m]:>7.1f}%")
    else:
        print("  Not enough data for Event vs Organic comparison")

    ax.set_title("Post-Core Retention: Event vs Organic")
    ax.set_xlabel("Months since achieving core")
    ax.set_ylabel("Probability of still being active")
    ax.set_xlim(0, 60)

    # ── Plot 2: Mentorship vs Non-Mentorship (core only) ──
    ax = axes[0, 1]
    mentor_data = df[(df["is_event"] == 1) & (df["is_mentorship"] == True)]
    non_mentor_data = df[(df["is_event"] == 1) & (df["is_mentorship"] == False)]

    mentor_milestones = {}
    nonmentor_milestones = {}

    if len(mentor_data) > 5 and len(non_mentor_data) > 5:
        kmf1 = KaplanMeierFitter()
        kmf1.fit(mentor_data["post_core_months"], mentor_data["event_observed"],
                 label="Mentorship (core)")
        kmf1.plot_survival_function(ax=ax)

        kmf2 = KaplanMeierFitter()
        kmf2.fit(non_mentor_data["post_core_months"], non_mentor_data["event_observed"],
                 label="Non-Mentorship (core)")
        kmf2.plot_survival_function(ax=ax)

        lr2 = logrank_test(
            mentor_data["post_core_months"], non_mentor_data["post_core_months"],
            mentor_data["event_observed"], non_mentor_data["event_observed"])
        sig_label2 = "SIGNIFICANT" if lr2.p_value < BONFERRONI_ALPHA else "not significant"
        logrank_results.append(("Mentorship vs Non-Mentorship (core)", float(lr2.test_statistic), float(lr2.p_value), sig_label2))
        print(f"\n  Mentorship vs Non-Mentorship (core contributors only):")
        print(f"    Log-rank chi2={lr2.test_statistic:.4f}, p={lr2.p_value:.4e} ({sig_label2})")

        mentor_milestones = extract_milestones(kmf1)
        nonmentor_milestones = extract_milestones(kmf2)

        print(f"\n  Milestone table (% still active after becoming core):")
        print(f"    {'Month':>6}  {'Mentorship':>12}  {'Non-Mentorship':>16}")
        for m in MILESTONES:
            print(f"    {m:>6}  {mentor_milestones[m]:>11.1f}%  {nonmentor_milestones[m]:>15.1f}%")
    else:
        print("  Not enough data for Mentorship vs Non-Mentorship comparison")

    ax.set_title("Post-Core Retention: Mentorship vs Non-Mentorship")
    ax.set_xlabel("Months since achieving core")
    ax.set_ylabel("Probability of still being active")
    ax.set_xlim(0, 60)

    # ── Plot 3: Per event type (core only) ──
    ax = axes[1, 0]
    event_type_milestones = {}
    for et in ["gsoc", "lfx", "24pr", "hacktoberfest"]:
        et_data = df[(df["is_event"] == 1) & (df["event_type"] == et)]
        if len(et_data) > 5:
            kmf = KaplanMeierFitter()
            kmf.fit(et_data["post_core_months"], et_data["event_observed"], label=et.upper())
            kmf.plot_survival_function(ax=ax)
            event_type_milestones[et.upper()] = extract_milestones(kmf)

    # Add organic reference
    if len(organic_data) > 5:
        kmf_ref = KaplanMeierFitter()
        kmf_ref.fit(organic_data["post_core_months"], organic_data["event_observed"], label="Organic")
        kmf_ref.plot_survival_function(ax=ax, ci_show=False, ls="--", color="gray")

    ax.set_title("Post-Core Retention by Event Type")
    ax.set_xlabel("Months since achieving core")
    ax.set_ylabel("Probability of still being active")
    ax.set_xlim(0, 60)

    # ── Plot 4: OSS4SG vs Conventional (core only) ──
    ax = axes[1, 1]
    oss4sg_data = df[df["is_oss4sg"] == True]
    conv_data = df[df["is_oss4sg"] == False]

    if len(oss4sg_data) > 5 and len(conv_data) > 5:
        kmf1 = KaplanMeierFitter()
        kmf1.fit(oss4sg_data["post_core_months"], oss4sg_data["event_observed"], label="OSS4SG (core)")
        kmf1.plot_survival_function(ax=ax)

        kmf2 = KaplanMeierFitter()
        kmf2.fit(conv_data["post_core_months"], conv_data["event_observed"], label="Conventional (core)")
        kmf2.plot_survival_function(ax=ax)

        lr3 = logrank_test(
            oss4sg_data["post_core_months"], conv_data["post_core_months"],
            oss4sg_data["event_observed"], conv_data["event_observed"])
        sig_label3 = "SIGNIFICANT" if lr3.p_value < BONFERRONI_ALPHA else "not significant"
        logrank_results.append(("OSS4SG vs Conventional (core)", float(lr3.test_statistic), float(lr3.p_value), sig_label3))
        print(f"\n  OSS4SG vs Conventional (core contributors only):")
        print(f"    Log-rank chi2={lr3.test_statistic:.4f}, p={lr3.p_value:.4e} ({sig_label3})")
    else:
        print("  Not enough data for OSS4SG vs Conventional comparison")

    ax.set_title("Post-Core Retention: OSS4SG vs Conventional")
    ax.set_xlabel("Months since achieving core")
    ax.set_ylabel("Probability of still being active")
    ax.set_xlim(0, 60)

    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "survival_core_retention_km.png"), dpi=150, bbox_inches="tight")
    print(f"\n  Saved KM plot: survival_core_retention_km.png")

    # ── Log-rank summary ──
    print("\n" + "-" * 50)
    print(f"LOG-RANK SUMMARY (Bonferroni-corrected, alpha={BONFERRONI_ALPHA:.4f})")
    print("-" * 50)
    for label, chi2, pval, sig in logrank_results:
        print(f"  {label:45s}: chi2={chi2:.4f}, p={pval:.4e} -> {sig}")

    # --- Cox Proportional Hazards ---
    print("\n" + "-" * 50)
    print("COX PROPORTIONAL HAZARDS MODEL (Post-Core Retention)")
    print("-" * 50)
    print("  HR > 1 => MORE likely to leave after becoming core")
    print("  HR < 1 => LESS likely to leave (stays longer)")

    cox_df = df[["post_core_months", "event_observed", "is_event",
                 "is_mentorship", "is_oss4sg"]].copy()
    cox_df["is_mentorship"] = cox_df["is_mentorship"].astype(int)
    cox_df["is_oss4sg"] = cox_df["is_oss4sg"].astype(int)

    # Handle zero-duration records
    cox_df = cox_df[cox_df["post_core_months"] > 0].copy()
    if len(cox_df) < 20:
        print("  Too few records for Cox PH model")
        cox_results = {"error": "too few records"}
    else:
        cph = CoxPHFitter()
        cox_results = {}
        try:
            cph.fit(cox_df, duration_col="post_core_months", event_col="event_observed")
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
                      f"p={r['p_value']:.4e} -> {direction} likely to leave after becoming core")
        except Exception as e:
            print(f"  Cox PH failed: {e}")
            cox_results = {"error": str(e)}

    # ── Save milestone table as CSV ──
    milestone_rows = []
    for m in MILESTONES:
        row = {"month": m}
        if event_milestones:
            row["event_core"] = event_milestones.get(m)
        if organic_milestones:
            row["organic_core"] = organic_milestones.get(m)
        if mentor_milestones:
            row["mentorship_core"] = mentor_milestones.get(m)
        if nonmentor_milestones:
            row["non_mentorship_core"] = nonmentor_milestones.get(m)
        for et_label, et_ms in event_type_milestones.items():
            row[et_label + "_core"] = et_ms.get(m)
        milestone_rows.append(row)
    milestone_df = pd.DataFrame(milestone_rows)
    milestone_df.to_csv(os.path.join(OUTPUT_DIR, "core_retention_milestones.csv"), index=False)
    print(f"\nSaved: core_retention_milestones.csv")

    # ── Save results ──
    results = {
        "analysis": "Post-Core Retention: How long do core contributors stay after achieving core?",
        "log_rank_tests": [
            {"comparison": label, "chi2": chi2, "p_value": pval,
             "bonferroni_alpha": BONFERRONI_ALPHA,
             "significant_after_correction": pval < BONFERRONI_ALPHA}
            for label, chi2, pval, sig in logrank_results
        ],
        "cox_ph": cox_results,
        "milestones_pct_active_post_core": {
            "months": MILESTONES,
            "event_core": [event_milestones.get(m) for m in MILESTONES] if event_milestones else None,
            "organic_core": [organic_milestones.get(m) for m in MILESTONES] if organic_milestones else None,
            "mentorship_core": [mentor_milestones.get(m) for m in MILESTONES] if mentor_milestones else None,
            "non_mentorship_core": [nonmentor_milestones.get(m) for m in MILESTONES] if nonmentor_milestones else None,
        },
        "n_event_core": int((df["is_event"] == 1).sum()),
        "n_organic_core": int((df["is_event"] == 0).sum()),
        "n_left_after_core": int(df["event_observed"].sum()),
        "n_still_active_after_core": int((df["event_observed"] == 0).sum()),
        "bonferroni_n_tests": N_LOGRANK_TESTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
    }

    with open(os.path.join(OUTPUT_DIR, "survival_core_retention_results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"Saved: survival_core_retention_results.json")
    print(f"Saved: per_core_contributor_post_core_retention.csv")
    print(f"Saved: survival_core_retention_km.png")
    print("\nPHASE 7 COMPLETE")


if __name__ == "__main__":
    main()
