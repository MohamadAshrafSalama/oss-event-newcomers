#!/usr/bin/env python3
"""
Resolve emails for event contributors who couldn't be matched to T7 git logs.

Problem: 713 event contributors have GitHub usernames that don't appear as
substrings in the T7 CSV author_email or author_name fields.

Solution: Use GitHub API to fetch one commit by each contributor in their repo,
extract the author.email from that commit, and save a mapping file.

Then re-run script 60 with this mapping as a fallback lookup.

Usage:
  python3 scripts/55_resolve_missing_emails.py
"""

import json
import os
import sys
import time
import gc
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

import pandas as pd

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7 = "/Volumes/T7/Event based OSS4SG/extracted"
OUTPUT = os.path.join(BASE, "08_analysis_results", "resolved_emails.json")
PROGRESS = os.path.join(BASE, "08_analysis_results", "resolve_progress.json")

# Load tokens
with open(os.path.join(BASE, "05_contributor_journey_extraction", "config.json")) as f:
    TOKENS = json.load(f).get("github_tokens", [])

print(f"Tokens: {len(TOKENS)}")


def api_get(url, token_idx):
    """Single GitHub API GET with error handling."""
    token = TOKENS[token_idx % len(TOKENS)]
    req = Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    try:
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read())
    except HTTPError as e:
        if e.code == 403:
            # Rate limited - wait and retry once
            time.sleep(5)
            try:
                resp = urlopen(req, timeout=15)
                return json.loads(resp.read())
            except Exception:
                return None
        elif e.code == 422:
            return None  # Unprocessable (user doesn't exist, etc.)
        elif e.code == 404:
            return None
        return None
    except Exception:
        return None


def resolve_one(username, repo, token_idx):
    """
    Resolve a GitHub username to their commit email in a specific repo.
    
    Strategy:
    1. Try GitHub commits API: /repos/{repo}/commits?author={username}&per_page=1
    2. If that fails, try /users/{username} for their public email
    3. Construct noreply email as last resort
    """
    # Strategy 1: Get a commit by this user in this repo
    url = f"https://api.github.com/repos/{repo}/commits?author={username}&per_page=1"
    data = api_get(url, token_idx)
    if data and isinstance(data, list) and len(data) > 0:
        commit = data[0].get("commit", {})
        author = commit.get("author", {})
        email = author.get("email", "")
        name = author.get("name", "")
        if email and "noreply" not in email.lower():
            return {"email": email, "name": name, "source": "repo_commits"}
        elif email:
            return {"email": email, "name": name, "source": "repo_commits_noreply"}

    # Strategy 2: Get user profile
    url2 = f"https://api.github.com/users/{username}"
    data2 = api_get(url2, token_idx)
    if data2 and isinstance(data2, dict):
        email = data2.get("email", "")
        name = data2.get("name", "")
        user_id = data2.get("id", "")
        if email:
            return {"email": email, "name": name or username, "source": "user_profile"}
        # Construct noreply email
        if user_id:
            noreply = f"{user_id}+{username}@users.noreply.github.com"
            return {"email": noreply, "name": name or username, "source": "noreply_constructed"}

    return None


def match_email_to_t7(email, name, repo):
    """Check if the resolved email or name exists in the T7 CSV for this repo."""
    csv_path = os.path.join(T7, repo.replace("/", "__") + ".csv")
    if not os.path.exists(csv_path):
        return None

    try:
        df = pd.read_csv(csv_path, usecols=["author_email", "author_name", "author_date"])
    except Exception:
        try:
            df = pd.read_csv(csv_path, usecols=["author_email", "author_name", "author_date"],
                            encoding="latin-1")
        except Exception:
            return None

    df["author_date"] = pd.to_datetime(df["author_date"], errors="coerce", utc=True)
    df = df.dropna(subset=["author_date"])
    if df.empty:
        return None

    email_lower = email.lower() if email else ""
    name_lower = name.lower() if name else ""

    # Try exact email match
    mask = df["author_email"].str.lower() == email_lower
    if not mask.any() and email_lower:
        # Try substring match
        mask = df["author_email"].str.lower().str.contains(email_lower.split("@")[0], na=False, regex=False)
    if not mask.any() and name_lower and len(name_lower) > 3:
        # Try name match
        mask = df["author_name"].str.lower().str.contains(name_lower, na=False, regex=False)
    if not mask.any() and name_lower:
        # Try first part of name
        first_name = name_lower.split()[0] if name_lower else ""
        if first_name and len(first_name) > 3:
            mask = df["author_name"].str.lower().str.contains(first_name, na=False, regex=False)

    if mask.any():
        dates = df.loc[mask, "author_date"]
        first = dates.min().to_period("M")
        last = dates.max().to_period("M")
        matched_email = df.loc[mask, "author_email"].iloc[0]
        return {
            "matched_email": matched_email,
            "first_period": str(first),
            "last_period": str(last),
            "n_commits": int(mask.sum())
        }

    return None


