#!/usr/bin/env python3
"""
Fetch GitHub Metadata for Event Repos - Phase B

Features:
- Progress bar with ETA
- Token rate limit tracking (remaining/reset time per token)
- Resume capability (saves after each repo)
- Clean output with status updates

Usage:
  python fetch_github_metadata.py

Tokens are hardcoded below for convenience.
"""

import json
import os
import sys
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ============================================================================
# CONFIGURATION
# ============================================================================

TOKENS = [
    "os.environ.get("GITHUB_TOKEN", "")",
    "os.environ.get("GITHUB_TOKEN", "")",
    "os.environ.get("GITHUB_TOKEN", "")",
    "os.environ.get("GITHUB_TOKEN", "")",
]

BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "all_event_repos_consolidated.json"
OUTPUT_FILE = BASE_DIR / "repo_metadata.json"
PROGRESS_FILE = BASE_DIR / "repo_metadata_progress.json"

# Optional: if these files exist, use them to limit targets.
# Each should contain a JSON array of repo names (owner/repo).
TARGETS_FILE = BASE_DIR / "targets_override.json"
TARGETS_MISSING_FILE = BASE_DIR / "targets_missing.json"

# Selection criteria: repos with >=5 event contributors OR is_oss4sg
MIN_CONTRIBUTORS = 5

# ============================================================================
# TOKEN MANAGER - Track rate limits per token
# ============================================================================

class TokenManager:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current_idx = 0
        # Track rate limits per token: {token_idx: {"remaining": X, "reset": timestamp}}
        self.limits = {i: {"remaining": 5000, "reset": 0} for i in range(len(tokens))}
        self.total_requests = 0
    
    def get_token(self):
        """Get current token."""
        return self.tokens[self.current_idx]
    
    def get_headers(self):
        """Get headers with current token."""
        return {
            "Authorization": f"token {self.get_token()}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "EventRepoMetadataFetcher/1.0"
        }
    
    def update_limits(self, headers):
        """Update rate limit info from response headers."""
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")
        if remaining is not None:
            self.limits[self.current_idx]["remaining"] = int(remaining)
        if reset is not None:
            self.limits[self.current_idx]["reset"] = int(reset)
        self.total_requests += 1
    
    def rotate_if_needed(self):
        """Rotate to next token if current is low on requests."""
        current = self.limits[self.current_idx]
        if current["remaining"] < 50:
            # Find token with most remaining
            best_idx = max(self.limits.keys(), key=lambda i: self.limits[i]["remaining"])
            if self.limits[best_idx]["remaining"] > current["remaining"]:
                self.current_idx = best_idx
    
    def wait_if_needed(self):
        """Wait if all tokens are rate limited."""
        # Check if all tokens are exhausted
        all_exhausted = all(self.limits[i]["remaining"] < 10 for i in range(len(self.tokens)))
        if all_exhausted:
            # Find earliest reset time
            earliest_reset = min(self.limits[i]["reset"] for i in range(len(self.tokens)))
            wait_time = earliest_reset - time.time() + 5  # +5 buffer
            if wait_time > 0:
                print(f"\n⏳ All tokens exhausted. Waiting {wait_time:.0f}s for reset...")
                time.sleep(wait_time)
                # Reset limits after waiting
                for i in range(len(self.tokens)):
                    self.limits[i]["remaining"] = 5000
    
    def get_status(self):
        """Get formatted status string."""
        parts = []
        for i, token in enumerate(self.tokens):
            remaining = self.limits[i]["remaining"]
            reset_ts = self.limits[i]["reset"]
            if reset_ts > 0:
                reset_in = max(0, reset_ts - time.time())
                reset_str = f"{reset_in/60:.0f}m"
            else:
                reset_str = "?"
            marker = "→" if i == self.current_idx else " "
            parts.append(f"{marker}T{i+1}:{remaining}({reset_str})")
        return " | ".join(parts)


# ============================================================================
# API FUNCTIONS
# ============================================================================

def api_request(url, token_mgr, is_search=False):
    """Make API request with error handling and rate limit tracking."""
    token_mgr.rotate_if_needed()
    token_mgr.wait_if_needed()
    
    headers = token_mgr.get_headers()
    req = Request(url, headers=headers)
    
    try:
        with urlopen(req, timeout=30) as resp:
            token_mgr.update_limits(dict(resp.headers))
            data = json.loads(resp.read().decode("utf-8"))
            link_header = resp.headers.get("Link", "")
            return {"data": data, "link": link_header, "status": 200}
    except HTTPError as e:
        token_mgr.update_limits(dict(e.headers) if hasattr(e, 'headers') else {})
        if e.code == 404:
            return {"data": None, "status": 404}
        elif e.code == 403:
            # Rate limited or blocked
            return {"data": None, "status": 403}
        elif e.code == 422:
            return {"data": None, "status": 422}
        else:
            return {"data": None, "status": e.code}
    except URLError as e:
        return {"data": None, "status": -1}
    except Exception as e:
        return {"data": None, "status": -1}


