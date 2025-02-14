#!/usr/bin/env python3
"""
Verify Commit Mining CSVs
Checks all 424 CSVs on T7 drive for valid headers and non-empty data
"""

import csv
import json
from pathlib import Path
import sys

def load_progress():
    """Load progress from T7 drive"""
    progress_path = Path("/Volumes/T7/Event based OSS4SG/progress.json")
    with open(progress_path, 'r') as f:
        return json.load(f)

def verify_csv(csv_path):
    """Verify a single CSV file"""
    issues = []
    
    # Check if file exists
    if not csv_path.exists():
        return ["File does not exist"]
    
    # Check file size
    size = csv_path.stat().st_size
    if size == 0:
        return ["Zero-byte file"]
    
    # Check CSV structure
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Check header
            expected_fields = ['repo_name', 'commit_hash', 'author_name', 'author_email', 
                             'author_date', 'committer_name', 'committer_email', 
                             'committer_date', 'subject']
            
            if reader.fieldnames is None:
                return ["No header found"]
            
            missing_fields = set(expected_fields) - set(reader.fieldnames)
            if missing_fields:
                issues.append(f"Missing fields: {missing_fields}")
            
            # Try to read first row
            try:
                first_row = next(reader, None)
                if first_row is None:
                    issues.append("Header-only file (no data rows)")
            except Exception as e:
                issues.append(f"Error reading first row: {e}")
                
    except Exception as e:
        issues.append(f"CSV parsing error: {e}")
    
    return issues

def main():
    print("=" * 80)
    print("COMMIT MINING CSV VERIFICATION")
    print("=" * 80)
    print()
    
    # Load progress
    print("Loading progress from T7 drive...")
    try:
        progress = load_progress()
    except Exception as e:
        print(f"ERROR: Cannot load progress.json: {e}")
        sys.exit(1)
    
    repos = progress.get('repos', {})
    print(f"  Total repos: {len(repos)}")
    
    # Count by status
    status_counts = {}
    for repo_data in repos.values():
        status = repo_data.get('status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print("\nStatus breakdown:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")
    
    # Verify CSVs
    print("\n" + "-" * 80)
    print("VERIFYING CSV FILES")
    print("-" * 80)
    
    extracted_dir = Path("/Volumes/T7/Event based OSS4SG/extracted")
    
    verified_count = 0
    issues_found = {}
    
    for repo_name, repo_data in repos.items():
        status = repo_data.get('status')
        
        if status == 'done':
            # Check CSV file
            csv_filename = repo_name.replace('/', '__') + '.csv'
            csv_path = extracted_dir / csv_filename
            
            issues = verify_csv(csv_path)
            
            if issues:
                issues_found[repo_name] = issues
                print(f"✗ {repo_name}")
                for issue in issues:
                    print(f"    - {issue}")
            else:
                verified_count += 1
                if verified_count <= 5:
                    print(f"✓ {repo_name}")
    
    if verified_count > 5:
        print(f"✓ ... and {verified_count - 5} more verified successfully")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Repos with status 'done': {status_counts.get('done', 0)}")
    print(f"CSVs verified OK: {verified_count}")
    print(f"CSVs with issues: {len(issues_found)}")
    print()
    
    if issues_found:
        print("ISSUES FOUND:")
        for repo, issues in list(issues_found.items())[:10]:
            print(f"\n{repo}:")
            for issue in issues:
                print(f"  - {issue}")
        
        if len(issues_found) > 10:
            print(f"\n... and {len(issues_found) - 10} more repos with issues")
    
    # Save report
    report = {
        "generated_at": "2026-02-01",
        "total_repos": len(repos),
        "status_counts": status_counts,
        "verified_ok": verified_count,
        "issues_found": {k: v for k, v in issues_found.items()}
    }
    
    report_path = Path("reports/csv_verification.json")
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\nReport saved to: {report_path}")
    print()
    
    # Return exit code
    if issues_found:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
