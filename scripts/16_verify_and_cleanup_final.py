#!/usr/bin/env python3
"""
Final verification and cleanup:
1. Verify all 2,068 entries are from 435 corpus
2. Keep only relevant journey files
3. Verify config uses 10 tokens
4. Ready to extract
"""

import json
from pathlib import Path
from datetime import datetime

def main():
    print("="*80)
    print("FINAL VERIFICATION AND CLEANUP")
    print("="*80)
    
    # Load selection
    event_file = Path(__file__).parent.parent / "04_contributor_selection_and_organic_matching" / "outputs" / "event_contributors_final.json"
    with open(event_file) as f:
        event_data = json.load(f)
    
    # Load corpus
    corpus_file = Path(__file__).parent / "final_corpus_435.json"
    with open(corpus_file) as f:
        corpus_data = json.load(f)
    corpus_repos = {r['repo_name'] for r in corpus_data['repos']}
    
    print(f"\n1. SELECTION VERIFICATION:")
    print(f"   Total entries: {len(event_data['contributors'])}")
    print(f"   Stated total: {event_data['total_contributors']}")
    print(f"   By event: {event_data['by_event']}")
    
    # Create unique ID for each entry (username + event + primary_repo)
    entry_ids = []
    for c in event_data['contributors']:
        username = c['github_username']
        event = c.get('event', 'unknown')
        # Use first corpus repo as identifier
        repos = c.get('corpus_repos', [])
        primary_repo = repos[0] if repos else 'unknown'
        entry_id = f"{username}|{event}|{primary_repo}"
        entry_ids.append(entry_id)
    
    print(f"   Unique IDs: {len(set(entry_ids))}")
    
    # Verify all in corpus
    not_in_corpus = 0
    for c in event_data['contributors']:
        contrib_repos = set(c.get('corpus_repos', []))
        if not (contrib_repos & corpus_repos):
            not_in_corpus += 1
            if not_in_corpus <= 5:
                print(f"   ⚠ {c['github_username']}: {contrib_repos}")
    
    print(f"   Not in corpus: {not_in_corpus}")
    print(f"   ✓ ALL IN CORPUS: {'YES' if not_in_corpus == 0 else 'NO'}")
    
    # Check config
    print(f"\n2. CONFIG VERIFICATION:")
    config_file = Path(__file__).parent.parent / "05_contributor_journey_extraction" / "config.json"
    with open(config_file) as f:
        config = json.load(f)
    
    print(f"   GitHub tokens: {len(config['github_tokens'])}")
    print(f"   Max workers: {config['max_workers']}")
    print(f"   ✓ OPTIMAL: {'YES' if len(config['github_tokens']) >= 10 else 'NO'}")
    
    # Check progress
    print(f"\n3. PROGRESS CHECK:")
    progress_file = Path(__file__).parent.parent / "05_contributor_journey_extraction" / "progress" / "progress.json"
    with open(progress_file) as f:
        progress = json.load(f)
    
    completed_usernames = set(progress.get('completed', []))
    
    # Check overlap with our entries
    our_usernames = {c['github_username'] for c in event_data['contributors']}
    
    valid_completed = completed_usernames & our_usernames
    invalid_completed = completed_usernames - our_usernames
    
    print(f"   Old completed: {len(completed_usernames)}")
    print(f"   Valid (keep): {len(valid_completed)}")
    print(f"   Invalid (delete): {len(invalid_completed)}")
    
    # Clean up journey files
    print(f"\n4. CLEANING JOURNEY FILES:")
    journey_dir = Path(__file__).parent.parent / "05_contributor_journey_extraction" / "contributors"
    
    deleted = 0
    kept = 0
    if journey_dir.exists():
        for f in journey_dir.glob("*.json"):
            username = f.stem
            if username not in our_usernames:
                f.unlink()
                deleted += 1
                if deleted % 500 == 0:
                    print(f"   Deleted {deleted}...")
            else:
                kept += 1
    
    print(f"   Kept: {kept}")
    print(f"   Deleted: {deleted}")
    
    # Update progress to only valid
    print(f"\n5. UPDATING PROGRESS:")
    new_progress = {
        'started_at': progress.get('started_at', datetime.now().isoformat()),
        'completed': sorted(list(valid_completed)),
        'errors': [],
        'total_processed': len(valid_completed),
        'last_checkpoint': datetime.now().isoformat(),
        'last_updated': datetime.now().isoformat()
    }
    
    # Backup
    backup_path = progress_file.with_suffix('.json.backup')
    with open(backup_path, 'w') as f:
        json.dump(progress, f)
    
    with open(progress_file, 'w') as f:
        json.dump(new_progress, f, indent=2)
    
    print(f"   Updated (backed up to {backup_path.name})")
    
    # Final summary
    print(f"\n{'='*80}")
    print("FINAL STATUS:")
    print(f"{'='*80}")
    print(f"  Total entries to extract: {len(event_data['contributors'])}")
    print(f"  Already completed: {len(valid_completed)}")
    print(f"  Remaining to extract: {len(event_data['contributors']) - len(valid_completed)}")
    print(f"  Corpus projects: {len(corpus_repos)}")
    print(f"  GitHub tokens: {len(config['github_tokens'])}")
    print(f"  Workers: {config['max_workers']}")
    
    print(f"\n✓ READY TO EXTRACT")
    
    return {
        'total': len(event_data['contributors']),
        'completed': len(valid_completed),
        'remaining': len(event_data['contributors']) - len(valid_completed),
        'consistent': not_in_corpus == 0
    }

if __name__ == "__main__":
    result = main()
    if result['consistent']:
        print("\n✓ All checks passed - ready to start extraction")
    else:
        print("\n⚠ INCONSISTENCY DETECTED - please review")