def parse_link_count(link_header):
    """Parse Link header to get last page number (= total count when per_page=1)."""
    if not link_header:
        return None
    match = re.search(r'<[^>]+[?&]page=(\d+)[^>]*>;\s*rel="last"', link_header)
    if match:
        return int(match.group(1))
    return None


def fetch_repo_metadata(repo_name, token_mgr):
    """Fetch all metadata for a single repo."""
    result = {
        "repo_name": repo_name,
        "stars": None,
        "forks": None,
        "open_issues": None,
        "watchers": None,
        "language": None,
        "created_at": None,
        "updated_at": None,
        "pushed_at": None,
        "contributor_count": None,
        "commit_count": None,
        "closed_pr_count": None,
        "status": "ok",
    }
    
    # 1. Basic repo info
    resp = api_request(f"https://api.github.com/repos/{repo_name}", token_mgr)
    if resp["status"] == 404:
        result["status"] = "not_found"
        return result
    elif resp["status"] != 200:
        result["status"] = f"error_{resp['status']}"
        return result
    
    data = resp["data"]
    result["stars"] = data.get("stargazers_count")
    result["forks"] = data.get("forks_count")
    result["open_issues"] = data.get("open_issues_count")
    result["watchers"] = data.get("subscribers_count")
    result["language"] = data.get("language")
    result["created_at"] = data.get("created_at")
    result["updated_at"] = data.get("updated_at")
    result["pushed_at"] = data.get("pushed_at")
    
    time.sleep(0.1)
    
    # 2. Contributor count (via Link header)
    resp = api_request(f"https://api.github.com/repos/{repo_name}/contributors?per_page=1&anon=1", token_mgr)
    if resp["status"] == 200:
        count = parse_link_count(resp["link"])
        if count:
            result["contributor_count"] = count
        elif resp["data"]:
            result["contributor_count"] = len(resp["data"])  # Single page = small count
    
    time.sleep(0.1)
    
    # 3. Commit count (via Link header) - can be slow for large repos
    resp = api_request(f"https://api.github.com/repos/{repo_name}/commits?per_page=1", token_mgr)
    if resp["status"] == 200:
        count = parse_link_count(resp["link"])
        if count:
            result["commit_count"] = count
        elif resp["data"]:
            result["commit_count"] = len(resp["data"])
    
    time.sleep(0.1)
    
    # 4. Closed PR count (via Search API - slower rate limit)
    # Search API has 30 requests/minute limit
    time.sleep(2.0)  # Be conservative with search API
    resp = api_request(
        f"https://api.github.com/search/issues?q=repo:{repo_name}+type:pr+is:closed&per_page=1",
        token_mgr,
        is_search=True
    )
    if resp["status"] == 200 and resp["data"]:
        result["closed_pr_count"] = resp["data"].get("total_count")
    
    return result


# ============================================================================
# PROGRESS DISPLAY
# ============================================================================

def format_time(seconds):
    """Format seconds as HH:MM:SS or MM:SS."""
    if seconds < 0:
        return "??:??"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    elif minutes > 0:
        return f"{minutes}m{secs:02d}s"
    else:
        return f"{secs}s"


def print_progress(current, total, repo_name, token_mgr, start_time, errors):
    """Print progress line."""
    pct = current / total * 100 if total > 0 else 0
    bar_width = 30
    filled = int(bar_width * current / total) if total > 0 else 0
    bar = "=" * filled + ">" + " " * (bar_width - filled - 1) if filled < bar_width else "=" * bar_width
    
    elapsed = time.time() - start_time
    if current > 0:
        rate = current / elapsed  # repos per second
        remaining = (total - current) / rate if rate > 0 else 0
        eta = format_time(remaining)
    else:
        eta = "??:??"
    
    # Truncate repo name
    repo_display = repo_name[:35] + "..." if len(repo_name) > 38 else repo_name
    
    print(f"\r[{bar}] {current}/{total} ({pct:.1f}%) | ETA: {eta} | Errors: {errors} | {repo_display:<40}", end="")
    sys.stdout.flush()


def print_token_status(token_mgr):
    """Print token status on new line."""
    print(f"\n📊 Tokens: {token_mgr.get_status()}")


# ============================================================================
# MAIN
# ============================================================================

