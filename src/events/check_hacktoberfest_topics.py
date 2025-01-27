#!/usr/bin/env python3
"""
Hacktoberfest Topic Checker

Checks which repos from our event list have the 'hacktoberfest' GitHub topic.
- Uses 4 GitHub tokens with rotation (20,000 requests/hour)
- Resume-safe with progress tracking
- Clear progress display
"""

import json
import time
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from datetime import datetime, timedelta

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
TOKENS_FILE = SCRIPT_DIR / "github_tokens.json"
INPUT_FILE = SCRIPT_DIR / "all_event_repos_combined.json"
PROGRESS_FILE = SCRIPT_DIR / "hacktoberfest_check_progress.json"
OUTPUT_FILE = SCRIPT_DIR / "hacktoberfest_repos.json"

# Progress save frequency
SAVE_EVERY = 100
PRINT_EVERY = 100

# ============================================================================
# Token Management
# ============================================================================

def load_tokens():
    """Load tokens from JSON file."""
    with open(TOKENS_FILE) as f:
        data = json.load(f)
        return data["tokens"]

TOKENS = load_tokens()
current_token_idx = 0
token_request_counts = [0] * len(TOKENS)

def get_current_token():
    """Get the current active token."""
    return TOKENS[current_token_idx]

def rotate_token():
    """Rotate to the next token."""
    global current_token_idx
    current_token_idx = (current_token_idx + 1) % len(TOKENS)

def get_headers():
    """Get request headers with current token."""
    return {
        "Accept": "application/vnd.github.mercy-preview+json",
        "Authorization": f"token {get_current_token()}",
        "User-Agent": "Hacktoberfest-Topic-Checker"
    }

# ============================================================================
# Progress Management
# ============================================================================

