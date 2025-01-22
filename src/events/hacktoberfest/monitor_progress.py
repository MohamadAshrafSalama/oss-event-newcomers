#!/usr/bin/env python3
"""
Monitor Hacktoberfest Extraction Progress

Run this to see the current progress in real-time.
"""

import json
import time
import os
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
PROGRESS_FILE = SCRIPT_DIR / "hacktoberfest_contributors_progress.json"
TOTAL_REPOS = 1656

def format_time(seconds):
    """Format seconds as HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def print_progress_bar(current, total, prs_found, first_time, elapsed, token_idx=1):
    """Display visual progress bar"""
    pct = (current / total) * 100
    rate = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / rate if rate > 0 else 0
    
    # Progress bar (30 chars wide)
    bar_width = 30
    filled = int(bar_width * current / total)
    bar = '█' * filled + '░' * (bar_width - filled)
    
    # Format time
    elapsed_str = format_time(elapsed)
    remaining_str = format_time(remaining)
    
    # Print
    print(f"\r[{bar}] {pct:5.1f}% | "
          f"Repos: {current:,}/{total:,} | "
          f"PRs: {prs_found:,} | "
          f"First-time: {first_time:,} | "
          f"Elapsed: {elapsed_str} | "
          f"ETA: {remaining_str} | "
          f"Token: {token_idx}/4    ", 
          end="", flush=True)

def main():
    print("=" * 80)
    print("HACKTOBERFEST EXTRACTION PROGRESS MONITOR")
    print("=" * 80)
    print("Press Ctrl+C to stop\n")
    
    if not PROGRESS_FILE.exists():
        print("Progress file not found. The script may still be initializing...")
        print("(Progress saves every 10 repos)")
        return
    
    try:
        start_time = None
        
        while True:
            # Load progress
            try:
                with open(PROGRESS_FILE, 'r') as f:
                    progress = json.load(f)
            except json.JSONDecodeError:
                print("\nProgress file is being written...")
                time.sleep(5)
                continue
            
            checked_repos = progress.get("checked_repos", {})
            contributors = progress.get("contributors", {})
            metadata = progress.get("metadata", {})
            
            # Get counts
            total_checked = len(checked_repos)
            total_prs = sum(r.get("prs_found", 0) for r in checked_repos.values())
            first_time_contribs = sum(len(r.get("first_contributors", [])) for r in checked_repos.values())
            
            # Calculate elapsed time
            started_at = metadata.get("started_at")
            if started_at:
                try:
                    start_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                    elapsed = (datetime.now(start_dt.tzinfo) - start_dt).total_seconds()
                except:
                    elapsed = 0
            else:
                elapsed = 0
            
            # Clear screen and print progress
            os.system('clear' if os.name != 'nt' else 'cls')
            print("=" * 80)
            print("HACKTOBERFEST EXTRACTION PROGRESS MONITOR")
            print("=" * 80)
            print(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print()
            
            # Progress bar
            if total_checked > 0:
                print_progress_bar(total_checked, TOTAL_REPOS, total_prs, first_time_contribs, elapsed, 1)
                print("\n\n")
            else:
                print("No repos checked yet...")
                print("(Progress saves every 10 repos)\n")
            
            # Detailed stats
            print("DETAILED STATISTICS:")
            print(f"  Repos checked: {total_checked:,} / {TOTAL_REPOS:,} ({total_checked*100/TOTAL_REPOS:.1f}%)")
            print(f"  Total PRs found: {total_prs:,}")
            print(f"  First-time contributors: {first_time_contribs:,}")
            print(f"  Total unique contributors: {len(contributors):,}")
            
            if total_checked > 0:
                avg_prs_per_repo = total_prs / total_checked
                print(f"  Average PRs per repo: {avg_prs_per_repo:.1f}")
                
                rate = total_checked / elapsed if elapsed > 0 else 0
                print(f"  Processing rate: {rate:.2f} repos/hour")
            
            # Check if complete
            complete_repos = sum(1 for r in checked_repos.values() if r.get("status") == "complete")
            print(f"  Complete repos: {complete_repos:,}")
            
            print("\n" + "=" * 80)
            print("Refreshing every 5 seconds... (Press Ctrl+C to stop)")
            
            time.sleep(5)
    
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")
    
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()
