#!/usr/bin/env python3
"""
Fetch LFX Mentorship Contributors

For each upstream issue in LFX projects, fetch the issue details
to find assignees (mentees who worked on the project).

Uses 4 GitHub tokens with rotation for better rate limits.
"""

import json
import time
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from collections import defaultdict

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
PARENT_DIR = SCRIPT_DIR.parent
TOKENS_FILE = PARENT_DIR / "github_tokens.json"
INPUT_FILE = SCRIPT_DIR / "lfx_all_projects.json"
PROGRESS_FILE = SCRIPT_DIR / "lfx_contributors_progress.json"
OUTPUT_FILE = SCRIPT_DIR / "lfx_contributors.json"

SAVE_EVERY = 50
PRINT_EVERY = 50

# ============================================================================
# Token Management
# ============================================================================

def load_tokens():
    with open(TOKENS_FILE) as f:
        return json.load(f)["tokens"]

TOKENS = load_tokens()
current_token_idx = 0

def get_current_token():
    return TOKENS[current_token_idx]

def rotate_token():
    global current_token_idx
    current_token_idx = (current_token_idx + 1) % len(TOKENS)

def get_headers():
    return {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {get_current_token()}",
        "User-Agent": "LFX-Contributor-Fetcher"
    }

# ============================================================================
# Progress Management
# ============================================================================

def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {"checked_issues": {}, "contributors": {}, "errors": []}

def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)

# ============================================================================
# API Functions
# ============================================================================

def fetch_issue(owner: str, repo: str, issue_num: int) -> dict:
    """Fetch issue details from GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_num}"
    
    for attempt in range(3):
        try:
            req = Request(url, headers=get_headers())
            with urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 404:
                return {"error": "not_found"}
            elif e.code in [403, 429]:
                rotate_token()
                time.sleep(1)
            elif e.code == 401:
                rotate_token()
            else:
                return {"error": f"http_{e.code}"}
        except URLError:
            time.sleep(1)
        except Exception as e:
            return {"error": str(e)[:50]}
    
    return {"error": "max_retries"}

def extract_contributors_from_issue(issue_data: dict) -> list:
    """Extract contributor usernames from issue data."""
    contributors = []
    
    # Get assignees
    assignees = issue_data.get("assignees", [])
    for assignee in assignees:
        if assignee and assignee.get("login"):
            contributors.append({
                "username": assignee["login"].lower(),
                "source": "assignee"
            })
    
    # Get single assignee if exists
    assignee = issue_data.get("assignee")
    if assignee and assignee.get("login"):
        username = assignee["login"].lower()
        if not any(c["username"] == username for c in contributors):
            contributors.append({
                "username": username,
                "source": "assignee"
            })
    
    return contributors

# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 60)
    print("LFX Mentorship - Contributor Fetcher")
    print("=" * 60)
    print(f"Tokens loaded: {len(TOKENS)}")
    
    # Load projects
    with open(INPUT_FILE) as f:
        data = json.load(f)
    
    projects = data.get("projects", [])
    
    # Filter to projects with upstream issues
    projects_with_issues = []
    for p in projects:
        issue = p.get("upstream_issue", "")
        if issue and "#" in issue:
            parts = issue.split("#")
            if len(parts) == 2 and "/" in parts[0]:
                owner_repo = parts[0]
                issue_num = parts[1]
                try:
                    issue_num = int(issue_num)
                    owner, repo = owner_repo.split("/", 1)
                    projects_with_issues.append({
                        "owner": owner,
                        "repo": repo,
                        "issue_num": issue_num,
                        "term": p.get("term", ""),
                        "title": p.get("title", ""),
                        "issue_key": issue
                    })
                except:
                    pass
    
    total = len(projects_with_issues)
    print(f"Projects with upstream issues: {total}")
    
    # Load progress
    progress = load_progress()
    checked = progress.get("checked_issues", {})
    all_contributors = progress.get("contributors", {})
    errors = progress.get("errors", [])
    
    print(f"Already checked: {len(checked)}")
    print(f"Contributors found so far: {len(all_contributors)}")
    print()
    
    # Process issues
    start_time = time.time()
    
    try:
        for i, proj in enumerate(projects_with_issues):
            issue_key = proj["issue_key"]
            
            # Skip if already checked
            if issue_key in checked:
                continue
            
            # Fetch issue
            issue_data = fetch_issue(proj["owner"], proj["repo"], proj["issue_num"])
            
            if "error" in issue_data:
                checked[issue_key] = {"status": issue_data["error"]}
                errors.append({"issue": issue_key, "error": issue_data["error"]})
            else:
                # Extract contributors
                contribs = extract_contributors_from_issue(issue_data)
                checked[issue_key] = {
                    "status": "ok",
                    "contributors": [c["username"] for c in contribs]
                }
                
                # Add to all_contributors
                for c in contribs:
                    username = c["username"]
                    if username not in all_contributors:
                        all_contributors[username] = {
                            "repos": [],
                            "terms": [],
                            "issues": []
                        }
                    
                    repo_full = f"{proj['owner']}/{proj['repo']}".lower()
                    if repo_full not in all_contributors[username]["repos"]:
                        all_contributors[username]["repos"].append(repo_full)
                    if proj["term"] not in all_contributors[username]["terms"]:
                        all_contributors[username]["terms"].append(proj["term"])
                    all_contributors[username]["issues"].append(issue_key)
            
            # Progress display
            done = len(checked)
            if done % PRINT_EVERY == 0 or done == total:
                elapsed = time.time() - start_time
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (total - done) / rate if rate > 0 else 0
                print(f"[{done}/{total}] Contributors: {len(all_contributors)} | "
                      f"Errors: {len(errors)} | ETA: {int(remaining)}s")
            
            # Save progress
            if done % SAVE_EVERY == 0:
                progress["checked_issues"] = checked
                progress["contributors"] = all_contributors
                progress["errors"] = errors
                save_progress(progress)
            
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\n\nInterrupted! Saving progress...")
    
    # Final save
    progress["checked_issues"] = checked
    progress["contributors"] = all_contributors
    progress["errors"] = errors
    save_progress(progress)
    
    # Generate output
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    ok_count = sum(1 for v in checked.values() if v.get("status") == "ok")
    error_count = len(errors)
    
    print(f"Issues checked: {len(checked)}")
    print(f"  - OK: {ok_count}")
    print(f"  - Errors: {error_count}")
    print(f"\nTotal contributors found: {len(all_contributors)}")
    
    # Create contributors list
    contributors_list = []
    for username, data in all_contributors.items():
        contributors_list.append({
            "github_username": username,
            "repos_contributed": data["repos"],
            "repo_count": len(data["repos"]),
            "lfx_terms": data["terms"],
            "issue_count": len(data["issues"]),
            "event": "lfx"
        })
    
    contributors_list.sort(key=lambda x: x["repo_count"], reverse=True)
    
    # Save output
    output = {
        "event": "lfx_mentorship",
        "total_contributors": len(contributors_list),
        "total_issues_checked": len(checked),
        "contributors": contributors_list
    }
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nTop 10 contributors:")
    for c in contributors_list[:10]:
        print(f"  {c['github_username']}: {c['repo_count']} repos, {c['issue_count']} issues")
    
    print(f"\nSaved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
