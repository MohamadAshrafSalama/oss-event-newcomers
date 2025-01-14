#!/usr/bin/env python3
"""
Extract GitHub repo links and PR links from GSoC student gists.
Outputs:
- gist_links_projects.{json,csv}
- gist_links_prs.{json,csv}
- gist_repos_unique.{json,csv}
- optional: oss4sg_matches_from_gist_links.json
"""

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).parent


def load_extracted() -> List[Dict]:
    with open(BASE_DIR / "gsoc_github_urls_extracted.json", "r", encoding="utf-8") as f:
        return json.load(f)


def filter_gists(data: List[Dict]) -> List[Dict]:
    return [d for d in data if "gist.github.com" in d.get("github_url", "")]


def parse_gist_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    url = url.strip().rstrip("/")
    if url.startswith("https://"):
        url = url[len("https://") :]
    if url.startswith("http://"):
        url = url[len("http://") :]
    parts = url.split("/")
    # gist.github.com/user/gistid or gist.github.com/gistid
    if len(parts) >= 3:
        return parts[1], parts[2]
    if len(parts) == 2:
        return None, parts[1]
    return None, None


def fetch_gist_raw(username: Optional[str], gist_id: Optional[str], delay: float) -> Optional[str]:
    """
    Fetch raw gist content directly via gist.githubusercontent.com (no API, no rate limits).
    """
    if not gist_id:
        return None

    time.sleep(delay)

    # Use raw URLs directly (no API needed, no rate limits)
    candidates = []
    if username:
        candidates.append(f"https://gist.githubusercontent.com/{username}/{gist_id}/raw")
    candidates.append(f"https://gist.githubusercontent.com/raw/{gist_id}")
    
    for raw_url in candidates:
        try:
            req = Request(raw_url, headers={"User-Agent": "GSoC-Link-Scraper/1.0"})
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError):
            continue
    return None


def extract_repo_links(text: str) -> List[str]:
    if not text:
        return []
    repos = set()
    # URLs containing github.com/owner/repo...
    url_pattern = r"github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)"
    for m in re.finditer(url_pattern, text):
        owner = m.group(1).lower()
        repo = m.group(2).lower()
        if owner == "gist":
            continue
        repos.add(f"{owner}/{repo}")
    return list(repos)


def extract_pr_links(text: str) -> List[Dict]:
    if not text:
        return []
    prs = []
    seen = set()
    # owner/repo#123
    pat1 = r"([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)#(\d+)"
    for m in re.finditer(pat1, text):
        owner, repo, pr = m.group(1).lower(), m.group(2).lower(), m.group(3)
        key = f"{owner}/{repo}#{pr}"
        if owner == "gist":
            continue
        if key not in seen:
            seen.add(key)
            prs.append({"repo_slug": f"{owner}/{repo}", "pr_number": pr})
    # github.com/owner/repo/pull/123
    pat2 = r"github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/pull/(\d+)"
    for m in re.finditer(pat2, text):
        owner, repo, pr = m.group(1).lower(), m.group(2).lower(), m.group(3)
        key = f"{owner}/{repo}#{pr}"
        if owner == "gist":
            continue
        if key not in seen:
            seen.add(key)
            prs.append({"repo_slug": f"{owner}/{repo}", "pr_number": pr})
    return prs


def normalize_repo_slug(slug: str) -> str:
    return slug.lower().rstrip("/").rstrip(".git")


def process_gists(gists: List[Dict], delay: float, max_gists: Optional[int]) -> Tuple[List[Dict], List[Dict]]:
    repo_rows: List[Dict] = []
    pr_rows: List[Dict] = []
    total = len(gists) if max_gists is None else min(len(gists), max_gists)
    for i, entry in enumerate(gists[:total]):
        if i % 100 == 0:
            print(f"Progress: {i}/{total}")
        gist_url = entry.get("github_url")
        year = entry.get("years", [None])[0]
        org = entry.get("org_names", [None])[0]
        user, gid = parse_gist_url(gist_url or "")
        content = fetch_gist_raw(user, gid, delay)
        repos = extract_repo_links(content or "")
        prs = extract_pr_links(content or "")
        for repo in repos:
            repo_rows.append(
                {
                    "gist_url": gist_url,
                    "repo_slug": normalize_repo_slug(repo),
                    "gist_year": year,
                    "gist_org": org,
                    "source_type": "repo",
                }
            )
        for pr in prs:
            pr_rows.append(
                {
                    "gist_url": gist_url,
                    "repo_slug": normalize_repo_slug(pr["repo_slug"]),
                    "pr_number": pr["pr_number"],
                    "gist_year": year,
                    "gist_org": org,
                    "source_type": "pr",
                }
            )
    return repo_rows, pr_rows


