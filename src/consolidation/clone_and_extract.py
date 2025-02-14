#!/usr/bin/env python3
"""
Clone and Extract Git Commit Data Pipeline

Features:
- Full clone of repositories (complete git history)
- Extract all commit data to CSV
- Progress bar with ETA
- Resume capability via progress.json
- Parallel: extract repo N while cloning repo N+1
- Error handling with detailed logging
- Sorted by size (smallest first)

Usage:
  python clone_and_extract.py [--test] [--consolidate-only]

  --test            Run on first repo only to verify pipeline
  --consolidate-only  Only merge existing CSVs into all_commits.csv
"""

import json
import os
import sys
import subprocess
import time
import csv
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import argparse

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_DIR = Path("/Volumes/T7/Event based OSS4SG")
REPOS_DIR = BASE_DIR / "repos"
EXTRACTED_DIR = BASE_DIR / "extracted"
LOGS_DIR = BASE_DIR / "logs"
REPOS_LIST_FILE = BASE_DIR / "repos_to_process.json"
PROGRESS_FILE = BASE_DIR / "progress.json"
ALL_COMMITS_FILE = BASE_DIR / "all_commits.csv"

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# CSV columns
CSV_COLUMNS = [
    'repo_name', 'commit_hash', 'author_name', 'author_email', 'author_date',
    'committer_name', 'committer_email', 'committer_date', 'parent_hashes',
    'tree_hash', 'subject', 'body', 'files_changed', 'insertions', 'deletions'
]

# ============================================================================
# PROGRESS TRACKING
# ============================================================================

class ProgressTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = self._load()
    
    def _load(self):
        if PROGRESS_FILE.exists():
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        return {
            'repos': {},
            'stats': {'total': 0, 'cloned': 0, 'extracted': 0, 'errors': 0},
            'last_updated': None
        }
    
    def save(self):
        with self.lock:
            self.data['last_updated'] = datetime.now(timezone.utc).isoformat()
            with open(PROGRESS_FILE, 'w') as f:
                json.dump(self.data, f, indent=2)
    
    def get_status(self, repo):
        with self.lock:
            return self.data['repos'].get(repo, {}).get('status', 'pending')
    
    def set_status(self, repo, status, **kwargs):
        with self.lock:
            if repo not in self.data['repos']:
                self.data['repos'][repo] = {}
            self.data['repos'][repo]['status'] = status
            for k, v in kwargs.items():
                self.data['repos'][repo][k] = v
            
            # Update stats
            statuses = [r.get('status') for r in self.data['repos'].values()]
            self.data['stats']['cloned'] = sum(1 for s in statuses if s in ['cloned', 'extracted', 'done'])
            self.data['stats']['extracted'] = sum(1 for s in statuses if s in ['extracted', 'done'])
            self.data['stats']['errors'] = sum(1 for s in statuses if s == 'error')
        self.save()
    
    def set_total(self, total):
        with self.lock:
            self.data['stats']['total'] = total
        self.save()


# ============================================================================
# LOGGING
# ============================================================================

def log_error(error_type, repo, error_msg, error_file):
    """Log error to JSON file."""
    error_path = LOGS_DIR / error_file
    errors = []
    if error_path.exists():
        with open(error_path, 'r') as f:
            errors = json.load(f)
    
    errors.append({
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'repo': repo,
        'error': str(error_msg)
    })
    
    with open(error_path, 'w') as f:
        json.dump(errors, f, indent=2)


def log_message(msg):
    """Log message to run_log.txt."""
    log_path = LOGS_DIR / "run_log.txt"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, 'a') as f:
        f.write(f"[{timestamp}] {msg}\n")


# ============================================================================
# CLONE FUNCTIONS
# ============================================================================

def clone_repo(repo_name, progress):
    """Clone a repository with retry logic."""
    repo_dir = REPOS_DIR / repo_name.replace('/', '__')
    
    # Skip if already cloned
    if repo_dir.exists() and (repo_dir / '.git').exists():
        return True, "already_cloned"
    
    # Remove partial clone if exists
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    
    url = f"https://github.com/{repo_name}.git"
    
    for attempt in range(MAX_RETRIES):
        try:
            result = subprocess.run(
                ['git', 'clone', '--quiet', url, str(repo_dir)],
                capture_output=True,
                text=True,
                timeout=1800  # 30 minute timeout for large repos
            )
            
            if result.returncode == 0:
                return True, "cloned"
            else:
                error_msg = result.stderr.strip()
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    log_error('clone', repo_name, error_msg, 'clone_errors.json')
                    return False, error_msg
                    
        except subprocess.TimeoutExpired:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                log_error('clone', repo_name, "Timeout after 30 minutes", 'clone_errors.json')
                return False, "timeout"
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                log_error('clone', repo_name, str(e), 'clone_errors.json')
                return False, str(e)
    
    return False, "max_retries_exceeded"


