#!/usr/bin/env python3
"""
Phase 3: Descriptive Statistics -- Core Contributor Counts + Time-to-Core.

Updated for MONTHLY cumulative core identification (script 50 v3).
Core data now includes:
  - last_evaluation: core list from final month (who is core)
  - first_core_month: {email: month} for time-to-core in months
  - yearly_cores: backward-compatible yearly snapshots

Reads each repo CSV only once, processes all contributors per repo.
"""

import json
import os
import csv
import pandas as pd
import numpy as np
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7_EXTRACTED = "/Volumes/T7/Event based OSS4SG/extracted"
CORE_DIR = os.path.join(BASE, "07_core_contributor_analysis")
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")

os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_oss4sg_repos():
    oss4sg = set()
    try:
        with open(os.path.join(BASE, "OSS4SG-Project-List.csv")) as f:
            reader = csv.DictReader(f)
            for row in reader:
                oss4sg.add(row["repo_name_with_owner"].strip().lower())
    except Exception:
        pass
    return oss4sg


def load_core_data(repo):
    fname = repo.replace("/", "__") + "_cores.json"
    path = os.path.join(CORE_DIR, fname)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def load_repo_author_index(csv_path):
    """Load a repo CSV and build an index: email -> (first_commit_period, last_commit_period).
    Also build name -> email mapping for fuzzy matching."""
    if not os.path.exists(csv_path):
        return {}, {}
    try:
        df = pd.read_csv(csv_path, usecols=["author_name", "author_email", "author_date"])
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, usecols=["author_name", "author_email", "author_date"],
                        encoding="latin-1")
    except Exception:
        return {}, {}
    
    df["author_date"] = pd.to_datetime(df["author_date"], errors="coerce", utc=True)
    df = df.dropna(subset=["author_date"])
    
    if df.empty:
        return {}, {}
    
    # Build email index
    email_index = {}
    grouped = df.groupby("author_email")["author_date"].agg(["min", "max"])
    for email, row in grouped.iterrows():
        email_lower = str(email).lower()
        first_period = row["min"].to_period("M")
        last_period = row["max"].to_period("M")
        email_index[email_lower] = (first_period, last_period)
    
    # Build name -> emails mapping
    name_emails = defaultdict(set)
    for email, name in zip(df["author_email"], df["author_name"]):
        if pd.notna(name):
            name_emails[str(name).lower()].add(str(email).lower())
    
    return email_index, dict(name_emails)


def find_contributor_in_email_index(email_index, name_emails, email=None, username=None, resolved_info=None):
    """Find a contributor in the email index. Returns (first_period, last_period) or (None, None).
    
    resolved_info: optional dict from resolved_emails.json with 't7_match' key.
    """
    # Priority 1: Use resolved email data (pre-matched to T7)
    if resolved_info and resolved_info.get("t7_match"):
        t7 = resolved_info["t7_match"]
        try:
            first_p = pd.Period(t7["first_period"], freq="M")
            last_p = pd.Period(t7["last_period"], freq="M")
            return first_p, last_p
        except Exception:
            pass
    
    # Priority 2: Use resolved email (try matching in index)
    if resolved_info and resolved_info.get("email"):
        resolved_email = resolved_info["email"].lower()
        if resolved_email in email_index:
            return email_index[resolved_email]
        # Try email prefix
        prefix = resolved_email.split("@")[0]
        if prefix and len(prefix) > 3:
            for e, periods in email_index.items():
                if prefix in e:
                    return periods
        # Try resolved name
        resolved_name = (resolved_info.get("name") or "").lower()
        if resolved_name and len(resolved_name) > 3:
            for n, emails_set in name_emails.items():
                if resolved_name in n or n in resolved_name:
                    for e in emails_set:
                        if e in email_index:
                            return email_index[e]
    
    # Priority 3: Direct email match
    if email:
        email_lower = email.lower()
        if email_lower in email_index:
            return email_index[email_lower]
        # Substring match
        for e, periods in email_index.items():
            if email_lower in e or e in email_lower:
                return periods
    
    # Priority 4: Username match
    if username and len(username) > 3:
        uname_lower = username.lower()
        for e, periods in email_index.items():
            if uname_lower in e:
                return periods
        for name, emails in name_emails.items():
            if uname_lower in name:
                for e in emails:
                    if e in email_index:
                        return email_index[e]
    
    return None, None


