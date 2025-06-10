#!/usr/bin/env python3
"""
Build monthly Contribution Index (CI) time series for all 4,002 contributors.

For each contributor, for each month of activity:
  CI = 0.35*commits + 0.25*prs_opened + 0.20*prs_merged + 0.20*issues_opened

Pipeline:
  1. Load journeys (PR/issue dates already available)
  2. Load 13M commit CSV -> build (repo, email) -> {YYYYMM: count} index
  3. Match event contributors to their commit emails (noreply patterns)
  4. Build monthly CI time series per contributor
  5. Save results + print distribution stats

Re-runnable: outputs saved to 08_analysis_results/contribution_index_timeseries.json
Fast: ~60s for CSV indexing, ~5s for CI computation

Usage:
  python3 scripts/76_contribution_index.py
"""

import json, os, sys, csv, time, re
from collections import defaultdict, Counter
from datetime import datetime

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNEYS_PATH = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")
COMMIT_CSV = os.path.join(BASE, "04_contributor_selection_and_organic_matching", "outputs", "all_commits_consolidated.csv")
USERNAME_MAP_PATH = os.path.join(BASE, "05_contributor_journey_extraction", "organic_usernames.json")
OUTPUT_DIR = os.path.join(BASE, "08_analysis_results")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "contribution_index_timeseries.json")

# CI weights
W_COMMITS = 0.35
W_PRS_OPENED = 0.25
W_PRS_MERGED = 0.20
W_ISSUES = 0.20


def ym(datestr):
    """Extract YYYY-MM from ISO date string."""
    if not datestr or not isinstance(datestr, str):
        return None
    try:
        return datestr[:7]  # "2020-03-15T..." -> "2020-03"
    except Exception:
        return None


