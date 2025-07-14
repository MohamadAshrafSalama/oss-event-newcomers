#!/usr/bin/env python3
"""
Mine PR and issue activity per contributor from the GitHub Search API.

Token rotation: the script cycles through all tokens you provide, so you
get N * 5000 requests/hour instead of 5000. Pass tokens via --tokens-file
(one token per line) or --tokens (comma-separated).

Progress is saved to a checkpoint file after each contributor. If the run
is interrupted, re-running the same command picks up where it left off.

Input:  CSV with columns: contributor_id, repo, username
Output: CSV with one row per PR or issue the contributor authored.

Usage:
  python 03_mine_pr_issue_with_token_rotation.py \
    --contributors contributors.csv \
    --out contributor_activity.csv \
    --checkpoint mining_checkpoint.json \
    --tokens-file ~/.github_tokens.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_contributors(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            contributor_id = (row.get("contributor_id") or "").strip()
            repo = (row.get("repo") or "").strip()
            username = (row.get("username") or row.get("github_username") or "").strip()
            if contributor_id and repo and username:
                rows.append(
                    {
                        "contributor_id": contributor_id,
                        "repo": repo,
                        "username": username,
                    }
                )
    return rows


def load_tokens(tokens_file: str, tokens_inline: str) -> List[str]:
    tokens: List[str] = []
    if tokens_inline.strip():
        tokens.extend([t.strip() for t in tokens_inline.split(",") if t.strip()])
    if tokens_file:
        content = Path(tokens_file).expanduser().read_text(encoding="utf-8")
        tokens.extend([line.strip() for line in content.splitlines() if line.strip()])
    unique = []
    seen = set()
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


class TokenRotator:
    def __init__(self, tokens: List[str]):
        self.tokens = tokens
        self.idx = 0

    def next_token(self) -> Optional[str]:
        if not self.tokens:
            return None
        token = self.tokens[self.idx]
        self.idx = (self.idx + 1) % len(self.tokens)
        return token


def api_get_json(url: str, token: Optional[str], retries: int = 3) -> Tuple[Optional[dict], Dict[str, str]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "lab-member-starter",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                payload = resp.read().decode("utf-8")
                return json.loads(payload), dict(resp.headers.items())
        except Exception:
            if attempt == retries - 1:
                return None, {}
            time.sleep(1.0 * (attempt + 1))
    return None, {}


def query_activities(repo: str, username: str, kind: str, token: Optional[str]) -> List[dict]:
    q = urllib.parse.quote_plus(f"author:{username} repo:{repo} type:{kind}")
    url = f"https://api.github.com/search/issues?q={q}&per_page=100"
    data, _ = api_get_json(url, token)
    if not isinstance(data, dict):
        return []
    return data.get("items", []) or []


def load_checkpoint(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"done_ids": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_checkpoint(path: Path, done_ids: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"done_ids": sorted(set(done_ids)), "updated_at": time.time()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_rows(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "contributor_id",
        "repo",
        "username",
        "activity_type",
        "number",
        "state",
        "created_at",
        "closed_at",
        "title",
        "url",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mine PR and issue activity with token rotation.")
    parser.add_argument("--contributors", required=True, help="Contributors CSV path.")
    parser.add_argument("--out", required=True, help="Output activity CSV path.")
    parser.add_argument("--checkpoint", required=True, help="Checkpoint JSON path.")
    parser.add_argument("--tokens", default="", help="Comma-separated GitHub tokens.")
    parser.add_argument("--tokens-file", default="", help="Text file with one token per line.")
    parser.add_argument("--sleep-ms", type=int, default=250, help="Delay between API calls.")
    args = parser.parse_args()

    contributors = read_contributors(Path(args.contributors))
    tokens = load_tokens(args.tokens_file, args.tokens)
    rotator = TokenRotator(tokens)

    checkpoint_path = Path(args.checkpoint)
    checkpoint = load_checkpoint(checkpoint_path)
    done_ids = set(checkpoint.get("done_ids", []))

    all_rows: List[Dict[str, object]] = []
    for idx, c in enumerate(contributors, start=1):
        cid = c["contributor_id"]
        if cid in done_ids:
            print(f"[{idx}/{len(contributors)}] Skip done contributor {cid}")
            continue
        print(f"[{idx}/{len(contributors)}] Mining {cid} ({c['username']} in {c['repo']})")
        token = rotator.next_token()
        prs = query_activities(c["repo"], c["username"], "pr", token)
        time.sleep(max(args.sleep_ms, 0) / 1000.0)
        token = rotator.next_token()
        issues = query_activities(c["repo"], c["username"], "issue", token)
        time.sleep(max(args.sleep_ms, 0) / 1000.0)

        for item in prs:
            all_rows.append(
                {
                    "contributor_id": cid,
                    "repo": c["repo"],
                    "username": c["username"],
                    "activity_type": "pr",
                    "number": item.get("number"),
                    "state": item.get("state"),
                    "created_at": item.get("created_at"),
                    "closed_at": item.get("closed_at"),
                    "title": item.get("title", ""),
                    "url": item.get("html_url", ""),
                }
            )
        for item in issues:
            all_rows.append(
                {
                    "contributor_id": cid,
                    "repo": c["repo"],
                    "username": c["username"],
                    "activity_type": "issue",
                    "number": item.get("number"),
                    "state": item.get("state"),
                    "created_at": item.get("created_at"),
                    "closed_at": item.get("closed_at"),
                    "title": item.get("title", ""),
                    "url": item.get("html_url", ""),
                }
            )

        done_ids.add(cid)
        save_checkpoint(checkpoint_path, list(done_ids))

    write_rows(Path(args.out), all_rows)
    print(f"Saved {len(all_rows)} activity rows -> {args.out}")


if __name__ == "__main__":
    main()