def build_search_terms(email=None, username=None, resolved_info=None):
    """Build sets of search emails and search names from contributor info."""
    search_emails = set()
    search_names = set()

    if email:
        search_emails.add(email.lower())
    if username and len(username) > 3:
        search_names.add(username.lower())

    if resolved_info:
        if resolved_info.get("email"):
            search_emails.add(resolved_info["email"].lower())
            prefix = resolved_info["email"].lower().split("@")[0]
            if prefix and len(prefix) > 3:
                search_names.add(prefix)
        if resolved_info.get("name"):
            search_names.add(resolved_info["name"].lower())
        if resolved_info.get("t7_match", {}).get("matched_email"):
            search_emails.add(resolved_info["t7_match"]["matched_email"].lower())

    return search_emails, search_names


def match_in_core_list(core_contributors, search_emails, search_names):
    """Check if any search term matches someone in the core list. Returns matched email or None."""
    for core_c in core_contributors:
        ce = str(core_c.get("email", "") or "").lower()
        cn = str(core_c.get("name", "") or "").lower()
        for se in search_emails:
            if se and ce and (se in ce or ce in se):
                return ce
        for sn in search_names:
            if sn and len(sn) > 3:
                if (ce and sn in ce) or (cn and sn in cn):
                    return ce
    return None


def check_core_and_time(core_data, email=None, username=None, resolved_info=None):
    """Check if a contributor is core (last evaluation) and find time-to-core in months.

    Uses:
      - last_evaluation (or yearly_cores fallback) for core identification
      - first_core_month dict for time-to-core

    Returns (is_core: bool, time_to_core_months: int or None, project_start: str or None).
    """
    if not core_data:
        return False, None, None

    project_start = core_data.get("project_start")
    search_emails, search_names = build_search_terms(email, username, resolved_info)

    # ── Step 1: Check if contributor is core in the last evaluation ──
    # Try last_evaluation first (new monthly format)
    last_eval = core_data.get("last_evaluation")
    if last_eval and last_eval.get("core_contributors"):
        matched_email = match_in_core_list(last_eval["core_contributors"], search_emails, search_names)
        is_core = matched_email is not None
    else:
        # Fallback to yearly_cores (old format)
        yearly_cores = core_data.get("yearly_cores", {})
        matched_email = None
        is_core = False
        for year_key in sorted(yearly_cores.keys(),
                               key=lambda k: yearly_cores[k].get("year_number", 0),
                               reverse=True):
            y_data = yearly_cores[year_key]
            if "skipped" not in y_data and y_data.get("core_contributors"):
                matched_email = match_in_core_list(y_data["core_contributors"], search_emails, search_names)
                is_core = matched_email is not None
                break

    # ── Step 2: Find time-to-core in months from first_core_month dict ──
    time_to_core_months = None
    if is_core and matched_email:
        fcm = core_data.get("first_core_month", {})
        # Direct match
        if matched_email in fcm:
            time_to_core_months = fcm[matched_email]
        else:
            # Try all search terms against the dict keys
            for se in search_emails:
                for fcm_email, month in fcm.items():
                    if se and fcm_email and (se in fcm_email or fcm_email in se):
                        time_to_core_months = month
                        break
                if time_to_core_months is not None:
                    break
            if time_to_core_months is None:
                for sn in search_names:
                    if sn and len(sn) > 3:
                        for fcm_email, month in fcm.items():
                            if sn in fcm_email:
                                time_to_core_months = month
                                break
                    if time_to_core_months is not None:
                        break

    return is_core, time_to_core_months, project_start


