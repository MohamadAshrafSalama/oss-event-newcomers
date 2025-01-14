#!/usr/bin/env python3
"""
GSoC Gist Scraping Pipeline

Scrapes GSoC student report gists to extract:
- Student names and GitHub usernames
- Organizations and sub-organizations
- Project titles and mentors
- PR references (to find actual repos)
- Mentioned GitHub repo URLs
"""

import json
import csv
import re
import time
import argparse
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from typing import Optional

BASE_DIR = Path(__file__).parent


def load_extracted_data() -> list[dict]:
    """Load the previously extracted GSoC GitHub URLs."""
    path = BASE_DIR / "gsoc_github_urls_extracted.json"
    with open(path) as f:
        return json.load(f)


def filter_gist_urls(data: list[dict]) -> list[dict]:
    """Filter entries that are gist.github.com URLs."""
    gists = []
    for entry in data:
        url = entry.get("github_url", "")
        if "gist.github.com" in url:
            gists.append(entry)
    return gists


def extract_gist_info(url: str) -> dict:
    """Extract username and gist_id from gist URL."""
    # Patterns:
    # https://gist.github.com/username/gist_id
    # https://gist.github.com/gist_id (anonymous or old format)
    
    url = url.rstrip("/")
    parts = url.replace("https://", "").replace("http://", "").split("/")
    
    if len(parts) >= 3:
        # gist.github.com/username/gist_id
        username = parts[1]
        gist_id = parts[2]
    elif len(parts) == 2:
        # gist.github.com/gist_id (no username visible)
        username = None
        gist_id = parts[1]
    else:
        username = None
        gist_id = None
    
    return {"username": username, "gist_id": gist_id}


def fetch_gist_raw(url: str, delay: float = 0.5) -> Optional[str]:
    """Fetch raw markdown content from a gist."""
    info = extract_gist_info(url)
    gist_id = info.get("gist_id")
    username = info.get("username")
    
    if not gist_id:
        return None
    
    # Try different raw URL patterns
    raw_urls = []
    if username:
        raw_urls.append(f"https://gist.githubusercontent.com/{username}/{gist_id}/raw")
    raw_urls.append(f"https://gist.githubusercontent.com/raw/{gist_id}")
    
    # Also try the API endpoint to get files list
    api_url = f"https://api.github.com/gists/{gist_id}"
    
    time.sleep(delay)
    
    # Try API first to get proper raw URL
    try:
        req = Request(api_url, headers={"User-Agent": "GSoC-Scraper/1.0"})
        with urlopen(req, timeout=30) as resp:
            gist_data = json.loads(resp.read().decode("utf-8"))
            files = gist_data.get("files", {})
            # Get the first markdown file
            for filename, file_info in files.items():
                if filename.lower().endswith(".md"):
                    return file_info.get("content", "")
            # If no .md file, get first file
            for filename, file_info in files.items():
                return file_info.get("content", "")
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        pass
    
    # Fallback to raw URLs
    for raw_url in raw_urls:
        try:
            req = Request(raw_url, headers={"User-Agent": "GSoC-Scraper/1.0"})
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError):
            continue
    
    return None


