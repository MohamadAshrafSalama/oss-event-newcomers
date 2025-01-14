#!/usr/bin/env python3
"""
Extract GSoC Contributors from Gist Data

Parses GitHub usernames from gist URLs and maps them to repos they contributed to.
No API calls needed - uses existing parsed data.
"""

import json
import re
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
GIST_LINKS_FILE = SCRIPT_DIR / "gist_links_projects.json"
GSOC_PROJECTS_FILE = SCRIPT_DIR / "gsoc_projects.json"
GITHUB_URLS_FILE = SCRIPT_DIR / "gsoc_github_urls_extracted.json"
OUTPUT_FILE = SCRIPT_DIR / "gsoc_contributors.json"

def extract_username_from_gist_url(url: str) -> str:
    """
    Extract GitHub username from gist URL.
    Format: gist.github.com/{USERNAME}/{gist_id}
    """
    if not url:
        return None
    
    # Pattern: gist.github.com/username/gistid
    match = re.search(r'gist\.github\.com/([a-zA-Z0-9_-]+)/[a-zA-Z0-9]+', url)
    if match:
        username = match.group(1)
        # Filter out invalid usernames (just hex IDs)
        if len(username) >= 3 and not re.match(r'^[0-9a-f]{10,}$', username.lower()):
            return username.lower()
    return None

def main():
    print("=" * 60)
    print("GSoC Contributors Extraction")
    print("=" * 60)
    
    contributors = defaultdict(lambda: {
        "repos": set(),
        "orgs": set(),
        "years": set(),
        "project_count": 0,
        "gist_urls": set()
    })
    
    # Method 1: Extract from gist_links_projects.json
    print(f"\n1. Processing {GIST_LINKS_FILE}...")
    if GIST_LINKS_FILE.exists():
        with open(GIST_LINKS_FILE) as f:
            gist_links = json.load(f)
        
        for entry in gist_links:
            gist_url = entry.get("gist_url", "")
            username = extract_username_from_gist_url(gist_url)
            
            if username:
                repo = entry.get("repo_slug", "").lower()
                year = entry.get("gist_year")
                org = entry.get("gist_org", "")
                
                contributors[username]["gist_urls"].add(gist_url)
                if repo:
                    contributors[username]["repos"].add(repo)
                if year:
                    contributors[username]["years"].add(year)
                if org:
                    contributors[username]["orgs"].add(org)
                contributors[username]["project_count"] += 1
        
        print(f"   Processed {len(gist_links):,} gist link entries")
    
    # Method 2: Extract from gsoc_github_urls_extracted.json
    print(f"\n2. Processing {GITHUB_URLS_FILE}...")
    if GITHUB_URLS_FILE.exists():
        with open(GITHUB_URLS_FILE) as f:
            github_urls = json.load(f)
        
        for entry in github_urls:
            url = entry.get("github_url", "")
            username = extract_username_from_gist_url(url)
            
            if username:
                years = entry.get("years", [])
                orgs = entry.get("org_names", [])
                
                contributors[username]["gist_urls"].add(url)
                for year in years:
                    contributors[username]["years"].add(year)
                for org in orgs:
                    contributors[username]["orgs"].add(org)
        
        print(f"   Processed {len(github_urls):,} GitHub URL entries")
    
    # Method 3: Look at gsoc_projects.json for code_urls
    print(f"\n3. Processing {GSOC_PROJECTS_FILE}...")
    if GSOC_PROJECTS_FILE.exists():
        with open(GSOC_PROJECTS_FILE) as f:
            projects = json.load(f)
        
        for proj in projects:
            code_url = proj.get("code_url", "")
            username = extract_username_from_gist_url(code_url)
            
            if username:
                year = proj.get("year")
                org = proj.get("org_name", "")
                title = proj.get("project_title", "")
                
                contributors[username]["gist_urls"].add(code_url)
                if year:
                    contributors[username]["years"].add(year)
                if org:
                    contributors[username]["orgs"].add(org)
        
        print(f"   Processed {len(projects):,} GSoC projects")
    
    # Convert to list format
    contributors_list = []
    for username, data in contributors.items():
        contributors_list.append({
            "github_username": username,
            "repos_contributed": sorted(list(data["repos"])),
            "repo_count": len(data["repos"]),
            "gsoc_orgs": sorted(list(data["orgs"])),
            "years_active": sorted(list(data["years"])),
            "gist_count": len(data["gist_urls"]),
            "event": "gsoc"
        })
    
    # Sort by repo count
    contributors_list.sort(key=lambda x: x["repo_count"], reverse=True)
    
    # Calculate stats
    total_repos = set()
    for c in contributors_list:
        total_repos.update(c["repos_contributed"])
    
    all_years = set()
    for c in contributors_list:
        all_years.update(c["years_active"])
    
    # Create output
    output = {
        "event": "google_summer_of_code",
        "total_contributors": len(contributors_list),
        "total_unique_repos": len(total_repos),
        "years_covered": sorted(list(all_years)),
        "contributors": contributors_list
    }
    
    # Save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Total contributors: {len(contributors_list):,}")
    print(f"Total unique repos: {len(total_repos):,}")
    print(f"Years covered: {min(all_years) if all_years else 'N/A'} - {max(all_years) if all_years else 'N/A'}")
    
    # Contributors with repos
    with_repos = sum(1 for c in contributors_list if c["repo_count"] > 0)
    print(f"Contributors with repo links: {with_repos:,}")
    
    print(f"\nTop 10 contributors by repo count:")
    for c in contributors_list[:10]:
        print(f"  {c['github_username']}: {c['repo_count']} repos, orgs: {', '.join(c['gsoc_orgs'][:3])}")
    
    print(f"\nSaved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
