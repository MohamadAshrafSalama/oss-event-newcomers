#!/usr/bin/env python3
"""
MLH Fellowship - OSS4SG Project Discovery

Checks if any OSS4SG projects participated in MLH Fellowship by:
1. Analyzing MLH-Fellowship org forks for OSS4SG parent repos
2. Searching OSS4SG repos for PRs mentioning MLH
"""

import json
import csv
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from typing import List, Dict, Set, Optional

BASE_DIR = Path(__file__).parent

# GitHub tokens for rotation
GITHUB_TOKENS = [
    "os.environ.get("GITHUB_TOKEN", "")",
    "os.environ.get("GITHUB_TOKEN", "")",
    "os.environ.get("GITHUB_TOKEN", "")",
    "os.environ.get("GITHUB_TOKEN", "")",
]


class TokenRotator:
    """Rotate through GitHub tokens."""
    
    def __init__(self, tokens: List[str]):
        self.tokens = tokens
        self.current_idx = 0
    
    def get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"token {self.tokens[self.current_idx]}",
            "User-Agent": "MLH-Fellowship-Checker/1.0",
            "Accept": "application/vnd.github.v3+json",
        }
    
    def rotate(self):
        self.current_idx = (self.current_idx + 1) % len(self.tokens)


def load_oss4sg_repos(csv_path: Path) -> Set[str]:
    """Load OSS4SG repo names (lowercase for matching)."""
    repos = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            repo = row.get("repo_name_with_owner", "").strip().lower()
            if repo:
                repos.add(repo)
    return repos


def api_call(url: str, rotator: TokenRotator, retries: int = 3) -> Optional[dict]:
    """Make GitHub API call with retry and token rotation."""
    for attempt in range(retries):
        try:
            req = Request(url, headers=rotator.get_headers())
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code == 403:  # Rate limit
                rotator.rotate()
                time.sleep(1)
            elif e.code == 404:
                return None
            elif e.code == 422:  # Validation failed (bad query)
                return None
            else:
                time.sleep(2 ** attempt)
        except (URLError, TimeoutError):
            time.sleep(2 ** attempt)
    return None


def get_all_mlh_forks(rotator: TokenRotator) -> List[Dict]:
    """Get all fork repos from MLH-Fellowship org."""
    print("Step 1: Fetching all forks from MLH-Fellowship org...")
    all_forks = []
    page = 1
    
    while True:
        url = f"https://api.github.com/orgs/MLH-Fellowship/repos?type=forks&per_page=100&page={page}"
        data = api_call(url, rotator)
        
        if not data:
            break
        
        all_forks.extend(data)
        print(f"  Page {page}: {len(data)} forks (total: {len(all_forks)})")
        
        if len(data) < 100:
            break
        
        page += 1
        time.sleep(0.1)
    
    print(f"  Total MLH forks: {len(all_forks)}")
    return all_forks


def analyze_fork_parents(forks: List[Dict], oss4sg: Set[str], rotator: TokenRotator) -> List[Dict]:
    """Check each fork's parent repo against OSS4SG list."""
    print("\nStep 2: Checking fork parent repos against OSS4SG...")
    
    matches = []
    all_forks_info = []
    
    for i, fork in enumerate(forks):
        if i % 50 == 0:
            print(f"  Progress: {i}/{len(forks)}")
        
        fork_name = fork["name"]
        
        # Get full repo details to see parent
        url = f"https://api.github.com/repos/MLH-Fellowship/{fork_name}"
        data = api_call(url, rotator)
        
        if data and data.get("parent"):
            parent_full = data["parent"]["full_name"].lower()
            fork_info = {
                "mlh_fork": f"MLH-Fellowship/{fork_name}",
                "parent_repo": parent_full,
                "created_at": fork.get("created_at", ""),
                "is_oss4sg": parent_full in oss4sg,
            }
            all_forks_info.append(fork_info)
            
            if parent_full in oss4sg:
                matches.append(fork_info)
                print(f"  ✅ MATCH: MLH-Fellowship/{fork_name} → {parent_full}")
        
        time.sleep(0.05)
        
        # Rotate token every 100 requests
        if (i + 1) % 100 == 0:
            rotator.rotate()
    
    print(f"  OSS4SG forks found: {len(matches)}")
    return all_forks_info, matches


def search_oss4sg_for_mlh_prs(oss4sg_repos: Set[str], rotator: TokenRotator) -> List[Dict]:
    """Search all OSS4SG repos for PRs mentioning MLH."""
    print("\nStep 3: Searching OSS4SG repos for MLH-related PRs...")
    
    results = []
    repos_list = sorted(oss4sg_repos)
    
    for i, repo in enumerate(repos_list):
        if i % 50 == 0:
            print(f"  Progress: {i}/{len(repos_list)}")
        
        # Search for PRs mentioning MLH in this repo
        query = f'repo:{repo} "MLH" type:pr'
        encoded_query = quote(query, safe='')
        url = f"https://api.github.com/search/issues?q={encoded_query}&per_page=10"
        
        data = api_call(url, rotator)
        
        if data and data.get("total_count", 0) > 0:
            pr_count = data["total_count"]
            pr_titles = [item["title"][:80] for item in data.get("items", [])[:5]]
            pr_authors = list(set(item["user"]["login"] for item in data.get("items", []) if item.get("user")))
            
            results.append({
                "repo": repo,
                "mlh_pr_count": pr_count,
                "sample_titles": pr_titles,
                "authors": pr_authors[:10],
            })
            print(f"  ✅ {repo}: {pr_count} MLH-related PRs")
        
        time.sleep(0.1)
        
        # Rotate token every 100 requests
        if (i + 1) % 100 == 0:
            rotator.rotate()
    
    print(f"  OSS4SG repos with MLH PRs: {len(results)}")
    return results