def parse_structured_fields(content: str) -> dict:
    """Parse structured fields from gist markdown content."""
    fields = {
        "student_name": None,
        "organisation": None,
        "sub_organisation": None,
        "project_title": None,
        "mentors": None,
        "proposal_url": None,
    }
    
    if not content:
        return fields
    
    # Patterns for each field (case insensitive)
    patterns = {
        "student_name": [
            r"(?:^|\n)\s*\*?\*?\s*(?:Name|Student)\s*\*?\*?\s*:?\s*\*?\*?\s*(.+?)(?:\n|$)",
            r"(?:^|\n)#+ .*?Name:?\s*(.+?)(?:\n|$)",
        ],
        "organisation": [
            r"(?:^|\n)\s*\*?\*?\s*(?:Organi[sz]ation)\s*\*?\*?\s*:?\s*\*?\*?\s*(.+?)(?:\n|$)",
        ],
        "sub_organisation": [
            r"(?:^|\n)\s*\*?\*?\s*(?:Sub[- ]?Organi[sz]ation)\s*\*?\*?\s*:?\s*\*?\*?\s*(.+?)(?:\n|$)",
        ],
        "project_title": [
            r"(?:^|\n)\s*\*?\*?\s*(?:Project)\s*\*?\*?\s*:?\s*\*?\*?\s*(.+?)(?:\n|$)",
        ],
        "mentors": [
            r"(?:^|\n)\s*\*?\*?\s*(?:Mentors?)\s*\*?\*?\s*:?\s*\*?\*?\s*(.+?)(?:\n|$)",
        ],
        "proposal_url": [
            r"(?:^|\n)\s*\*?\*?\s*(?:Proposal)\s*\*?\*?\s*:?\s*\*?\*?\s*\[?([^\]\n]+)\]?\(?([^\)\n]+)?\)?",
        ],
    }
    
    for field, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
            if match:
                value = match.group(1).strip()
                # Clean up markdown formatting
                value = re.sub(r"\*+", "", value)
                value = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", value)
                value = value.strip()
                if value and len(value) > 1:
                    fields[field] = value
                    break
    
    # Special handling for proposal URL
    proposal_match = re.search(
        r"(?:Proposal).*?(https?://[^\s\)]+)",
        content,
        re.IGNORECASE
    )
    if proposal_match:
        fields["proposal_url"] = proposal_match.group(1)
    
    return fields


def extract_pr_references(content: str) -> list[dict]:
    """Extract PR references like owner/repo#123 from content."""
    if not content:
        return []
    
    prs = []
    seen = set()
    
    # Pattern: owner/repo#number
    pattern1 = r"([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)#(\d+)"
    for match in re.finditer(pattern1, content):
        repo = match.group(1)
        pr_num = match.group(2)
        key = f"{repo}#{pr_num}"
        if key not in seen:
            seen.add(key)
            prs.append({"repo": repo, "pr_number": pr_num})
    
    # Pattern: full GitHub PR URL
    pattern2 = r"github\.com/([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)/pull/(\d+)"
    for match in re.finditer(pattern2, content):
        repo = match.group(1)
        pr_num = match.group(2)
        key = f"{repo}#{pr_num}"
        if key not in seen:
            seen.add(key)
            prs.append({"repo": repo, "pr_number": pr_num})
    
    return prs


def extract_repo_urls(content: str) -> list[str]:
    """Extract GitHub repo URLs mentioned in content."""
    if not content:
        return []
    
    repos = set()
    
    # Pattern: github.com/owner/repo (not gist, not PR, not issue)
    pattern = r"github\.com/([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)(?:/(?!pull|issues|blob|tree|commit)|\s|$|[)\]])"
    for match in re.finditer(pattern, content):
        repo = match.group(1).lower()
        # Skip if it looks like a gist
        if "gist" not in repo:
            repos.add(repo)
    
    # Also extract from explicit repo URLs
    pattern2 = r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_.-]+)(?:\.git)?"
    for match in re.finditer(pattern2, content):
        owner = match.group(1).lower()
        name = match.group(2).lower()
        if owner != "gist" and "gist" not in name:
            repos.add(f"{owner}/{name}")
    
    return list(repos)


