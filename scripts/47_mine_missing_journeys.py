#!/usr/bin/env python3
"""
Phase A: Mine missing contributor journeys via GitHub API.

For each contributor missing journey data, fetches:
  - Pull requests (via GitHub Search API)
  - Issues (via GitHub Search API)

Uses 10 GitHub tokens with round-robin to maximize throughput.
Saves one JSON file per contributor, resumable.

Usage:
  python3 scripts/47_mine_missing_journeys.py          # mine all missing
  python3 scripts/47_mine_missing_journeys.py --test 5  # test on 5
"""

import json, os, sys, re, time, argparse
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories
EVENT_DIR = os.path.join(BASE, "05_contributor_journey_extraction", "contributions")
ORGANIC_DIR = os.path.join(BASE, "05_contributor_journey_extraction", "organic_contributions")
os.makedirs(EVENT_DIR, exist_ok=True)
os.makedirs(ORGANIC_DIR, exist_ok=True)

# Load tokens from config
with open(os.path.join(BASE, "05_contributor_journey_extraction", "config.json")) as f:
    CONFIG = json.load(f)
TOKENS = CONFIG["github_tokens"]

# Thread-safe token rotation
_token_idx = 0
_token_lock = threading.Lock()
_token_waits = [0.0] * len(TOKENS)  # next-ok timestamp per token


def get_token():
    """Round-robin token selection that respects per-token rate limits."""
    global _token_idx
    with _token_lock:
        idx = _token_idx % len(TOKENS)
        _token_idx += 1
    return idx, TOKENS[idx]


def api_get(url, token_idx=None):
    """GET request with automatic rate-limit handling and retry."""
    if token_idx is None:
        token_idx, token = get_token()
    else:
        token = TOKENS[token_idx]

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "JourneyMiner/2.0",
    }

    for attempt in range(3):
        # Respect per-token wait
        wait_until = _token_waits[token_idx]
        now = time.time()
        if now < wait_until:
            time.sleep(wait_until - now)

        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=30)
            data = json.loads(resp.read().decode())

            # Update rate limit info
            remaining = resp.headers.get("X-RateLimit-Remaining")
            reset = resp.headers.get("X-RateLimit-Reset")
            if remaining and int(remaining) < 5 and reset:
                _token_waits[token_idx] = int(reset) + 1

            return data
        except HTTPError as e:
            if e.code == 403:
                # Rate limited - wait for reset
                reset = e.headers.get("X-RateLimit-Reset")
                if reset:
                    wait = max(0, int(reset) - int(time.time())) + 2
                    _token_waits[token_idx] = time.time() + wait
                    time.sleep(min(wait, 60))
                else:
                    time.sleep(30)
            elif e.code == 422:
                return {"items": []}  # Unprocessable (e.g., too many results)
            elif e.code == 404:
                return None
            else:
                time.sleep(5 * (attempt + 1))
        except (URLError, TimeoutError, Exception):
            time.sleep(5 * (attempt + 1))

    return None


def search_prs(username, repo, token_idx):
    """Search for PRs by a user in a repo."""
    owner, name = repo.split("/")
    url = (f"https://api.github.com/search/issues?"
           f"q=author:{username}+repo:{owner}/{name}+type:pr"
           f"&per_page=100&sort=created&order=asc")
    data = api_get(url, token_idx)
    if not data or "items" not in data:
        return []

    prs = []
    for item in data["items"]:
        prs.append({
            "number": item["number"],
            "title": item.get("title", ""),
            "state": item.get("state", ""),
            "created_at": item.get("created_at"),
            "merged_at": item.get("pull_request", {}).get("merged_at")
            if item.get("pull_request") else None,
        })
    return prs


def search_issues(username, repo, token_idx):
    """Search for issues (not PRs) by a user in a repo."""
    owner, name = repo.split("/")
    url = (f"https://api.github.com/search/issues?"
           f"q=author:{username}+repo:{owner}/{name}+type:issue"
           f"&per_page=100&sort=created&order=asc")
    data = api_get(url, token_idx)
    if not data or "items" not in data:
        return []

    issues = []
    for item in data["items"]:
        issues.append({
            "number": item["number"],
            "title": item.get("title", ""),
            "state": item.get("state", ""),
            "created_at": item.get("created_at"),
            "comments": item.get("comments", 0),
        })
    return issues


def extract_username_from_email(email):
    """Try to extract GitHub username from noreply email patterns."""
    if not email:
        return None
    email = email.lower().strip()
    # Pattern: 12345+username@users.noreply.github.com
    m = re.match(r"\d+\+(.+)@users\.noreply\.github\.com", email)
    if m:
        return m.group(1)
    # Pattern: username@users.noreply.github.com
    m = re.match(r"([^@]+)@users\.noreply\.github\.com", email)
    if m:
        return m.group(1)
    return None


