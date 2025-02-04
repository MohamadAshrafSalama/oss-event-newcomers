#!/usr/bin/env python3
"""
Consolidate All Event Repos with Contributor Counts
Phase A: No API needed - processes existing JSON files

Output: all_event_repos_consolidated.json and .csv
"""

import json
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENT_DIR = os.path.join(BASE_DIR, "02_event_data_extraction_and_contributor_discovery")
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Data files - contributor data
FILES = {
    "24pr": os.path.join(EVENT_DIR, "24_pull_requests", "24pr_contributors.json"),
    "gsoc": os.path.join(EVENT_DIR, "google_summer_of_code", "gsoc_contributors.json"),
    "hacktoberfest": os.path.join(EVENT_DIR, "hacktoberfest", "hacktoberfest_contributors.json"),
    "lfx": os.path.join(EVENT_DIR, "lfx_mentorship", "lfx_contributors.json"),
}

# Match files - repos identified as participating in events (may not have contributors extracted)
MATCH_FILES = {
    "gsoc": os.path.join(EVENT_DIR, "google_summer_of_code", "oss4sg_gsoc_final_matches.json"),
    "24pr": os.path.join(EVENT_DIR, "24_pull_requests", "oss4sg_24pr_matches.json"),
    "hacktoberfest": os.path.join(EVENT_DIR, "hacktoberfest", "oss4sg_hacktoberfest_matches.json"),
    "mlh": os.path.join(EVENT_DIR, "mlh_fellowship", "oss4sg_mlh_matches.json"),
}

OSS4SG_FILE = os.path.join(BASE_DIR, "OSS4SG-Project-List.csv")


def progress_bar(current, total, prefix="Progress", width=40):
    """Display a progress bar."""
    percent = current / total if total > 0 else 0
    filled = int(width * percent)
    bar = "=" * filled + ">" + " " * (width - filled - 1) if filled < width else "=" * width
    sys.stdout.write(f"\r{prefix}: [{bar}] {current:,}/{total:,} ({percent*100:.1f}%)")
    sys.stdout.flush()


def normalize_repo(repo_name):
    """Normalize repo name to lowercase owner/repo format."""
    if not repo_name:
        return None
    repo = repo_name.lower().strip()
    # Remove github.com prefix if present
    if "github.com/" in repo:
        repo = repo.split("github.com/")[-1]
    # Remove .git suffix
    if repo.endswith(".git"):
        repo = repo[:-4]
    # Remove trailing slashes
    repo = repo.rstrip("/")
    # Must have owner/repo format
    if "/" not in repo or repo.count("/") > 1:
        return None
    return repo


