#!/usr/bin/env python3
"""
Phase 1 - Step 3: Re-match organic contributors using activity band matching.
For each event contributor, find an organic match in the same repo with
commit count in the range [event_commits * 0.5, event_commits * 1.5].
"""

import json
import os
import random
import pandas as pd
import numpy as np
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7_EXTRACTED = "/Volumes/T7/Event based OSS4SG/extracted"
MIN_COMMITS = 3
SEED = 42

# Bot patterns to exclude
BOT_PATTERNS = [
    "bot", "dependabot", "renovate", "greenkeeper", "github-actions",
    "noreply", "snyk-bot", "codecov", "semantic-release", "mergify",
    "stale[bot]", "allcontributors", "imgbot", "netlify", "vercel",
    "auto-merge", "ci-bot", "release-bot"
]

def is_bot(email, name):
    """Check if an author is likely a bot."""
    combined = (str(email) + " " + str(name)).lower()
    return any(p in combined for p in BOT_PATTERNS)

def repo_to_csv_path(repo):
    return os.path.join(T7_EXTRACTED, repo.replace("/", "__") + ".csv")

def get_all_authors_in_repo(csv_path):
    """Get all unique authors and their commit counts from a repo CSV."""
    if not os.path.exists(csv_path):
        return {}
    try:
        df = pd.read_csv(csv_path, usecols=["author_name", "author_email", "author_date"])
    except Exception:
        return {}
    
    # Group by email (primary key) and count commits
    author_counts = df.groupby("author_email").agg(
        commits=("author_email", "count"),
        name=("author_name", "first"),
        first_commit=("author_date", "min"),
        last_commit=("author_date", "max"),
    ).reset_index()
    
    result = {}
    for _, row in author_counts.iterrows():
        email = row["author_email"]
        if not is_bot(email, row["name"]):
            result[email] = {
                "email": email,
                "name": row["name"],
                "commits": int(row["commits"]),
                "first_commit": row["first_commit"],
                "last_commit": row["last_commit"],
            }
    return result