def main():
    print("=" * 70)
    print("RESOLVE MISSING EVENT CONTRIBUTOR EMAILS")
    print("=" * 70)

    # Load core status to find missing contributors
    core = pd.read_csv(os.path.join(BASE, "08_analysis_results", "per_contributor_core_status.csv"))
    missing = core[(core["first_commit_period"].isna()) & (core["contributor_type"] == "event")]
    print(f"Missing event contributors: {len(missing)}")

    # Load previous progress
    resolved = {}
    if os.path.exists(PROGRESS):
        with open(PROGRESS) as f:
            resolved = json.load(f)
        print(f"Loaded {len(resolved)} previously resolved")

    # Build work list
    work = []
    for _, row in missing.iterrows():
        cid = row["contributor_id"]
        if cid in resolved:
            continue
        username = row["username_or_email"]
        repo = row["repo"]
        if username and repo:
            work.append((cid, username, repo))

    print(f"To resolve: {len(work)}")

    if not work:
        print("Nothing to do!")
        return

    # Phase 1: Resolve emails via GitHub API (parallel, 5 workers)
    print(f"\nPhase 1: Resolving emails via GitHub API...")
    batch_size = 50
    total_resolved = 0
    total_matched = 0

    for batch_start in range(0, len(work), batch_size):
        batch = work[batch_start:batch_start + batch_size]

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {}
            for i, (cid, username, repo) in enumerate(batch):
                token_idx = (batch_start + i) % len(TOKENS)
                fut = pool.submit(resolve_one, username, repo, token_idx)
                futures[fut] = (cid, username, repo)

            for fut in as_completed(futures):
                cid, username, repo = futures[fut]
                result = fut.result()
                if result:
                    resolved[cid] = {
                        "username": username,
                        "repo": repo,
                        **result
                    }
                    total_resolved += 1
                else:
                    resolved[cid] = {
                        "username": username,
                        "repo": repo,
                        "email": None,
                        "source": "not_found"
                    }

        # Save progress
        with open(PROGRESS, "w") as f:
            json.dump(resolved, f, indent=2)

        done = min(batch_start + batch_size, len(work))
        found = sum(1 for v in resolved.values() if v.get("email"))
        print(f"  [{done}/{len(work)}] resolved={total_resolved}, API found={found}")

        # Small delay to be nice to API
        time.sleep(0.5)

    # Phase 2: Match resolved emails to T7 CSVs
    print(f"\nPhase 2: Matching resolved emails to T7 CSVs...")
    # Group by repo to load each CSV only once
    repo_cids = defaultdict(list)
    for cid, info in resolved.items():
        if info.get("email") and info.get("repo"):
            repo_cids[info["repo"]].append(cid)

    for ri, (repo, cids) in enumerate(repo_cids.items()):
        csv_path = os.path.join(T7, repo.replace("/", "__") + ".csv")
        if not os.path.exists(csv_path):
            continue

        try:
            df = pd.read_csv(csv_path, usecols=["author_email", "author_name", "author_date"])
        except Exception:
            try:
                df = pd.read_csv(csv_path, usecols=["author_email", "author_name", "author_date"],
                                encoding="latin-1")
            except Exception:
                continue

        df["author_date"] = pd.to_datetime(df["author_date"], errors="coerce", utc=True)
        df = df.dropna(subset=["author_date"])
        if df.empty:
            del df; gc.collect()
            continue

        for cid in cids:
            info = resolved[cid]
            email = info.get("email", "")
            name = info.get("name", "")

            if not email:
                continue

            email_lower = email.lower()
            name_lower = (name or "").lower()

            # Try matching strategies
            matched = False
            for strategy, mask in [
                ("exact_email", df["author_email"].str.lower() == email_lower),
                ("email_prefix", df["author_email"].str.lower().str.contains(
                    email_lower.split("@")[0], na=False, regex=False) if "@" in email_lower else pd.Series([False]*len(df))),
                ("name_exact", df["author_name"].str.lower() == name_lower if name_lower else pd.Series([False]*len(df))),
                ("name_contains", df["author_name"].str.lower().str.contains(
                    name_lower, na=False, regex=False) if name_lower and len(name_lower) > 3 else pd.Series([False]*len(df))),
            ]:
                if mask.any():
                    dates = df.loc[mask, "author_date"]
                    info["t7_match"] = {
                        "strategy": strategy,
                        "matched_email": df.loc[mask, "author_email"].iloc[0],
                        "first_period": str(dates.min().to_period("M")),
                        "last_period": str(dates.max().to_period("M")),
                        "n_commits": int(mask.sum())
                    }
                    total_matched += 1
                    matched = True
                    break

        del df
        gc.collect()

        if (ri + 1) % 30 == 0:
            print(f"  [{ri+1}/{len(repo_cids)}] matched={total_matched}")

    # Save final results
    with open(OUTPUT, "w") as f:
        json.dump(resolved, f, indent=2)

    # Summary
    api_found = sum(1 for v in resolved.values() if v.get("email"))
    t7_matched = sum(1 for v in resolved.values() if v.get("t7_match"))
    not_found = sum(1 for v in resolved.values() if not v.get("email"))

    print(f"\n{'='*70}")
    print(f"RESOLUTION COMPLETE")
    print(f"{'='*70}")
    print(f"  Total missing: {len(missing)}")
    print(f"  API email found: {api_found}")
    print(f"  Matched to T7: {t7_matched}")
    print(f"  Not found at all: {not_found}")
    print(f"  Saved: {OUTPUT}")


if __name__ == "__main__":
    main()
