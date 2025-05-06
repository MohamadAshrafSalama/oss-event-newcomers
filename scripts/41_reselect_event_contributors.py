#!/usr/bin/env python3
"""
Phase 1 - Step 2: Re-select event contributors for 24PR and HF.
- Keep GSoC and LFX as-is
- For 24PR and HF: look up commit counts from T7 CSVs, cap at MAX_COMMITS
- Random sample to target size
- Output: new event contributor list
"""

import json
import os
import sys
import random
import pandas as pd
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7_EXTRACTED = "/Volumes/T7/Event based OSS4SG/extracted"
MAX_COMMITS = 50
MIN_COMMITS = 3
SEED = 42

def repo_to_csv_path(repo):
    """Convert owner/repo to T7 CSV path."""
    return os.path.join(T7_EXTRACTED, repo.replace("/", "__") + ".csv")

def count_commits_for_user(csv_path, username):
    """Count commits in a repo CSV matching a GitHub username.
    
    Match by: author_name contains username (case-insensitive) OR
              author_email contains username (case-insensitive) OR
              commit subject/body mentions the username.
    
    More reliable: check noreply email pattern.
    """
    if not os.path.exists(csv_path):
        return 0
    try:
        df = pd.read_csv(csv_path, usecols=["author_name", "author_email"])
    except Exception:
        return 0
    
    uname_lower = username.lower()
    # Match by GitHub noreply email pattern or username in email/name
    mask = (
        df["author_email"].str.lower().str.contains(uname_lower, na=False) |
        df["author_name"].str.lower().str.contains(uname_lower, na=False)
    )
    return int(mask.sum())

def load_repo_commit_data(csv_path):
    """Load commit data for a repo, return DataFrame with author info."""
    if not os.path.exists(csv_path):
        return None
    try:
        return pd.read_csv(csv_path, usecols=["author_name", "author_email", "author_date"])
    except Exception:
        return None

def main():
    print("=" * 70)
    print("PHASE 1 - STEP 2: Re-select Event Contributors")
    print("=" * 70)
    
    # Load current event contributions
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching", 
                           "outputs", "contributions_FINAL_VALID.json")) as f:
        event_data = json.load(f)
    
    contributions = event_data["contributions"]
    print(f"\nCurrent total contributions: {len(contributions)}")
    
    # Separate by event
    by_event = defaultdict(list)
    for c in contributions:
        by_event[c["event"]].append(c)
    
    for ev, items in by_event.items():
        print(f"  {ev}: {len(items)}")
    
    # Keep GSoC and LFX as-is
    kept_gsoc = by_event["gsoc"]
    kept_lfx = by_event["lfx"]
    print(f"\nKeeping GSoC ({len(kept_gsoc)}) and LFX ({len(kept_lfx)}) as-is")
    
    # Process 24PR and HF: look up commit counts from T7
    print(f"\nRe-selecting 24PR and HF with commit cap {MIN_COMMITS}-{MAX_COMMITS}...")
    
    # Cache repo DataFrames to avoid re-reading
    repo_cache = {}
    
    def get_user_commits_in_repo(username, repo):
        csv_path = repo_to_csv_path(repo)
        if repo not in repo_cache:
            repo_cache[repo] = load_repo_commit_data(csv_path)
        df = repo_cache[repo]
        if df is None:
            return 0
        uname_lower = username.lower()
        mask = (
            df["author_email"].str.lower().str.contains(uname_lower, na=False) |
            df["author_name"].str.lower().str.contains(uname_lower, na=False)
        )
        return int(mask.sum())
    
    # Process each non-mentorship event
    new_24pr = []
    new_hf = []
    
    for event_name, event_list, target_list in [
        ("24pr", by_event["24pr"], new_24pr),
        ("hf", by_event["hf"], new_hf),
    ]:
        print(f"\n  Processing {event_name} ({len(event_list)} candidates)...")
        qualifying = []
        skipped_no_csv = 0
        skipped_too_few = 0
        skipped_too_many = 0
        
        for i, c in enumerate(event_list):
            if (i + 1) % 100 == 0:
                print(f"    Checked {i+1}/{len(event_list)}...")
            
            commits = get_user_commits_in_repo(c["github_username"], c["repo"])
            c["t7_commit_count"] = commits
            
            if commits < MIN_COMMITS:
                skipped_too_few += 1
            elif commits > MAX_COMMITS:
                skipped_too_many += 1
            else:
                qualifying.append(c)
        
        print(f"    Results: {len(qualifying)} qualifying, "
              f"{skipped_too_few} too few (<{MIN_COMMITS}), "
              f"{skipped_too_many} too many (>{MAX_COMMITS})")
        
        # Random sample if we have more than needed
        # Target: similar to current size but from the qualifying pool
        random.seed(SEED)
        target_size = min(len(qualifying), len(event_list))
        sampled = random.sample(qualifying, target_size) if len(qualifying) > target_size else qualifying
        target_list.extend(sampled)
        print(f"    Selected: {len(sampled)} contributors")
    
    # Combine all
    new_contributions = kept_gsoc + kept_lfx + new_24pr + new_hf
    
    # Balance check
    mentorship_count = len(kept_gsoc) + len(kept_lfx)
    non_mentorship_count = len(new_24pr) + len(new_hf)
    
    print(f"\n{'='*50}")
    print(f"NEW EVENT CONTRIBUTOR SELECTION")
    print(f"{'='*50}")
    print(f"  GSoC:   {len(kept_gsoc)}")
    print(f"  LFX:    {len(kept_lfx)}")
    print(f"  24PR:   {len(new_24pr)}")
    print(f"  HF:     {len(new_hf)}")
    print(f"  TOTAL:  {len(new_contributions)}")
    print(f"  Mentorship:     {mentorship_count}")
    print(f"  Non-mentorship: {non_mentorship_count}")
    
    # Print commit count stats for new non-mentorship
    if new_24pr:
        commits_24pr = [c["t7_commit_count"] for c in new_24pr]
        print(f"\n  24PR commit stats: mean={sum(commits_24pr)/len(commits_24pr):.1f}, "
              f"median={sorted(commits_24pr)[len(commits_24pr)//2]}, "
              f"min={min(commits_24pr)}, max={max(commits_24pr)}")
    if new_hf:
        commits_hf = [c["t7_commit_count"] for c in new_hf]
        print(f"  HF commit stats: mean={sum(commits_hf)/len(commits_hf):.1f}, "
              f"median={sorted(commits_hf)[len(commits_hf)//2]}, "
              f"min={min(commits_hf)}, max={max(commits_hf)}")
    
    # Save new event contributors
    output = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "description": "Re-selected event contributors: GSoC/LFX kept, 24PR/HF capped at 3-50 commits",
        "max_commits_cap": MAX_COMMITS,
        "min_commits_floor": MIN_COMMITS,
        "total_contributions": len(new_contributions),
        "by_event": {
            "gsoc": len(kept_gsoc),
            "lfx": len(kept_lfx),
            "24pr": len(new_24pr),
            "hf": len(new_hf),
        },
        "mentorship_total": mentorship_count,
        "non_mentorship_total": non_mentorship_count,
        "contributions": new_contributions,
    }
    
    output_path = os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                               "outputs", "event_contributors_v2.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\nSaved to: {output_path}")
    print("DONE")

if __name__ == "__main__":
    main()
