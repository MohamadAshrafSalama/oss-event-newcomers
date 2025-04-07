#!/usr/bin/env python3
"""
Select top 50 repos from each event FROM healthy pool only
"""
import json
from pathlib import Path
from datetime import datetime

def main():
    # Load healthy repos
    healthy_path = Path(__file__).parent / "healthy_repos_filtered.json"
    with open(healthy_path) as f:
        healthy_data = json.load(f)
    
    healthy_repos = {r['repo_name']: r for r in healthy_data['repos']}
    
    # Load event data
    events_path = Path(__file__).parent.parent / "03_consolidated_dataset/all_event_repos_consolidated.json"
    with open(events_path) as f:
        events_data = json.load(f)
    
    # Build event info for healthy repos only
    healthy_with_events = {}
    
    for event_repo in events_data['repos']:
        name = event_repo['repo_name']
        if name in healthy_repos:
            healthy_with_events[name] = {
                **healthy_repos[name],
                'gsoc': event_repo.get('gsoc_contributors', 0),
                'lfx': event_repo.get('lfx_contributors', 0),
                '24pr': event_repo.get('24pr_contributors', 0),
                'hf': event_repo.get('hf_contributors', 0)
            }
    
    print("="*80)
    print("SELECTING FROM HEALTHY POOL")
    print("="*80)
    print(f"\nHealthy repos: {len(healthy_repos)}")
    print(f"Healthy repos with events: {len(healthy_with_events)}")
    
    # Selection function
    def get_top_n(repos_dict, event_key, n, min_contributors=0):
        filtered = [(name, data) for name, data in repos_dict.items() 
                    if data.get(event_key, 0) >= min_contributors]
        sorted_repos = sorted(filtered, key=lambda x: x[1][event_key], reverse=True)
        return sorted_repos[:n]
    
    # Top 50 from each event
    top_hf = get_top_n(healthy_with_events, 'hf', 50, min_contributors=4)
    top_24pr = get_top_n(healthy_with_events, '24pr', 50, min_contributors=4)
    top_lfx = get_top_n(healthy_with_events, 'lfx', 50, min_contributors=1)
    top_gsoc = get_top_n(healthy_with_events, 'gsoc', 50, min_contributors=2)
    
    print(f"\n--- TOP SELECTIONS ---")
    print(f"Top 50 Hacktoberfest (4+ contributors): {len(top_hf)} repos")
    if top_hf:
        print(f"  Range: {top_hf[0][1]['hf']} to {top_hf[-1][1]['hf']} HF contributors")
    
    print(f"Top 50 24PR (4+ contributors): {len(top_24pr)} repos")
    if top_24pr:
        print(f"  Range: {top_24pr[0][1]['24pr']} to {top_24pr[-1][1]['24pr']} 24PR contributors")
    
    print(f"Top 50 LFX (1+ contributor): {len(top_lfx)} repos")
    if top_lfx:
        print(f"  Range: {top_lfx[0][1]['lfx']} to {top_lfx[-1][1]['lfx']} LFX contributors")
    
    print(f"Top 50 GSoC (2+ contributors): {len(top_gsoc)} repos")
    if top_gsoc:
        print(f"  Range: {top_gsoc[0][1]['gsoc']} to {top_gsoc[-1][1]['gsoc']} GSoC contributors")
    
    # OSS4SG healthy repos
    oss4sg = [(name, data) for name, data in healthy_with_events.items() 
              if data.get('is_oss4sg', False)]
    print(f"OSS4SG (healthy): {len(oss4sg)} repos")
    
    # Combine unique
    selected = {}
    for name, data in top_hf + top_24pr + top_lfx + top_gsoc + oss4sg:
        if name not in selected:
            selected[name] = data
    
    # Build final corpus
    corpus_repos = []
    for name, data in selected.items():
        corpus_repos.append({
            'repo_name': name,
            'contributors': data['contributors'],
            'commits': data['commits'],
            'age_years': data['age_years'],
            'days_since_push': data['days_since_push'],
            'stars': data['stars'],
            'forks': data['forks'],
            'language': data['language'],
            'is_oss4sg': data.get('is_oss4sg', False),
            'gsoc_contributors': data.get('gsoc', 0),
            'lfx_contributors': data.get('lfx', 0),
            '24pr_contributors': data.get('24pr', 0),
            'hf_contributors': data.get('hf', 0),
            'total_event_contributors': sum([
                data.get('gsoc', 0),
                data.get('lfx', 0),
                data.get('24pr', 0),
                data.get('hf', 0)
            ])
        })
    
    # Sort by name
    corpus_repos.sort(key=lambda x: x['repo_name'])
    
    # Save
    output = {
        'generated_at': datetime.now().isoformat(),
        'description': 'Selected from healthy repos only: Top 50 HF (4+), Top 50 24PR (4+), Top 50 LFX (1+), Top 50 GSoC (2+), All healthy OSS4SG',
        'total_repos': len(corpus_repos),
        'selection_criteria': {
            'health_filters': 'Applied: 10+ contributors, 500+ commits, 1+ year old, active within 1 year',
            'event_filters': 'HF 4+, 24PR 4+, LFX 1+, GSoC 2+, OSS4SG all'
        },
        'repos': corpus_repos
    }
    
    output_path = Path(__file__).parent / "corpus_from_healthy.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Summary
    print(f"\n{'='*80}")
    print("FINAL CORPUS FROM HEALTHY REPOS")
    print("="*80)
    print(f"Unique repos: {len(corpus_repos)}")
    
    # Calculate total event contributors
    total_gsoc = sum(r['gsoc_contributors'] for r in corpus_repos)
    total_lfx = sum(r['lfx_contributors'] for r in corpus_repos)
    total_24pr = sum(r['24pr_contributors'] for r in corpus_repos)
    total_hf = sum(r['hf_contributors'] for r in corpus_repos)
    
    print(f"\nTotal event contributors in corpus:")
    print(f"  GSoC: {total_gsoc}")
    print(f"  LFX: {total_lfx}")
    print(f"  24PR: {total_24pr}")
    print(f"  Hacktoberfest: {total_hf}")
    print(f"  TOTAL: {total_gsoc + total_lfx + total_24pr + total_hf}")
    
    print(f"\n✓ Saved to: {output_path}")

if __name__ == "__main__":
    main()