def main():
    print("=" * 70)
    print("PHASE 1 - STEP 3: Re-match Organic Contributors")
    print("=" * 70)
    
    random.seed(SEED)
    
    # Load the re-selected event contributors (from step 2)
    v2_path = os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "event_contributors_v2.json")
    with open(v2_path) as f:
        event_data = json.load(f)
    
    contributions = event_data["contributions"]
    print(f"\nEvent contributors to match: {len(contributions)}")
    
    # Group by repo for efficient matching
    by_repo = defaultdict(list)
    for c in contributions:
        by_repo[c["repo"]].append(c)
    
    unique_repos = list(by_repo.keys())
    print(f"Unique repos: {len(unique_repos)}")
    
    # Collect all event usernames for exclusion
    event_usernames = set()
    for c in contributions:
        event_usernames.add(c["github_username"].lower())
    
    # Match organic contributors
    matches = []
    no_match_count = 0
    widened_count = 0
    
    # Cache repo author data
    repo_authors_cache = {}
    # Track which organic authors have been used (per repo)
    used_organic = defaultdict(set)
    
    for repo_idx, (repo, event_contribs) in enumerate(by_repo.items()):
        if (repo_idx + 1) % 20 == 0:
            print(f"  Processing repo {repo_idx + 1}/{len(unique_repos)}: {repo} "
                  f"({len(event_contribs)} event contributors)...")
        
        csv_path = repo_to_csv_path(repo)
        if repo not in repo_authors_cache:
            repo_authors_cache[repo] = get_all_authors_in_repo(csv_path)
        
        all_authors = repo_authors_cache[repo]
        
        for ec in event_contribs:
            uname = ec["github_username"].lower()
            # Determine event contributor's commit count
            ec_commits = ec.get("t7_commit_count", 0)
            
            # For GSoC/LFX that don't have t7_commit_count, look it up
            if ec_commits == 0:
                for email, auth_info in all_authors.items():
                    if uname in email.lower() or uname in str(auth_info["name"]).lower():
                        ec_commits = auth_info["commits"]
                        break
            
            if ec_commits < MIN_COMMITS:
                ec_commits = MIN_COMMITS  # floor for matching
            
            # Activity band: narrow first, then widen
            band_lo = max(MIN_COMMITS, int(ec_commits * 0.5))
            band_hi = int(ec_commits * 1.5)
            
            # Find candidates
            candidates = []
            for email, auth_info in all_authors.items():
                # Exclude: event contributors, already used organic, bots
                if email.lower() in used_organic[repo]:
                    continue
                # Check if this is an event contributor by username in email
                is_event = any(eu in email.lower() or eu in str(auth_info["name"]).lower() 
                             for eu in event_usernames if len(eu) > 3)
                if is_event:
                    continue
                
                c = auth_info["commits"]
                if band_lo <= c <= band_hi:
                    candidates.append(auth_info)
            
            # If no match in narrow band, widen
            if not candidates:
                band_lo = max(MIN_COMMITS, int(ec_commits * 0.3))
                band_hi = int(ec_commits * 2.0)
                for email, auth_info in all_authors.items():
                    if email.lower() in used_organic[repo]:
                        continue
                    is_event = any(eu in email.lower() or eu in str(auth_info["name"]).lower() 
                                 for eu in event_usernames if len(eu) > 3)
                    if is_event:
                        continue
                    c = auth_info["commits"]
                    if band_lo <= c <= band_hi:
                        candidates.append(auth_info)
                if candidates:
                    widened_count += 1
            
            # If still no match, try ANY contributor with >= MIN_COMMITS
            if not candidates:
                for email, auth_info in all_authors.items():
                    if email.lower() in used_organic[repo]:
                        continue
                    is_event = any(eu in email.lower() or eu in str(auth_info["name"]).lower()
                                 for eu in event_usernames if len(eu) > 3)
                    if is_event:
                        continue
                    if auth_info["commits"] >= MIN_COMMITS:
                        candidates.append(auth_info)
            
            if candidates:
                # Pick one randomly, preferring the one closest to ec_commits
                # Sort by distance to ec_commits and pick from the closest 5
                candidates.sort(key=lambda x: abs(x["commits"] - ec_commits))
                top_n = candidates[:min(5, len(candidates))]
                chosen = random.choice(top_n)
                
                used_organic[repo].add(chosen["email"].lower())
                
                matches.append({
                    "event_contribution_id": ec["contribution_id"],
                    "repo": repo,
                    "event_type": ec["event"],
                    "event_username": ec["github_username"],
                    "event_commits": ec_commits,
                    "organic_email": chosen["email"],
                    "organic_name": chosen["name"],
                    "organic_commits": chosen["commits"],
                    "organic_first_commit": chosen["first_commit"],
                    "organic_last_commit": chosen["last_commit"],
                })
            else:
                no_match_count += 1
    
    print(f"\n{'='*50}")
    print(f"ORGANIC MATCHING RESULTS")
    print(f"{'='*50}")
    print(f"  Total event contributors: {len(contributions)}")
    print(f"  Matched: {len(matches)}")
    print(f"  No match found: {no_match_count}")
    print(f"  Widened band: {widened_count}")
    
    # Stats on matched organic
    if matches:
        oc = [m["organic_commits"] for m in matches]
        ec = [m["event_commits"] for m in matches]
        print(f"\n  Organic commit stats: mean={np.mean(oc):.1f}, median={np.median(oc):.0f}, "
              f"min={min(oc)}, max={max(oc)}")
        print(f"  Event commit stats:   mean={np.mean(ec):.1f}, median={np.median(ec):.0f}, "
              f"min={min(ec)}, max={max(ec)}")
        
        # Ratio
        ratio = np.mean(ec) / np.mean(oc) if np.mean(oc) > 0 else float('inf')
        print(f"  Event/Organic mean ratio: {ratio:.3f}")
    
    # Save
    output = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "description": "Organic matches using activity band matching (0.5x-1.5x of event commits)",
        "total_matches": len(matches),
        "no_match_count": no_match_count,
        "matches": matches,
    }
    
    output_path = os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                               "outputs", "organic_matches_v2.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\nSaved to: {output_path}")
    print("DONE")

if __name__ == "__main__":
    main()