def main():
    print("=" * 70)
    print("PHASE 3: Descriptive Core Contributor Statistics")
    print("=" * 70)
    
    oss4sg_repos = load_oss4sg_repos()
    print(f"OSS4SG repos: {len(oss4sg_repos)}")
    
    # Load resolved emails (from script 55)
    resolved_path = os.path.join(OUTPUT_DIR, "resolved_emails.json")
    resolved_emails = {}
    if os.path.exists(resolved_path):
        with open(resolved_path) as f:
            resolved_emails = json.load(f)
        print(f"Loaded {len(resolved_emails)} resolved emails")
    else:
        print("No resolved_emails.json found (run script 55 first)")
    
    # Load contributors
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "event_contributors_v2.json")) as f:
        event_data = json.load(f)
    
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "organic_matches_v2.json")) as f:
        organic_data = json.load(f)
    
    event_contribs = event_data["contributions"]
    organic_matches = organic_data["matches"]
    
    print(f"Event contributors: {len(event_contribs)}")
    print(f"Organic contributors: {len(organic_matches)}")
    
    # Group all contributors by repo
    repo_contributors = defaultdict(list)
    
    for ec in event_contribs:
        cid = ec["contribution_id"]
        repo_contributors[ec["repo"]].append({
            "contributor_id": cid,
            "contributor_type": "event",
            "event_type": ec["event"],
            "username": ec["github_username"],
            "email": None,
            "is_mentorship": ec["event"] in ("gsoc", "lfx"),
            "resolved_info": resolved_emails.get(cid),
        })
    
    for om in organic_matches:
        repo_contributors[om["repo"]].append({
            "contributor_id": om["event_contribution_id"] + "__organic",
            "contributor_type": "organic",
            "event_type": om["event_type"],
            "username": None,
            "email": om["organic_email"],
            "is_mentorship": False,
            "resolved_info": None,
        })
    
    unique_repos = list(repo_contributors.keys())
    print(f"Unique repos to process: {len(unique_repos)}")
    
    # Process each repo
    all_results = []
    
    for ri, repo in enumerate(unique_repos):
        if (ri + 1) % 50 == 0:
            print(f"  Repo {ri+1}/{len(unique_repos)}: {repo}")
        
        contribs = repo_contributors[repo]
        
        # Load core data (once per repo)
        core_data = load_core_data(repo)
        
        # Load repo author index (once per repo)
        csv_path = os.path.join(T7_EXTRACTED, repo.replace("/", "__") + ".csv")
        email_index, name_emails = load_repo_author_index(csv_path)
        
        is_oss4sg = repo.lower() in oss4sg_repos
        
        # Get project start date for time-to-core calculation
        project_start_str = core_data.get("project_start") if core_data else None
        
        for c in contribs:
            email = c["email"]
            username = c["username"]
            resolved_info = c.get("resolved_info")
            
            # Find first commit period (with resolved email fallback)
            first_period, last_period = find_contributor_in_email_index(
                email_index, name_emails, email, username, resolved_info)
            
            # Check if contributor is core + time-to-core in months
            is_core, ttc_months, _ = check_core_and_time(
                core_data, email, username, resolved_info)
            
            all_results.append({
                "contributor_id": c["contributor_id"],
                "contributor_type": c["contributor_type"],
                "event_type": c["event_type"],
                "repo": repo,
                "username_or_email": username or email,
                "ever_core": is_core,
                "time_to_core_months": ttc_months,
                "first_commit_period": str(first_period) if first_period else None,
                "is_oss4sg": is_oss4sg,
                "is_mentorship": c["is_mentorship"],
            })
    
    # Save per-contributor results
    results_df = pd.DataFrame(all_results)
    results_path = os.path.join(OUTPUT_DIR, "per_contributor_core_status.csv")
    results_df.to_csv(results_path, index=False)
    print(f"\nSaved: {results_path} ({len(results_df)} rows)")
    
    # --- Compute statistics ---
    print("\n" + "=" * 70)
    print("DESCRIPTIVE STATISTICS")
    print("=" * 70)
    
    def compute_group_stats(df, label):
        n = len(df)
        core_count = int(df["ever_core"].sum())
        not_core = n - core_count
        rate = (core_count / n * 100) if n > 0 else 0
        
        # Time-to-core stats (only for those who are core)
        core_with_ttc = df[df["ever_core"] & df["time_to_core_months"].notna()]["time_to_core_months"]
        ttc_median = round(core_with_ttc.median(), 1) if len(core_with_ttc) > 0 else None
        ttc_mean = round(core_with_ttc.mean(), 1) if len(core_with_ttc) > 0 else None
        ttc_q1 = round(core_with_ttc.quantile(0.25), 1) if len(core_with_ttc) > 0 else None
        ttc_q3 = round(core_with_ttc.quantile(0.75), 1) if len(core_with_ttc) > 0 else None
        
        stats = {
            "group": label,
            "total": n,
            "is_core": core_count,
            "not_core": not_core,
            "core_rate_pct": round(rate, 2),
            "ttc_n": len(core_with_ttc),
            "ttc_median_months": ttc_median,
            "ttc_mean_months": ttc_mean,
            "ttc_q1_months": ttc_q1,
            "ttc_q3_months": ttc_q3,
        }
        
        return stats
    
    event_df = results_df[results_df["contributor_type"] == "event"]
    organic_df = results_df[results_df["contributor_type"] == "organic"]
    
    groups = []
    groups.append(compute_group_stats(event_df, "Event-All"))
    groups.append(compute_group_stats(event_df[event_df["event_type"] == "gsoc"], "GSoC"))
    groups.append(compute_group_stats(event_df[event_df["event_type"] == "lfx"], "LFX"))
    groups.append(compute_group_stats(event_df[event_df["event_type"] == "24pr"], "24PR"))
    groups.append(compute_group_stats(event_df[event_df["event_type"] == "hacktoberfest"], "HF"))
    groups.append(compute_group_stats(organic_df, "Organic-All"))
    
    mentorship = event_df[event_df["is_mentorship"]]
    non_mentorship = event_df[~event_df["is_mentorship"]]
    groups.append(compute_group_stats(mentorship, "Mentorship (GSoC+LFX)"))
    groups.append(compute_group_stats(non_mentorship, "Non-Mentorship (24PR+HF)"))
    
    oss4sg_event = event_df[event_df["is_oss4sg"]]
    oss_event = event_df[~event_df["is_oss4sg"]]
    oss4sg_organic = organic_df[organic_df["is_oss4sg"]]
    oss_organic = organic_df[~organic_df["is_oss4sg"]]
    
    groups.append(compute_group_stats(oss4sg_event, "Event-OSS4SG"))
    groups.append(compute_group_stats(oss_event, "Event-ConvOSS"))
    groups.append(compute_group_stats(oss4sg_organic, "Organic-OSS4SG"))
    groups.append(compute_group_stats(oss_organic, "Organic-ConvOSS"))
    
    # Print core rate table
    header = f"{'Group':<25} {'Total':>6} {'Core':>6} {'NotCore':>8} {'Rate%':>7}"
    print(f"\n{header}")
    print("-" * len(header))
    for g in groups:
        print(f"{g['group']:<25} {g['total']:>6} {g['is_core']:>6} {g['not_core']:>8} "
              f"{g['core_rate_pct']:>7.2f}")
    
    # Print time-to-core table
    print(f"\n{'TIME TO CORE (months, for core contributors only)'}")
    ttc_header = f"{'Group':<25} {'n':>5} {'Median':>8} {'Mean':>8} {'Q1':>6} {'Q3':>6}"
    print(f"\n{ttc_header}")
    print("-" * len(ttc_header))
    for g in groups:
        if g['ttc_n'] and g['ttc_n'] > 0:
            print(f"{g['group']:<25} {g['ttc_n']:>5} {g['ttc_median_months']:>8.1f} "
                  f"{g['ttc_mean_months']:>8.1f} {g['ttc_q1_months']:>6.1f} {g['ttc_q3_months']:>6.1f}")
        else:
            print(f"{g['group']:<25} {'—':>5}")
    
    # Save statistics CSV
    stats_df = pd.DataFrame(groups)
    stats_path = os.path.join(OUTPUT_DIR, "descriptive_core_stats.csv")
    stats_df.to_csv(stats_path, index=False)
    print(f"\nSaved statistics: {stats_path}")
    
    print("\n" + "=" * 70)
    print("PHASE 3 COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
