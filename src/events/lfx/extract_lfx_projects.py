#!/usr/bin/env python3
"""
LFX Mentorship Project Extractor

Extracts all projects from the CNCF mentoring repository README files.
Parses upstream issue references to get exact GitHub repos.

Data source: https://github.com/cncf/mentoring/tree/main/programs/lfx-mentorship/
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

# ============================================================================
# Configuration
# ============================================================================

BASE_RAW_URL = "https://raw.githubusercontent.com/cncf/mentoring/main/programs/lfx-mentorship"

# Years to process
YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]

# Term folder naming patterns (varies by year)
# We'll try multiple patterns and use what works
TERM_PATTERNS = [
    # Modern naming (2023+)
    ["01-Mar-May", "02-Jun-Aug", "03-Sep-Nov"],
    # Alternative naming
    ["01-Mar-May", "02-Jun-Aug", "03-Sep-Dec"],
    # 2021-2022 style
    ["01-Spring", "02-Summer", "03-Fall"],
    # 2022 specific
    ["01-Spring", "02-Summer", "03-Sept-Nov"],
    # 2020 style
    ["q1", "q2", "q3-q4"],
    # Other variations
    ["Q1", "Q2", "Q3", "Q4"],
    ["Term1", "Term2", "Term3"],
]

# Output paths
SCRIPT_DIR = Path(__file__).parent
RAW_TERMS_DIR = SCRIPT_DIR / "lfx_raw_terms"
PROJECTS_OUTPUT = SCRIPT_DIR / "lfx_all_projects.json"
REPOS_OUTPUT = SCRIPT_DIR / "lfx_all_repos.json"
PROGRESS_FILE = SCRIPT_DIR / "lfx_extraction_progress.json"

# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class LFXProject:
    term: str
    title: str
    upstream_issue: str
    repo: str
    issue_number: int
    lfx_url: Optional[str]
    mentors: List[str]
    organization: str

# ============================================================================
# HTTP Utilities
# ============================================================================

def fetch_url(url: str, retries: int = 3) -> Optional[str]:
    """Fetch URL content with retries."""
    headers = {"User-Agent": "Mozilla/5.0 (LFX-Extractor)"}
    
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as response:
                return response.read().decode("utf-8")
        except HTTPError as e:
            if e.code == 404:
                return None  # Not found, don't retry
            print(f"  HTTP error {e.code} for {url}, attempt {attempt + 1}/{retries}")
        except URLError as e:
            print(f"  URL error for {url}: {e.reason}, attempt {attempt + 1}/{retries}")
        except Exception as e:
            print(f"  Error fetching {url}: {e}, attempt {attempt + 1}/{retries}")
        
        if attempt < retries - 1:
            time.sleep(1)
    
    return None

# ============================================================================
# Parsing Functions
# ============================================================================

def parse_upstream_issue(text: str) -> List[Tuple[str, str, int]]:
    """
    Extract upstream issues from text.
    Returns list of (full_ref, repo, issue_number) tuples.
    
    Patterns:
    - owner/repo#123
    - https://github.com/owner/repo/issues/123
    """
    results = []
    
    # Pattern 1: owner/repo#123 (most common)
    pattern1 = r'([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)#(\d+)'
    for match in re.finditer(pattern1, text):
        repo = match.group(1)
        issue_num = int(match.group(2))
        full_ref = f"{repo}#{issue_num}"
        results.append((full_ref, repo, issue_num))
    
    # Pattern 2: Full GitHub URL
    pattern2 = r'https://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)/issues/(\d+)'
    for match in re.finditer(pattern2, text):
        repo = match.group(1)
        issue_num = int(match.group(2))
        full_ref = f"{repo}#{issue_num}"
        if (full_ref, repo, issue_num) not in results:
            results.append((full_ref, repo, issue_num))
    
    return results

def extract_lfx_url(text: str) -> Optional[str]:
    """Extract LFX mentorship URL from text."""
    pattern = r'https://mentorship\.lfx\.linuxfoundation\.org/project/[a-zA-Z0-9-]+'
    match = re.search(pattern, text)
    return match.group(0) if match else None

def extract_mentors(text: str) -> List[str]:
    """Extract mentor GitHub handles from text."""
    # Look for @username patterns
    pattern = r'@([a-zA-Z0-9_-]+)'
    handles = re.findall(pattern, text)
    # Filter out common false positives
    filtered = [h for h in handles if h.lower() not in ['gmail', 'hotmail', 'yahoo', 'outlook', 'example']]
    return list(set(filtered))

def parse_readme_projects(content: str, term: str) -> List[LFXProject]:
    """
    Parse a README.md file and extract all projects.
    
    The structure is typically:
    ### Project Name (under organization header)
    - Description: ...
    - Upstream Issue: owner/repo#123
    - LFX URL: https://...
    - Mentor(s): @handle, ...
    """
    projects = []
    current_org = "Unknown"
    
    # Split by lines for processing
    lines = content.split('\n')
    
    # First pass: find all organization headers (## Org Name)
    # and project headers (### Project Name or #### Project Name)
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Organization header (## Name or # Name at top level)
        if line.startswith('## ') and not line.startswith('## Accepted') and not line.startswith('## Timeline'):
            org_name = line.lstrip('#').strip()
            # Clean up org name
            if org_name and len(org_name) > 2 and not org_name.lower().startswith('project'):
                current_org = org_name
        
        # Project header (### Name or #### Name)
        if (line.startswith('### ') or line.startswith('#### ')) and not 'Timeline' in line:
            project_title = line.lstrip('#').strip()
            
            # Skip non-project headers
            skip_titles = ['timeline', 'accepted projects', 'project instructions', 
                          'application instructions', 'project ideas', 'mentorship']
            if any(skip in project_title.lower() for skip in skip_titles):
                i += 1
                continue
            
            # Collect the project block (until next header or significant gap)
            project_block = []
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Stop at next header of same or higher level
                if next_line.strip().startswith('### ') or next_line.strip().startswith('## '):
                    break
                if next_line.strip().startswith('#### ') and j > i + 1:
                    # Another project at #### level
                    break
                project_block.append(next_line)
                j += 1
            
            block_text = '\n'.join(project_block)
            
            # Extract upstream issues
            issues = parse_upstream_issue(block_text)
            
            # Extract LFX URL
            lfx_url = extract_lfx_url(block_text)
            
            # Extract mentors
            mentors = extract_mentors(block_text)
            
            # Create project entries for each upstream issue found
            if issues:
                for full_ref, repo, issue_num in issues:
                    project = LFXProject(
                        term=term,
                        title=project_title,
                        upstream_issue=full_ref,
                        repo=repo,
                        issue_number=issue_num,
                        lfx_url=lfx_url,
                        mentors=mentors,
                        organization=current_org
                    )
                    projects.append(project)
            elif lfx_url:
                # Project has LFX URL but no upstream issue - still record it
                project = LFXProject(
                    term=term,
                    title=project_title,
                    upstream_issue="",
                    repo="",
                    issue_number=0,
                    lfx_url=lfx_url,
                    mentors=mentors,
                    organization=current_org
                )
                projects.append(project)
        
        i += 1
    
    return projects

# ============================================================================
# Main Extraction Logic
# ============================================================================

def get_term_urls(year: int) -> List[Tuple[str, str]]:
    """
    Get all possible README URLs for a given year.
    Returns list of (term_name, url) tuples to try.
    """
    urls = []
    
    for patterns in TERM_PATTERNS:
        for term in patterns:
            term_name = f"{year}/{term}"
            url = f"{BASE_RAW_URL}/{year}/{term}/README.md"
            urls.append((term_name, url))
    
    return urls

def load_progress() -> Dict:
    """Load extraction progress from file."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {"completed_terms": [], "all_projects": []}

