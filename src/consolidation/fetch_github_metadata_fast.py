#!/usr/bin/env python3
"""
Fast GitHub Metadata Fetcher - Uses all tokens in parallel

Speed optimizations:
- Parallel requests across 4 tokens (ThreadPoolExecutor)
- Minimal delays (respecting rate limits)
- Skips Search API for closed PRs (slowest call) - can add later if needed

Bug fixes:
- Always preserves ALL fetched repos (never deletes data)
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
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

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
TARGETS_FILE = BASE_DIR / "targets_override.json"
TARGETS_MISSING_FILE = BASE_DIR / "targets_missing.json"

MIN_CONTRIBUTORS = 5

# Each token gets ~83 requests/min (5000/hour)
# With 4 tokens running in parallel = ~332 requests/min
# 3 API calls per repo = ~110 repos/min theoretical max
# Being conservative: ~60-80 repos/min realistic

# ============================================================================
# THREAD-SAFE TOKEN MANAGER
# ============================================================================

class ParallelTokenManager:
    def __init__(self, tokens):
        self.tokens = tokens
        self.locks = [threading.Lock() for _ in tokens]
        self.limits = [{"remaining": 5000, "reset": 0, "requests": 0} for _ in tokens]
        self.global_lock = threading.Lock()
        self.total_requests = 0
        self.total_errors = 0
    
    def get_headers(self, token_idx):
        return {
            "Authorization": f"token {self.tokens[token_idx]}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "EventRepoMetadataFetcher/2.0"
        }
    
    def update_limits(self, token_idx, headers):
        with self.locks[token_idx]:
            remaining = headers.get("X-RateLimit-Remaining")
            reset = headers.get("X-RateLimit-Reset")
            if remaining is not None:
                self.limits[token_idx]["remaining"] = int(remaining)
            if reset is not None:
                self.limits[token_idx]["reset"] = int(reset)
            self.limits[token_idx]["requests"] += 1
        with self.global_lock:
            self.total_requests += 1
    
    def check_rate_limit(self, token_idx):
        """Wait if this token is rate limited."""
        with self.locks[token_idx]:
            if self.limits[token_idx]["remaining"] < 10:
                reset_time = self.limits[token_idx]["reset"]
                wait = reset_time - time.time() + 2
                if wait > 0:
                    print(f"\n⏳ Token {token_idx+1} rate limited. Waiting {wait:.0f}s...")
                    time.sleep(wait)
                    self.limits[token_idx]["remaining"] = 5000
    
    def increment_errors(self):
        with self.global_lock:
            self.total_errors += 1
    
    def get_status(self):
        parts = []
        for i in range(len(self.tokens)):
            with self.locks[i]:
                r = self.limits[i]["remaining"]
                req = self.limits[i]["requests"]
            parts.append(f"T{i+1}:{r}({req}req)")
        return " | ".join(parts)


# ============================================================================
# API FUNCTIONS (per-token)
# ============================================================================

def api_request(url, token_idx, token_mgr):
    """Make API request with specific token."""
    token_mgr.check_rate_limit(token_idx)
    
    headers = token_mgr.get_headers(token_idx)
    req = Request(url, headers=headers)
    
    try:
        with urlopen(req, timeout=30) as resp:
            token_mgr.update_limits(token_idx, dict(resp.headers))
            data = json.loads(resp.read().decode("utf-8"))
            link_header = resp.headers.get("Link", "")
            return {"data": data, "link": link_header, "status": 200}
    except HTTPError as e:
        if hasattr(e, 'headers'):
            token_mgr.update_limits(token_idx, dict(e.headers))
        return {"data": None, "status": e.code}
    except Exception:
        return {"data": None, "status": -1}


def parse_link_count(link_header):
    if not link_header:
        return None
    match = re.search(r'<[^>]+[?&]page=(\d+)[^>]*>;\s*rel="last"', link_header)
    return int(match.group(1)) if match else None


def fetch_repo_metadata(repo_info, token_idx, token_mgr):
    """Fetch metadata for a single repo using assigned token."""
    repo_name = repo_info["repo_name"]
    
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
        "closed_pr_count": None,  # Skipped for speed - can add later
        "status": "ok",
        "is_oss4sg": repo_info.get("is_oss4sg", False),
        "total_event_contributors": repo_info.get("total_event_contributors", 0),
        "event_count": repo_info.get("event_count", 0),
        "events": repo_info.get("events", []),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # 1. Basic repo info
    resp = api_request(f"https://api.github.com/repos/{repo_name}", token_idx, token_mgr)
    if resp["status"] == 404:
        result["status"] = "not_found"
        token_mgr.increment_errors()
        return result
    elif resp["status"] != 200:
        result["status"] = f"error_{resp['status']}"
        token_mgr.increment_errors()
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
    
    # Small delay between calls (same token)
    time.sleep(0.05)
    
    # 2. Contributor count
    resp = api_request(f"https://api.github.com/repos/{repo_name}/contributors?per_page=1&anon=1", token_idx, token_mgr)
    if resp["status"] == 200:
        count = parse_link_count(resp["link"])
        if count:
            result["contributor_count"] = count
        elif resp["data"]:
            result["contributor_count"] = len(resp["data"])
    
    time.sleep(0.05)
    
    # 3. Commit count
    resp = api_request(f"https://api.github.com/repos/{repo_name}/commits?per_page=1", token_idx, token_mgr)
    if resp["status"] == 200:
        count = parse_link_count(resp["link"])
        if count:
            result["commit_count"] = count
        elif resp["data"]:
            result["commit_count"] = len(resp["data"])
    
    # NOTE: Skipping closed_pr_count (Search API) for speed
    # The Search API has 30 req/min limit and adds ~2s per repo
    # Can fetch this separately later if needed
    
    return result


# ============================================================================
# DATA LOADING / SAVING
# ============================================================================

def load_input():
    """Load consolidated repo data."""
    with open(INPUT_FILE, "r") as f:
        data = json.load(f)
    return {r["repo_name"].lower(): r for r in data.get("repos", [])}


def load_targets():
    """Load target list (which repos to fetch)."""
    if TARGETS_MISSING_FILE.exists():
        with open(TARGETS_MISSING_FILE, "r") as f:
            return [r.strip().lower() for r in json.load(f)]
    if TARGETS_FILE.exists():
        with open(TARGETS_FILE, "r") as f:
            return [r.strip().lower() for r in json.load(f)]
    return None  # Use default selection


def load_all_metadata():
    """Load ALL previously fetched metadata (never filter/delete)."""
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r") as f:
            data = json.load(f)
            return {item["repo_name"].lower(): item for item in data}
    return {}


def save_all_metadata(all_metadata, current_targets_count):
    """Save ALL metadata (preserves everything)."""
    items = list(all_metadata.values())
    with open(OUTPUT_FILE, "w") as f:
        json.dump(items, f, indent=2)
    
    # Progress is relative to current target
    progress = {
        "total_fetched": len(items),
        "current_target": current_targets_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


# ============================================================================
# PROGRESS DISPLAY
# ============================================================================

class ProgressTracker:
    def __init__(self, total):
        self.total = total
        self.completed = 0
        self.errors = 0
        self.start_time = time.time()
        self.lock = threading.Lock()
        self.last_print = 0
    
    def update(self, repo_name, is_error=False):
        with self.lock:
            self.completed += 1
            if is_error:
                self.errors += 1
            
            # Throttle printing (every 0.2s max)
            now = time.time()
            if now - self.last_print < 0.2 and self.completed < self.total:
                return
            self.last_print = now
            
            pct = self.completed / self.total * 100
            bar_width = 40
            filled = int(bar_width * self.completed / self.total)
            bar = "█" * filled + "░" * (bar_width - filled)
            
            elapsed = now - self.start_time
            rate = self.completed / elapsed if elapsed > 0 else 0
            remaining = (self.total - self.completed) / rate if rate > 0 else 0
            
            eta = f"{int(remaining//60)}m{int(remaining%60):02d}s" if remaining < 3600 else f"{remaining/3600:.1f}h"
            
            repo_short = repo_name[:30] + "..." if len(repo_name) > 30 else repo_name
            
            print(f"\r{bar} {self.completed}/{self.total} ({pct:.1f}%) | "
                  f"ETA: {eta} | {rate:.1f}/s | Err: {self.errors} | {repo_short:<35}", end="")
            sys.stdout.flush()


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 75)
    print("FAST GITHUB METADATA FETCHER - PARALLEL MODE")
    print("=" * 75)
    
    # Load data
    all_repos = load_input()
    print(f"\n📁 Loaded {len(all_repos)} repos from consolidated data")
    
    # Determine targets
    target_list = load_targets()
    if target_list:
        targets = [all_repos[name] for name in target_list if name in all_repos]
        print(f"🎯 Target list: {len(targets)} repos")
    else:
        # Default: >=5 contributors or is_oss4sg
        targets = [r for r in all_repos.values() 
                   if r.get("total_event_contributors", 0) >= MIN_CONTRIBUTORS or r.get("is_oss4sg")]
        print(f"🎯 Default selection: {len(targets)} repos (>={MIN_CONTRIBUTORS} contributors or OSS4SG)")
    
    # Load existing metadata (PRESERVE ALL)
    all_metadata = load_all_metadata()
    print(f"💾 Existing metadata: {len(all_metadata)} repos")
    
    # Find what still needs to be fetched
    target_names = {t["repo_name"].lower() for t in targets}
    already_done = target_names & set(all_metadata.keys())
    to_fetch = [t for t in targets if t["repo_name"].lower() not in all_metadata]
    
    print(f"✅ Already done (from target): {len(already_done)}")
    print(f"📋 Need to fetch: {len(to_fetch)}")
    
    if not to_fetch:
        print("\n✨ All targets already fetched!")
        return
    
    # Setup parallel processing
    print(f"\n🔑 Using {len(TOKENS)} tokens in parallel")
    print(f"📊 Estimated time: {len(to_fetch) * 0.8 / 60:.1f} - {len(to_fetch) * 1.5 / 60:.1f} minutes")
    print("\n" + "-" * 75)
    print("Starting parallel fetch... (Ctrl+C to stop, progress is saved)")
    print("-" * 75 + "\n")
    
    token_mgr = ParallelTokenManager(TOKENS)
    progress = ProgressTracker(len(to_fetch))
    save_interval = 25  # Save every N repos
    unsaved_count = 0
    
    def process_repo(args):
        repo_info, token_idx = args
        result = fetch_repo_metadata(repo_info, token_idx, token_mgr)
        return result
    
    try:
        # Distribute repos across tokens
        work_items = [(repo, i % len(TOKENS)) for i, repo in enumerate(to_fetch)]
        
        # Use ThreadPoolExecutor with 4 workers (one per token)
        with ThreadPoolExecutor(max_workers=len(TOKENS)) as executor:
            futures = {executor.submit(process_repo, item): item[0] for item in work_items}
            
            for future in as_completed(futures):
                repo_info = futures[future]
                try:
                    result = future.result()
                    all_metadata[result["repo_name"].lower()] = result
                    progress.update(result["repo_name"], is_error=(result["status"] != "ok"))
                    unsaved_count += 1
                    
                    # Periodic save
                    if unsaved_count >= save_interval:
                        save_all_metadata(all_metadata, len(targets))
                        unsaved_count = 0
                        
                except Exception as e:
                    progress.update(repo_info["repo_name"], is_error=True)
    
    except KeyboardInterrupt:
        print("\n\n⏸️  Interrupted! Saving progress...")
    
    finally:
        # Always save at end
        save_all_metadata(all_metadata, len(targets))
    
    # Final stats
    elapsed = time.time() - progress.start_time
    print(f"\n\n{'=' * 75}")
    print("COMPLETE!")
    print("=" * 75)
    print(f"✅ Fetched: {progress.completed} repos")
    print(f"❌ Errors: {progress.errors}")
    print(f"⏱️  Time: {elapsed/60:.1f} minutes ({progress.completed/elapsed:.2f} repos/sec)")
    print(f"📊 API calls: {token_mgr.total_requests}")
    print(f"🔑 Token usage: {token_mgr.get_status()}")
    print(f"💾 Total metadata saved: {len(all_metadata)} repos")
    print(f"📁 Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
