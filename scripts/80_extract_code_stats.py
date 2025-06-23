#!/usr/bin/env python3
"""
Extract per-contributor code size stats from per-repo CSVs on external drive.

The per-repo CSVs at /Volumes/T7/Event based OSS4SG/extracted/ contain full
commit data including insertions, deletions, files_changed per commit.
The consolidated CSV (all_commits_consolidated.csv) stripped these columns.

This script:
  1. Builds a lookup of (repo, email) for all 4,002 contributors
  2. Streams each per-repo CSV row-by-row (never loads full file)
  3. Accumulates insertions/deletions/files_changed per contributor
  4. Saves aggregated stats to contributor_code_stats.json

Design:
  - Streams CSVs row-by-row via csv.DictReader
  - Checkpoints after each CSV file (re-runnable)
  - --test flag processes only 10 CSV files
  - Progress bar with file count and matched contributors

Usage:
  python3 scripts/80_extract_code_stats.py --test    # 10 files first
  python3 scripts/80_extract_code_stats.py            # all 378 files
"""

import argparse
import csv
import glob
import json
import os
import sys
import time

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNEY_PATH = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")
RESOLVED_PATH = os.path.join(BASE, "08_analysis_results", "resolved_emails.json")
EXTRACTED_DIR = "/Volumes/T7/Event based OSS4SG/extracted"
OUTPUT_PATH = os.path.join(BASE, "08_analysis_results", "contributor_code_stats.json")
CHECKPOINT_PATH = os.path.join(BASE, "08_analysis_results", "code_stats_checkpoint.json")


def normalize_repo(repo_name):
    return repo_name.lower().strip().rstrip("/")


def normalize_email(email):
    if not email:
        return ""
    return email.lower().strip()


def repo_from_filename(filepath):
    """Convert owner__repo.csv filename back to owner/repo."""
    stem = os.path.splitext(os.path.basename(filepath))[0]
    return stem.replace("__", "/")


def build_contributor_lookup(journeys, resolved_emails):
    """Build (repo_normalized, email_normalized) -> contributor_id lookup."""
    lookup = {}
    email_sources = {}

    for j in journeys["event_journeys"]:
        username = j.get("github_username", "")
        repo = normalize_repo(j.get("repo", ""))
        cid = j.get("contribution_id", f"ev_{username}_{repo}")

        emails_to_try = set()

        # From resolved_emails
        resolved = resolved_emails.get(cid, {})
        if resolved.get("email"):
            emails_to_try.add(normalize_email(resolved["email"]))
        matched_email = (resolved.get("t7_match") or {}).get("matched_email")
        if matched_email:
            emails_to_try.add(normalize_email(matched_email))

        # Noreply patterns
        if username:
            emails_to_try.add(normalize_email(f"{username}@users.noreply.github.com"))

        for em in emails_to_try:
            if em:
                key = (repo, em)
                lookup[key] = cid
                email_sources[cid] = em

    for j in journeys["organic_journeys"]:
        email = normalize_email(j.get("organic_email", ""))
        repo = normalize_repo(j.get("repo", ""))
        username = j.get("github_username", "")
        cid = j.get("matched_event_contribution_id", "") + "__organic"
        if not cid or cid == "__organic":
            cid = f"org_{email}_{repo}"

        emails_to_try = set()
        if email:
            emails_to_try.add(email)
        if username:
            emails_to_try.add(normalize_email(f"{username}@users.noreply.github.com"))

        for em in emails_to_try:
            if em:
                key = (repo, em)
                lookup[key] = cid
                email_sources[cid] = em

    return lookup, email_sources


def load_checkpoint():
    if os.path.exists(CHECKPOINT_PATH):
        with open(CHECKPOINT_PATH) as f:
            return json.load(f)
    return {"processed_files": [], "stats": {}}