def load_input():
    """Load repos to process."""
    with open(INPUT_FILE, "r") as f:
        data = json.load(f)
    repos = data.get("repos", [])

    # If override file exists, use it to limit targets
    # Missing override takes precedence (to resume partial sets)
    if TARGETS_MISSING_FILE.exists():
        with open(TARGETS_MISSING_FILE, "r") as f:
            override_list = [r.strip().lower() for r in json.load(f)]
        lookup = {r["repo_name"].lower(): r for r in repos}
        targets = [lookup[name] for name in override_list if name in lookup]
        print(f"   → Using override target list: {len(targets)} repos from {TARGETS_MISSING_FILE.name}")
        return targets

    # Otherwise use full override if present
    if TARGETS_FILE.exists():
        with open(TARGETS_FILE, "r") as f:
            override_list = [r.strip().lower() for r in json.load(f)]
        lookup = {r["repo_name"].lower(): r for r in repos}
        targets = [lookup[name] for name in override_list if name in lookup]
        print(f"   → Using override target list: {len(targets)} repos from {TARGETS_FILE.name}")
        return targets

    # Default selection: >=MIN_CONTRIBUTORS OR is_oss4sg
    targets = [r for r in repos if r.get("total_event_contributors", 0) >= MIN_CONTRIBUTORS or r.get("is_oss4sg")]
    return targets


def load_progress():
    """Load already-processed repos."""
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r") as f:
            data = json.load(f)
            return {item["repo_name"].lower(): item for item in data}
    return {}


def save_progress(done_dict, targets):
    """Save current progress."""
    items = list(done_dict.values())
    with open(OUTPUT_FILE, "w") as f:
        json.dump(items, f, indent=2)
    
    progress = {
        "completed": len(items),
        "total": len(targets),
        "percent": len(items) / len(targets) * 100 if targets else 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def main():
    print("=" * 70)
    print("FETCH GITHUB METADATA - PHASE B")
    print("=" * 70)
    
    # Load targets
    targets = load_input()
    print(f"\n📁 Loaded {len(targets)} repos to process")
    print(f"   (OSS4SG projects + repos with >={MIN_CONTRIBUTORS} event contributors)")
    
    # Load progress and filter to current targets only
    done_all = load_progress()
    target_names = {t["repo_name"].lower() for t in targets}
    done = {k: v for k, v in done_all.items() if k in target_names}
    print(f"✅ Already completed (in this target set): {len(done)}")
    print(f"📋 Remaining: {len(targets) - len(done)}")
    
    if len(done) >= len(targets):
        print("\n✨ All repos in this target set already processed!")
        return
    
    # Initialize token manager
    token_mgr = TokenManager(TOKENS)
    print(f"\n🔑 Using {len(TOKENS)} tokens")
    print_token_status(token_mgr)
    
    print("\n" + "-" * 70)
    print("Starting... (Ctrl+C to pause, will resume on next run)")
    print("-" * 70 + "\n")
    
    start_time = time.time()
    errors = 0
    processed = len(done)
    
    try:
        for i, repo in enumerate(targets):
            repo_name = repo["repo_name"].lower()
            
            # Skip if already done
            if repo_name in done:
                continue
            
            # Print progress
            print_progress(processed, len(targets), repo_name, token_mgr, start_time, errors)
            
            # Fetch metadata
            metadata = fetch_repo_metadata(repo_name, token_mgr)
            
            # Add event info from input
            metadata["is_oss4sg"] = repo.get("is_oss4sg", False)
            metadata["total_event_contributors"] = repo.get("total_event_contributors", 0)
            metadata["event_count"] = repo.get("event_count", 0)
            metadata["events"] = repo.get("events", [])
            metadata["fetched_at"] = datetime.now(timezone.utc).isoformat()
            
            if metadata["status"] != "ok":
                errors += 1
            
            done[repo_name] = metadata
            processed += 1
            
            # Save progress after each repo
            save_progress(done, targets)
            
            # Print token status every 50 repos
            if processed % 50 == 0:
                print_token_status(token_mgr)
                print()
            
            # Small delay between repos
            time.sleep(0.2)
    
    except KeyboardInterrupt:
        print("\n\n⏸️  Paused by user. Progress saved. Run again to resume.")
        save_progress(done, targets)
        return
    
    # Final summary
    print("\n\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)
    print(f"✅ Processed: {len(done)}/{len(targets)} repos")
    print(f"❌ Errors: {errors}")
    print(f"⏱️  Time: {format_time(time.time() - start_time)}")
    print(f"📁 Output: {OUTPUT_FILE}")
    print_token_status(token_mgr)


if __name__ == "__main__":
    main()