def save_progress(progress: Dict):
    """Save extraction progress to file."""
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)

def main():
    """Main extraction function."""
    print("=" * 60)
    print("LFX Mentorship Project Extractor")
    print("=" * 60)
    
    # Create output directories
    RAW_TERMS_DIR.mkdir(exist_ok=True)
    
    # Load progress
    progress = load_progress()
    completed_terms = set(progress.get("completed_terms", []))
    all_projects = progress.get("all_projects", [])
    
    print(f"\nResuming from {len(completed_terms)} completed terms, {len(all_projects)} projects")
    
    # Track statistics
    terms_processed = len(completed_terms)
    terms_found = 0
    
    # Process each year
    for year in YEARS:
        print(f"\n--- Year {year} ---")
        
        # Get all possible term URLs for this year
        term_urls = get_term_urls(year)
        seen_terms_this_year = set()
        
        for term_name, url in term_urls:
            # Skip if already completed
            if term_name in completed_terms:
                continue
            
            # Skip duplicate terms (from trying multiple patterns)
            term_key = term_name.split('/')[1]
            if term_key in seen_terms_this_year:
                continue
            
            print(f"  Trying {term_name}...", end=" ")
            
            content = fetch_url(url)
            
            if content is None:
                print("not found")
                continue
            
            print("found!")
            seen_terms_this_year.add(term_key)
            terms_found += 1
            
            # Save raw content
            safe_term_name = term_name.replace("/", "_")
            raw_path = RAW_TERMS_DIR / f"{safe_term_name}.md"
            with open(raw_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Parse projects
            term_projects = parse_readme_projects(content, term_name)
            print(f"    Extracted {len(term_projects)} projects")
            
            # Add to all projects
            for proj in term_projects:
                all_projects.append(asdict(proj))
            
            # Mark as completed and save progress
            completed_terms.add(term_name)
            progress["completed_terms"] = list(completed_terms)
            progress["all_projects"] = all_projects
            save_progress(progress)
            
            terms_processed += 1
            
            # Small delay to be nice to GitHub
            time.sleep(0.5)
    
    # Generate final outputs
    print("\n" + "=" * 60)
    print("Generating final outputs...")
    
    # Calculate statistics
    repos_dict = {}
    for proj in all_projects:
        repo = proj.get("repo", "")
        if repo:
            if repo not in repos_dict:
                repos_dict[repo] = {"repo": repo, "project_count": 0, "terms": set()}
            repos_dict[repo]["project_count"] += 1
            repos_dict[repo]["terms"].add(proj["term"])
    
    # Convert sets to lists for JSON serialization
    repos_list = []
    for repo_data in repos_dict.values():
        repo_data["terms"] = sorted(list(repo_data["terms"]))
        repos_list.append(repo_data)
    
    # Sort by project count
    repos_list.sort(key=lambda x: x["project_count"], reverse=True)
    
    # Create output data
    projects_output = {
        "projects": all_projects,
        "stats": {
            "total_projects": len(all_projects),
            "projects_with_repos": len([p for p in all_projects if p.get("repo")]),
            "unique_repos": len(repos_dict),
            "terms_processed": len(completed_terms)
        }
    }
    
    repos_output = {
        "repos": repos_list,
        "total_unique_repos": len(repos_list)
    }
    
    # Write outputs
    with open(PROJECTS_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(projects_output, f, indent=2)
    print(f"  Wrote {PROJECTS_OUTPUT}")
    
    with open(REPOS_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(repos_output, f, indent=2)
    print(f"  Wrote {REPOS_OUTPUT}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Terms found/processed: {len(completed_terms)}")
    print(f"Total projects: {len(all_projects)}")
    print(f"Projects with GitHub repos: {len([p for p in all_projects if p.get('repo')])}")
    print(f"Unique GitHub repos: {len(repos_dict)}")
    
    # Show top repos
    if repos_list:
        print("\nTop 10 repos by project count:")
        for repo_data in repos_list[:10]:
            print(f"  {repo_data['repo']}: {repo_data['project_count']} projects")

if __name__ == "__main__":
    main()