def scrape_gists(gist_entries: list[dict], max_gists: int = None, delay: float = 0.3) -> list[dict]:
    """Scrape all gist entries and extract metadata."""
    results = []
    total = len(gist_entries) if max_gists is None else min(len(gist_entries), max_gists)
    
    print(f"Scraping {total} gists...")
    
    for i, entry in enumerate(gist_entries[:total]):
        url = entry.get("github_url", "")
        if i % 50 == 0:
            print(f"  Progress: {i}/{total}")
        
        gist_info = extract_gist_info(url)
        content = fetch_gist_raw(url, delay=delay)
        
        if content:
            fields = parse_structured_fields(content)
            prs = extract_pr_references(content)
            repos = extract_repo_urls(content)
            
            # Get unique repos from PRs
            repos_from_prs = list(set(pr["repo"] for pr in prs))
            pr_numbers = [pr["pr_number"] for pr in prs]
            
            result = {
                "gist_url": url,
                "github_username": gist_info.get("username"),
                "gist_id": gist_info.get("gist_id"),
                "gsoc_year": entry.get("years", [None])[0],
                "gsoc_org_name": entry.get("org_names", [None])[0],
                "project_title_from_api": entry.get("project_titles", [None])[0],
                **fields,
                "repos_from_prs": repos_from_prs,
                "pr_numbers": pr_numbers,
                "repos_mentioned": repos,
                "raw_content_length": len(content),
            }
            results.append(result)
        else:
            # Still record the entry even if we couldn't fetch content
            result = {
                "gist_url": url,
                "github_username": gist_info.get("username"),
                "gist_id": gist_info.get("gist_id"),
                "gsoc_year": entry.get("years", [None])[0],
                "gsoc_org_name": entry.get("org_names", [None])[0],
                "project_title_from_api": entry.get("project_titles", [None])[0],
                "student_name": None,
                "organisation": None,
                "sub_organisation": None,
                "project_title": None,
                "mentors": None,
                "proposal_url": None,
                "repos_from_prs": [],
                "pr_numbers": [],
                "repos_mentioned": [],
                "raw_content_length": 0,
            }
            results.append(result)
        
        time.sleep(delay)
    
    print(f"  Done: {len(results)} gists processed")
    return results


def extract_unique_repos(results: list[dict]) -> list[dict]:
    """Extract unique repos from all scraped gists."""
    repo_info = {}
    
    for r in results:
        all_repos = set(r.get("repos_from_prs", [])) | set(r.get("repos_mentioned", []))
        for repo in all_repos:
            repo_lower = repo.lower()
            if repo_lower not in repo_info:
                repo_info[repo_lower] = {
                    "repo": repo_lower,
                    "gist_sources": [],
                    "gsoc_years": set(),
                    "gsoc_orgs": set(),
                    "students": [],
                }
            repo_info[repo_lower]["gist_sources"].append(r.get("gist_url"))
            if r.get("gsoc_year"):
                repo_info[repo_lower]["gsoc_years"].add(r.get("gsoc_year"))
            if r.get("gsoc_org_name"):
                repo_info[repo_lower]["gsoc_orgs"].add(r.get("gsoc_org_name"))
            if r.get("github_username"):
                repo_info[repo_lower]["students"].append(r.get("github_username"))
    
    # Convert sets to lists for JSON
    for repo in repo_info.values():
        repo["gsoc_years"] = sorted(repo["gsoc_years"])
        repo["gsoc_orgs"] = list(repo["gsoc_orgs"])
        repo["students"] = list(set(repo["students"]))
    
    return list(repo_info.values())


def load_oss4sg_projects(csv_path: str, url_column: str = "repo_name_with_owner") -> list[str]:
    """Load project list from CSV."""
    projects = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            val = row.get(url_column, "").strip()
            if val:
                # Normalize to owner/repo format
                val = val.lower()
                val = val.replace("https://github.com/", "").replace("http://github.com/", "")
                val = val.replace("www.github.com/", "").replace("github.com/", "")
                val = val.rstrip("/").rstrip(".git")
                projects.append(val)
    return projects


def match_repos_to_oss4sg(repos: list[dict], oss4sg_projects: list[str]) -> list[dict]:
    """Match extracted repos against OSS4SG project list."""
    oss4sg_set = set(oss4sg_projects)
    matches = []
    
    for repo in repos:
        repo_slug = repo["repo"]
        if repo_slug in oss4sg_set:
            matches.append({
                "repo": repo_slug,
                "match_type": "exact",
                "gsoc_years": repo["gsoc_years"],
                "gsoc_orgs": repo["gsoc_orgs"],
                "student_usernames": repo["students"],
                "gist_count": len(repo["gist_sources"]),
            })
    
    return matches


