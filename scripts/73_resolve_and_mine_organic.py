#!/usr/bin/env python3
"""
Resolve GitHub usernames for organic contributors and mine their PRs/issues.

Steps:
  1. Parse usernames from noreply emails (instant, no API)
  2. Resolve remaining usernames via GitHub Commits API
  3. Mine PRs/issues for all resolved organic contributors
  4. Update complete_contributor_journeys.json

Uses 10 GitHub tokens with round-robin for maximum throughput.
Shows progress bars for every step.

Usage:
  python3 scripts/73_resolve_and_mine_organic.py
  python3 scripts/73_resolve_and_mine_organic.py --skip-mining   # only resolve usernames
  python3 scripts/73_resolve_and_mine_organic.py --test 20       # test on 20 contributors
"""

import json, os, sys, re, time, argparse, threading
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load tokens
with open(os.path.join(BASE, "05_contributor_journey_extraction", "config.json")) as f:
    CONFIG = json.load(f)
TOKENS = CONFIG["github_tokens"]

# Output paths
USERNAME_MAP_PATH = os.path.join(BASE, "05_contributor_journey_extraction", "organic_usernames.json")
JOURNEYS_PATH = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")

# Token rotation
_token_idx = 0
_token_lock = threading.Lock()
_token_waits = [0.0] * len(TOKENS)


# ─── Progress bar ───────────────────────────────────────────────────────

def progress_bar(current, total, prefix="", width=40, extra=""):
    pct = current / max(total, 1)
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    sys.stdout.write(f"\r  {prefix} |{bar}| {current}/{total} ({pct*100:.1f}%) {extra}  ")
    sys.stdout.flush()
    if current >= total:
        print()


# ─── API helpers ────────────────────────────────────────────────────────

def get_token():
    global _token_idx
    with _token_lock:
        idx = _token_idx % len(TOKENS)
        _token_idx += 1
    return idx, TOKENS[idx]


def api_get(url, token_idx=None):
    if token_idx is None:
        token_idx, token = get_token()
    else:
        token = TOKENS[token_idx]

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "OrganicMiner/1.0",
    }

    for attempt in range(3):
        wait_until = _token_waits[token_idx]
        now = time.time()
        if now < wait_until:
            time.sleep(wait_until - now)

        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=30)
            data = json.loads(resp.read().decode())

            remaining = resp.headers.get("X-RateLimit-Remaining")
            reset = resp.headers.get("X-RateLimit-Reset")
            if remaining and int(remaining) < 5 and reset:
                _token_waits[token_idx] = int(reset) + 1

            return data
        except HTTPError as e:
            if e.code == 403:
                reset = e.headers.get("X-RateLimit-Reset")
                if reset:
                    wait = max(0, int(reset) - int(time.time())) + 2
                    _token_waits[token_idx] = time.time() + wait
                    time.sleep(min(wait, 60))
                else:
                    time.sleep(30)
            elif e.code == 422:
                return {"items": []}
            elif e.code == 404:
                return None
            else:
                time.sleep(5 * (attempt + 1))
        except (URLError, TimeoutError, Exception):
            time.sleep(5 * (attempt + 1))

    return None


# ─── Step 1: Parse noreply emails ───────────────────────────────────────

def extract_username_from_email(email):
    if not email:
        return None
    email = email.lower().strip()
    # 12345+username@users.noreply.github.com
    m = re.match(r"\d+\+(.+)@users\.noreply\.github\.com", email)
    if m:
        return m.group(1)
    # username@users.noreply.github.com
    m = re.match(r"([^@]+)@users\.noreply\.github\.com", email)
    if m:
        return m.group(1)
    return None


def step1_parse_noreply(organic_journeys):
    """Parse GitHub usernames from noreply emails. Returns {email: username}."""
    print("\n" + "=" * 60)
    print("STEP 1: Parse usernames from noreply emails")
    print("=" * 60)

    username_map = {}
    total = len(organic_journeys)

    for i, j in enumerate(organic_journeys):
        email = j.get("organic_email", "")
        username = extract_username_from_email(email)
        if username:
            username_map[email] = username
        progress_bar(i + 1, total, prefix="Parsing emails")

    print(f"  Resolved from noreply: {len(username_map)}/{total}")
    return username_map


# ─── Step 2: Resolve via Commits API ───────────────────────────────────

