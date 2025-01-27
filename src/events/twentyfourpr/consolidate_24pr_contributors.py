#!/usr/bin/env python3
"""
Consolidate 24 Pull Requests Contributors

Extracts unique contributors from 24pr_all_prs.json and creates
a consolidated contributors file with stats per user.
"""

import json
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
INPUT_FILE = SCRIPT_DIR / "24pr_all_prs.json"
OUTPUT_FILE = SCRIPT_DIR / "24pr_contributors.json"

def main():
    print("=" * 60)
    print("24 Pull Requests - Contributor Consolidation")
    print("=" * 60)
    
    # Load PRs
    print(f"Loading {INPUT_FILE}...")
    with open(INPUT_FILE) as f:
        prs = json.load(f)
    
    print(f"Total PRs: {len(prs):,}")
    
    # Group by contributor
    contributors = defaultdict(lambda: {
        "repos": set(),
        "prs": [],
        "years": set(),
        "pr_count": 0
    })
    
    for pr in prs:
        username = pr.get("user_nickname")
        if not username:
            continue
        
        repo = pr.get("repo_name", "").lower()
        year = None
        if pr.get("created_at"):
            try:
                year = int(pr["created_at"][:4])
            except:
                pass
        
        contributors[username]["repos"].add(repo)
        contributors[username]["pr_count"] += 1
        if year:
            contributors[username]["years"].add(year)
        
        # Store first 5 PRs as sample
        if len(contributors[username]["prs"]) < 5:
            contributors[username]["prs"].append({
                "repo": repo,
                "title": pr.get("title", ""),
                "url": pr.get("issue_url", ""),
                "date": pr.get("created_at", "")
            })
    
    # Convert to list format
    contributors_list = []
    for username, data in contributors.items():
        contributors_list.append({
            "github_username": username,
            "repos_contributed": sorted(list(data["repos"])),
            "repo_count": len(data["repos"]),
            "total_prs": data["pr_count"],
            "years_active": sorted(list(data["years"])),
            "sample_prs": data["prs"],
            "event": "24pr"
        })
    
    # Sort by PR count
    contributors_list.sort(key=lambda x: x["total_prs"], reverse=True)
    
    # Create output
    output = {
        "event": "24_pull_requests",
        "total_contributors": len(contributors_list),
        "total_prs": len(prs),
        "total_unique_repos": len(set(pr.get("repo_name", "").lower() for pr in prs if pr.get("repo_name"))),
        "contributors": contributors_list
    }
    
    # Save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nResults:")
    print(f"  Total contributors: {len(contributors_list):,}")
    print(f"  Total PRs: {len(prs):,}")
    print(f"  Unique repos: {output['total_unique_repos']:,}")
    print(f"\nTop 10 contributors:")
    for c in contributors_list[:10]:
        print(f"  {c['github_username']}: {c['total_prs']} PRs across {c['repo_count']} repos")
    
    print(f"\nSaved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
