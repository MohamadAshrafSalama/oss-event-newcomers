#!/usr/bin/env python3
"""
Fetch descriptive stats for a list of repos from the GitHub API.

Input:  CSV with a `repo` column (owner/name format).
Output: CSV with one row per repo -- stars, forks, open_issues,
        commit_count, pr_count, issue_count, contributor_count.

Usage:
  python 01_collect_repo_metadata.py --repos repos.csv --out repo_metadata.csv

Pass --token with a GitHub token to avoid hitting rate limits quickly.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def read_repos(path: Path) -> List[str]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("repos", [])
        else:
            raise ValueError("Unsupported JSON shape for repos input.")
        repos = [extract_repo_name(item) for item in items]
    else:
        repos = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                repos.append(extract_repo_name(row))
    out = []
    seen = set()
    for repo in repos:
        if repo and "/" in repo and repo not in seen:
            seen.add(repo)
            out.append(repo)
    return out


def extract_repo_name(item) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    for key in ("repo", "full_name", "repository", "github_repo"):
        value = (item.get(key) or "").strip()
        if value:
            return value
    return ""


def build_request(url: str, token: Optional[str]) -> urllib.request.Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "lab-member-starter",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def api_get_json(url: str, token: Optional[str], retries: int = 3):
    for attempt in range(retries):
        req = build_request(url, token)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = resp.read().decode("utf-8")
                return json.loads(payload), dict(resp.headers.items())
        except Exception:
            if attempt == retries - 1:
                return None, {}
            time.sleep(1.5 * (attempt + 1))
    return None, {}


def parse_last_page(headers: Dict[str, str]) -> Optional[int]:
    link = headers.get("Link") or headers.get("link")
    if not link:
        return None
    parts = [p.strip() for p in link.split(",")]
    for part in parts:
        if 'rel="last"' not in part:
            continue
        start = part.find("<")
        end = part.find(">")
        if start == -1 or end == -1:
            continue
        url = part[start + 1 : end]
        q = urllib.parse.urlparse(url).query
        page = urllib.parse.parse_qs(q).get("page", [None])[0]
        if page is not None:
            try:
                return int(page)
            except ValueError:
                return None
    return 1


def estimate_count_from_link(url: str, token: Optional[str]) -> int:
    data, headers = api_get_json(url, token)
    if data is None:
        return -1
    if isinstance(data, list) and not data:
        return 0
    last = parse_last_page(headers)
    if last is None:
        if isinstance(data, list):
            return len(data)
        return 0
    return last


def get_repo_metadata(repo: str, token: Optional[str]) -> Dict[str, object]:
    row: Dict[str, object] = {
        "repo": repo,
        "stars": -1,
        "forks": -1,
        "open_issues": -1,
        "commit_count": -1,
        "pr_count": -1,
        "issue_count": -1,
        "contributor_count": -1,
        "status": "ok",
    }

    base_url = f"https://api.github.com/repos/{repo}"
    repo_data, _ = api_get_json(base_url, token)
    if not isinstance(repo_data, dict):
        row["status"] = "repo_fetch_failed"
        return row

    row["stars"] = int(repo_data.get("stargazers_count", -1))
    row["forks"] = int(repo_data.get("forks_count", -1))
    row["open_issues"] = int(repo_data.get("open_issues_count", -1))

    row["commit_count"] = estimate_count_from_link(
        f"{base_url}/commits?per_page=1", token
    )
    row["contributor_count"] = estimate_count_from_link(
        f"{base_url}/contributors?per_page=1&anon=true", token
    )

    repo_query = urllib.parse.quote_plus(f"repo:{repo}")
    pr_query = urllib.parse.quote_plus("is:pr")
    issue_query = urllib.parse.quote_plus("is:issue")
    pr_data, _ = api_get_json(
        f"https://api.github.com/search/issues?q={repo_query}+{pr_query}", token
    )
    issue_data, _ = api_get_json(
        f"https://api.github.com/search/issues?q={repo_query}+{issue_query}", token
    )
    if isinstance(pr_data, dict):
        row["pr_count"] = int(pr_data.get("total_count", -1))
    if isinstance(issue_data, dict):
        row["issue_count"] = int(issue_data.get("total_count", -1))

    return row


def write_csv(rows: Iterable[Dict[str, object]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "repo",
        "stars",
        "forks",
        "open_issues",
        "commit_count",
        "pr_count",
        "issue_count",
        "contributor_count",
        "status",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect GitHub repo metadata.")
    parser.add_argument("--repos", required=True, help="Path to repos CSV/JSON.")
    parser.add_argument("--out", required=True, help="Output CSV path.")
    parser.add_argument(
        "--token", default="", help="Optional GitHub token (recommended)."
    )
    parser.add_argument("--sleep-ms", type=int, default=150, help="Delay between repos.")
    args = parser.parse_args()

    repos = read_repos(Path(args.repos))
    rows = []
    for idx, repo in enumerate(repos, start=1):
        print(f"[{idx}/{len(repos)}] Collecting metadata for {repo}")
        rows.append(get_repo_metadata(repo, args.token or None))
        time.sleep(max(args.sleep_ms, 0) / 1000.0)
    write_csv(rows, Path(args.out))
    print(f"Saved {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