def step2_resolve_via_api(organic_journeys, username_map, max_resolve=None):
    """Resolve remaining usernames via GitHub Commits API (search by email in repo)."""
    print("\n" + "=" * 60)
    print("STEP 2: Resolve usernames via GitHub Commits API")
    print("=" * 60)

    # Find contributors that still need resolution
    need_resolution = []
    for j in organic_journeys:
        email = j.get("organic_email", "")
        if email in username_map:
            continue
        # Check if already has username in journey data
        existing = j.get("github_username")
        if existing and existing not in ("", "None", None):
            username_map[email] = existing
            continue
        repo = j.get("repo", "")
        if repo:
            need_resolution.append({"email": email, "repo": repo})

    if max_resolve:
        need_resolution = need_resolution[:max_resolve]

    total = len(need_resolution)
    print(f"  Already resolved: {len(username_map)}")
    print(f"  Need API resolution: {total}")

    if total == 0:
        print("  Nothing to resolve!")
        return username_map

    resolved = 0
    failed = 0
    start_time = time.time()

    for i, item in enumerate(need_resolution):
        repo = item["repo"]
        email = item["email"]

        # Use Commits API: search by author email in the repo
        url = (f"https://api.github.com/repos/{repo}/commits"
               f"?author={quote(email)}&per_page=1")
        data = api_get(url)

        if data and isinstance(data, list) and len(data) > 0:
            commit = data[0]
            author = commit.get("author")
            if author and author.get("login"):
                username = author["login"]
                username_map[email] = username
                resolved += 1
            else:
                failed += 1
        else:
            failed += 1

        elapsed = time.time() - start_time
        rate = (i + 1) / max(elapsed, 0.1)
        remaining_time = (total - i - 1) / max(rate, 0.01)
        if remaining_time > 60:
            eta = f"ETA: {remaining_time/60:.0f}m"
        else:
            eta = f"ETA: {int(remaining_time)}s"
        progress_bar(i + 1, total, prefix="Resolving",
                     extra=f"ok={resolved} fail={failed} {eta}")

        # Checkpoint every 200
        if (i + 1) % 200 == 0:
            with open(USERNAME_MAP_PATH, "w") as f:
                json.dump(username_map, f, indent=2)

    elapsed = time.time() - start_time
    print(f"  Resolved via API: {resolved}/{total} in {elapsed:.0f}s")
    print(f"  Failed/no GitHub account: {failed}")
    print(f"  Total usernames now: {len(username_map)}")

    return username_map


# ─── Step 3: Mine PRs and issues ───────────────────────────────────────

def search_prs(username, repo, token_idx):
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


def step3_mine_prs_issues(organic_journeys, username_map, max_mine=None):
    """Mine PRs and issues for all organic contributors with resolved usernames."""
    print("\n" + "=" * 60)
    print("STEP 3: Mine PRs and issues for organic contributors")
    print("=" * 60)

    # Build list of contributors to mine
    to_mine = []
    for j in organic_journeys:
        email = j.get("organic_email", "")
        username = username_map.get(email)
        if username:
            to_mine.append({
                "email": email,
                "username": username,
                "repo": j.get("repo", ""),
            })

    if max_mine:
        to_mine = to_mine[:max_mine]

    total = len(to_mine)
    print(f"  Contributors to mine: {total}")

    if total == 0:
        print("  Nothing to mine!")
        return {}

    # Mine results: email -> {pull_requests, issues}
    mined_data = {}
    total_prs = 0
    total_issues = 0
    start_time = time.time()

    for i, item in enumerate(to_mine):
        token_idx, _ = get_token()

        prs = search_prs(item["username"], item["repo"], token_idx)
        # Search API: 30 req/min/token, 10 tokens = 300/min
        # 2 searches per contributor, so wait ~0.4s between searches
        time.sleep(0.4)

        token_idx2, _ = get_token()
        issues = search_issues(item["username"], item["repo"], token_idx2)
        time.sleep(0.4)

        mined_data[item["email"]] = {
            "github_username": item["username"],
            "pull_requests": prs,
            "issues": issues,
            "pr_count": len(prs),
            "issue_count": len(issues),
        }

        total_prs += len(prs)
        total_issues += len(issues)

        elapsed = time.time() - start_time
        rate = (i + 1) / max(elapsed, 0.1)
        remaining = (total - i - 1) / max(rate, 0.01)
        if remaining > 60:
            eta = f"ETA: {remaining/60:.0f}m"
        else:
            eta = f"ETA: {int(remaining)}s"
        progress_bar(i + 1, total, prefix="Mining",
                     extra=f"PRs={total_prs} Issues={total_issues} {eta}")

    elapsed = time.time() - start_time
    print(f"  Mined {total} contributors in {elapsed:.0f}s")
    print(f"  Total PRs found: {total_prs}")
    print(f"  Total issues found: {total_issues}")
    print(f"  Avg PRs/contributor: {total_prs/max(total,1):.1f}")
    print(f"  Avg issues/contributor: {total_issues/max(total,1):.1f}")

    return mined_data