def load_oss4sg_repos():
    """Load OSS4SG project list and return set of normalized repo names."""
    print("\n[1/7] Loading OSS4SG project list...")
    oss4sg_repos = set()
    
    with open(OSS4SG_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            repo = normalize_repo(row.get("repo_name_with_owner", ""))
            if repo:
                oss4sg_repos.add(repo)
    
    print(f"       Loaded {len(oss4sg_repos)} OSS4SG projects")
    return oss4sg_repos


def load_match_files():
    """Load repos from match files (identified as participating but may not have contributors)."""
    print("\n[1.5/7] Loading match files (repos identified as participating in events)...")
    
    match_repos = {
        "gsoc": set(),
        "24pr": set(),
        "hacktoberfest": set(),
        "mlh": set(),
    }
    
    # GSoC matches - simple array of strings
    if os.path.exists(MATCH_FILES["gsoc"]):
        with open(MATCH_FILES["gsoc"], "r") as f:
            data = json.load(f)
            for repo in data:
                normalized = normalize_repo(repo)
                if normalized:
                    match_repos["gsoc"].add(normalized)
        print(f"       GSoC matches: {len(match_repos['gsoc'])} repos")
    
    # 24PR matches - array of objects with repo_name
    if os.path.exists(MATCH_FILES["24pr"]):
        with open(MATCH_FILES["24pr"], "r") as f:
            data = json.load(f)
            for item in data:
                normalized = normalize_repo(item.get("repo_name", ""))
                if normalized:
                    match_repos["24pr"].add(normalized)
        print(f"       24PR matches: {len(match_repos['24pr'])} repos")
    
    # Hacktoberfest matches - simple array of strings
    if os.path.exists(MATCH_FILES["hacktoberfest"]):
        with open(MATCH_FILES["hacktoberfest"], "r") as f:
            data = json.load(f)
            for repo in data:
                normalized = normalize_repo(repo)
                if normalized:
                    match_repos["hacktoberfest"].add(normalized)
        print(f"       Hacktoberfest matches: {len(match_repos['hacktoberfest'])} repos")
    
    # MLH matches - array of objects with repo
    if os.path.exists(MATCH_FILES["mlh"]):
        with open(MATCH_FILES["mlh"], "r") as f:
            data = json.load(f)
            for item in data:
                normalized = normalize_repo(item.get("repo", ""))
                if normalized:
                    match_repos["mlh"].add(normalized)
        print(f"       MLH matches: {len(match_repos['mlh'])} repos")
    
    all_match_repos = match_repos["gsoc"] | match_repos["24pr"] | match_repos["hacktoberfest"] | match_repos["mlh"]
    print(f"       Total unique repos from match files: {len(all_match_repos)}")
    
    return match_repos


def extract_24pr_repos(data):
    """Extract repos and contributor counts from 24PR data."""
    print("\n[2/7] Processing 24 Pull Requests data...")
    repos = defaultdict(set)  # repo -> set of contributors
    
    contributors = data.get("contributors", [])
    total = len(contributors)
    
    for i, contrib in enumerate(contributors):
        if i % 500 == 0:
            progress_bar(i, total, "24PR")
        
        username = contrib.get("github_username", "")
        for repo in contrib.get("repos_contributed", []):
            normalized = normalize_repo(repo)
            if normalized:
                repos[normalized].add(username)
    
    progress_bar(total, total, "24PR")
    print(f"\n       Found {len(repos):,} unique repos, {data.get('total_contributors', 0):,} contributors")
    
    # Convert sets to counts
    return {repo: len(contributors) for repo, contributors in repos.items()}


def extract_gsoc_repos(data):
    """Extract repos and contributor counts from GSoC data."""
    print("\n[3/7] Processing Google Summer of Code data...")
    repos = defaultdict(set)  # repo -> set of contributors
    
    contributors = data.get("contributors", [])
    total = len(contributors)
    
    for i, contrib in enumerate(contributors):
        if i % 200 == 0:
            progress_bar(i, total, "GSoC")
        
        username = contrib.get("github_username", "")
        for repo in contrib.get("repos_contributed", []):
            normalized = normalize_repo(repo)
            if normalized:
                repos[normalized].add(username)
    
    progress_bar(total, total, "GSoC")
    print(f"\n       Found {len(repos):,} unique repos, {data.get('total_contributors', 0):,} contributors")
    
    return {repo: len(contributors) for repo, contributors in repos.items()}


def extract_hacktoberfest_repos(data):
    """Extract repos and contributor counts from Hacktoberfest data."""
    print("\n[4/7] Processing Hacktoberfest data...")
    repos = defaultdict(set)  # repo -> set of contributors
    
    contributors = data.get("contributors", [])
    total = len(contributors)
    
    for i, contrib in enumerate(contributors):
        if i % 2000 == 0:
            progress_bar(i, total, "Hacktoberfest")
        
        username = contrib.get("github_username", "")
        for repo in contrib.get("repos_contributed", []):
            normalized = normalize_repo(repo)
            if normalized:
                repos[normalized].add(username)
    
    progress_bar(total, total, "Hacktoberfest")
    print(f"\n       Found {len(repos):,} unique repos, {data.get('total_contributors', 0):,} contributors")
    
    return {repo: len(contributors) for repo, contributors in repos.items()}


def extract_lfx_repos(data):
    """Extract repos and contributor counts from LFX data."""
    print("\n[5/7] Processing LFX Mentorship data...")
    repos = defaultdict(set)  # repo -> set of contributors
    
    contributors = data.get("contributors", [])
    total = len(contributors)
    
    for i, contrib in enumerate(contributors):
        if i % 50 == 0:
            progress_bar(i, total, "LFX")
        
        username = contrib.get("github_username", "")
        for repo in contrib.get("repos_contributed", []):
            normalized = normalize_repo(repo)
            if normalized:
                repos[normalized].add(username)
    
    progress_bar(total, total, "LFX")
    print(f"\n       Found {len(repos):,} unique repos, {data.get('total_contributors', 0):,} contributors")
    
    return {repo: len(contributors) for repo, contributors in repos.items()}


def merge_all_repos(pr24_repos, gsoc_repos, hf_repos, lfx_repos, oss4sg_set, match_repos):
    """Merge all repos into single consolidated list."""
    print("\n[6/7] Merging all repos...")
    
    # Get all unique repos from contributor data
    all_repos = set(pr24_repos.keys()) | set(gsoc_repos.keys()) | set(hf_repos.keys()) | set(lfx_repos.keys())
    
    # Also add repos from match files (these are confirmed event participants)
    match_gsoc = match_repos.get("gsoc", set())
    match_24pr = match_repos.get("24pr", set())
    match_hf = match_repos.get("hacktoberfest", set())
    match_mlh = match_repos.get("mlh", set())
    all_match_repos = match_gsoc | match_24pr | match_hf | match_mlh
    
    # Combine all repos
    all_repos = all_repos | all_match_repos
    
    total = len(all_repos)
    print(f"       Repos from contributor data: {len(set(pr24_repos.keys()) | set(gsoc_repos.keys()) | set(hf_repos.keys()) | set(lfx_repos.keys())):,}")
    print(f"       Repos from match files: {len(all_match_repos):,}")
    print(f"       Total unique repos: {total:,}")
    
    consolidated = []
    
    for i, repo in enumerate(all_repos):
        if i % 2000 == 0:
            progress_bar(i, total, "Merging")
        
        gsoc_count = gsoc_repos.get(repo, 0)
        pr24_count = pr24_repos.get(repo, 0)
        hf_count = hf_repos.get(repo, 0)
        lfx_count = lfx_repos.get(repo, 0)
        
        total_contributors = gsoc_count + pr24_count + hf_count + lfx_count
        
        # Track event participation - include from both contributor data AND match files
        events = []
        if gsoc_count > 0 or repo in match_gsoc:
            events.append("GSoC")
        if pr24_count > 0 or repo in match_24pr:
            events.append("24PR")
        if hf_count > 0 or repo in match_hf:
            events.append("HF")
        if lfx_count > 0:
            events.append("LFX")
        if repo in match_mlh:
            events.append("MLH")
        
        consolidated.append({
            "repo_name": repo,
            "is_oss4sg": repo in oss4sg_set,
            "total_event_contributors": total_contributors,
            "event_count": len(events),
            "gsoc_contributors": gsoc_count,
            "24pr_contributors": pr24_count,
            "hf_contributors": hf_count,
            "lfx_contributors": lfx_count,
            "events": events,
        })
    
    progress_bar(total, total, "Merging")
    
    # Sort by total contributors descending, then by event count, then by name
    consolidated.sort(key=lambda x: (-x["total_event_contributors"], -x["event_count"], x["repo_name"]))
    
    return consolidated


def save_outputs(consolidated):
    """Save consolidated data to JSON and CSV."""
    print("\n\nSaving outputs...")
    
    # Save JSON
    json_path = os.path.join(OUTPUT_DIR, "all_event_repos_consolidated.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "total_repos": len(consolidated),
            "total_oss4sg": sum(1 for r in consolidated if r["is_oss4sg"]),
            "repos": consolidated
        }, f, indent=2)
    print(f"       Saved: {json_path}")
    
    # Save CSV
    csv_path = os.path.join(OUTPUT_DIR, "all_event_repos_consolidated.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "repo_name", "is_oss4sg", "total_event_contributors", "event_count",
            "gsoc_contributors", "24pr_contributors", "hf_contributors", "lfx_contributors", "events"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in consolidated:
            row_copy = row.copy()
            row_copy["events"] = ",".join(row_copy["events"])
            writer.writerow(row_copy)
    print(f"       Saved: {csv_path}")
    
    return json_path, csv_path


def print_summary(consolidated):
    """Print summary statistics."""
    total = len(consolidated)
    oss4sg_count = sum(1 for r in consolidated if r["is_oss4sg"])
    
    # Count by contributor ranges
    c_1 = sum(1 for r in consolidated if r["total_event_contributors"] == 1)
    c_2_5 = sum(1 for r in consolidated if 2 <= r["total_event_contributors"] <= 5)
    c_6_10 = sum(1 for r in consolidated if 6 <= r["total_event_contributors"] <= 10)
    c_11_50 = sum(1 for r in consolidated if 11 <= r["total_event_contributors"] <= 50)
    c_51_plus = sum(1 for r in consolidated if r["total_event_contributors"] > 50)
    
    # Count by event count
    e_1 = sum(1 for r in consolidated if r["event_count"] == 1)
    e_2 = sum(1 for r in consolidated if r["event_count"] == 2)
    e_3 = sum(1 for r in consolidated if r["event_count"] == 3)
    e_4 = sum(1 for r in consolidated if r["event_count"] == 4)
    e_5 = sum(1 for r in consolidated if r["event_count"] == 5)
    
    # Count by event (based on events list which includes match file participation)
    in_gsoc = sum(1 for r in consolidated if "GSoC" in r["events"])
    in_24pr = sum(1 for r in consolidated if "24PR" in r["events"])
    in_hf = sum(1 for r in consolidated if "HF" in r["events"])
    in_lfx = sum(1 for r in consolidated if "LFX" in r["events"])
    in_mlh = sum(1 for r in consolidated if "MLH" in r["events"])
    
    print("\n" + "=" * 60)
    print("CONSOLIDATION COMPLETE")
    print("=" * 60)
    
    print(f"\n📊 TOTAL REPOS: {total:,}")
    print(f"   - OSS4SG projects: {oss4sg_count:,}")
    print(f"   - Conventional OSS: {total - oss4sg_count:,}")
    
    print(f"\n📈 BY CONTRIBUTOR COUNT:")
    print(f"   - 1 contributor:     {c_1:,} repos ({c_1/total*100:.1f}%)")
    print(f"   - 2-5 contributors:  {c_2_5:,} repos ({c_2_5/total*100:.1f}%)")
    print(f"   - 6-10 contributors: {c_6_10:,} repos ({c_6_10/total*100:.1f}%)")
    print(f"   - 11-50 contributors:{c_11_50:,} repos ({c_11_50/total*100:.1f}%)")
    print(f"   - 51+ contributors:  {c_51_plus:,} repos ({c_51_plus/total*100:.1f}%)")
    
    print(f"\n🎯 BY EVENT COUNT:")
    print(f"   - 1 event:  {e_1:,} repos")
    print(f"   - 2 events: {e_2:,} repos")
    print(f"   - 3 events: {e_3:,} repos")
    print(f"   - 4 events: {e_4:,} repos")
    print(f"   - 5 events: {e_5:,} repos")
    
    print(f"\n🏷️ BY EVENT:")
    print(f"   - GSoC:         {in_gsoc:,} repos")
    print(f"   - 24PR:         {in_24pr:,} repos")
    print(f"   - Hacktoberfest:{in_hf:,} repos")
    print(f"   - LFX:          {in_lfx:,} repos")
    print(f"   - MLH:          {in_mlh:,} repos")
    
    print(f"\n🔝 TOP 20 REPOS BY EVENT CONTRIBUTORS:")
    for i, repo in enumerate(consolidated[:20], 1):
        oss_flag = " [OSS4SG]" if repo["is_oss4sg"] else ""
        events_str = ",".join(repo["events"])
        print(f"   {i:2}. {repo['repo_name']}: {repo['total_event_contributors']} contributors ({events_str}){oss_flag}")
    
    # Save summary to file
    summary_path = os.path.join(OUTPUT_DIR, "summary_stats.txt")
    with open(summary_path, "w") as f:
        f.write(f"Event Repos Consolidation Summary\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"{'=' * 50}\n\n")
        f.write(f"Total Repos: {total:,}\n")
        f.write(f"OSS4SG Projects: {oss4sg_count:,}\n")
        f.write(f"Conventional OSS: {total - oss4sg_count:,}\n\n")
        f.write(f"By Contributor Count:\n")
        f.write(f"  1 contributor: {c_1:,}\n")
        f.write(f"  2-5 contributors: {c_2_5:,}\n")
        f.write(f"  6-10 contributors: {c_6_10:,}\n")
        f.write(f"  11-50 contributors: {c_11_50:,}\n")
        f.write(f"  51+ contributors: {c_51_plus:,}\n\n")
        f.write(f"By Event:\n")
        f.write(f"  GSoC: {in_gsoc:,}\n")
        f.write(f"  24PR: {in_24pr:,}\n")
        f.write(f"  Hacktoberfest: {in_hf:,}\n")
        f.write(f"  LFX: {in_lfx:,}\n")
        f.write(f"  MLH: {in_mlh:,}\n")
    print(f"\n       Summary saved: {summary_path}")


def main():
    print("=" * 60)
    print("CONSOLIDATE ALL EVENT REPOS - PHASE A")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check files exist
    print("\nChecking data files...")
    for name, path in FILES.items():
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  ✓ {name}: {path} ({size_mb:.1f} MB)")
        else:
            print(f"  ✗ {name}: {path} NOT FOUND")
            sys.exit(1)
    
    # Load OSS4SG repos
    oss4sg_set = load_oss4sg_repos()
    
    # Load match files (repos identified as participating in events)
    match_repos = load_match_files()
    
    # Load and process each event
    print("\nLoading event contributor data files...")
    
    with open(FILES["24pr"], "r", encoding="utf-8") as f:
        pr24_data = json.load(f)
    pr24_repos = extract_24pr_repos(pr24_data)
    
    with open(FILES["gsoc"], "r", encoding="utf-8") as f:
        gsoc_data = json.load(f)
    gsoc_repos = extract_gsoc_repos(gsoc_data)
    
    with open(FILES["hacktoberfest"], "r", encoding="utf-8") as f:
        hf_data = json.load(f)
    hf_repos = extract_hacktoberfest_repos(hf_data)
    
    with open(FILES["lfx"], "r", encoding="utf-8") as f:
        lfx_data = json.load(f)
    lfx_repos = extract_lfx_repos(lfx_data)
    
    # Merge all repos
    consolidated = merge_all_repos(pr24_repos, gsoc_repos, hf_repos, lfx_repos, oss4sg_set, match_repos)
    
    # Save outputs
    save_outputs(consolidated)
    
    # Print summary
    print_summary(consolidated)
    
    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