# ============================================================================
# EXTRACT FUNCTIONS
# ============================================================================

def extract_commits(repo_name):
    """Extract all commit data from a cloned repository."""
    repo_dir = REPOS_DIR / repo_name.replace('/', '__')
    output_file = EXTRACTED_DIR / f"{repo_name.replace('/', '__')}.csv"
    
    # Skip if already extracted
    if output_file.exists():
        # Count lines to get commit count
        with open(output_file, 'r', encoding='utf-8', errors='replace') as f:
            commit_count = sum(1 for _ in f) - 1  # minus header
        return True, commit_count, "already_extracted"
    
    if not repo_dir.exists() or not (repo_dir / '.git').exists():
        return False, 0, "repo_not_cloned"
    
    try:
        # Use a custom format with unique delimiters
        delimiter = "<<<FIELD_SEP>>>"
        commit_sep = "<<<COMMIT_SEP>>>"
        
        # Git log format: hash, author_name, author_email, author_date, committer_name, committer_email, committer_date, parents, tree, subject, body
        format_str = f"%H{delimiter}%an{delimiter}%ae{delimiter}%aI{delimiter}%cn{delimiter}%ce{delimiter}%cI{delimiter}%P{delimiter}%T{delimiter}%s{delimiter}%b{commit_sep}"
        
        # Run git log (use bytes to handle encoding issues)
        result = subprocess.run(
            ['git', 'log', '--all', f'--format={format_str}', '--numstat'],
            cwd=repo_dir,
            capture_output=True,
            timeout=3600  # 1 hour timeout
        )
        
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='replace').strip()
            log_error('extract', repo_name, stderr, 'extract_errors.json')
            return False, 0, stderr
        
        # Decode output with error handling for non-UTF-8 characters
        stdout = result.stdout.decode('utf-8', errors='replace')
        
        # Parse output
        commits = parse_git_log(stdout, repo_name, delimiter, commit_sep)
        
        # Write to CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(commits)
        
        return True, len(commits), "extracted"
        
    except subprocess.TimeoutExpired:
        log_error('extract', repo_name, "Timeout after 1 hour", 'extract_errors.json')
        return False, 0, "timeout"
    except Exception as e:
        log_error('extract', repo_name, str(e), 'extract_errors.json')
        return False, 0, str(e)


def parse_git_log(output, repo_name, delimiter, commit_sep):
    """Parse git log output into commit dictionaries."""
    commits = []
    
    # Split by commit separator
    raw_commits = output.split(commit_sep)
    
    for raw in raw_commits:
        raw = raw.strip()
        if not raw:
            continue
        
        # Split commit info from numstat
        lines = raw.split('\n')
        
        # Find the main commit line (contains our delimiter)
        commit_line = None
        numstat_lines = []
        
        for i, line in enumerate(lines):
            if delimiter in line:
                commit_line = line
                numstat_lines = lines[i+1:]
                break
        
        if not commit_line:
            continue
        
        # Parse commit fields
        parts = commit_line.split(delimiter)
        if len(parts) < 11:
            continue
        
        # Parse numstat for files changed, insertions, deletions
        files_changed = 0
        insertions = 0
        deletions = 0
        
        for ns_line in numstat_lines:
            ns_line = ns_line.strip()
            if not ns_line:
                continue
            # Format: insertions\tdeletions\tfilename
            ns_parts = ns_line.split('\t')
            if len(ns_parts) >= 2:
                files_changed += 1
                try:
                    if ns_parts[0] != '-':
                        insertions += int(ns_parts[0])
                    if ns_parts[1] != '-':
                        deletions += int(ns_parts[1])
                except ValueError:
                    pass
        
        # Clean body - remove any numstat that might have been included
        body = parts[10] if len(parts) > 10 else ''
        # Remove lines that look like numstat
        body_lines = []
        for bl in body.split('\n'):
            if not re.match(r'^\d+\t\d+\t', bl) and not re.match(r'^-\t-\t', bl):
                body_lines.append(bl)
        body = '\n'.join(body_lines).strip()
        
        commit = {
            'repo_name': repo_name,
            'commit_hash': parts[0],
            'author_name': parts[1],
            'author_email': parts[2],
            'author_date': parts[3],
            'committer_name': parts[4],
            'committer_email': parts[5],
            'committer_date': parts[6],
            'parent_hashes': parts[7],
            'tree_hash': parts[8],
            'subject': parts[9],
            'body': body,
            'files_changed': files_changed,
            'insertions': insertions,
            'deletions': deletions
        }
        commits.append(commit)
    
    return commits