# ─── Step 4: Update journeys ───────────────────────────────────────────

def step4_update_journeys(journeys_data, username_map, mined_data):
    """Update organic journeys with resolved usernames and mined data."""
    print("\n" + "=" * 60)
    print("STEP 4: Update complete_contributor_journeys.json")
    print("=" * 60)

    organic_journeys = journeys_data["organic_journeys"]
    updated = 0

    for i, j in enumerate(organic_journeys):
        email = j.get("organic_email", "")

        # Update username
        if email in username_map:
            j["github_username"] = username_map[email]

        # Update PR/issue data
        if email in mined_data:
            md = mined_data[email]
            j["pull_requests"] = md["pull_requests"]
            j["issues"] = md["issues"]
            j["pr_count"] = md["pr_count"]
            j["issue_count"] = md["issue_count"]
            updated += 1

        progress_bar(i + 1, len(organic_journeys), prefix="Updating journeys")

    print(f"  Updated {updated}/{len(organic_journeys)} organic journeys")

    # Save
    print("  Saving (this may take a moment for large files)...")
    with open(JOURNEYS_PATH, "w") as f:
        json.dump(journeys_data, f)
    print(f"  Saved to {JOURNEYS_PATH}")

    # Print summary
    org_with_prs = sum(1 for j in organic_journeys if j.get("pr_count", 0) > 0)
    org_with_issues = sum(1 for j in organic_journeys if j.get("issue_count", 0) > 0)
    total_prs = sum(j.get("pr_count", 0) for j in organic_journeys)
    total_issues = sum(j.get("issue_count", 0) for j in organic_journeys)
    print(f"\n  Final organic stats:")
    print(f"    With PRs: {org_with_prs}/{len(organic_journeys)} ({org_with_prs/len(organic_journeys)*100:.1f}%)")
    print(f"    With issues: {org_with_issues}/{len(organic_journeys)} ({org_with_issues/len(organic_journeys)*100:.1f}%)")
    print(f"    Total PRs: {total_prs} (avg {total_prs/len(organic_journeys):.1f}/contributor)")
    print(f"    Total issues: {total_issues} (avg {total_issues/len(organic_journeys):.1f}/contributor)")


# ─── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-mining", action="store_true",
                        help="Only resolve usernames, skip PR/issue mining")
    parser.add_argument("--test", type=int, default=0,
                        help="Test mode: limit to N contributors")
    args = parser.parse_args()

    print("=" * 60)
    print("ORGANIC CONTRIBUTOR USERNAME RESOLUTION & MINING")
    print("=" * 60)
    print(f"  Tokens available: {len(TOKENS)}")
    print(f"  Test mode: {'yes (' + str(args.test) + ')' if args.test else 'no'}")

    # Load journeys
    print("\n  Loading complete_contributor_journeys.json...")
    with open(JOURNEYS_PATH) as f:
        journeys_data = json.load(f)
    organic_journeys = journeys_data["organic_journeys"]
    print(f"  Organic contributors: {len(organic_journeys)}")

    # Load existing username map if it exists
    existing_map = {}
    if os.path.exists(USERNAME_MAP_PATH):
        with open(USERNAME_MAP_PATH) as f:
            existing_map = json.load(f)
        print(f"  Loaded existing username map: {len(existing_map)} entries")

    # Step 1: Parse noreply emails
    username_map = step1_parse_noreply(organic_journeys)

    # Merge with existing
    for k, v in existing_map.items():
        if k not in username_map:
            username_map[k] = v

    # Step 2: Resolve via API
    max_resolve = args.test if args.test else None
    username_map = step2_resolve_via_api(organic_journeys, username_map, max_resolve)

    # Save username map (checkpoint)
    with open(USERNAME_MAP_PATH, "w") as f:
        json.dump(username_map, f, indent=2)
    print(f"\n  Saved username map: {USERNAME_MAP_PATH} ({len(username_map)} entries)")

    if args.skip_mining:
        print("\n  Skipping mining (--skip-mining). Done!")
        return

    # Step 3: Mine PRs and issues
    max_mine = args.test if args.test else None
    mined_data = step3_mine_prs_issues(organic_journeys, username_map, max_mine)

    # Step 4: Update journeys
    step4_update_journeys(journeys_data, username_map, mined_data)

    print("\n" + "=" * 60)
    print("ALL DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
