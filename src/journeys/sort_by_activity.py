#!/usr/bin/env python3
"""
Sort remaining contributors by estimated activity level (lowest first).
Uses GitHub Search API to get quick activity counts before processing.
"""

import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).parent

# Load config for tokens
with open(SCRIPT_DIR / "config.json") as f:
    CONFIG = json.load(f)

TOKENS = CONFIG["github_tokens"]

def get_activity_estimate(username, token_idx):
    """Quick estimate of user activity using single search API call"""
    token = TOKENS[token_idx % len(TOKENS)]
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ActivityEstimator/1.0"
    }
    
    # Single query for all issues/PRs by this author
    try:
        url = f"https://api.github.com/search/issues?q=author:{username}&per_page=1"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("total_count", 0)
    except HTTPError as e:
        if e.code == 403:
            time.sleep(30)  # Rate limited, wait shorter
            return get_activity_estimate(username, (token_idx + 1) % len(TOKENS))
        return 99999  # Put at end if error
    except Exception:
        return 99999


def main():
    print("Loading contributors...")
    
    # Load all contributors
    contributors_path = Path(CONFIG["paths"]["project_root"]) / CONFIG["paths"]["contributors_input"]
    with open(contributors_path) as f:
        data = json.load(f)
    
    # Contributors are in an array under "contributors" key
    all_contributors = data.get("contributors", [])
    all_usernames = [c.get("github_username", "") for c in all_contributors if c.get("github_username")]
    print(f"Total contributors: {len(all_usernames)}")
    
    # Load completed
    progress_path = SCRIPT_DIR / CONFIG["paths"]["progress_file"]
    with open(progress_path) as f:
        progress = json.load(f)
    
    completed = set(progress.get("completed", []))
    print(f"Already completed: {len(completed)}")
    
    # Get remaining
    remaining = [u for u in all_usernames if u not in completed]
    print(f"Remaining to process: {len(remaining)}")
    
    if not remaining:
        print("All contributors already processed!")
        return
    
    # Estimate activity for each remaining contributor using parallel requests
    print("\nEstimating activity levels (this takes ~15 minutes)...")
    print("Using 4 tokens with parallel processing...")
    
    activity_estimates = {}
    errors = []
    
    def estimate_worker(args):
        username, idx = args
        token_idx = idx % len(TOKENS)
        estimate = get_activity_estimate(username, token_idx)
        time.sleep(0.6)  # Rate limit spacing
        return username, estimate
    
    # Process with thread pool (4 workers, one per token)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(estimate_worker, (u, i)): u 
                   for i, u in enumerate(remaining)}
        
        with tqdm(total=len(remaining), desc="Estimating") as pbar:
            for future in as_completed(futures):
                try:
                    username, estimate = future.result()
                    activity_estimates[username] = estimate
                except Exception as e:
                    username = futures[future]
                    activity_estimates[username] = 99999
                    errors.append(username)
                pbar.update(1)
    
    if errors:
        print(f"Warning: {len(errors)} contributors had estimation errors (will process last)")
    
    # Sort by activity (lowest first)
    sorted_remaining = sorted(remaining, key=lambda u: activity_estimates.get(u, 99999))
    
    # Save sorted order
    sorted_order_path = SCRIPT_DIR / "progress" / "sorted_remaining.json"
    with open(sorted_order_path, "w") as f:
        json.dump({
            "sorted_contributors": sorted_remaining,
            "activity_estimates": activity_estimates,
            "total_remaining": len(sorted_remaining),
            "sorted_at": time.strftime("%Y-%m-%dT%H:%M:%S")
        }, f, indent=2)
    
    print(f"\n✓ Saved sorted order to {sorted_order_path}")
    
    # Show distribution
    print("\nActivity distribution of remaining contributors:")
    brackets = [(0, 100), (100, 500), (500, 1000), (1000, 5000), (5000, 99999)]
    for low, high in brackets:
        count = sum(1 for u in sorted_remaining if low <= activity_estimates.get(u, 0) < high)
        print(f"  {low}-{high}: {count} contributors")
    
    # Show first and last 10
    print(f"\nLowest activity (will process first):")
    for u in sorted_remaining[:10]:
        print(f"  {u}: ~{activity_estimates.get(u, '?')} activities")
    
    print(f"\nHighest activity (will process last):")
    for u in sorted_remaining[-10:]:
        print(f"  {u}: ~{activity_estimates.get(u, '?')} activities")


if __name__ == "__main__":
    main()
