#!/usr/bin/env python3
"""
Select event contributors from validated corpus only
"""
import json
from pathlib import Path
from datetime import datetime

def main():
    # Load validated corpus
    corpus_path = Path(__file__).parent / "corpus_validated.json"
    with open(corpus_path) as f:
        corpus = json.load(f)
    
    corpus_repos = {r['repo_name'] for r in corpus['repos']}
    
    # Load event data
    events_path = Path(__file__).parent.parent / "03_consolidated_dataset/all_event_repos_consolidated.json"
    with open(events_path) as f:
        events_data = json.load(f)
    
    print("="*80)
    print("SELECTING EVENT CONTRIBUTORS FROM VALIDATED CORPUS")
    print("="*80)
    print(f"\nValidated corpus: {len(corpus_repos)} repos")
    
    # For each event contributor, check if their repo is in corpus
    contributions = []
    
    for event_repo in events_data['repos']:
        repo_name = event_repo['repo_name']
        
        # Only process if in validated corpus
        if repo_name not in corpus_repos:
            continue
        
        # Get contributors for each event
        for event in ['gsoc', 'lfx', '24pr', 'hf']:
            event_key = f"{event}_contributors"
            contributors_list = event_repo.get(event_key, [])
            
            if not isinstance(contributors_list, list):
                continue
            
            # Apply thresholds
            if event == 'gsoc':
                min_contrib = 2
            elif event in ['24pr', 'hf']:
                min_contrib = 4
            else:  # lfx
                min_contrib = 1
            
            for contrib in contributors_list:
                if isinstance(contrib, dict):
                    username = contrib.get('username', '')
                    activity_count = contrib.get('contribution_count', 0) or contrib.get('pr_count', 0)
                    
                    if activity_count >= min_contrib and username:
                        contributions.append({
                            'github_username': username,
                            'repo': repo_name,
                            'event': event,
                            'contribution_id': f"{username}__{event}__{repo_name.replace('/', '__')}",
                            'activity_count': activity_count
                        })
    
    # Remove duplicates
    seen = set()
    unique_contributions = []
    for c in contributions:
        if c['contribution_id'] not in seen:
            seen.add(c['contribution_id'])
            unique_contributions.append(c)
    
    # Count by event
    by_event = {}
    for event in ['gsoc', 'lfx', '24pr', 'hf']:
        by_event[event] = len([c for c in unique_contributions if c['event'] == event])
    
    # Save
    output = {
        'generated_at': datetime.now().isoformat(),
        'description': 'Event contributions from validated healthy corpus only',
        'total_contributions': len(unique_contributions),
        'by_event': by_event,
        'thresholds': {
            'gsoc': '2+ contributions',
            'lfx': '1+ contribution',
            '24pr': '4+ PRs',
            'hf': '4+ PRs'
        },
        'contributions': unique_contributions
    }
    
    output_path = Path(__file__).parent.parent / "04_contributor_selection_and_organic_matching/outputs/contributions_from_validated_corpus.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Print summary
    print(f"\n{'='*80}")
    print("CONTRIBUTOR SELECTION")
    print("="*80)
    print(f"Total contributions: {len(unique_contributions)}")
    print(f"\nBy event:")
    for event, count in by_event.items():
        print(f"  {event}: {count}")
    
    print(f"\n✓ Saved to: {output_path}")

if __name__ == "__main__":
    main()
