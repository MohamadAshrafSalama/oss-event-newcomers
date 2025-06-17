#!/usr/bin/env python3
"""
Mine PRs/issues for ALL contributors missing data.

Mines:
  1. Event contributors with 0 PRs AND 0 issues (1,141 need re-mining)
  2. Organic contributors with resolved usernames (1,797 to mine)
  Total: ~2,938 contributors

Strategy: Sequential with round-robin token rotation.
  - 10 tokens rotated, each API call uses next token
  - GitHub Search API: 30 req/min/token -> 300 req/min total
  - 2 searches per contributor -> ~150 contributors/min -> ~20 min total

Usage:
  python3 scripts/74_mine_organic_parallel.py
  python3 scripts/74_mine_organic_parallel.py --test 50
  python3 scripts/74_mine_organic_parallel.py --event-only
  python3 scripts/74_mine_organic_parallel.py --organic-only
"""

import json, os, sys, time, argparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE, "05_contributor_journey_extraction", "config.json")) as f:
    CONFIG = json.load(f)
TOKENS = CONFIG["github_tokens"]

USERNAME_MAP_PATH = os.path.join(BASE, "05_contributor_journey_extraction", "organic_usernames.json")
JOURNEYS_PATH = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")

# Token rotation
_token_idx = 0
_token_waits = [0.0] * len(TOKENS)


def next_token():
    """Round-robin, skip rate-limited tokens."""
    global _token_idx
    for _ in range(len(TOKENS)):
        idx = _token_idx % len(TOKENS)
        _token_idx += 1
        wait = _token_waits[idx] - time.time()
        if wait <= 0:
            return idx, TOKENS[idx]
    # All rate-limited, wait for the soonest one
    soonest = min(_token_waits)
    wait = soonest - time.time()
    if wait > 0:
        time.sleep(wait + 0.5)
    idx = _token_waits.index(soonest)
    _token_waits[idx] = 0
    return idx, TOKENS[idx]


def api_get(url):
    for attempt in range(8):
        idx, token = next_token()
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "FullMiner/1.0",
        }
        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=30)
            data = json.loads(resp.read().decode())

            remaining = resp.headers.get("X-RateLimit-Remaining")
            reset = resp.headers.get("X-RateLimit-Reset")
            if remaining and int(remaining) < 3 and reset:
                _token_waits[idx] = int(reset) + 1

            return data
        except HTTPError as e:
            if e.code == 403:
                reset = e.headers.get("X-RateLimit-Reset")
                if reset:
                    _token_waits[idx] = int(reset) + 2
                else:
                    _token_waits[idx] = time.time() + 30
                # Don't sleep, try next token
                continue
            elif e.code == 422:
                return {"items": []}
            elif e.code == 404:
                return None
            else:
                time.sleep(1)
        except (URLError, TimeoutError, Exception):
            time.sleep(1)
    return None


def search_prs(username, repo):
    owner, name = repo.split("/")
    url = (f"https://api.github.com/search/issues?"
           f"q=author:{quote(username)}+repo:{owner}/{name}+type:pr"
           f"&per_page=100&sort=created&order=asc")
    data = api_get(url)
    if not data or "items" not in data:
        return []
    return [{
        "number": item["number"],
        "title": item.get("title", ""),
        "state": item.get("state", ""),
        "created_at": item.get("created_at"),
        "merged_at": item.get("pull_request", {}).get("merged_at")
        if item.get("pull_request") else None,
    } for item in data["items"]]


def search_issues(username, repo):
    owner, name = repo.split("/")
    url = (f"https://api.github.com/search/issues?"
           f"q=author:{quote(username)}+repo:{owner}/{name}+type:issue"
           f"&per_page=100&sort=created&order=asc")
    data = api_get(url)
    if not data or "items" not in data:
        return []
    return [{
        "number": item["number"],
        "title": item.get("title", ""),
        "state": item.get("state", ""),
        "created_at": item.get("created_at"),
        "comments": item.get("comments", 0),
    } for item in data["items"]]


def progress_bar(current, total, prefix="", width=40, extra=""):
    pct = current / max(total, 1)
    filled = int(width * pct)
    bar = "\u2588" * filled + "\u2591" * (width - filled)
    sys.stdout.write(f"\r  {prefix} |{bar}| {current}/{total} ({pct*100:.1f}%) {extra}  ")
    sys.stdout.flush()
    if current >= total:
        print()


