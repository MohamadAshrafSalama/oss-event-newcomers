#!/usr/bin/env python3
"""
Fast parallel mining of PRs/issues for ALL contributors using REST API.

KEY INSIGHT: Uses REST API (5000 req/hr/token) NOT Search API (30 req/min/token).
  - GET /repos/{owner}/{repo}/issues?creator={username}&state=all&per_page=100
  - Returns BOTH issues and PRs (PRs have 'pull_request' key)
  - 10 tokens * 5000/hr = 50,000 req/hr = 833/min = ~14/sec
  - 1 request per contributor -> ~2,938 contributors in ~3.5 minutes

Architecture:
  - 10 worker threads, each owns one token
  - Shared thread-safe work queue
  - Results written to checkpoint file every 100 items
  - Can resume from checkpoint if interrupted

Usage:
  python3 scripts/75_fast_mine_all.py --test 10       # Test 10 contributors
  python3 scripts/75_fast_mine_all.py                  # Full run
  python3 scripts/75_fast_mine_all.py --resume         # Resume from checkpoint
  python3 scripts/75_fast_mine_all.py --event-only
  python3 scripts/75_fast_mine_all.py --organic-only
"""

import json, os, sys, time, argparse, threading, queue
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE, "05_contributor_journey_extraction", "config.json")) as f:
    TOKENS = json.load(f)["github_tokens"]
NUM_THREADS = len(TOKENS)

USERNAME_MAP_PATH = os.path.join(BASE, "05_contributor_journey_extraction", "organic_usernames.json")
JOURNEYS_PATH = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")
CHECKPOINT_PATH = os.path.join(BASE, "05_contributor_journey_extraction", "mining_checkpoint.json")

# Shared state
results_lock = threading.Lock()
mined_results = {}  # key -> {github_username, pull_requests, issues, pr_count, issue_count}
stats = {"done": 0, "total": 0, "prs": 0, "issues": 0, "errors": 0}
checkpoint_counter = 0


# ─── API ────────────────────────────────────────────────────────────────

def api_get(url, token):
    """Single GET request. Returns parsed JSON or None."""
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "FastMiner/1.0",
    }
    for attempt in range(3):
        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=30)
            return json.loads(resp.read().decode()), resp.headers
        except HTTPError as e:
            if e.code == 403:
                # Rate limited - wait for reset
                reset = e.headers.get("X-RateLimit-Reset")
                if reset:
                    wait = max(0, int(reset) - int(time.time())) + 1
                    time.sleep(wait)
                else:
                    time.sleep(10)
            elif e.code == 404:
                return None, None
            elif e.code == 422:
                return [], None
            else:
                time.sleep(1)
        except (URLError, TimeoutError, Exception):
            time.sleep(1)
    return None, None


def fetch_all_pages(base_url, token):
    """Fetch all pages of a paginated REST endpoint."""
    all_items = []
    url = base_url
    while url:
        data, headers = api_get(url, token)
        if data is None or not isinstance(data, list):
            break
        all_items.extend(data)
        if len(data) < 100:
            break
        # Check Link header for next page
        link = headers.get("Link", "") if headers else ""
        url = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]
    return all_items


def mine_contributor(username, repo, token):
    """Mine all PRs and issues for a contributor using REST API.
    One API call returns both (PRs have pull_request key)."""
    owner, name = repo.split("/")
    base_url = (f"https://api.github.com/repos/{owner}/{name}/issues"
                f"?creator={quote(username)}&state=all&per_page=100&sort=created&direction=asc")

    items = fetch_all_pages(base_url, token)

    prs = []
    issues = []
    for item in items:
        if item.get("pull_request"):
            prs.append({
                "number": item["number"],
                "title": item.get("title", ""),
                "state": item.get("state", ""),
                "created_at": item.get("created_at"),
                "merged_at": item.get("pull_request", {}).get("merged_at"),
            })
        else:
            issues.append({
                "number": item["number"],
                "title": item.get("title", ""),
                "state": item.get("state", ""),
                "created_at": item.get("created_at"),
                "comments": item.get("comments", 0),
            })

    return prs, issues


# ─── Worker ─────────────────────────────────────────────────────────────

