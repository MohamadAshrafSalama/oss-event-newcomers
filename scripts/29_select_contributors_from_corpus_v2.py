#!/usr/bin/env python3
"""
Select event contributors from validated corpus using original event data
"""
import json
from pathlib import Path
from datetime import datetime

def load_event_contributors(event_name):
    """Load contributors from original event files"""
    base_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery"
    
    event_files = {
        'gsoc': base_path / "google_summer_of_code/gsoc_contributors.json",
        'lfx': base_path / "lfx/lfx_contributors.json",
        '24pr': base_path / "24_pull_requests/24pr_contributors.json",
        'hf': base_path / "hacktoberfest/hacktoberfest_contributors.json"
    }
    
    if event_name not in event_files:
        return []
    
    file_path = event_files[event_name]
    if not file_path.exists():
        print(f"  ⚠ File not found: {file_path}")
        return []
    
    with open(file_path) as f:
        data = json.load(f)
    
    # Get contributors list
    if isinstance(data, dict):
        return data.get('contributors', [])
    elif isinstance(data, list):
        return data
    return []

def main():
    # Load validated corpus
    corpus_path = Path(__file__).parent / "corpus_validated.json"
    with open(corpus_path) as f:
        corpus = json.load(f)
    
    corpus_repos = {r['repo_name'] for r in corpus['repos']}
    
    print("="*80)
    print("SELECTING EVENT CONTRIBUTORS FROM VALIDATED CORPUS")
    print("="*80)
    print(f"\nValidated corpus: {len(corpus_repos)} repos")
    
    # Load contributors from each event
    contributions = []
    
    for event in ['gsoc', 'lfx', '24pr', 'hf']:
        print(f"\nLoading {event} contributors...")
        event_contributors = load_event_contributors(event)
        print(f"  Total {event} contributors in data: {len(event_contributors)}")
        
        # Set threshold
        if event == 'gsoc':
            min_contrib = 2
        elif event in ['24pr', 'hf']:
            min_contrib = 4
        else:  # lfx
            min_contrib = 1
        
        # Filter by corpus and threshold
        for contrib in event_contributors:
            if not isinstance(contrib, dict):
                continue
            
            username = contrib.get('username', '') or contrib.get('github_username', '')
            repo = contrib.get('repo', '') or contrib.get('repo_name', '')
            
            # Check if in corpus
            if repo not in corpus_repos:
                continue
            
            # Check activity threshold
            activity_count = (contrib.get('contribution_count', 0) or 
                            contrib.get('pr_count', 0) or 
                            contrib.get('commit_count', 0) or 0)
            
            if activity_count >= min_contrib and username:
                contributions.append({
                    'github_username': username,
                    'repo': repo,
                    'event': event,
                    'contribution_id': f"{username}__{event}__{repo.replace('/', '__')}",
                    'activity_count': activity_count
                })
        
        print(f"  From corpus: {len([c for c in contributions if c['event'] == event])}")
    
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
        'description': 'Event contributions from validated healthy corpus (207 repos)',
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
    print("CONTRIBUTOR SELECTION SUMMARY")
    print("="*80)
    print(f"Total contributions: {len(unique_contributions)}")
    print(f"\nBy event:")
    for event, count in by_event.items():
        print(f"  {event}: {count}")
    
    print(f"\n✓ Saved to: {output_path}")

if __name__ == "__main__":
    main()