def save_checkpoint(processed_files, stats):
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump({"processed_files": processed_files, "stats": stats}, f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Process only 10 CSV files")
    parser.add_argument("--fresh", action="store_true", help="Ignore checkpoint, start fresh")
    args = parser.parse_args()

    t0 = time.time()
    print("=" * 60)
    print("EXTRACT CODE STATS FROM PER-REPO CSVs")
    print("=" * 60)

    # Check external drive
    if not os.path.isdir(EXTRACTED_DIR):
        print(f"ERROR: External drive not found at {EXTRACTED_DIR}")
        sys.exit(1)

    # Load journeys
    print("\n[1/4] Loading contributor identities...")
    with open(JOURNEY_PATH) as f:
        journeys = json.load(f)

    resolved_emails = {}
    if os.path.exists(RESOLVED_PATH):
        with open(RESOLVED_PATH) as f:
            resolved_emails = json.load(f)

    lookup, email_sources = build_contributor_lookup(journeys, resolved_emails)
    print(f"  Lookup size: {len(lookup)} (repo, email) pairs")
    print(f"  Unique contributor IDs: {len(set(lookup.values()))}")

    # Get CSV files
    csv_files = sorted(glob.glob(os.path.join(EXTRACTED_DIR, "*.csv")))
    print(f"\n[2/4] Found {len(csv_files)} CSV files on external drive")

    if args.test:
        csv_files = csv_files[:10]
        print(f"  TEST MODE: processing only {len(csv_files)} files")

    # Load checkpoint
    if args.fresh:
        processed_files = []
        stats = {}
    else:
        ckpt = load_checkpoint()
        processed_files = ckpt["processed_files"]
        stats = ckpt["stats"]
        if processed_files:
            print(f"  Resuming: {len(processed_files)} files already processed")

    # Process CSV files
    print(f"\n[3/4] Processing CSV files...")
    total_commits_scanned = 0
    total_matched = 0
    files_to_process = [f for f in csv_files if f not in processed_files]

    for file_idx, filepath in enumerate(files_to_process):
        file_repo = normalize_repo(repo_from_filename(filepath))
        file_commits = 0
        file_matched = 0

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    file_commits += 1
                    email = normalize_email(row.get("author_email", ""))
                    if not email:
                        continue

                    key = (file_repo, email)
                    cid = lookup.get(key)
                    if cid is None:
                        continue

                    file_matched += 1

                    try:
                        ins = int(row.get("insertions", 0) or 0)
                        dels = int(row.get("deletions", 0) or 0)
                        files_ch = int(row.get("files_changed", 0) or 0)
                    except (ValueError, TypeError):
                        ins, dels, files_ch = 0, 0, 0

                    if cid not in stats:
                        stats[cid] = {
                            "total_insertions": 0,
                            "total_deletions": 0,
                            "total_files_changed": 0,
                            "num_commits": 0,
                        }
                    stats[cid]["total_insertions"] += ins
                    stats[cid]["total_deletions"] += dels
                    stats[cid]["total_files_changed"] += files_ch
                    stats[cid]["num_commits"] += 1

        except Exception as e:
            print(f"  WARNING: Error reading {filepath}: {e}")

        total_commits_scanned += file_commits
        total_matched += file_matched
        processed_files.append(filepath)

        # Progress
        done = len(processed_files)
        total = len(csv_files)
        pct = done / total * 100
        elapsed = time.time() - t0
        eta = (elapsed / max(done - (len(ckpt.get("processed_files", [])) if not args.fresh else 0), 1)) * (total - done)
        print(f"  [{done:3d}/{total}] {pct:5.1f}% | {os.path.basename(filepath):50s} | {file_commits:>7,} commits, {file_matched:>5,} matched | ETA: {eta:.0f}s", end="\r")

        # Checkpoint every 20 files
        if done % 20 == 0:
            save_checkpoint(processed_files, stats)

    print(f"\n  Total commits scanned: {total_commits_scanned:,}")
    print(f"  Total matched to our contributors: {total_matched:,}")
    print(f"  Contributors with stats: {len(stats)}")

    # Compute aggregates
    print(f"\n[4/4] Computing per-contributor aggregates...")
    output = {}
    for cid, s in stats.items():
        n = s["num_commits"]
        total_churn = s["total_insertions"] + s["total_deletions"]
        output[cid] = {
            "total_insertions": s["total_insertions"],
            "total_deletions": s["total_deletions"],
            "total_files_changed": s["total_files_changed"],
            "num_commits_with_stats": n,
            "total_code_churn": total_churn,
            "mean_churn_per_commit": round(total_churn / n, 2) if n > 0 else 0,
            "mean_files_per_commit": round(s["total_files_changed"] / n, 2) if n > 0 else 0,
        }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  Saved: {OUTPUT_PATH}")

    # Cleanup checkpoint on full completion
    if not args.test and len(files_to_process) == 0 or len(processed_files) == len(csv_files):
        if os.path.exists(CHECKPOINT_PATH):
            os.remove(CHECKPOINT_PATH)
            print("  Checkpoint cleaned up (full run complete)")

    # Summary stats
    churns = [v["mean_churn_per_commit"] for v in output.values() if v["num_commits_with_stats"] > 0]
    if churns:
        import statistics
        print(f"\n  Code churn/commit: median={statistics.median(churns):.1f}, mean={statistics.mean(churns):.1f}, max={max(churns):.1f}")

    print(f"\n  Total time: {time.time() - t0:.1f}s")
    print("=" * 60)
    print("DONE!")


if __name__ == "__main__":
    main()