def worker(thread_id, token, work_queue):
    """Worker: owns one token, pulls items from queue."""
    global checkpoint_counter
    while True:
        try:
            item = work_queue.get_nowait()
        except queue.Empty:
            return

        key = item["key"]
        username = item["username"]
        repo = item["repo"]

        try:
            prs, issues = mine_contributor(username, repo, token)
            with results_lock:
                mined_results[key] = {
                    "github_username": username,
                    "pull_requests": prs,
                    "issues": issues,
                    "pr_count": len(prs),
                    "issue_count": len(issues),
                }
                stats["done"] += 1
                stats["prs"] += len(prs)
                stats["issues"] += len(issues)
                checkpoint_counter += 1
        except Exception:
            with results_lock:
                stats["done"] += 1
                stats["errors"] += 1
                checkpoint_counter += 1

        work_queue.task_done()


# ─── Progress ───────────────────────────────────────────────────────────

def show_progress(extra=""):
    d = stats["done"]
    t = max(stats["total"], 1)
    pct = d / t
    filled = int(40 * pct)
    bar = "\u2588" * filled + "\u2591" * (40 - filled)
    sys.stdout.write(
        f"\r  Mining |{bar}| {d}/{t} ({pct*100:.1f}%) "
        f"PRs={stats['prs']} Issues={stats['issues']} Err={stats['errors']} {extra}  "
    )
    sys.stdout.flush()


def save_checkpoint():
    """Save current results to checkpoint file."""
    with results_lock:
        with open(CHECKPOINT_PATH, "w") as f:
            json.dump(mined_results, f)


# ─── Main ───────────────────────────────────────────────────────────────

def main():
    global checkpoint_counter

    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=int, default=0, help="Test with N contributors")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--event-only", action="store_true")
    parser.add_argument("--organic-only", action="store_true")
    parser.add_argument("--skip-update", action="store_true", help="Mine only, don't update journeys")
    args = parser.parse_args()

    print("=" * 60)
    print("FAST PARALLEL MINING (REST API)")
    print("=" * 60)
    print(f"  Threads: {NUM_THREADS}")
    print(f"  API: REST (5000/hr/token = {NUM_THREADS * 5000}/hr total)")
    print(f"  Test mode: {'yes (' + str(args.test) + ')' if args.test else 'no'}")

    # Load journeys
    print("\n  Loading data...")
    with open(JOURNEYS_PATH) as f:
        journeys_data = json.load(f)
    ev_journeys = journeys_data["event_journeys"]
    org_journeys = journeys_data["organic_journeys"]

    username_map = {}
    if os.path.exists(USERNAME_MAP_PATH):
        with open(USERNAME_MAP_PATH) as f:
            username_map = json.load(f)

    print(f"  Event: {len(ev_journeys)}, Organic: {len(org_journeys)}")
    print(f"  Organic usernames: {len(username_map)}")

    # Load checkpoint if resuming
    if args.resume and os.path.exists(CHECKPOINT_PATH):
        with open(CHECKPOINT_PATH) as f:
            mined_results.update(json.load(f))
        print(f"  Resumed checkpoint: {len(mined_results)} already mined")

    # Build work items
    work_items = []

    if not args.organic_only:
        for j in ev_journeys:
            if j.get("pr_count", 0) == 0 and j.get("issue_count", 0) == 0:
                username = j.get("github_username", "")
                repo = j.get("repo", "")
                if username and repo:
                    key = f"ev_{username}_{repo}"
                    if key not in mined_results:  # skip already done
                        work_items.append({"key": key, "username": username, "repo": repo, "type": "event"})

    if not args.event_only:
        for j in org_journeys:
            email = j.get("organic_email", "")
            username = username_map.get(email)
            if username:
                repo = j.get("repo", "")
                if repo:
                    key = f"org_{email}"
                    if key not in mined_results:
                        work_items.append({"key": key, "username": username, "repo": repo, "type": "organic"})

    ev_count = sum(1 for w in work_items if w["type"] == "event")
    org_count = sum(1 for w in work_items if w["type"] == "organic")

    if args.test:
        work_items = work_items[:args.test]
        ev_count = sum(1 for w in work_items if w["type"] == "event")
        org_count = sum(1 for w in work_items if w["type"] == "organic")

    print(f"\n  Work: {len(work_items)} total ({ev_count} event, {org_count} organic)")
    print(f"  Est. time: ~{len(work_items) / (NUM_THREADS * 1.5):.0f}s ({len(work_items) / (NUM_THREADS * 1.5) / 60:.1f}m)")

    if not work_items:
        print("  Nothing to mine!")
        if not args.skip_update:
            _update_journeys(journeys_data, ev_journeys, org_journeys, username_map)
        return

    # Fill queue
    work_queue = queue.Queue()
    for item in work_items:
        work_queue.put(item)
    stats["total"] = len(work_items)

    # Launch threads
    print(f"\n  Launching {NUM_THREADS} threads...")
    start = time.time()
    threads = []
    for i in range(NUM_THREADS):
        t = threading.Thread(target=worker, args=(i, TOKENS[i], work_queue), daemon=True)
        t.start()
        threads.append(t)

    # Monitor
    last_checkpoint = 0
    while any(t.is_alive() for t in threads):
        elapsed = time.time() - start
        done = stats["done"]
        if done > 0:
            rate = done / elapsed
            remaining = (stats["total"] - done) / rate
            if remaining > 60:
                eta = f"ETA:{remaining/60:.0f}m"
            else:
                eta = f"ETA:{int(remaining)}s"
        else:
            eta = "starting..."
        show_progress(eta)

        # Checkpoint every 100
        if checkpoint_counter - last_checkpoint >= 100:
            save_checkpoint()
            last_checkpoint = checkpoint_counter

        time.sleep(0.3)

    # Final
    show_progress("DONE!")
    print()

    elapsed = time.time() - start
    print(f"\n  Completed: {stats['done']}/{stats['total']} in {elapsed:.1f}s")
    print(f"  PRs found: {stats['prs']}")
    print(f"  Issues found: {stats['issues']}")
    print(f"  Errors: {stats['errors']}")
    if stats["done"] > 0:
        print(f"  Speed: {stats['done']/elapsed:.1f} contributors/sec")

    # Save final checkpoint
    save_checkpoint()
    print(f"  Checkpoint saved: {CHECKPOINT_PATH}")

    if args.skip_update:
        print("\n  Skipping journey update (--skip-update)")
        return

    _update_journeys(journeys_data, ev_journeys, org_journeys, username_map)


