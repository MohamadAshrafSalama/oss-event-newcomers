#!/usr/bin/env python3
"""
Validation Script: Identify Missing Contributors
Compares event_contributors_final.json (4001) vs progress.json (3979) to find missing extractions
"""

import json
import os
from pathlib import Path

def load_event_contributors():
    """Load the list of selected event contributors"""
    path = Path("../04_contributor_selection_and_organic_matching/outputs/event_contributors_final.json")
    with open(path, 'r') as f:
        data = json.load(f)
    return [c['github_username'] for c in data['contributors']]

def load_extracted_contributors():
    """Load the list of successfully extracted contributors"""
    path = Path("progress/progress.json")
    with open(path, 'r') as f:
        data = json.load(f)
    return data.get('completed', [])

def check_csv_files():
    """Check which contributors have CSV files"""
    output_dir = Path("outputs/contributors")
    csv_files = list(output_dir.glob("*_journey.csv"))
    return [f.stem.replace('_journey', '') for f in csv_files]

def main():
    print("=" * 80)
    print("MISSING CONTRIBUTOR VALIDATION REPORT")
    print("=" * 80)
    print()
    
    # Load data
    print("Loading event contributors...")
    event_contributors = load_event_contributors()
    print(f"  Total selected: {len(event_contributors)}")
    
    print("\nLoading extraction progress...")
    extracted = load_extracted_contributors()
    print(f"  Total extracted: {len(extracted)}")
    
    print("\nChecking CSV files...")
    csv_contributors = check_csv_files()
    print(f"  Total CSV files: {len(csv_contributors)}")
    
    # Find missing
    print("\n" + "-" * 80)
    print("ANALYSIS")
    print("-" * 80)
    
    event_set = set(event_contributors)
    extracted_set = set(extracted)
    csv_set = set(csv_contributors)
    
    # Missing from progress.json
    missing_from_progress = event_set - extracted_set
    print(f"\nMissing from progress.json: {len(missing_from_progress)}")
    if missing_from_progress:
        print("\nContributors not in progress.json:")
        for username in sorted(missing_from_progress)[:20]:
            print(f"  - {username}")
        if len(missing_from_progress) > 20:
            print(f"  ... and {len(missing_from_progress) - 20} more")
    
    # Missing CSV files
    missing_csv = event_set - csv_set
    print(f"\nMissing CSV files: {len(missing_csv)}")
    if missing_csv:
        print("\nContributors without CSV files:")
        for username in sorted(missing_csv)[:20]:
            print(f"  - {username}")
        if len(missing_csv) > 20:
            print(f"  ... and {len(missing_csv) - 20} more")
    
    # In progress but no CSV
    in_progress_no_csv = extracted_set - csv_set
    print(f"\nIn progress.json but no CSV: {len(in_progress_no_csv)}")
    if in_progress_no_csv:
        print("\nContributors in progress but missing CSV:")
        for username in sorted(in_progress_no_csv)[:20]:
            print(f"  - {username}")
    
    # CSV but not in progress
    csv_not_progress = csv_set - extracted_set
    print(f"\nHas CSV but not in progress.json: {len(csv_not_progress)}")
    if csv_not_progress:
        print("\nContributors with CSV but not in progress:")
        for username in sorted(csv_not_progress)[:20]:
            print(f"  - {username}")
    
    # Check for duplicates
    event_dupes = len(event_contributors) - len(event_set)
    print(f"\nDuplicates in event list: {event_dupes}")
    
    extracted_dupes = len(extracted) - len(extracted_set)
    print(f"Duplicates in progress: {extracted_dupes}")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Expected contributors: {len(event_contributors)}")
    print(f"Extracted (progress): {len(extracted)}")
    print(f"CSV files present: {len(csv_contributors)}")
    print(f"Missing: {len(missing_from_progress)}")
    print()
    
    # Save missing list
    if missing_from_progress or missing_csv:
        report_path = Path("reports/missing_contributors.json")
        report_path.parent.mkdir(exist_ok=True)
        
        report = {
            "generated_at": "2026-02-01",
            "total_expected": len(event_contributors),
            "total_extracted": len(extracted),
            "total_csv_files": len(csv_contributors),
            "missing_from_progress": sorted(list(missing_from_progress)),
            "missing_csv_files": sorted(list(missing_csv)),
            "in_progress_no_csv": sorted(list(in_progress_no_csv)),
            "csv_not_progress": sorted(list(csv_not_progress))
        }
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"Report saved to: {report_path}")
    
    print()

if __name__ == "__main__":
    main()
