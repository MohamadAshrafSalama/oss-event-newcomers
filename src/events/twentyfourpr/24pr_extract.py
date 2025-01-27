#!/usr/bin/env python3
"""
24 Pull Requests Data Extraction

Downloads all users from 24pullrequests.com API, extracts PRs and repos,
and matches against OSS4SG project list.
"""

import json
import csv
import time
import argparse
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import List, Dict, Set

BASE_DIR = Path(__file__).parent
BASE_URL = "https://24pullrequests.com"


def fetch_page(page: int, delay: float = 0.3) -> List[Dict]:
    """Fetch a single page of users."""
    url = f"{BASE_URL}/users.json?page={page}"
    time.sleep(delay)
    try:
        req = Request(url, headers={"User-Agent": "24PR-Extractor/1.0"})
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError) as e:
        print(f"  Error on page {page}: {e}")
        return []


def download_all_users(max_pages: int = 100, delay: float = 0.3) -> List[Dict]:
    """Download all users from all pages."""
    all_users = []
    print(f"Downloading users (up to {max_pages} pages)...")
    
    for page in range(1, max_pages + 1):
        users = fetch_page(page, delay)
        if not users:
            print(f"  Page {page}: empty, stopping")
            break
        all_users.extend(users)
        if page % 10 == 0:
            print(f"  Progress: {page}/{max_pages} pages, {len(all_users)} users so far")
    
    print(f"  Done: {len(all_users)} users downloaded")
    return all_users


def extract_prs(users: List[Dict]) -> List[Dict]:
    """Extract all PRs from users with user info attached."""
    all_prs = []
    for user in users:
        nickname = user.get("nickname", "")
        github_profile = user.get("github_profile", "")
        for pr in user.get("pull_requests", []):
            all_prs.append({
                "user_nickname": nickname,
                "user_github": github_profile,
                "repo_name": pr.get("repo_name", ""),
                "title": pr.get("title", ""),
                "issue_url": pr.get("issue_url", ""),
                "created_at": pr.get("created_at", ""),
            })
    return all_prs


def extract_unique_repos(prs: List[Dict]) -> List[Dict]:
    """Extract unique repos with PR counts and year ranges."""
    repo_info: Dict[str, Dict] = {}
    
    for pr in prs:
        repo = pr.get("repo_name", "").lower()
        if not repo:
            continue
        
        if repo not in repo_info:
            repo_info[repo] = {
                "repo_name": repo,
                "pr_count": 0,
                "years": set(),
                "contributors": set(),
            }
        
        repo_info[repo]["pr_count"] += 1
        
        # Extract year from created_at
        created = pr.get("created_at", "")
        if created and len(created) >= 4:
            year = created[:4]
            if year.isdigit():
                repo_info[repo]["years"].add(int(year))
        
        # Track contributors
        user = pr.get("user_nickname", "")
        if user:
            repo_info[repo]["contributors"].add(user)
    
    # Convert sets to lists for JSON
    result = []
    for repo, info in repo_info.items():
        result.append({
            "repo_name": info["repo_name"],
            "pr_count": info["pr_count"],
            "years": sorted(info["years"]),
            "contributor_count": len(info["contributors"]),
        })
    
    # Sort by PR count descending
    result.sort(key=lambda x: -x["pr_count"])
    return result


def load_oss4sg(csv_path: Path, column: str = "repo_name_with_owner") -> Set[str]:
    """Load OSS4SG project list."""
    projects = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            val = row.get(column, "").strip().lower()
            if val:
                projects.add(val)
    return projects


def match_oss4sg(repos: List[Dict], oss4sg: Set[str]) -> List[Dict]:
    """Match repos against OSS4SG list."""
    matches = []
    for repo in repos:
        repo_name = repo["repo_name"]
        if repo_name in oss4sg:
            matches.append({
                "repo_name": repo_name,
                "pr_count": repo["pr_count"],
                "years": repo["years"],
                "contributor_count": repo["contributor_count"],
            })
    return matches


def save_json(path: Path, data) -> None:
    """Save data to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def save_csv(path: Path, data: List[Dict], headers: List[str]) -> None:
    """Save data to CSV file."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in data:
            # Convert lists to pipe-separated strings
            csv_row = {}
            for h in headers:
                val = row.get(h, "")
                if isinstance(val, list):
                    val = "|".join(str(v) for v in val)
                csv_row[h] = val
            writer.writerow(csv_row)


def main():
    parser = argparse.ArgumentParser(description="Extract 24 Pull Requests data")
    parser.add_argument("--max-pages", type=int, default=100, help="Max pages to download")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests")
    parser.add_argument("--oss4sg-csv", type=Path, 
                        default=BASE_DIR.parent.parent / "OSS4SG-Project-List.csv",
                        help="Path to OSS4SG CSV")
    parser.add_argument("--skip-download", action="store_true", 
                        help="Skip download, use existing users file")
    args = parser.parse_args()
    
    users_file = BASE_DIR / "24pr_users_raw.json"
    
    # Step 1: Download users (or load existing)
    if args.skip_download and users_file.exists():
        print("Loading existing users file...")
        with open(users_file) as f:
            users = json.load(f)
        print(f"  Loaded {len(users)} users")
    else:
        users = download_all_users(max_pages=args.max_pages, delay=args.delay)
        save_json(users_file, users)
        print(f"  Saved to {users_file.name}")
    
    # Step 2: Extract PRs
    print("\nExtracting PRs...")
    prs = extract_prs(users)
    print(f"  Total PRs: {len(prs)}")
    save_json(BASE_DIR / "24pr_all_prs.json", prs)
    save_csv(BASE_DIR / "24pr_all_prs.csv", prs, 
             ["user_nickname", "user_github", "repo_name", "title", "issue_url", "created_at"])
    print(f"  Saved to 24pr_all_prs.json/csv")
    
    # Step 3: Extract unique repos
    print("\nExtracting unique repos...")
    repos = extract_unique_repos(prs)
    print(f"  Unique repos: {len(repos)}")
    save_json(BASE_DIR / "24pr_repos_unique.json", repos)
    save_csv(BASE_DIR / "24pr_repos_unique.csv", repos,
             ["repo_name", "pr_count", "years", "contributor_count"])
    print(f"  Saved to 24pr_repos_unique.json/csv")
    
    # Step 4: Match against OSS4SG
    print(f"\nMatching against OSS4SG ({args.oss4sg_csv})...")
    oss4sg = load_oss4sg(args.oss4sg_csv)
    print(f"  OSS4SG projects: {len(oss4sg)}")
    matches = match_oss4sg(repos, oss4sg)
    print(f"  Matches: {len(matches)}")
    save_json(BASE_DIR / "oss4sg_24pr_matches.json", matches)
    print(f"  Saved to oss4sg_24pr_matches.json")
    
    # Step 5: Summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    print(f"Total users:     {len(users)}")
    print(f"Total PRs:       {len(prs)}")
    print(f"Unique repos:    {len(repos)}")
    print(f"OSS4SG matches:  {len(matches)}")
    
    if prs:
        dates = [pr["created_at"][:10] for pr in prs if pr.get("created_at")]
        if dates:
            print(f"Date range:      {min(dates)} to {max(dates)}")
    
    if matches:
        print("\nTop 10 OSS4SG matches by PR count:")
        for m in matches[:10]:
            print(f"  {m['repo_name']}: {m['pr_count']} PRs, {m['contributor_count']} contributors")


if __name__ == "__main__":
    main()
