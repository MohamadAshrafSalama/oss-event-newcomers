#!/usr/bin/env python3
"""
Create contribution-level selection: (person, project) pairs
Total: 3,256 unique contributions
"""

import json
from pathlib import Path
from datetime import datetime

def main():
    print("="*80)
    print("CREATING CONTRIBUTION-LEVEL SELECTION")
    print("="*80)
    
    # Load current selection
    event_file = Path(__file__).parent.parent / "04_contributor_selection_and_organic_matching" / "outputs" / "event_contributors_final.json"
    with open(event_file) as f:
        data = json.load(f)
    
    # Load corpus for verification
    corpus_file = Path(__file__).parent / "final_corpus_435.json"
    with open(corpus_file) as f:
        corpus_data = json.load(f)
    corpus_repos = {r['repo_name'] for r in corpus_data['repos']}
    
    print(f"\nInput: {len(data['contributors'])} person-level entries")
    print(f"Corpus: {len(corpus_repos)} projects")
    
    # Create contribution-level entries
    contributions = []
    by_event = {'gsoc': 0, 'lfx': 0, '24pr': 0, 'hacktoberfest': 0}
    
    for c in data['contributors']:
        username = c['github_username']
        event = c.get('event', 'unknown')
        repos = c.get('corpus_repos', [])
        
        for repo in repos:
            # Verify repo is in corpus
            if repo not in corpus_repos:
                print(f"  WARNING: {repo} not in corpus, skipping")
                continue
            
            contribution = {
                'github_username': username,
                'repo': repo,
                'event': event,
                'contribution_id': f"{username}__{repo.replace('/', '__')}"
            }
            contributions.append(contribution)
            
            if event in by_event:
                by_event[event] += 1
    
    print(f"\nOutput: {len(contributions)} contribution-level entries")
    print(f"\nBy event:")
    for event, count in by_event.items():
        print(f"  {event}: {count}")
    
    # Verify all unique
    ids = [c['contribution_id'] for c in contributions]
    unique_ids = set(ids)
    if len(ids) != len(unique_ids):
        print(f"\n  WARNING: {len(ids) - len(unique_ids)} duplicate IDs!")
    else:
        print(f"\n  All {len(contributions)} IDs are unique")
    
    # Save
    output = {
        'generated_at': datetime.now().isoformat(),
        'description': 'Contribution-level selection: (person, project) pairs',
        'total_contributions': len(contributions),
        'by_event': by_event,
        'corpus_projects': len(corpus_repos),
        'contributions': contributions
    }
    
    output_path = Path(__file__).parent.parent / "04_contributor_selection_and_organic_matching" / "outputs" / "contributions_final.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nSaved to: {output_path}")
    
    # Verify corpus consistency
    print(f"\n{'='*80}")
    print("CONSISTENCY CHECK:")
    print(f"{'='*80}")
    
    contribution_repos = {c['repo'] for c in contributions}
    missing_from_corpus = contribution_repos - corpus_repos
    extra_in_corpus = corpus_repos - contribution_repos
    
    print(f"  Repos in contributions: {len(contribution_repos)}")
    print(f"  Repos in corpus: {len(corpus_repos)}")
    print(f"  Missing from corpus: {len(missing_from_corpus)}")
    print(f"  Extra in corpus (OK): {len(extra_in_corpus)}")
    
    if missing_from_corpus:
        print(f"\n  PROBLEM: These repos are NOT in corpus:")
        for r in list(missing_from_corpus)[:5]:
            print(f"    - {r}")
    else:
        print(f"\n  ALL contribution repos are in corpus")
    
    print(f"\n{'='*80}")
    print(f"FINAL: {len(contributions)} contributions ready for extraction")
    print(f"{'='*80}")
    
    return len(contributions)

if __name__ == "__main__":
    main()
