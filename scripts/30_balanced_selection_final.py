#!/usr/bin/env python3
"""
Select balanced contributors from 426-repo corpus
Mentorship (GSoC + LFX) = Non-Mentorship (24PR + HF sample)
"""
import json
import random
from pathlib import Path
from datetime import datetime

def load_event_contributors(event_name):
    """Load contributors from original event files"""
    base_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery"
    
    event_files = {
        'gsoc': base_path / "google_summer_of_code/gsoc_contributors.json",
        'lfx': base_path / "lfx_mentorship/lfx_contributors.json",
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
    
    if isinstance(data, dict):
        return data.get('contributors', [])
    elif isinstance(data, list):
        return data
    return []

def expand_to_contributions(contributors, corpus_repos, event, min_activity, correction_map, event_name):
    """Expand contributor list to (person, repo) pairs"""
    contributions = []
    
    for contrib in contributors:
        if not isinstance(contrib, dict):
            continue
        
        username = contrib.get('username', '') or contrib.get('github_username', '')
        repos_contributed = contrib.get('repos_contributed', [])
        
        # Get activity count - GSoC and LFX use repo_count, others use PR/commit counts
        if event_name in ['gsoc', 'lfx']:
            activity_count = contrib.get('repo_count', 0) or len(repos_contributed)
        else:
            activity_count = (contrib.get('contribution_count', 0) or 
                             contrib.get('total_prs', 0) or 
                             contrib.get('pr_count', 0) or 
                             contrib.get('commit_count', 0) or 0)
        
        if not username or not repos_contributed:
            continue
        
        # Expand to individual repos
        for repo in repos_contributed:
            # Apply correction if needed
            if repo in correction_map:
                corrected = correction_map[repo]
                if corrected:
                    repo = corrected
                else:
                    continue  # Skip unfixable repos
            
            # Only include if in corpus
            if repo not in corpus_repos:
                continue
            
            contributions.append({
                'github_username': username,
                'repo': repo,
                'event': event,
                'contribution_id': f"{username}__{event}__{repo.replace('/', '__')}",
                'activity_count': activity_count
            })
    
    # Apply activity threshold
    contributions = [c for c in contributions if c['activity_count'] >= min_activity]
    
    return contributions

def main():
    # Load 426-repo corpus
    corpus_path = Path(__file__).parent / "final_corpus_435.json"
    with open(corpus_path) as f:
        corpus = json.load(f)
    
    corpus_repos = {r['repo_name'] for r in corpus['repos']}
    
    # Load correction map
    correction_path = Path(__file__).parent / "repo_correction_map.json"
    with open(correction_path) as f:
        correction_map = json.load(f)
    
    print("="*80)
    print("BALANCED CONTRIBUTOR SELECTION FROM 426-REPO CORPUS")
    print("="*80)
    print(f"\nCorpus: {len(corpus_repos)} repos")
    print(f"Correction map: {len(correction_map)} repo name fixes")
    
    # Load and expand each event
    all_contributions = {}
    
    for event, min_activity in [('gsoc', 2), ('lfx', 1), ('24pr', 4), ('hf', 4)]:
        print(f"\nProcessing {event}...")
        contributors = load_event_contributors(event)
        print(f"  Loaded: {len(contributors)} contributors")
        
        contributions = expand_to_contributions(contributors, corpus_repos, event, min_activity, correction_map, event)
        print(f"  Expanded: {len(contributions)} (person, repo) pairs from corpus")
        
        all_contributions[event] = contributions
    
    # Calculate balanced selection
    mentorship_total = len(all_contributions['gsoc']) + len(all_contributions['lfx'])
    non_mentorship_available = len(all_contributions['24pr'])
    hf_needed = mentorship_total - non_mentorship_available
    
    print(f"\n{'='*80}")
    print("BALANCING")
    print("="*80)
    print(f"Mentorship (GSoC + LFX): {mentorship_total}")
    print(f"  GSoC: {len(all_contributions['gsoc'])}")
    print(f"  LFX: {len(all_contributions['lfx'])}")
    
    print(f"\nNon-Mentorship target: {mentorship_total}")
    print(f"  24PR: {len(all_contributions['24pr'])}")
    print(f"  Hacktoberfest available: {len(all_contributions['hf'])}")
    print(f"  Hacktoberfest needed: {hf_needed}")
    
    # Sample Hacktoberfest
    if hf_needed > 0 and hf_needed < len(all_contributions['hf']):
        random.seed(42)  # Reproducible
        sampled_hf = random.sample(all_contributions['hf'], hf_needed)
        print(f"  Hacktoberfest sampled: {len(sampled_hf)}")
    else:
        sampled_hf = all_contributions['hf']
        print(f"  Hacktoberfest using all: {len(sampled_hf)}")
    
    # Combine all
    final_contributions = (
        all_contributions['gsoc'] +
        all_contributions['lfx'] +
        all_contributions['24pr'] +
        sampled_hf
    )
    
    # Remove duplicates
    seen = set()
    unique_contributions = []
    for c in final_contributions:
        if c['contribution_id'] not in seen:
            seen.add(c['contribution_id'])
            unique_contributions.append(c)
    
    # Count by event
    by_event = {
        'gsoc': len([c for c in unique_contributions if c['event'] == 'gsoc']),
        'lfx': len([c for c in unique_contributions if c['event'] == 'lfx']),
        '24pr': len([c for c in unique_contributions if c['event'] == '24pr']),
        'hacktoberfest': len([c for c in unique_contributions if c['event'] == 'hf'])
    }
    
    # Save
    output = {
        'generated_at': datetime.now().isoformat(),
        'description': 'Balanced contributions from 426-repo corpus: Mentorship (GSoC+LFX) = Non-Mentorship (24PR+HF)',
        'total_contributions': len(unique_contributions),
        'by_event': by_event,
        'thresholds': {
            'gsoc': '2+ contributions',
            'lfx': '1+ contribution',
            '24pr': '4+ PRs',
            'hf': '4+ PRs (sampled to balance)'
        },
        'contributions': unique_contributions
    }
    
    output_path = Path(__file__).parent.parent / "04_contributor_selection_and_organic_matching/outputs/contributions_balanced_final.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Print summary
    print(f"\n{'='*80}")
    print("FINAL BALANCED DATASET")
    print("="*80)
    print(f"Total contributions: {len(unique_contributions)}")
    print(f"\nBy event:")
    for event, count in by_event.items():
        print(f"  {event}: {count}")
    
    mentorship = by_event['gsoc'] + by_event['lfx']
    non_mentorship = by_event['24pr'] + by_event['hacktoberfest']
    print(f"\nMentorship total: {mentorship}")
    print(f"Non-mentorship total: {non_mentorship}")
    print(f"Difference: {abs(mentorship - non_mentorship)}")
    
    print(f"\n✓ Saved to: {output_path}")
    print(f"\nNext: Extract journeys, then match ~{len(unique_contributions)} organic contributors")
    print(f"Final dataset: ~{len(unique_contributions) * 2} total journeys")

if __name__ == "__main__":
    main()
