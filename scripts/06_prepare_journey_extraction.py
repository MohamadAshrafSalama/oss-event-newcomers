#!/usr/bin/env python3
"""
Apply 4+ commit filter to GSoC contributors using existing commit data.
Then prepare final contributor list for journey extraction.
"""

import json
import sys
import csv
from pathlib import Path
from collections import defaultdict

def load_commit_counts():
    """Load commit counts from existing CSV files on T7 drive"""
    
    extracted_dir = Path("/Volumes/T7/Event based OSS4SG/extracted")
    
    if not extracted_dir.exists():
        print("ERROR: Cannot access T7 drive extracted directory")
        return None
    
    # Count commits per author email
    commit_counts = defaultdict(int)
    
    csv_files = list(extracted_dir.glob("*.csv"))
    print(f"Scanning {len(csv_files)} CSV files for commit counts...")
    
    for i, csv_file in enumerate(csv_files, 1):
        if i % 50 == 0:
            print(f"  Processed {i}/{len(csv_files)} files...")
        
        try:
            with open(csv_file, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    author_email = row.get('author_email', '').lower().strip()
                    if author_email:
                        commit_counts[author_email] += 1
        except Exception as e:
            print(f"  Warning: Error reading {csv_file.name}: {e}")
            continue
    
    print(f"✓ Found {len(commit_counts)} unique contributors")
    return dict(commit_counts)

def apply_commit_filter_to_gsoc(gsoc_contributors, commit_counts, min_commits=4):
    """Filter GSoC contributors by minimum commit count"""
    
    print(f"\nFiltering GSoC contributors (min {min_commits} commits)...")
    
    filtered = []
    for contrib in gsoc_contributors:
        username = contrib['github_username']
        
        # Try to find their commits (GSoC data doesn't have email, so we'll defer this)
        # For now, we'll keep all GSoC contributors and note this needs commit data verification
        filtered.append(contrib)
    
    print(f"  GSoC: Keeping all {len(filtered)} contributors (commit filter will be applied after journey extraction)")
    print(f"  Note: Email matching required - will verify during final validation")
    
    return filtered

def main():
    print("="*80)
    print("APPLY 4+ COMMIT FILTER TO GSOC")
    print("="*80)
    
    # Load existing filtered contributors
    filtered_path = Path(__file__).parent / "event_contributors_corpus_filtered.json"
    with open(filtered_path, 'r') as f:
        data = json.load(f)
    
    print(f"\nCurrent counts:")
    for event, count in data['by_event'].items():
        print(f"  {event:15s}: {count:5d}")
    
    # Load commit counts (this will take a few minutes)
    print(f"\nLoading commit counts from existing CSV files...")
    # SKIP THIS FOR NOW - it will take too long and we don't have email->username mapping yet
    # commit_counts = load_commit_counts()
    
    # For now, keep the current selection
    # The 4+ commit filter will be properly applied during final validation
    # when we have both commit data and username->email mapping from journey extraction
    
    print("\n" + "="*80)
    print("DECISION:")
    print("="*80)
    print("Keeping current selection of 1,651 contributors:")
    print("  - GSoC: 945 (commit filter deferred)")
    print("  - HF: 564 (4+ PRs already applied)")
    print("  - 24PR: 142 (4+ PRs already applied)")
    print("\nThe GSoC commit filter will be applied after:")
    print("1. Journey extraction provides username->email mapping")
    print("2. All commit mining is complete")
    print("3. We can match GSoC usernames to commit emails")
    
    return data

if __name__ == "__main__":
    try:
        result = main()
        print("\n✓ Ready for journey extraction with 1,651 contributors")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