def mine_list(work_items, label):
    """Mine a list of {email/username/repo} items. Returns {email: mined_data}."""
    total = len(work_items)
    if total == 0:
        print(f"  Nothing to mine for {label}!")
        return {}

    print(f"\n  Mining {label}: {total} contributors")
    mined = {}
    total_prs = 0
    total_issues = 0
    start = time.time()

    for i, item in enumerate(work_items):
        prs = search_prs(item["username"], item["repo"])
        issues = search_issues(item["username"], item["repo"])

        key = item.get("email", item["username"])
        mined[key] = {
            "github_username": item["username"],
            "pull_requests": prs,
            "issues": issues,
            "pr_count": len(prs),
            "issue_count": len(issues),
        }
        total_prs += len(prs)
        total_issues += len(issues)

        elapsed = time.time() - start
        rate = (i + 1) / max(elapsed, 0.1)
        remaining = (total - i - 1) / max(rate, 0.01)
        if remaining > 60:
            eta = f"ETA:{remaining/60:.0f}m"
        else:
            eta = f"ETA:{int(remaining)}s"
        progress_bar(i + 1, total, prefix=label,
                     extra=f"PRs={total_prs} Issues={total_issues} {eta}")

    elapsed = time.time() - start
    print(f"  {label}: {total} done in {elapsed:.0f}s. PRs={total_prs} Issues={total_issues}")
    return mined


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=int, default=0)
    parser.add_argument("--event-only", action="store_true")
    parser.add_argument("--organic-only", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("FULL CONTRIBUTOR PR/ISSUE MINING")
    print("=" * 60)
    print(f"  Tokens: {len(TOKENS)}")

    # Load journeys
    print("  Loading journeys...")
    with open(JOURNEYS_PATH) as f:
        journeys_data = json.load(f)
    ev_journeys = journeys_data["event_journeys"]
    org_journeys = journeys_data["organic_journeys"]
    print(f"  Event: {len(ev_journeys)}, Organic: {len(org_journeys)}")

    # Load organic username map
    username_map = {}
    if os.path.exists(USERNAME_MAP_PATH):
        with open(USERNAME_MAP_PATH) as f:
            username_map = json.load(f)
        print(f"  Organic usernames: {len(username_map)}")

    # === Build work lists ===

    # Event contributors with 0 PRs AND 0 issues
    event_work = []
    if not args.organic_only:
        for j in ev_journeys:
            if j.get("pr_count", 0) == 0 and j.get("issue_count", 0) == 0:
                username = j.get("github_username", "")
                repo = j.get("repo", "")
                if username and repo:
                    event_work.append({"email": f"event_{username}_{repo}", "username": username, "repo": repo})
        print(f"  Event to mine (0 PRs+issues): {len(event_work)}")

    # Organic contributors with resolved usernames
    organic_work = []
    if not args.event_only:
        for j in org_journeys:
            email = j.get("organic_email", "")
            username = username_map.get(email)
            if username:
                repo = j.get("repo", "")
                if repo:
                    organic_work.append({"email": email, "username": username, "repo": repo})
        print(f"  Organic to mine: {len(organic_work)}")

    if args.test:
        event_work = event_work[:args.test]
        organic_work = organic_work[:args.test]

    total_work = len(event_work) + len(organic_work)
    print(f"  TOTAL: {total_work}")

    # Mine event contributors
    event_mined = mine_list(event_work, "Event")

    # Mine organic contributors
    organic_mined = mine_list(organic_work, "Organic")

    # === Update journeys ===
    print("\n" + "=" * 60)
    print("Updating journeys...")
    print("=" * 60)

    # Update event
    ev_updated = 0
    for j in ev_journeys:
        username = j.get("github_username", "")
        repo = j.get("repo", "")
        key = f"event_{username}_{repo}"
        if key in event_mined:
            md = event_mined[key]
            j["pull_requests"] = md["pull_requests"]
            j["issues"] = md["issues"]
            j["pr_count"] = md["pr_count"]
            j["issue_count"] = md["issue_count"]
            ev_updated += 1
    print(f"  Event updated: {ev_updated}")

    # Update organic
    org_updated = 0
    for j in org_journeys:
        email = j.get("organic_email", "")
        if email in username_map:
            j["github_username"] = username_map[email]
        if email in organic_mined:
            md = organic_mined[email]
            j["pull_requests"] = md["pull_requests"]
            j["issues"] = md["issues"]
            j["pr_count"] = md["pr_count"]
            j["issue_count"] = md["issue_count"]
            org_updated += 1
    print(f"  Organic updated: {org_updated}")

    # Save
    print("  Saving...")
    with open(JOURNEYS_PATH, "w") as f:
        json.dump(journeys_data, f)
    print(f"  Saved: {JOURNEYS_PATH}")

    # Final stats
    print("\n" + "=" * 60)
    print("FINAL STATS")
    print("=" * 60)
    for label, jlist in [("Event", ev_journeys), ("Organic", org_journeys)]:
        with_prs = sum(1 for j in jlist if j.get("pr_count", 0) > 0)
        with_issues = sum(1 for j in jlist if j.get("issue_count", 0) > 0)
        tot_prs = sum(j.get("pr_count", 0) for j in jlist)
        tot_issues = sum(j.get("issue_count", 0) for j in jlist)
        print(f"  {label}:")
        print(f"    With PRs: {with_prs}/{len(jlist)} ({with_prs/len(jlist)*100:.1f}%)")
        print(f"    With issues: {with_issues}/{len(jlist)} ({with_issues/len(jlist)*100:.1f}%)")
        print(f"    Total PRs: {tot_prs} (avg {tot_prs/len(jlist):.1f})")
        print(f"    Total issues: {tot_issues} (avg {tot_issues/len(jlist):.1f})")

    print("\n" + "=" * 60)
    print("ALL DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
