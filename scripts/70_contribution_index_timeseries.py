#!/usr/bin/env python3
"""
Phase 7a: Contribution Index Time Series.

Build weekly CI time series for all contributors (event + organic).
Two versions:
  1. Full CI (uses commits + PRs + issues + comments) -- mainly useful for event
  2. Commit-only CI -- for fair event vs organic comparison

Data sources:
  - Commits: T7 CSVs (for all contributors)
  - PRs, issues, comments: journey JSON (mainly for event)

Output: 08_analysis_results/ci_timeseries/ with per-contributor JSON files
        08_analysis_results/ci_timeseries_index.json (master index)
"""

import json
import os
import pandas as pd
import numpy as np
from collections import defaultdict
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7_EXTRACTED = "/Volumes/T7/Event based OSS4SG/extracted"
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results", "ci_timeseries")

os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_journey_data():
    """Load journey data from the consolidated JSON.
    Returns two dicts keyed by contribution_id -> journey data."""
    journey_path = os.path.join(BASE, "06_final_dataset",
                                "complete_contributor_journeys.json")
    with open(journey_path) as f:
        data = json.load(f)

    event_journeys = {}
    for j in data["event_journeys"]:
        event_journeys[j["contribution_id"]] = j

    organic_journeys = {}
    for j in data["organic_journeys"]:
        key = j["matched_event_contribution_id"] + "__organic"
        organic_journeys[key] = j

    return event_journeys, organic_journeys


def load_repo_commits(csv_path):
    """Load all commits from a repo CSV. Returns a DataFrame with parsed dates."""
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path,
                         usecols=["author_name", "author_email", "author_date"],
                         dtype={"author_name": str, "author_email": str})
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path,
                         usecols=["author_name", "author_email", "author_date"],
                         encoding="latin-1",
                         dtype={"author_name": str, "author_email": str})
    except Exception:
        return None

    df["author_date"] = pd.to_datetime(df["author_date"], errors="coerce", utc=True)
    df = df.dropna(subset=["author_date"])
    df["author_email"] = df["author_email"].str.lower()
    return df


def find_contributor_emails(repo_df, email=None, username=None):
    """Find all matching emails for a contributor in the repo."""
    emails = set()
    if email:
        e_lower = email.lower()
        # Direct match
        if e_lower in repo_df["author_email"].values:
            emails.add(e_lower)
        else:
            # Substring match
            for e in repo_df["author_email"].unique():
                if e_lower in str(e) or str(e) in e_lower:
                    emails.add(str(e))

    if username and len(username) > 3:
        u = username.lower()
        for e in repo_df["author_email"].unique():
            if u in str(e):
                emails.add(str(e))
        # Also check names
        for _, row in repo_df[["author_name", "author_email"]].drop_duplicates().iterrows():
            if pd.notna(row["author_name"]) and u in str(row["author_name"]).lower():
                emails.add(str(row["author_email"]).lower())

    return emails


def build_weekly_ci(contributor_commits_df, journey_data=None, max_weeks=52):
    """Build weekly CI time series for a single contributor.

    Args:
        contributor_commits_df: DataFrame of this contributor's commits from T7
        journey_data: dict with pull_requests, issues from journey JSON (optional)
        max_weeks: maximum number of weeks to include (for normalization)

    Returns:
        dict with 'commit_ci' (commit-only) and 'full_ci' (full CI with PRs etc.)
        Each is a list of weekly values.
    """
    if contributor_commits_df.empty:
        return None

    dates = contributor_commits_df["author_date"].sort_values()
    first_date = dates.iloc[0]
    last_date = dates.iloc[-1]

    # Determine time span
    total_days = (last_date - first_date).days
    if total_days <= 0:
        # Single commit or all on same day
        return {
            "commit_ci": [1.0],
            "full_ci": [1.0],
            "n_weeks": 1,
            "first_date": str(first_date.date()),
            "last_date": str(last_date.date()),
            "total_commits": len(dates),
        }

    # Create weekly bins from first_date
    week_start = first_date
    weeks = []
    while week_start <= last_date:
        week_end = week_start + pd.Timedelta(days=7)
        weeks.append((week_start, week_end))
        week_start = week_end

    n_weeks = len(weeks)

    # --- Commit-only CI ---
    commit_counts = []
    for ws, we in weeks:
        mask = (dates >= ws) & (dates < we)
        commit_counts.append(int(mask.sum()))

    # --- Full CI (with PRs, issues, comments) ---
    pr_merged_counts = [0] * n_weeks
    comment_counts = [0] * n_weeks
    issue_counts = [0] * n_weeks

    if journey_data:
        # PRs merged
        for pr in journey_data.get("pull_requests", []):
            if pr.get("merged_at"):
                try:
                    merged_dt = pd.Timestamp(pr["merged_at"], tz="UTC")
                    for i, (ws, we) in enumerate(weeks):
                        if ws <= merged_dt < we:
                            pr_merged_counts[i] += 1
                            break
                except Exception:
                    pass

        # Issues opened
        for issue in journey_data.get("issues", []):
            if issue.get("created_at"):
                try:
                    created_dt = pd.Timestamp(issue["created_at"], tz="UTC")
                    for i, (ws, we) in enumerate(weeks):
                        if ws <= created_dt < we:
                            issue_counts[i] += 1
                            break
                except Exception:
                    pass

        # Comments (from issues)
        for issue in journey_data.get("issues", []):
            n_comments = issue.get("comments", 0)
            if n_comments > 0 and issue.get("created_at"):
                try:
                    created_dt = pd.Timestamp(issue["created_at"], tz="UTC")
                    for i, (ws, we) in enumerate(weeks):
                        if ws <= created_dt < we:
                            comment_counts[i] += n_comments
                            break
                except Exception:
                    pass

    # Compute CI per week
    # CI(week) = 0.25*commits + 0.20*prs_merged + 0.15*comments
    #          + 0.15*issues_opened + 0.15*active_days_norm + 0.10*duration
    commit_ci = []
    full_ci = []

    for i in range(n_weeks):
        c = commit_counts[i]
        pr_m = pr_merged_counts[i]
        comm = comment_counts[i]
        iss = issue_counts[i]

        # Active days: how many days in this week had any activity
        ws, we = weeks[i]
        active_days = 0
        for d in dates:
            if ws <= d < we:
                active_days += 1
        # Normalize to [0, 1]
        active_days_norm = min(active_days, 7) / 7.0

        # Duration: proportion of active weeks in last 4 weeks
        lookback_start = max(0, i - 3)
        active_in_window = sum(1 for j in range(lookback_start, i + 1)
                               if commit_counts[j] > 0 or pr_merged_counts[j] > 0
                               or comment_counts[j] > 0 or issue_counts[j] > 0)
        window_size = i - lookback_start + 1
        duration = active_in_window / max(window_size, 1)

        # Commit-only CI: just normalized commit count
        commit_ci.append(float(c))

        # Full CI
        ci_val = (0.25 * c + 0.20 * pr_m + 0.15 * comm
                  + 0.15 * iss + 0.15 * active_days_norm + 0.10 * duration)
        full_ci.append(float(ci_val))

    return {
        "commit_ci": commit_ci,
        "full_ci": full_ci,
        "n_weeks": n_weeks,
        "first_date": str(first_date.date()),
        "last_date": str(last_date.date()),
        "total_commits": int(len(dates)),
    }


