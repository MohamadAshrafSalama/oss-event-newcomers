#!/usr/bin/env python3
"""
Filter healthy repos from metadata based on strict health criteria
"""
import json
from pathlib import Path
from datetime import datetime, timezone

def main():
    # Load metadata
    metadata_path = Path(__file__).parent.parent / "03_consolidated_dataset/repo_metadata.json"
    with open(metadata_path) as f:
        metadata = json.load(f)
    
    print("="*80)
    print("FILTERING HEALTHY REPOS")
    print("="*80)
    print(f"\nTotal repos with metadata: {len(metadata)}")
    
    # Apply health criteria
    healthy = []
    unhealthy_reasons = {
        'not_found': 0,
        'contributors': 0,
        'commits': 0,
        'age': 0,
        'activity': 0
    }
    
    now = datetime.now(timezone.utc)
    
    for repo in metadata:
        name = repo.get('repo_name', '')
        status = repo.get('status', '')
        
        # Check if repo exists
        if status != 'ok':
            unhealthy_reasons['not_found'] += 1
            continue
        
        # Get metrics
        contrib_count = repo.get('contributor_count', 0) or 0
        commit_count = repo.get('commit_count', 0) or 0
        created_at = repo.get('created_at', '')
        pushed_at = repo.get('pushed_at', '')
        
        # Parse dates
        try:
            created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            age_years = (now - created).days / 365
        except:
            age_years = 0
        
        try:
            pushed = datetime.fromisoformat(pushed_at.replace('Z', '+00:00'))
            days_since_push = (now - pushed).days
        except:
            days_since_push = 9999
        
        # Apply health criteria
        fails = []
        if contrib_count < 10:
            fails.append('contributors')
            unhealthy_reasons['contributors'] += 1
        if commit_count < 500:
            fails.append('commits')
            unhealthy_reasons['commits'] += 1
        if age_years < 1:
            fails.append('age')
            unhealthy_reasons['age'] += 1
        if days_since_push > 365:
            fails.append('activity')
            unhealthy_reasons['activity'] += 1
        
        # Only add if passes ALL criteria
        if not fails:
            healthy.append({
                'repo_name': name,
                'contributors': contrib_count,
                'commits': commit_count,
                'age_years': round(age_years, 1),
                'days_since_push': days_since_push,
                'created_at': created_at,
                'pushed_at': pushed_at,
                'stars': repo.get('stars', 0),
                'forks': repo.get('forks', 0),
                'language': repo.get('language', ''),
                'is_oss4sg': repo.get('is_oss4sg', False)
            })
    
    # Save healthy repos
    output = {
        'generated_at': datetime.now().isoformat(),
        'description': 'Repos passing ALL health criteria: 10+ contributors, 500+ commits, 1+ year old, active within 1 year',
        'total_healthy': len(healthy),
        'repos': healthy
    }
    
    output_path = Path(__file__).parent / "healthy_repos_filtered.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Print summary
    print(f"\nHealthy repos (pass ALL criteria): {len(healthy)}")
    print(f"\nUnhealthy breakdown (may overlap):")
    for reason, count in unhealthy_reasons.items():
        print(f"  {reason}: {count}")
    
    print(f"\nHealthy repo statistics:")
    if healthy:
        contrib_counts = [r['contributors'] for r in healthy]
        commit_counts = [r['commits'] for r in healthy]
        print(f"  Contributors: {min(contrib_counts)}-{max(contrib_counts)} (avg: {sum(contrib_counts)//len(contrib_counts)})")
        print(f"  Commits: {min(commit_counts)}-{max(commit_counts)} (avg: {sum(commit_counts)//len(commit_counts)})")
    
    print(f"\n✓ Saved to: {output_path}")

if __name__ == "__main__":
    main()