def aggregate_unique_repos(repo_rows: List[Dict], pr_rows: List[Dict]) -> List[Dict]:
    agg: Dict[str, Dict] = {}
    for row in repo_rows:
        slug = row["repo_slug"]
        agg.setdefault(slug, {"repo_slug": slug, "count_repos": 0, "count_prs": 0, "gist_urls": set()})
        agg[slug]["count_repos"] += 1
        agg[slug]["gist_urls"].add(row["gist_url"])
    for row in pr_rows:
        slug = row["repo_slug"]
        agg.setdefault(slug, {"repo_slug": slug, "count_repos": 0, "count_prs": 0, "gist_urls": set()})
        agg[slug]["count_prs"] += 1
        agg[slug]["gist_urls"].add(row["gist_url"])
    out = []
    for slug, info in agg.items():
        out.append(
            {
                "repo_slug": slug,
                "count_repos": info["count_repos"],
                "count_prs": info["count_prs"],
                "gist_count": len(info["gist_urls"]),
            }
        )
    out.sort(key=lambda x: x["repo_slug"])
    return out


def write_json(path: Path, data: List[Dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def write_csv(path: Path, rows: List[Dict], headers: List[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h, "") for h in headers})


def load_oss4sg(csv_path: Path, col: str) -> List[str]:
    projects = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            val = row.get(col, "").strip().lower()
            if val:
                val = val.replace("https://github.com/", "").replace("http://github.com/", "")
                val = val.replace("www.github.com/", "").replace("github.com/", "")
                val = val.rstrip("/").rstrip(".git")
                projects.append(val)
    return projects


def match_oss4sg(repos: List[Dict], oss4sg: List[str]) -> List[Dict]:
    s = set(oss4sg)
    matches = []
    for r in repos:
        if r["repo_slug"] in s:
            matches.append({"repo_slug": r["repo_slug"], "count_repos": r["count_repos"], "count_prs": r["count_prs"]})
    return matches


def main():
    parser = argparse.ArgumentParser(description="Extract repo and PR links from GSoC gists.")
    parser.add_argument("--max-gists", type=int, default=None, help="Limit gists for testing.")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between requests.")
    parser.add_argument("--oss4sg-csv", type=Path, default=BASE_DIR.parent.parent / "OSS4SG-Project-List.csv")
    parser.add_argument("--url-column", type=str, default="repo_name_with_owner")
    parser.add_argument("--no-match", action="store_true", help="Skip OSS4SG matching.")
    args = parser.parse_args()

    print("Loading extracted data...")
    data = load_extracted()
    gists = filter_gists(data)
    print(f"Total gists: {len(gists)}")

    repo_rows, pr_rows = process_gists(gists, delay=args.delay, max_gists=args.max_gists)
    unique_repos = aggregate_unique_repos(repo_rows, pr_rows)

    # Write outputs
    write_json(BASE_DIR / "gist_links_projects.json", repo_rows)
    write_csv(
        BASE_DIR / "gist_links_projects.csv",
        repo_rows,
        ["gist_url", "repo_slug", "gist_year", "gist_org", "source_type"],
    )
    write_json(BASE_DIR / "gist_links_prs.json", pr_rows)
    write_csv(
        BASE_DIR / "gist_links_prs.csv",
        pr_rows,
        ["gist_url", "repo_slug", "pr_number", "gist_year", "gist_org", "source_type"],
    )
    write_json(BASE_DIR / "gist_repos_unique.json", unique_repos)
    write_csv(
        BASE_DIR / "gist_repos_unique.csv",
        unique_repos,
        ["repo_slug", "count_repos", "count_prs", "gist_count"],
    )

    if not args.no_match:
        oss4sg = load_oss4sg(args.oss4sg_csv, args.url_column)
        matches = match_oss4sg(unique_repos, oss4sg)
        write_json(BASE_DIR / "oss4sg_matches_from_gist_links.json", matches)
        print(f"OSS4SG matches: {len(matches)}")

    print(f"Repo rows: {len(repo_rows)}, PR rows: {len(pr_rows)}, Unique repos: {len(unique_repos)}")


if __name__ == "__main__":
    main()