def main():
    print("=" * 70)
    print("PHASE 7a: Contribution Index Time Series")
    print("=" * 70)

    # Load journey data for PR/issue/comment info
    print("Loading journey data...")
    event_journeys, organic_journeys = load_journey_data()
    print(f"  Event journeys: {len(event_journeys)}")
    print(f"  Organic journeys: {len(organic_journeys)}")

    # Load contributors
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "event_contributors_v2.json")) as f:
        event_contribs = json.load(f)["contributions"]

    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "organic_matches_v2.json")) as f:
        organic_matches = json.load(f)["matches"]

    # Group by repo for efficient CSV reading
    repo_contributors = defaultdict(list)

    for ec in event_contribs:
        cid = ec["contribution_id"]
        repo_contributors[ec["repo"]].append({
            "contribution_id": cid,
            "contributor_type": "event",
            "event_type": ec["event"],
            "username": ec["github_username"],
            "email": None,
            "is_mentorship": ec["event"] in ("gsoc", "lfx"),
            "journey": event_journeys.get(cid),
        })

    for om in organic_matches:
        cid = om["event_contribution_id"] + "__organic"
        repo_contributors[om["repo"]].append({
            "contribution_id": cid,
            "contributor_type": "organic",
            "event_type": om["event_type"],
            "username": None,
            "email": om["organic_email"],
            "is_mentorship": False,
            "journey": organic_journeys.get(cid),
        })

    print(f"\nProcessing {len(repo_contributors)} repos...")

    index = []
    processed = 0
    skipped = 0

    for ri, (repo, contribs) in enumerate(repo_contributors.items()):
        if (ri + 1) % 50 == 0:
            print(f"  Repo {ri+1}/{len(repo_contributors)}: {repo} "
                  f"(processed={processed}, skipped={skipped})")

        csv_path = os.path.join(T7_EXTRACTED, repo.replace("/", "__") + ".csv")
        repo_df = load_repo_commits(csv_path)
        if repo_df is None:
            skipped += len(contribs)
            continue

        for c in contribs:
            # Find this contributor's commits
            emails = find_contributor_emails(
                repo_df, c["email"], c["username"])

            if not emails:
                skipped += 1
                continue

            contributor_df = repo_df[repo_df["author_email"].isin(emails)]
            if contributor_df.empty:
                skipped += 1
                continue

            # Build CI time series
            ci_data = build_weekly_ci(contributor_df, c["journey"])
            if ci_data is None:
                skipped += 1
                continue

            # Save individual time series
            ci_data["contribution_id"] = c["contribution_id"]
            ci_data["contributor_type"] = c["contributor_type"]
            ci_data["event_type"] = c["event_type"]
            ci_data["is_mentorship"] = c["is_mentorship"]
            ci_data["repo"] = repo

            safe_id = c["contribution_id"].replace("/", "__").replace(" ", "_")
            out_path = os.path.join(OUTPUT_DIR, f"{safe_id}.json")
            with open(out_path, "w") as f:
                json.dump(ci_data, f)

            index.append({
                "contribution_id": c["contribution_id"],
                "contributor_type": c["contributor_type"],
                "event_type": c["event_type"],
                "is_mentorship": c["is_mentorship"],
                "repo": repo,
                "n_weeks": ci_data["n_weeks"],
                "total_commits": ci_data["total_commits"],
                "file": f"{safe_id}.json",
            })
            processed += 1

    # Save master index
    index_path = os.path.join(OUTPUT_DIR, "ci_timeseries_index.json")
    with open(index_path, "w") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "total_processed": processed,
            "total_skipped": skipped,
            "entries": index,
        }, f, indent=2)

    print(f"\n{'='*70}")
    print(f"PHASE 7a COMPLETE")
    print(f"  Processed: {processed}")
    print(f"  Skipped: {skipped}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Index: {index_path}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
