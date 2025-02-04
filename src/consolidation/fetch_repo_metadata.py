#!/usr/bin/env python3
"""
Fetch GitHub metadata for selected repos (Phase B).

- Input: 03_consolidated_dataset/all_event_repos_consolidated.json
- Selection: repos with total_event_contributors >= 5 OR is_oss4sg == True
- Output: repo_metadata.json (one record per repo)

Fields collected:
- stargazers_count, forks_count, open_issues_count, watchers_count
- language, created_at, updated_at, pushed_at
- contributor_count (from /contributors Link header)
- commit_count (from /commits Link header)
- closed_pr_count (from Search API total_count)

Usage:
  export GITHUB_TOKENS="token1,token2,token3"  # required
  python3 fetch_repo_metadata.py

Notes:
- Token rotation per request
- Search API is rate-limited (30/min); we sleep to ~20/min
- Progress saved to repo_metadata.json (append/update) and repo_metadata_progress.json
"""

import json
import os
import sys
import time
import math
import random
import requests
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_JSON = BASE_DIR / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
OUTPUT_JSON = BASE_DIR / "03_consolidated_dataset" / "repo_metadata.json"
PROGRESS_JSON = BASE_DIR / "03_consolidated_dataset" / "repo_metadata_progress.json"

TOKENS = [t.strip() for t in os.getenv("GITHUB_TOKENS", "").split(",") if t.strip()]
if not TOKENS:
    print("ERROR: Please set GITHUB_TOKENS env var (comma-separated tokens)")
    sys.exit(1)

auth_headers = [ {"Authorization": f"token {t}"} for t in TOKENS ]

SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/vnd.github+json"})

RATE_DELAY_SEARCH = 3.0  # seconds between search requests (≈20/min)
RATE_DELAY_REST = 0.2     # small delay for REST calls


def pick_header(idx: int):
    return auth_headers[idx % len(auth_headers)]


def load_input():
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    repos = data.get("repos", [])
    # Select repos: >=5 contributors OR is_oss4sg
    targets = [r for r in repos if r.get("total_event_contributors", 0) >= 5 or r.get("is_oss4sg")]
    print(f"Loaded {len(repos)} repos; selected {len(targets)} for metadata")
    return targets


def load_progress():
    done = {}
    if OUTPUT_JSON.exists():
        with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                done[item["repo_name"].lower()] = item
    return done


def save_outputs(done_dict):
    items = list(done_dict.values())
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    with open(PROGRESS_JSON, "w", encoding="utf-8") as f:
        json.dump({"completed": len(items), "updated_at": datetime.utcnow().isoformat()}, f, indent=2)


def parse_link_count(link_header: str):
    """Parse GitHub Link header to estimate total items."""
    if not link_header:
        return None
    # Example: <https://api.github.com/repositories/64778136/commits?per_page=1&page=7265>; rel="last"
    parts = link_header.split(",")
    last = None
    for p in parts:
        if 'rel="last"' in p:
            last = p
            break
    if not last:
        return None
    import re
    m = re.search(r"[&?]page=(\d+)>", last)
    if m:
        page = int(m.group(1))
        # per_page default 30; but we request per_page=1
        return page
    return None


def get_repo_basic(repo, h):
    url = f"https://api.github.com/repos/{repo}"
    r = SESSION.get(url, headers=h)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def get_count_via_link(repo, kind, h):
    # kind: "contributors" or "commits"
    url = f"https://api.github.com/repos/{repo}/{kind}?per_page=1&anon=1"
    r = SESSION.get(url, headers=h)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    link = r.headers.get("Link", "")
    return parse_link_count(link)


def get_closed_pr_count(repo, h):
    # Search API: 30/min limit
    url = "https://api.github.com/search/issues"
    params = {"q": f"repo:{repo} type:pr is:closed", "per_page": 1}
    r = SESSION.get(url, headers=h, params=params)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    return data.get("total_count")


def main():
    targets = load_input()
    done = load_progress()

    total = len(targets)
    start_idx = len(done)
    print(f"Already have {start_idx} repos; remaining {total - start_idx}")

    for i, repo in enumerate(targets):
        name = repo["repo_name"].lower()
        if name in done:
            continue
        h = pick_header(i)
        try:
            # Repo basic
            basic = get_repo_basic(name, h)
            time.sleep(RATE_DELAY_REST)

            # contributors and commits via Link
            contributor_count = get_count_via_link(name, "contributors", h)
            time.sleep(RATE_DELAY_REST)
            commit_count = get_count_via_link(name, "commits", h)
            time.sleep(RATE_DELAY_REST)

            # closed PRs via search (slower)
            closed_pr_count = get_closed_pr_count(name, h)
            time.sleep(RATE_DELAY_SEARCH)

            done[name] = {
                "repo_name": name,
                "is_oss4sg": repo.get("is_oss4sg", False),
                "total_event_contributors": repo.get("total_event_contributors", 0),
                "event_count": repo.get("event_count", 0),
                "events": repo.get("events", []),
                "stars": basic.get("stargazers_count") if basic else None,
                "forks": basic.get("forks_count") if basic else None,
                "open_issues": basic.get("open_issues_count") if basic else None,
                "watchers": basic.get("subscribers_count") if basic else None,
                "language": basic.get("language") if basic else None,
                "created_at": basic.get("created_at") if basic else None,
                "updated_at": basic.get("updated_at") if basic else None,
                "pushed_at": basic.get("pushed_at") if basic else None,
                "contributor_count": contributor_count,
                "commit_count": commit_count,
                "closed_pr_count": closed_pr_count,
                "fetched_at": datetime.utcnow().isoformat(),
            }

            if (len(done) % 20) == 0:
                save_outputs(done)
                print(f"Saved progress at {len(done)}/{total}")
        except Exception as e:
            print(f"Error on {name}: {e}")
            save_outputs(done)
            time.sleep(5)
            continue

    save_outputs(done)
    print(f"Done. Saved metadata for {len(done)} repos.")


if __name__ == "__main__":
    main()