def months_between(start_ym, end_ym):
    """Generate all YYYY-MM between start and end inclusive."""
    sy, sm = int(start_ym[:4]), int(start_ym[5:7])
    ey, em = int(end_ym[:4]), int(end_ym[5:7])
    months = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def build_commit_index():
    """Read 13M commit CSV, build (repo, email) -> {YYYYMM: count}."""
    print("  [1/5] Building commit index from CSV...")
    t0 = time.time()

    # We need: for each (repo, email) -> monthly commit counts
    # Also: for each repo -> set of (email, author_name) for matching
    commit_index = {}  # (repo, email) -> Counter({YYYYMM: count})
    repo_emails = defaultdict(dict)  # repo -> {email_lower: email_original}
    repo_name_to_emails = defaultdict(lambda: defaultdict(set))  # repo -> {name_lower: set(emails)}

    rows_read = 0
    with open(COMMIT_CSV, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        # repo_name, author_email, author_name, author_date, subject
        for row in reader:
            rows_read += 1
            if len(row) < 4:
                continue
            repo, email, name, date = row[0], row[1], row[2], row[3]
            month = ym(date)
            if not month or not email:
                continue

            key = (repo, email)
            if key not in commit_index:
                commit_index[key] = Counter()
            commit_index[key][month] += 1

            email_lower = email.lower()
            repo_emails[repo][email_lower] = email
            if name:
                repo_name_to_emails[repo][name.lower()].add(email_lower)

            if rows_read % 2_000_000 == 0:
                elapsed = time.time() - t0
                print(f"    {rows_read/1e6:.0f}M rows... ({elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"    Done: {rows_read:,} rows, {len(commit_index):,} (repo,email) pairs in {elapsed:.1f}s")
    return commit_index, repo_emails, repo_name_to_emails


def find_event_commits(username, repo, commit_index, repo_emails, repo_name_to_emails):
    """Find monthly commit counts for an event contributor by trying email patterns."""
    # Strategy 1: noreply email
    noreply = f"{username}@users.noreply.github.com"
    key = (repo, noreply)
    if key in commit_index:
        return commit_index[key]

    # Strategy 2: ID+username noreply pattern
    repo_email_set = repo_emails.get(repo, {})
    username_lower = username.lower()
    for email_lower, email_orig in repo_email_set.items():
        if email_lower.endswith(f"+{username_lower}@users.noreply.github.com"):
            key = (repo, email_orig)
            if key in commit_index:
                return commit_index[key]

    # Strategy 3: email contains username (e.g., username@gmail.com)
    for email_lower, email_orig in repo_email_set.items():
        local = email_lower.split("@")[0]
        if local == username_lower:
            key = (repo, email_orig)
            if key in commit_index:
                return commit_index[key]

    # Strategy 4: author_name matches username
    name_emails = repo_name_to_emails.get(repo, {})
    if username_lower in name_emails:
        # Use the first matching email
        for email_lower in name_emails[username_lower]:
            email_orig = repo_email_set.get(email_lower, email_lower)
            key = (repo, email_orig)
            if key in commit_index:
                return commit_index[key]

    return None


def build_contributor_ci(j, contributor_type, commit_months, commit_count_total):
    """Build monthly CI time series for one contributor."""
    # Collect all monthly activity
    monthly = defaultdict(lambda: {"commits": 0, "prs_opened": 0, "prs_merged": 0, "issues": 0})

    # Commits
    if commit_months:
        for m, count in commit_months.items():
            monthly[m]["commits"] += count
    elif commit_count_total and commit_count_total > 0:
        # Fallback: spread commits across months with PR/issue activity
        pass  # will handle after collecting PR/issue months

    # PRs
    for pr in j.get("pull_requests", []):
        m = ym(pr.get("created_at"))
        if m:
            monthly[m]["prs_opened"] += 1
        mm = ym(pr.get("merged_at"))
        if mm:
            monthly[mm]["prs_merged"] += 1

    # Issues
    for iss in j.get("issues", []):
        m = ym(iss.get("created_at"))
        if m:
            monthly[m]["issues"] += 1

    # If no commit dates found but we have a commit count, spread across known months
    if not commit_months and commit_count_total and commit_count_total > 0 and monthly:
        n_months = len(monthly)
        per_month = commit_count_total / n_months
        for m in list(monthly.keys()):
            monthly[m]["commits"] += per_month

    if not monthly:
        return None

    # Build continuous time series (fill gaps with 0)
    all_months = sorted(monthly.keys())
    if len(all_months) < 1:
        return None

    full_months = months_between(all_months[0], all_months[-1])

    ci_series = []
    raw_series = []
    for m in full_months:
        d = monthly.get(m, {"commits": 0, "prs_opened": 0, "prs_merged": 0, "issues": 0})
        ci = (W_COMMITS * d["commits"] +
              W_PRS_OPENED * d["prs_opened"] +
              W_PRS_MERGED * d["prs_merged"] +
              W_ISSUES * d["issues"])
        ci_series.append(round(ci, 4))
        raw_series.append({
            "month": m,
            "commits": round(d["commits"], 2),
            "prs_opened": d["prs_opened"],
            "prs_merged": d["prs_merged"],
            "issues": d["issues"],
            "ci": round(ci, 4),
        })

    return {
        "months": full_months,
        "ci": ci_series,
        "length": len(full_months),
        "start": full_months[0],
        "end": full_months[-1],
        "total_ci": round(sum(ci_series), 4),
        "max_ci": round(max(ci_series), 4),
        "raw": raw_series,
    }


def main():
    t_start = time.time()

    print("=" * 60)
    print("CONTRIBUTION INDEX TIME SERIES BUILDER")
    print("=" * 60)

    # Load journeys
    print("\n  Loading journeys...")
    with open(JOURNEYS_PATH) as f:
        journeys_data = json.load(f)
    ev_journeys = journeys_data["event_journeys"]
    org_journeys = journeys_data["organic_journeys"]

    username_map = {}
    if os.path.exists(USERNAME_MAP_PATH):
        with open(USERNAME_MAP_PATH) as f:
            username_map = json.load(f)

    print(f"    Event: {len(ev_journeys)}, Organic: {len(org_journeys)}")
    print(f"    Organic usernames: {len(username_map)}")

    # Build commit index
    commit_index, repo_emails, repo_name_to_emails = build_commit_index()

    # Process contributors
    print("\n  [2/5] Building CI for event contributors...")
    t1 = time.time()

    results = {"event": [], "organic": []}
    ev_commit_matched = 0
    ev_commit_fallback = 0
    ev_no_data = 0

    for i, j in enumerate(ev_journeys):
        username = j.get("github_username", "")
        repo = j.get("repo", "")
        commit_count = j.get("commit_count", j.get("activity", 0))
        if isinstance(commit_count, list):
            commit_count = len(commit_count)

        commit_months = None
        if username and repo:
            commit_months = find_event_commits(username, repo, commit_index, repo_emails, repo_name_to_emails)

        if commit_months:
            ev_commit_matched += 1
        elif commit_count and commit_count > 0:
            ev_commit_fallback += 1

        ci_data = build_contributor_ci(j, "event", commit_months, commit_count)
        if ci_data:
            ci_data["username"] = username
            ci_data["repo"] = repo
            ci_data["event_type"] = j.get("event", "")
            ci_data["contributor_type"] = "event"
            ci_data["commit_source"] = "csv" if commit_months else ("spread" if commit_count else "none")
            results["event"].append(ci_data)
        else:
            ev_no_data += 1

        if (i + 1) % 500 == 0:
            print(f"    {i+1}/{len(ev_journeys)}...")

    t2 = time.time()
    print(f"    Event done: {len(results['event'])}/{len(ev_journeys)} with CI "
          f"(commits: {ev_commit_matched} from CSV, {ev_commit_fallback} spread, {ev_no_data} no data) "
          f"in {t2-t1:.1f}s")

    # Organic
    print("\n  [3/5] Building CI for organic contributors...")
    t3 = time.time()
    org_commit_matched = 0
    org_commit_fallback = 0
    org_no_data = 0

    for i, j in enumerate(org_journeys):
        email = j.get("organic_email", "")
        repo = j.get("repo", "")
        username = j.get("github_username", username_map.get(email, ""))
        commit_count = j.get("organic_commits", j.get("commit_count", 0))
        if isinstance(commit_count, list):
            commit_count = len(commit_count)

        # Try email match first
        commit_months = None
        key = (repo, email)
        if key in commit_index:
            commit_months = commit_index[key]
        elif username:
            # Try username-based matching
            commit_months = find_event_commits(username, repo, commit_index, repo_emails, repo_name_to_emails)

        if commit_months:
            org_commit_matched += 1
        elif commit_count and commit_count > 0:
            org_commit_fallback += 1

        ci_data = build_contributor_ci(j, "organic", commit_months, commit_count)
        if ci_data:
            ci_data["email"] = email
            ci_data["username"] = username
            ci_data["repo"] = repo
            ci_data["contributor_type"] = "organic"
            ci_data["commit_source"] = "csv" if commit_months else ("spread" if commit_count else "none")
            results["organic"].append(ci_data)
        else:
            org_no_data += 1

        if (i + 1) % 500 == 0:
            print(f"    {i+1}/{len(org_journeys)}...")

    t4 = time.time()
    print(f"    Organic done: {len(results['organic'])}/{len(org_journeys)} with CI "
          f"(commits: {org_commit_matched} from CSV, {org_commit_fallback} spread, {org_no_data} no data) "
          f"in {t4-t3:.1f}s")

    # Min-max normalize each time series to [0, 1]
    print("\n  [4/5] Normalizing time series (per-contributor min-max to [0,1])...")
    for group in ["event", "organic"]:
        for entry in results[group]:
            ci = entry["ci"]
            mn = min(ci)
            mx = max(ci)
            rng = mx - mn
            if rng > 0:
                entry["ci_normalized"] = [round((v - mn) / rng, 4) for v in ci]
            else:
                entry["ci_normalized"] = [0.0] * len(ci)

    # Save (without raw to keep file smaller)
    print("\n  [5/5] Saving results...")
    save_data = {"event": [], "organic": []}
    for group in ["event", "organic"]:
        for entry in results[group]:
            save_entry = {k: v for k, v in entry.items() if k != "raw"}
            save_data[group].append(save_entry)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(save_data, f)
    print(f"    Saved: {OUTPUT_PATH}")

    # Stats
    t_end = time.time()
    print("\n" + "=" * 60)
    print("STATISTICS")
    print("=" * 60)

    all_lengths = []
    for group_label, group_key in [("Event", "event"), ("Organic", "organic")]:
        lengths = [e["length"] for e in results[group_key]]
        all_lengths.extend(lengths)
        if not lengths:
            print(f"\n  {group_label}: no data")
            continue

        lengths.sort()
        n = len(lengths)
        avg = sum(lengths) / n
        median = lengths[n // 2]
        p25 = lengths[n // 4]
        p75 = lengths[3 * n // 4]
        p90 = lengths[int(n * 0.9)]
        mn = min(lengths)
        mx = max(lengths)

        print(f"\n  {group_label} ({n} contributors):")
        print(f"    Length (months): min={mn}, p25={p25}, median={median}, mean={avg:.1f}, p75={p75}, p90={p90}, max={mx}")

        # Distribution buckets
        buckets = [(1, 3), (4, 6), (7, 12), (13, 24), (25, 48), (49, 72), (73, 96), (97, 120), (121, 999)]
        print(f"    Distribution:")
        for lo, hi in buckets:
            count = sum(1 for l in lengths if lo <= l <= hi)
            pct = count / n * 100
            label = f"{lo}-{hi}" if hi < 999 else f"{lo}+"
            bar = "#" * int(pct / 2)
            print(f"      {label:>7} months: {count:>4} ({pct:5.1f}%) {bar}")

    # Overall
    if all_lengths:
        all_lengths.sort()
        n = len(all_lengths)
        avg = sum(all_lengths) / n
        median = all_lengths[n // 2]
        print(f"\n  OVERALL ({n} contributors):")
        print(f"    Length: min={min(all_lengths)}, median={median}, mean={avg:.1f}, max={max(all_lengths)}")

        # Zero-CI months analysis
        total_months = sum(e["length"] for group in results.values() for e in group)
        zero_months = sum(sum(1 for v in e["ci"] if v == 0) for group in results.values() for e in group)
        print(f"    Total month-points: {total_months:,}")
        print(f"    Zero-CI months: {zero_months:,} ({zero_months/total_months*100:.1f}%)")

        # CI distribution
        all_ci = [v for group in results.values() for e in group for v in e["ci"] if v > 0]
        if all_ci:
            all_ci.sort()
            nc = len(all_ci)
            print(f"    Non-zero CI values: {nc:,}")
            print(f"    CI: min={min(all_ci):.2f}, median={all_ci[nc//2]:.2f}, mean={sum(all_ci)/nc:.2f}, "
                  f"p90={all_ci[int(nc*0.9)]:.2f}, max={max(all_ci):.2f}")

    print(f"\n  Total time: {t_end - t_start:.1f}s")
    print("=" * 60)
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