def generate_outputs(forks_info: List[Dict], fork_matches: List[Dict], 
                     pr_results: List[Dict], oss4sg_count: int):
    """Generate all output files."""
    print("\nStep 4: Generating output files...")
    
    # Save fork analysis
    save_json(BASE_DIR / "mlh_forks_analysis.json", forks_info)
    print(f"  - mlh_forks_analysis.json ({len(forks_info)} forks analyzed)")
    
    # Save PR search results
    save_json(BASE_DIR / "mlh_pr_search_results.json", pr_results)
    print(f"  - mlh_pr_search_results.json ({len(pr_results)} repos with MLH PRs)")
    
    # Combine all matches
    all_matches = []
    
    # Add fork matches
    for m in fork_matches:
        all_matches.append({
            "repo": m["parent_repo"],
            "match_type": "mlh_fork",
            "mlh_fork": m["mlh_fork"],
            "evidence": f"MLH-Fellowship forked this repo on {m['created_at'][:10]}"
        })
    
    # Add PR matches
    for r in pr_results:
        # Check if already in matches
        existing = next((m for m in all_matches if m["repo"] == r["repo"]), None)
        if existing:
            existing["match_type"] = "fork_and_pr"
            existing["mlh_pr_count"] = r["mlh_pr_count"]
        else:
            all_matches.append({
                "repo": r["repo"],
                "match_type": "mlh_pr",
                "mlh_pr_count": r["mlh_pr_count"],
                "evidence": f"{r['mlh_pr_count']} PRs mention MLH"
            })
    
    save_json(BASE_DIR / "oss4sg_mlh_matches.json", all_matches)
    print(f"  - oss4sg_mlh_matches.json ({len(all_matches)} total matches)")
    
    # Summary
    summary = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "oss4sg_repos_checked": oss4sg_count,
        "mlh_forks_analyzed": len(forks_info),
        "mlh_forks_of_oss4sg": len(fork_matches),
        "oss4sg_repos_with_mlh_prs": len(pr_results),
        "total_unique_matches": len(all_matches),
        "matched_repos": [m["repo"] for m in all_matches],
    }
    save_json(BASE_DIR / "mlh_summary.json", summary)
    print(f"  - mlh_summary.json")
    
    return all_matches


def save_json(path: Path, data):
    """Save data to JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Check MLH Fellowship participation in OSS4SG")
    parser.add_argument("--oss4sg-csv", type=Path,
                        default=BASE_DIR.parent.parent / "OSS4SG-Project-List.csv",
                        help="Path to OSS4SG CSV")
    args = parser.parse_args()
    
    # Load OSS4SG repos
    print(f"Loading OSS4SG repos from {args.oss4sg_csv}...")
    oss4sg = load_oss4sg_repos(args.oss4sg_csv)
    print(f"  Loaded {len(oss4sg)} OSS4SG repos")
    
    # Initialize token rotator
    rotator = TokenRotator(GITHUB_TOKENS)
    print(f"  Using {len(GITHUB_TOKENS)} GitHub tokens")
    
    # Step 1 & 2: Get and analyze MLH forks
    forks = get_all_mlh_forks(rotator)
    forks_info, fork_matches = analyze_fork_parents(forks, oss4sg, rotator)
    
    # Step 3: Search OSS4SG repos for MLH PRs
    pr_results = search_oss4sg_for_mlh_prs(oss4sg, rotator)
    
    # Step 4: Generate outputs
    all_matches = generate_outputs(forks_info, fork_matches, pr_results, len(oss4sg))
    
    # Final summary
    print("\n" + "=" * 60)
    print("MLH FELLOWSHIP - OSS4SG CHECK COMPLETE")
    print("=" * 60)
    print(f"OSS4SG repos checked:        {len(oss4sg)}")
    print(f"MLH forks analyzed:          {len(forks_info)}")
    print(f"MLH forks of OSS4SG:         {len(fork_matches)}")
    print(f"OSS4SG repos with MLH PRs:   {len(pr_results)}")
    print(f"Total unique matches:        {len(all_matches)}")
    
    if all_matches:
        print("\nMatched OSS4SG projects:")
        for m in all_matches:
            print(f"  ✅ {m['repo']} ({m['match_type']})")
    else:
        print("\n⚠️  No OSS4SG projects found with MLH Fellowship participation")


if __name__ == "__main__":
    main()
