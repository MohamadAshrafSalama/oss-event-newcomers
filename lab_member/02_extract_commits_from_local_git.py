#!/usr/bin/env python3
"""
Extract commit data from locally cloned git repos using `git log`.

Much faster than the API -- a repo with 50k commits takes a couple of seconds.

Input:  CSV with a `repo` column. Either add a `local_path` column per row,
        or pass --repos-root and the script will look for owner__repo folders.
Output: One CSV per repo in --out-dir. Pass --combined-out to also write
        everything into a single file.

Columns: repo_name, commit_hash, author_name, author_email, author_date,
         committer_name, committer_email, committer_date, parent_hashes,
         tree_hash, subject, body, files_changed, insertions, deletions

Usage:
  python 02_extract_commits_from_local_git.py \
    --repos repos.csv \
    --repos-root /data/repos \
    --out-dir commits/ \
    --combined-out commits_all.csv
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


CSV_COLUMNS = [
    "repo_name",
    "commit_hash",
    "author_name",
    "author_email",
    "author_date",
    "committer_name",
    "committer_email",
    "committer_date",
    "parent_hashes",
    "tree_hash",
    "subject",
    "body",
    "files_changed",
    "insertions",
    "deletions",
]


def read_repo_rows(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            repo = (row.get("repo") or row.get("full_name") or "").strip()
            if repo:
                rows.append(
                    {
                        "repo": repo,
                        "local_path": (row.get("local_path") or "").strip(),
                    }
                )
    return rows


def resolve_repo_path(repo: str, local_path: str, repos_root: Optional[Path]) -> Optional[Path]:
    if local_path:
        p = Path(local_path).expanduser()
        return p if p.exists() else None
    if repos_root is None:
        return None
    candidate1 = repos_root / repo.replace("/", "__")
    candidate2 = repos_root / repo
    for candidate in (candidate1, candidate2):
        if candidate.exists():
            return candidate
    return None


def parse_git_log(output: str, repo_name: str, delimiter: str, commit_sep: str) -> List[Dict[str, object]]:
    commits: List[Dict[str, object]] = []
    raw_commits = output.split(commit_sep)
    for raw in raw_commits:
        raw = raw.strip()
        if not raw:
            continue
        lines = raw.split("\n")
        commit_line = None
        numstat_lines: List[str] = []
        for i, line in enumerate(lines):
            if delimiter in line:
                commit_line = line
                numstat_lines = lines[i + 1 :]
                break
        if not commit_line:
            continue
        parts = commit_line.split(delimiter)
        if len(parts) < 11:
            continue
        files_changed = 0
        insertions = 0
        deletions = 0
        for ns_line in numstat_lines:
            ns_line = ns_line.strip()
            if not ns_line:
                continue
            ns_parts = ns_line.split("\t")
            if len(ns_parts) >= 2:
                files_changed += 1
                if ns_parts[0].isdigit():
                    insertions += int(ns_parts[0])
                if ns_parts[1].isdigit():
                    deletions += int(ns_parts[1])
        commits.append(
            {
                "repo_name": repo_name,
                "commit_hash": parts[0],
                "author_name": parts[1],
                "author_email": parts[2],
                "author_date": parts[3],
                "committer_name": parts[4],
                "committer_email": parts[5],
                "committer_date": parts[6],
                "parent_hashes": parts[7],
                "tree_hash": parts[8],
                "subject": parts[9],
                "body": parts[10].strip(),
                "files_changed": files_changed,
                "insertions": insertions,
                "deletions": deletions,
            }
        )
    return commits


def extract_commits(repo_name: str, repo_path: Path) -> Tuple[bool, List[Dict[str, object]], str]:
    delimiter = "<<<FIELD_SEP>>>"
    commit_sep = "<<<COMMIT_SEP>>>"
    format_str = (
        f"%H{delimiter}%an{delimiter}%ae{delimiter}%aI{delimiter}"
        f"%cn{delimiter}%ce{delimiter}%cI{delimiter}%P{delimiter}"
        f"%T{delimiter}%s{delimiter}%b{commit_sep}"
    )
    try:
        result = subprocess.run(
            ["git", "log", "--all", f"--format={format_str}", "--numstat"],
            cwd=repo_path,
            capture_output=True,
            timeout=3600,
        )
    except Exception as exc:
        return False, [], f"git log failed: {exc}"
    if result.returncode != 0:
        return False, [], result.stderr.decode("utf-8", errors="replace").strip()
    stdout = result.stdout.decode("utf-8", errors="replace")
    commits = parse_git_log(stdout, repo_name, delimiter, commit_sep)
    return True, commits, "ok"


def write_repo_csv(rows: Iterable[Dict[str, object]], out_file: Path) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def append_to_combined(combined_path: Path, rows: Iterable[Dict[str, object]], write_header: bool) -> None:
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    with combined_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract commit-level data from local git repos.")
    parser.add_argument("--repos", required=True, help="CSV containing repo list.")
    parser.add_argument("--repos-root", default="", help="Root directory for local clones.")
    parser.add_argument("--out-dir", required=True, help="Output directory for per-repo CSVs.")
    parser.add_argument("--combined-out", default="", help="Optional combined CSV path.")
    args = parser.parse_args()

    repo_rows = read_repo_rows(Path(args.repos))
    repos_root = Path(args.repos_root).expanduser() if args.repos_root else None
    out_dir = Path(args.out_dir)
    combined_path = Path(args.combined_out) if args.combined_out else None

    if combined_path and combined_path.exists():
        combined_path.unlink()

    write_header = True
    for idx, row in enumerate(repo_rows, start=1):
        repo = row["repo"]
        repo_path = resolve_repo_path(repo, row["local_path"], repos_root)
        if repo_path is None:
            print(f"[{idx}/{len(repo_rows)}] SKIP {repo}: local path not found.")
            continue
        print(f"[{idx}/{len(repo_rows)}] Extracting commits from {repo}")
        ok, commits, msg = extract_commits(repo, repo_path)
        if not ok:
            print(f"  FAILED: {msg}")
            continue
        repo_file = out_dir / f"{repo.replace('/', '__')}.csv"
        write_repo_csv(commits, repo_file)
        if combined_path:
            append_to_combined(combined_path, commits, write_header)
            write_header = False
        print(f"  Saved {len(commits)} commits -> {repo_file}")

    if combined_path:
        print(f"Combined CSV ready -> {combined_path}")


if __name__ == "__main__":
    main()