# ============================================================================
# CONSOLIDATE
# ============================================================================

def consolidate_csvs():
    """Merge all per-repo CSVs into one all_commits.csv."""
    print("\nConsolidating all CSV files...")
    
    csv_files = list(EXTRACTED_DIR.glob("*.csv"))
    print(f"Found {len(csv_files)} CSV files to merge")
    
    if not csv_files:
        print("No CSV files found to consolidate")
        return
    
    total_commits = 0
    
    with open(ALL_COMMITS_FILE, 'w', newline='', encoding='utf-8') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        
        for i, csv_file in enumerate(csv_files):
            repo_name = csv_file.stem.replace('__', '/')
            print(f"\r  Processing {i+1}/{len(csv_files)}: {repo_name[:40]:<40}", end='')
            
            try:
                with open(csv_file, 'r', encoding='utf-8') as infile:
                    reader = csv.DictReader(infile)
                    for row in reader:
                        writer.writerow(row)
                        total_commits += 1
            except Exception as e:
                print(f"\n  Error reading {csv_file}: {e}")
    
    print(f"\n\nConsolidation complete!")
    print(f"  Total commits: {total_commits:,}")
    print(f"  Output file: {ALL_COMMITS_FILE}")
    print(f"  File size: {ALL_COMMITS_FILE.stat().st_size / (1024*1024):.2f} MB")


# ============================================================================
# PROGRESS DISPLAY
# ============================================================================

def format_time(seconds):
    """Format seconds as HH:MM:SS."""
    if seconds < 0:
        return "??:??"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    elif minutes > 0:
        return f"{minutes}m{secs:02d}s"
    else:
        return f"{secs}s"