def _update_journeys(journeys_data, ev_journeys, org_journeys, username_map):
    """Apply mined results to journeys and save."""
    print("\n" + "=" * 60)
    print("UPDATING JOURNEYS")
    print("=" * 60)

    ev_updated = 0
    for j in ev_journeys:
        username = j.get("github_username", "")
        repo = j.get("repo", "")
        key = f"ev_{username}_{repo}"
        if key in mined_results:
            md = mined_results[key]
            j["pull_requests"] = md["pull_requests"]
            j["issues"] = md["issues"]
            j["pr_count"] = md["pr_count"]
            j["issue_count"] = md["issue_count"]
            ev_updated += 1

    org_updated = 0
    for j in org_journeys:
        email = j.get("organic_email", "")
        if email in username_map:
            j["github_username"] = username_map[email]
        key = f"org_{email}"
        if key in mined_results:
            md = mined_results[key]
            j["pull_requests"] = md["pull_requests"]
            j["issues"] = md["issues"]
            j["pr_count"] = md["pr_count"]
            j["issue_count"] = md["issue_count"]
            org_updated += 1

    print(f"  Event updated: {ev_updated}")
    print(f"  Organic updated: {org_updated}")

    print("  Saving...")
    with open(JOURNEYS_PATH, "w") as f:
        json.dump(journeys_data, f)
    print(f"  Saved: {JOURNEYS_PATH}")

    # Stats
    print("\n  FINAL STATS:")
    for label, jlist in [("Event", ev_journeys), ("Organic", org_journeys)]:
        with_prs = sum(1 for j in jlist if j.get("pr_count", 0) > 0)
        with_issues = sum(1 for j in jlist if j.get("issue_count", 0) > 0)
        tot_prs = sum(j.get("pr_count", 0) for j in jlist)
        tot_issues = sum(j.get("issue_count", 0) for j in jlist)
        print(f"    {label}: {with_prs}/{len(jlist)} with PRs ({with_prs/len(jlist)*100:.1f}%), "
              f"{with_issues}/{len(jlist)} with issues ({with_issues/len(jlist)*100:.1f}%), "
              f"total PRs={tot_prs} issues={tot_issues}")

    print("\n" + "=" * 60)
    print("ALL DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