def save_results(results: list[dict], repos: list[dict], matches: list[dict]):
    """Save all output files."""
    # Student contributions JSON
    with open(BASE_DIR / "gsoc_student_contributions.json", "w") as f:
        json.dump(results, f, indent=2, default=list)
    
    # Student contributions CSV
    csv_fields = [
        "gist_url", "github_username", "gist_id", "gsoc_year", "gsoc_org_name",
        "project_title_from_api", "student_name", "organisation", "sub_organisation",
        "project_title", "mentors", "proposal_url", "repos_from_prs", "pr_numbers",
        "repos_mentioned", "raw_content_length"
    ]
    with open(BASE_DIR / "gsoc_student_contributions.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for r in results:
            row = {k: r.get(k) for k in csv_fields}
            # Convert lists to pipe-separated strings
            for k in ["repos_from_prs", "pr_numbers", "repos_mentioned"]:
                if isinstance(row[k], list):
                    row[k] = "|".join(str(x) for x in row[k])
            writer.writerow(row)
    
    # Unique repos JSON
    with open(BASE_DIR / "gsoc_repos_from_gists.json", "w") as f:
        json.dump(repos, f, indent=2, default=list)
    
    # Unique repos CSV
    with open(BASE_DIR / "gsoc_repos_from_gists.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["repo", "gsoc_years", "gsoc_orgs", "students", "gist_count"])
        for r in repos:
            writer.writerow([
                r["repo"],
                "|".join(str(y) for y in r["gsoc_years"]),
                "|".join(r["gsoc_orgs"]),
                "|".join(r["students"]),
                len(r["gist_sources"]),
            ])
    
    # Matches JSON
    with open(BASE_DIR / "oss4sg_gsoc_matches_from_gists.json", "w") as f:
        json.dump(matches, f, indent=2, default=list)
    
    print(f"Saved:")
    print(f"  - gsoc_student_contributions.json/csv ({len(results)} entries)")
    print(f"  - gsoc_repos_from_gists.json/csv ({len(repos)} unique repos)")
    print(f"  - oss4sg_gsoc_matches_from_gists.json ({len(matches)} matches)")


def main():
    parser = argparse.ArgumentParser(description="Scrape GSoC student report gists")
    parser.add_argument("--max-gists", type=int, default=None,
                        help="Maximum number of gists to scrape (for testing)")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="Delay between requests in seconds")
    parser.add_argument("--oss4sg-csv", type=str,
                        default=str(BASE_DIR.parent.parent / "OSS4SG-Project-List.csv"),
                        help="Path to OSS4SG project list CSV")
    parser.add_argument("--url-column", type=str, default="repo_name_with_owner",
                        help="Column name for project URLs in OSS4SG CSV")
    args = parser.parse_args()
    
    # Load and filter
    print("Loading extracted GSoC data...")
    data = load_extracted_data()
    gists = filter_gist_urls(data)
    print(f"Found {len(gists)} gist URLs to scrape")
    
    # Scrape
    results = scrape_gists(gists, max_gists=args.max_gists, delay=args.delay)
    
    # Extract unique repos
    repos = extract_unique_repos(results)
    print(f"Extracted {len(repos)} unique repos from gists")
    
    # Load OSS4SG and match
    print(f"Loading OSS4SG projects from {args.oss4sg_csv}...")
    oss4sg_projects = load_oss4sg_projects(args.oss4sg_csv, args.url_column)
    print(f"Loaded {len(oss4sg_projects)} OSS4SG projects")
    
    matches = match_repos_to_oss4sg(repos, oss4sg_projects)
    print(f"Found {len(matches)} matches!")
    
    # Save
    save_results(results, repos, matches)


if __name__ == "__main__":
    main()
