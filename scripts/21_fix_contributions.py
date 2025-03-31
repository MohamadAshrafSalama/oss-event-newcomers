#!/usr/bin/env python3
"""
Remove contributions with unfixable repos and apply corrections
"""
import json
from pathlib import Path
from datetime import datetime

def main():
    # Load data
    contrib_path = Path(__file__).parent.parent / "04_contributor_selection_and_organic_matching/outputs/contributions_final.json"
    with open(contrib_path) as f:
        data = json.load(f)
    
    # Load analysis
    with open(Path(__file__).parent / "invalid_repos_analysis.json") as f:
        analysis = json.load(f)
    
    # Load correction map
    with open(Path(__file__).parent / "repo_correction_map.json") as f:
        correction_map = json.load(f)
    
    print("="*80)
    print("FIXING CONTRIBUTIONS")
    print("="*80)
    
    # GitHub-internal repos to remove
    github_internal = set(analysis['github_internal'])
    
    # Apply corrections and removals
    original_count = len(data['contributions'])
    fixed_contributions = []
    removed_internal = 0
    removed_unfixable = 0
    fixed_truncated = 0
    
    by_event = {'gsoc': 0, 'lfx': 0, '24pr': 0, 'hacktoberfest': 0}
    
    for contrib in data['contributions']:
        repo = contrib['repo']
        event = contrib['event']
        
        # Remove GitHub-internal
        if repo in github_internal:
            removed_internal += 1
            continue
        
        # Fix truncated
        if repo in correction_map:
            corrected = correction_map[repo]
            if corrected:
                contrib['repo'] = corrected
                fixed_truncated += 1
            else:
                # Could not fix
                removed_unfixable += 1
                continue
        
        # Update contribution_id with corrected repo
        username = contrib['github_username']
        event = contrib['event']
        repo_normalized = contrib['repo'].replace('/', '__')
        contrib['contribution_id'] = f"{username}__{event}__{repo_normalized}"
        
        fixed_contributions.append(contrib)
        if event in by_event:
            by_event[event] += 1
    
    # Update data
    data['contributions'] = fixed_contributions
    data['total_contributions'] = len(fixed_contributions)
    data['by_event'] = by_event
    data['generated_at'] = datetime.now().isoformat()
    data['description'] = 'Contribution-level: (person, event, project) - corrected repo names'
    
    # Save
    with open(contrib_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\nOriginal contributions: {original_count}")
    print(f"  Removed (GitHub-internal): {removed_internal}")
    print(f"  Removed (unfixable truncated): {removed_unfixable}")
    print(f"  Fixed (truncated names): {fixed_truncated}")
    print(f"  Final contributions: {len(fixed_contributions)}")
    
    print(f"\nBy event:")
    for event, count in by_event.items():
        print(f"  {event}: {count}")
    
    print(f"\n✓ Updated: {contrib_path}")

if __name__ == "__main__":
    main()