def load_progress():
    """Load progress from file."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {
        "checked": {},
        "hacktoberfest_repos": [],
        "errors": [],
        "last_index": 0
    }

def save_progress(progress):
    """Save progress to file."""
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)

# ============================================================================
# API Functions
# ============================================================================

def check_repo_topics(repo: str) -> dict:
    """
    Check if a repo has hacktoberfest topic.
    Returns dict with status and topics.
    """
    global current_token_idx, token_request_counts
    
    # Clean repo name
    repo = repo.strip().lower()
    if not repo or '/' not in repo:
        return {"status": "invalid", "has_hacktoberfest": False}
    
    url = f"https://api.github.com/repos/{repo}/topics"
    
    for attempt in range(3):
        try:
            token_request_counts[current_token_idx] += 1
            req = Request(url, headers=get_headers())
            with urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                topics = data.get("names", [])
                has_hacktoberfest = "hacktoberfest" in [t.lower() for t in topics]
                return {
                    "status": "ok",
                    "topics": topics,
                    "has_hacktoberfest": has_hacktoberfest
                }
        except HTTPError as e:
            if e.code == 404:
                return {"status": "not_found", "has_hacktoberfest": False}
            elif e.code == 403:
                # Rate limited - rotate token
                rotate_token()
                if attempt < 2:
                    time.sleep(1)
                continue
            elif e.code == 401:
                # Bad token - rotate
                rotate_token()
                continue
            else:
                return {"status": f"error_{e.code}", "has_hacktoberfest": False}
        except URLError:
            if attempt < 2:
                time.sleep(1)
            continue
        except Exception as e:
            return {"status": f"error_{str(e)[:30]}", "has_hacktoberfest": False}
    
    return {"status": "max_retries", "has_hacktoberfest": False}

# ============================================================================
# Progress Display
# ============================================================================

def format_time(seconds):
    """Format seconds as HH:MM:SS."""
    return str(timedelta(seconds=int(seconds)))

def print_progress(current, total, found, errors, start_time):
    """Print progress bar and stats."""
    elapsed = time.time() - start_time
    rate = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / rate if rate > 0 else 0
    
    pct = current / total * 100
    bar_width = 30
    filled = int(bar_width * current / total)
    bar = '█' * filled + '░' * (bar_width - filled)
    
    # Token usage
    token_str = " | ".join([f"T{i+1}:{c}" for i, c in enumerate(token_request_counts)])
    
    print(f"\r[{bar}] {pct:5.1f}% | {current:,}/{total:,} | "
          f"Found: {found} | Errors: {errors} | "
          f"ETA: {format_time(remaining)} | {token_str}    ", end="", flush=True)

# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 70)
    print("HACKTOBERFEST TOPIC CHECKER")
    print("=" * 70)
    print(f"Tokens loaded: {len(TOKENS)}")
    print(f"Capacity: {len(TOKENS) * 5000:,} requests/hour")
    print()
    
    # Load repos
    if not INPUT_FILE.exists():
        print(f"ERROR: Input file not found: {INPUT_FILE}")
        print("Run the repo combination script first.")
        sys.exit(1)
    
    with open(INPUT_FILE, 'r') as f:
        all_repos = json.load(f)
    
    total = len(all_repos)
    print(f"Total repos to check: {total:,}")
    
    # Load progress
    progress = load_progress()
    checked = progress.get("checked", {})
    hacktoberfest_repos = progress.get("hacktoberfest_repos", [])
    errors = progress.get("errors", [])
    
    already_done = len(checked)
    print(f"Already checked: {already_done:,}")
    print(f"Hacktoberfest repos found so far: {len(hacktoberfest_repos)}")
    print(f"Remaining: {total - already_done:,}")
    print()
    
    if already_done >= total:
        print("All repos already checked!")
    else:
        print("Starting checks... (Press Ctrl+C to pause, progress is saved)")
        print()
        
        start_time = time.time()
        
        try:
            for i, repo in enumerate(all_repos):
                # Skip already checked
                if repo in checked:
                    continue
                
                # Check repo
                result = check_repo_topics(repo)
                checked[repo] = result
                
                if result.get("has_hacktoberfest"):
                    hacktoberfest_repos.append(repo)
                
                if result.get("status") not in ["ok", "not_found"]:
                    errors.append({"repo": repo, "status": result.get("status")})
                
                # Progress display
                done = len(checked)
                if done % PRINT_EVERY == 0 or done == total:
                    print_progress(done, total, len(hacktoberfest_repos), len(errors), start_time)
                
                # Save progress periodically
                if done % SAVE_EVERY == 0:
                    progress["checked"] = checked
                    progress["hacktoberfest_repos"] = hacktoberfest_repos
                    progress["errors"] = errors
                    save_progress(progress)
                
                # Small delay to be nice
                time.sleep(0.05)
        
        except KeyboardInterrupt:
            print("\n\nInterrupted! Saving progress...")
        
        # Final save
        progress["checked"] = checked
        progress["hacktoberfest_repos"] = hacktoberfest_repos
        progress["errors"] = errors
        save_progress(progress)
    
    # Generate output
    print("\n")
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    ok_count = sum(1 for r in checked.values() if r.get("status") == "ok")
    not_found = sum(1 for r in checked.values() if r.get("status") == "not_found")
    error_count = len(errors)
    
    print(f"Repos checked:      {len(checked):,}")
    print(f"  - OK:             {ok_count:,}")
    print(f"  - Not found:      {not_found:,}")
    print(f"  - Errors:         {error_count:,}")
    print()
    print(f"HACKTOBERFEST REPOS: {len(hacktoberfest_repos):,}")
    
    # Save final output
    output = {
        "summary": {
            "total_checked": len(checked),
            "repos_ok": ok_count,
            "repos_not_found": not_found,
            "repos_error": error_count,
            "hacktoberfest_count": len(hacktoberfest_repos)
        },
        "hacktoberfest_repos": sorted(hacktoberfest_repos),
        "errors": errors[:100]  # Keep first 100 errors
    }
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nResults saved to: {OUTPUT_FILE}")
    
    # Show sample
    if hacktoberfest_repos:
        print(f"\nSample Hacktoberfest repos (first 20):")
        for repo in sorted(hacktoberfest_repos)[:20]:
            print(f"  - {repo}")
        if len(hacktoberfest_repos) > 20:
            print(f"  ... and {len(hacktoberfest_repos) - 20} more")

if __name__ == "__main__":
    main()