def mine_event_contributor(contrib, token_idx):
    """Mine a single event contributor."""
    cid = contrib["contribution_id"]
    username = contrib["github_username"]
    repo = contrib["repo"]
    out_path = os.path.join(EVENT_DIR, f"{cid}.json")

    if os.path.exists(out_path):
        return "skip"

    prs = search_prs(username, repo, token_idx)
    # Small delay between search requests (search API is 30/min)
    time.sleep(2.5)
    issues = search_issues(username, repo, token_idx)
    time.sleep(0.5)

    result = {
        "contribution_id": cid,
        "github_username": username,
        "repo": repo,
        "event": contrib["event"],
        "extracted_at": datetime.now().isoformat(),
        "pull_requests": prs,
        "issues": issues,
        "summary": {"total_prs": len(prs), "total_issues": len(issues)},
    }

    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    return "mined"


def mine_organic_contributor(match, token_idx):
    """Mine a single organic contributor."""
    eid = match["event_contribution_id"]
    out_path = os.path.join(ORGANIC_DIR, f"{eid}.json")

    if os.path.exists(out_path):
        return "skip"

    email = match.get("organic_email", "")
    name = match.get("organic_name", "")
    repo = match["repo"]

    # Try to get username from email
    username = extract_username_from_email(email)

    prs, issues = [], []
    if username:
        prs = search_prs(username, repo, token_idx)
        time.sleep(2.5)
        issues = search_issues(username, repo, token_idx)
        time.sleep(0.5)

    result = {
        "organic_email": email,
        "organic_name": name,
        "repo": repo,
        "event_contribution_id": eid,
        "organic_commits": match.get("organic_commits", 0),
        "github_username": username,
        "pull_requests": prs,
        "issues": issues,
    }

    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    return "mined"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=int, default=0)
    args = parser.parse_args()

    print("=" * 60)
    print("PHASE A: Mine Missing Contributor Journeys")
    print("=" * 60)
    print(f"  Tokens: {len(TOKENS)}")

    # Load v4 corpus
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "event_contributors_v2.json")) as f:
        events = json.load(f)["contributions"]

    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "organic_matches_v2.json")) as f:
        matches = json.load(f)["matches"]

    # Find missing event contributors
    existing_event = set(f.replace(".json", "") for f in os.listdir(EVENT_DIR)
                         if f.endswith(".json"))
    missing_events = [e for e in events if e["contribution_id"] not in existing_event]

    # Find missing organic contributors (check both naming conventions)
    existing_organic = set(f.replace(".json", "") for f in os.listdir(ORGANIC_DIR)
                           if f.endswith(".json"))
    missing_organics = []
    for m in matches:
        eid = m["event_contribution_id"]
        if eid in existing_organic or f"organic__{eid}" in existing_organic:
            continue
        missing_organics.append(m)

    print(f"  Event missing:   {len(missing_events)}/{len(events)}")
    print(f"  Organic missing: {len(missing_organics)}/{len(matches)}")
    total = len(missing_events) + len(missing_organics)
    print(f"  Total to mine:   {total}")

    if total == 0:
        print("  Nothing to mine!")
        return

    if args.test > 0:
        missing_events = missing_events[:args.test]
        missing_organics = missing_organics[:args.test]
        total = len(missing_events) + len(missing_organics)
        print(f"  TEST MODE: mining {total}")

    # Mine sequentially with token rotation to avoid search API rate limits
    # (search API is 30 requests/min/token, so 10 tokens = 300/min)
    # Each contributor needs 2 search requests, so ~150 contributors/min

    done = 0
    errors = 0
    start = time.time()

    # Process event contributors
    print(f"\n--- Mining {len(missing_events)} event contributors ---")
    for i, contrib in enumerate(missing_events):
        tidx = i % len(TOKENS)
        try:
            status = mine_event_contributor(contrib, tidx)
            done += 1
        except Exception as e:
            errors += 1
            print(f"  ERROR [{contrib['contribution_id']}]: {e}")

        if (done) % 20 == 0:
            elapsed = time.time() - start
            rate = done / elapsed * 60 if elapsed > 0 else 0
            remaining = (total - done) / rate if rate > 0 else 0
            print(f"  [{done}/{total}] {rate:.0f}/min, ~{remaining:.0f}min left")

    # Process organic contributors
    print(f"\n--- Mining {len(missing_organics)} organic contributors ---")
    for i, match in enumerate(missing_organics):
        tidx = i % len(TOKENS)
        try:
            status = mine_organic_contributor(match, tidx)
            done += 1
        except Exception as e:
            errors += 1
            print(f"  ERROR [{match['event_contribution_id']}]: {e}")

        if (done) % 20 == 0:
            elapsed = time.time() - start
            rate = done / elapsed * 60 if elapsed > 0 else 0
            remaining = (total - done) / rate if rate > 0 else 0
            print(f"  [{done}/{total}] {rate:.0f}/min, ~{remaining:.0f}min left")

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"MINING COMPLETE")
    print(f"  Mined: {done}, Errors: {errors}")
    print(f"  Time: {elapsed/60:.1f} min")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