def format_size(size_mb):
    """Format size in MB/GB."""
    if size_mb >= 1024:
        return f"{size_mb/1024:.2f} GB"
    return f"{size_mb:.2f} MB"


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def process_repo(repo_info, progress):
    """Process a single repo: clone and extract."""
    repo_name = repo_info['repo']
    size_mb = repo_info['size_mb']
    
    # Check current status
    status = progress.get_status(repo_name)
    
    result = {
        'repo': repo_name,
        'size_mb': size_mb,
        'clone_success': False,
        'extract_success': False,
        'commit_count': 0,
        'error': None
    }
    
    # Clone if needed
    if status in ['pending', 'error']:
        start_time = time.time()
        success, msg = clone_repo(repo_name, progress)
        clone_time = time.time() - start_time
        
        if success:
            progress.set_status(repo_name, 'cloned', clone_time=clone_time)
            result['clone_success'] = True
        else:
            progress.set_status(repo_name, 'error', error=msg)
            result['error'] = msg
            return result
    else:
        result['clone_success'] = True
    
    # Extract if needed
    status = progress.get_status(repo_name)
    if status in ['cloned']:
        start_time = time.time()
        success, commit_count, msg = extract_commits(repo_name)
        extract_time = time.time() - start_time
        
        if success:
            progress.set_status(repo_name, 'done', 
                              extract_time=extract_time, 
                              commit_count=commit_count)
            result['extract_success'] = True
            result['commit_count'] = commit_count
        else:
            progress.set_status(repo_name, 'error', error=msg)
            result['error'] = msg
    elif status == 'done':
        result['extract_success'] = True
        result['commit_count'] = progress.data['repos'].get(repo_name, {}).get('commit_count', 0)
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Clone and extract git commit data')
    parser.add_argument('--test', action='store_true', help='Test with first repo only')
    parser.add_argument('--consolidate-only', action='store_true', help='Only consolidate existing CSVs')
    args = parser.parse_args()
    
    # Consolidate only mode
    if args.consolidate_only:
        consolidate_csvs()
        return
    
    # Check if drive is mounted
    if not BASE_DIR.exists():
        print(f"ERROR: External drive not found at {BASE_DIR}")
        sys.exit(1)
    
    # Load repos list
    if not REPOS_LIST_FILE.exists():
        print(f"ERROR: Repos list not found at {REPOS_LIST_FILE}")
        sys.exit(1)
    
    with open(REPOS_LIST_FILE, 'r') as f:
        repos_data = json.load(f)
    
    repos = repos_data['repos']
    
    # Test mode - only first repo
    if args.test:
        repos = repos[:1]
        print(f"TEST MODE: Processing only first repo: {repos[0]['repo']}")
    
    print("=" * 75)
    print("CLONE AND EXTRACT GIT COMMIT DATA PIPELINE")
    print("=" * 75)
    print(f"\nTarget directory: {BASE_DIR}")
    print(f"Repos to process: {len(repos)}")
    print(f"Total size: {format_size(sum(r['size_mb'] for r in repos))}")
    print(f"\nSorted by size (smallest first)")
    print(f"Smallest: {repos[0]['repo']} ({format_size(repos[0]['size_mb'])})")
    print(f"Largest: {repos[-1]['repo']} ({format_size(repos[-1]['size_mb'])})")
    
    # Initialize progress tracker
    progress = ProgressTracker()
    progress.set_total(len(repos))
    
    # Check how many already done
    already_done = sum(1 for r in repos if progress.get_status(r['repo']) == 'done')
    already_cloned = sum(1 for r in repos if progress.get_status(r['repo']) in ['cloned', 'done'])
    
    print(f"\nResume status:")
    print(f"  Already cloned: {already_cloned}/{len(repos)}")
    print(f"  Already extracted: {already_done}/{len(repos)}")
    print(f"  Remaining: {len(repos) - already_done}")
    
    if already_done == len(repos):
        print("\nAll repos already processed!")
        print("Run with --consolidate-only to merge CSVs")
        return
    
    print("\n" + "-" * 75)
    print("Starting pipeline... (Ctrl+C to stop, will resume on next run)")
    print("-" * 75 + "\n")
    
    log_message(f"Started processing {len(repos)} repos")
    
    start_time = time.time()
    processed = 0
    errors = 0
    total_commits = 0
    
    try:
        for i, repo_info in enumerate(repos):
            repo_name = repo_info['repo']
            size_mb = repo_info['size_mb']
            
            # Skip if done
            if progress.get_status(repo_name) == 'done':
                processed += 1
                continue
            
            # Progress display
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 and processed > 0 else 0
            remaining = (len(repos) - i) / rate if rate > 0 else 0
            
            pct = (i + 1) / len(repos) * 100
            bar_width = 30
            filled = int(bar_width * (i + 1) / len(repos))
            bar = "█" * filled + "░" * (bar_width - filled)
            
            print(f"\r{bar} {i+1}/{len(repos)} ({pct:.1f}%) | "
                  f"ETA: {format_time(remaining)} | "
                  f"Err: {errors} | "
                  f"{repo_name[:35]:<35} ({format_size(size_mb)})", end='')
            sys.stdout.flush()
            
            # Process repo
            result = process_repo(repo_info, progress)
            
            if result['error']:
                errors += 1
                log_message(f"ERROR {repo_name}: {result['error']}")
            else:
                total_commits += result['commit_count']
                log_message(f"OK {repo_name}: {result['commit_count']} commits")
            
            processed += 1
            
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Progress saved.")
        log_message("Interrupted by user")
        return
    
    # Final summary
    elapsed = time.time() - start_time
    print(f"\n\n{'=' * 75}")
    print("PIPELINE COMPLETE!")
    print("=" * 75)
    print(f"Processed: {processed}/{len(repos)} repos")
    print(f"Errors: {errors}")
    print(f"Total commits extracted: {total_commits:,}")
    print(f"Time elapsed: {format_time(elapsed)}")
    
    log_message(f"Completed: {processed} repos, {errors} errors, {total_commits} commits")
    
    # Auto-consolidate if not in test mode
    if not args.test:
        consolidate_csvs()


if __name__ == "__main__":
    main()
