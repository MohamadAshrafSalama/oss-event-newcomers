#!/usr/bin/env python3
"""
Count non-comment lines of code (NCLOC) per repo.

Used as a project-size proxy for normalization. Runs `git ls-files` to get
tracked files only, so it won't count vendored packages or build artifacts
as long as they are gitignored.

Supported extensions: .py .js .ts .java .cpp .cc .c .h .hpp .go .rb .rs
                      .kt .swift .php  (add more in SUPPORTED_EXTS as needed)

Input:  CSV with a `repo` column and optional `local_path`. Or pass --repos-root.
Output: CSV with repo, file_count, total_lines, code_lines, comment_lines,
        blank_lines, ncloc_proxy (= code_lines).

Usage:
  python 04_count_project_code_size.py \
    --repos repos.csv \
    --repos-root /data/repos \
    --out project_size_metrics.csv
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


SUPPORTED_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".java",
    ".cpp",
    ".cc",
    ".c",
    ".h",
    ".hpp",
    ".go",
    ".rb",
    ".rs",
    ".kt",
    ".swift",
    ".php",
}


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
    c1 = repos_root / repo.replace("/", "__")
    c2 = repos_root / repo
    for c in (c1, c2):
        if c.exists():
            return c
    return None


def tracked_files(repo_path: Path) -> List[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return []
    files = []
    for line in result.stdout.splitlines():
        p = repo_path / line.strip()
        if p.suffix.lower() in SUPPORTED_EXTS and p.exists():
            files.append(p)
    return files


def classify_line(line: str, ext: str, in_block_comment: bool) -> Tuple[str, bool]:
    stripped = line.strip()
    if not stripped:
        return "blank", in_block_comment

    if ext in {".py", ".rb"}:
        if stripped.startswith("#"):
            return "comment", in_block_comment
        return "code", in_block_comment

    # C-like heuristic
    if in_block_comment:
        if "*/" in stripped:
            return "comment", False
        return "comment", True
    if stripped.startswith("//"):
        return "comment", in_block_comment
    if stripped.startswith("/*"):
        if "*/" in stripped and stripped.index("/*") < stripped.index("*/"):
            return "comment", in_block_comment
        return "comment", True
    return "code", in_block_comment


def analyze_file(path: Path) -> Dict[str, int]:
    total = code = comment = blank = 0
    in_block_comment = False
    ext = path.suffix.lower()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                total += 1
                kind, in_block_comment = classify_line(line, ext, in_block_comment)
                if kind == "code":
                    code += 1
                elif kind == "comment":
                    comment += 1
                else:
                    blank += 1
    except Exception:
        return {"total": 0, "code": 0, "comment": 0, "blank": 0}
    return {"total": total, "code": code, "comment": comment, "blank": blank}


def main() -> None:
    parser = argparse.ArgumentParser(description="Count project code size and NCLOC proxy.")
    parser.add_argument("--repos", required=True, help="Repos CSV path.")
    parser.add_argument("--repos-root", default="", help="Root directory for local repos.")
    parser.add_argument("--out", required=True, help="Output CSV path.")
    args = parser.parse_args()

    repo_rows = read_repo_rows(Path(args.repos))
    repos_root = Path(args.repos_root).expanduser() if args.repos_root else None
    out_rows: List[Dict[str, object]] = []

    for idx, row in enumerate(repo_rows, start=1):
        repo = row["repo"]
        repo_path = resolve_repo_path(repo, row["local_path"], repos_root)
        if repo_path is None:
            print(f"[{idx}/{len(repo_rows)}] SKIP {repo}: local path not found")
            out_rows.append(
                {
                    "repo": repo,
                    "file_count": 0,
                    "total_lines": 0,
                    "code_lines": 0,
                    "comment_lines": 0,
                    "blank_lines": 0,
                    "ncloc_proxy": 0,
                    "status": "missing_repo",
                }
            )
            continue

        files = tracked_files(repo_path)
        total = code = comment = blank = 0
        for file_path in files:
            m = analyze_file(file_path)
            total += m["total"]
            code += m["code"]
            comment += m["comment"]
            blank += m["blank"]
        print(f"[{idx}/{len(repo_rows)}] Counted {repo}: {len(files)} files")
        out_rows.append(
            {
                "repo": repo,
                "file_count": len(files),
                "total_lines": total,
                "code_lines": code,
                "comment_lines": comment,
                "blank_lines": blank,
                "ncloc_proxy": code,
                "status": "ok",
            }
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "repo",
        "file_count",
        "total_lines",
        "code_lines",
        "comment_lines",
        "blank_lines",
        "ncloc_proxy",
        "status",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"Saved {len(out_rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
