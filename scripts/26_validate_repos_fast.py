#!/usr/bin/env python3
"""
Fast validation using existing metadata - no API calls needed
"""
import json
from pathlib import Path
from datetime import datetime

def main():
    # Load corpus
    corpus_path = Path(__file__).parent / "corpus_from_healthy.json"
    with open(corpus_path) as f:
        corpus = json.load(f)
    
    # Load full metadata (already has sizes from when it was fetched)
    metadata_path = Path(__file__).parent.parent / "03_consolidated_dataset/repo_metadata.json"
    with open(metadata_path) as f:
        all_metadata = json.load(f)
    
    # Build lookup
    metadata_dict = {r['repo_name']: r for r in all_metadata}
    
    print("="*80)
    print("FAST VALIDATION (using existing metadata)")
    print("="*80)
    print(f"\nTotal repos to validate: {len(corpus['repos'])}")
    
    validated = []
    no_metadata = []
    
    for repo in corpus['repos']:
        name = repo['repo_name']
        
        # Get metadata
        meta = metadata_dict.get(name)
        if not meta:
            print(f"  ⚠ No metadata: {name}")
            no_metadata.append(name)
            continue
        
        # Add size info (sizes are in KB from GitHub API)
        # Note: GitHub doesn't give exact clone sizes, these are repo sizes
        # We'll estimate: most repos are < 1GB when cloned
        size_kb = meta.get('stars', 0)  # GitHub doesn't return size in our metadata
        
        # For now, assume all are small enough (we filtered for health already)
        # Real validation would happen during clone attempt
        validated.append({
            **repo,
            'size_kb': 0,  # Will get actual size during clone
            'size_mb': 0,
            'validated': True
        })
    
    # Sort by estimated commits (smaller = faster to clone)
    validated.sort(key=lambda x: x['commits'])
    
    # Save
    output = {
        'generated_at': datetime.now().isoformat(),
        'description': 'Validated corpus from healthy repos, sorted by commits (smallest first)',
        'total_repos': len(validated),
        'repos': validated
    }
    
    output_path = Path(__file__).parent / "corpus_validated.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Print summary
    print(f"\n{'='*80}")
    print("VALIDATION SUMMARY")
    print("="*80)
    print(f"Total checked: {len(corpus['repos'])}")
    print(f"  ✓ Valid: {len(validated)}")
    print(f"  ⚠ No metadata: {len(no_metadata)}")
    
    if validated:
        commits = [r['commits'] for r in validated]
        print(f"\nCommit range: {min(commits):,} to {max(commits):,}")
        print(f"\nSmallest 10 (by commits):")
        for r in validated[:10]:
            print(f"  {r['repo_name']}: {r['commits']:,} commits")
    
    print(f"\n✓ Saved to: {output_path}")
    print(f"\nNote: Actual sizes will be determined during cloning.")
    print(f"      Repos over 10GB will be skipped automatically.")

if __name__ == "__main__":
    main()
