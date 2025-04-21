#!/usr/bin/env python3
"""
Prepare a safe resume state after an interruption:

- Reconcile `progress/progress.json` with existing `outputs/contributors/*_journey.csv`
  - Add CSV-present usernames to `completed` (crash can happen after writing CSV but before saving progress)
  - Remove usernames from `completed` if their CSV is missing (so they get reprocessed)
- Build a new `progress/sorted_remaining.json` ordering remaining contributors from "smaller" to "larger"
  using a local proxy: `len(repos_contributed)` from `event_contributors_final.json`.

This avoids extra GitHub API calls (which are heavily rate-limited) and still prioritizes smaller profiles first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple


SCRIPT_DIR = Path(__file__).parent


@dataclass(frozen=True)
class PrepResult:
    completed_before: int
    completed_after: int
    added_from_csv: int
    removed_missing_csv: int
    csv_count: int
    remaining_count: int
    sorted_file: Path


def _load_json(path: Path) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")


def _csv_usernames(outputs_dir: Path) -> Set[str]:
    usernames: Set[str] = set()
    for p in outputs_dir.glob("*_journey.csv"):
        name = p.name
        if name.endswith("_journey.csv"):
            usernames.add(name[: -len("_journey.csv")])
    return usernames


def _repos_count_by_username(contributors_file: Path) -> Dict[str, int]:
    data = _load_json(contributors_file)
    contributors = data.get("contributors", [])

    out: Dict[str, int] = {}
    for c in contributors:
        username = (c.get("github_username") or "").strip()
        if not username:
            continue
        repos = c.get("repos_contributed") or []
        try:
            out[username] = len(repos)
        except Exception:
            out[username] = 0
    return out


def prepare(
    *,
    progress_file: Path,
    outputs_dir: Path,
    contributors_file: Path,
    sorted_remaining_file: Path,
) -> PrepResult:
    progress = _load_json(progress_file)
    completed: List[str] = list(progress.get("completed", []))
    completed_set: Set[str] = set(completed)

    completed_before = len(completed_set)

    csv_users = _csv_usernames(outputs_dir)
    csv_count = len(csv_users)

    # 1) Add CSV-present users to completed
    added = 0
    for u in sorted(csv_users):
        if u not in completed_set:
            completed.append(u)
            completed_set.add(u)
            added += 1

    # 2) Remove completed users whose CSV is missing
    removed = 0
    if outputs_dir.exists():
        keep: List[str] = []
        for u in completed:
            if u in csv_users:
                keep.append(u)
            else:
                removed += 1
        completed = keep
        completed_set = set(keep)

    progress["completed"] = completed
    progress["last_updated"] = datetime.now().isoformat()

    _save_json(progress_file, progress)

    # Build sorted remaining order using repos_contributed count
    repos_count = _repos_count_by_username(contributors_file)
    all_users = list(repos_count.keys())
    remaining = [u for u in all_users if u not in completed_set]

    remaining_sorted = sorted(
        remaining,
        key=lambda u: (repos_count.get(u, 0), u.lower()),
    )

    sorted_payload = {
        "sorted_at": datetime.now().isoformat(),
        "sort_strategy": "len(repos_contributed) ascending, then username",
        "total_remaining": len(remaining_sorted),
        "sorted_contributors": remaining_sorted,
        "activity_estimates": repos_count,  # proxy score: repos_contributed count
    }
    _save_json(sorted_remaining_file, sorted_payload)

    return PrepResult(
        completed_before=completed_before,
        completed_after=len(completed_set),
        added_from_csv=added,
        removed_missing_csv=removed,
        csv_count=csv_count,
        remaining_count=len(remaining_sorted),
        sorted_file=sorted_remaining_file,
    )


def main() -> int:
    config_path = SCRIPT_DIR / "config.json"
    config = _load_json(config_path)

    project_root = Path(config["paths"]["project_root"])
    contributors_file = project_root / config["paths"]["contributors_input"]
    progress_file = SCRIPT_DIR / config["paths"]["progress_file"]
    outputs_dir = SCRIPT_DIR / config["paths"]["contributors_output_dir"]
    sorted_remaining_file = SCRIPT_DIR / "progress" / "sorted_remaining.json"

    res = prepare(
        progress_file=progress_file,
        outputs_dir=outputs_dir,
        contributors_file=contributors_file,
        sorted_remaining_file=sorted_remaining_file,
    )

    print("OK")
    print(f"Completed: {res.completed_before} → {res.completed_after}")
    print(f"CSV files: {res.csv_count}")
    print(f"Added to completed from existing CSVs: {res.added_from_csv}")
    print(f"Removed from completed (missing CSV): {res.removed_missing_csv}")
    print(f"Remaining to process: {res.remaining_count}")
    print(f"Wrote sorted order: {res.sorted_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

