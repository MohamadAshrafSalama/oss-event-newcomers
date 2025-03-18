#!/usr/bin/env python3
"""
Analyze top 50 projects from each event (24PR, Hacktoberfest, LFX)
to create a balanced corpus.
"""

import json
from pathlib import Path
from collections import defaultdict

def analyze_top_50_event(event_name, event_key):
    """Analyze top 50 projects for a specific event"""
    
    print(f"\n{'='*80}")
    print(f"TOP 50 {event_name.upper()} PROJECTS")
    print(f"{'='*80}")
    
    # Load all event repos
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    
    # Filter repos with this event's contributors
    event_repos = [r for r in repos if r.get(event_key, 0) > 0]
    event_repos.sort(key=lambda x: x[event_key], reverse=True)
    
    top_50 = event_repos[:50]
    
    print(f"\nTotal repos with {event_name}: {len(event_repos)}")
    print(f"\nTop 50 {event_name} projects:")
    print(f"{'Rank':<6} {event_name[:5]:<6} {'GSoC':<6} {'Repo':<50}")
    print("-"*80)
    
    total_event = 0
    total_gsoc = 0
    
    for i, repo in enumerate(top_50, 1):
        total_event += repo[event_key]
        total_gsoc += repo.get('gsoc_contributors', 0)
        if i <= 20:  # Show first 20
            print(f"{i:<6} {repo[event_key]:<6} {repo.get('gsoc_contributors', 0):<6} {repo['repo_name'][:48]:<50}")
    
    if len(top_50) > 20:
        print(f"  ... and {len(top_50) - 20} more")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY - Top 50 {event_name} Projects:")
    print(f"  {event_name} contributors: {total_event}")
    print(f"  GSoC contributors: {total_gsoc}")
    print(f"  Total event contributors: {total_event + total_gsoc}")
    
    return top_50, total_event

def analyze_contributors_from_top_50(event_name, event_file, top_50_repos, activity_key='total_prs'):
    """Analyze actual contributors from top 50 projects"""
    
    print(f"\n{'='*80}")
    print(f"{event_name.upper()} CONTRIBUTORS FROM TOP 50 PROJECTS")
    print(f"{'='*80}")
    
    # Load contributors
    with open(event_file, 'r') as f:
        data = json.load(f)
    
    contributors = data['contributors']
    top_50_names = {r['repo_name'] for r in top_50_repos}
    
    # Filter by top 50
    filtered = []
    activity_dist = {1: 0, 2: 0, 3: 0, '4+': 0}
    
    for c in contributors:
        contrib_repos = set(c.get('repos_contributed', []))
        if contrib_repos & top_50_names:
            activity = c.get(activity_key, 0)
            filtered.append(c)
            
            if activity == 1:
                activity_dist[1] += 1
            elif activity == 2:
                activity_dist[2] += 1
            elif activity == 3:
                activity_dist[3] += 1
            elif activity >= 4:
                activity_dist['4+'] += 1
    
    print(f"\nTotal {event_name} contributors: {len(contributors)}")
    print(f"Contributors from top 50 projects: {len(filtered)}")
    print(f"\nActivity distribution:")
    print(f"  1 activity:   {activity_dist[1]:5d}")
    print(f"  2 activities: {activity_dist[2]:5d}")
    print(f"  3 activities: {activity_dist[3]:5d}")
    print(f"  4+ activities: {activity_dist['4+']:5d}")
    print(f"\nWith 4+ filter: {activity_dist['4+']}")
    print(f"Without filter: {len(filtered)}")
    
    return len(filtered), activity_dist['4+']

def main():
    print("="*80)
    print("BALANCED CORPUS DESIGN - TOP 50 FROM EACH EVENT")
    print("="*80)
    
    # Analyze top 50 from each event
    print("\n" + "="*80)
    print("STEP 1: ANALYZE TOP 50 PROJECTS FROM EACH EVENT")
    print("="*80)
    
    # Hacktoberfest
    hf_repos, hf_raw = analyze_top_50_event("Hacktoberfest", "hf_contributors")
    
    # 24PR
    pr24_repos, pr24_raw = analyze_top_50_event("24 Pull Requests", "24pr_contributors")
    
    # LFX
    lfx_repos, lfx_raw = analyze_top_50_event("LFX", "lfx_contributors")
    
    # GSoC (top 335, not 385)
    print(f"\n{'='*80}")
    print("TOP 335 GSoC PROJECTS (excluding bottom 50)")
    print(f"{'='*80}")
    
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    gsoc_repos = [r for r in repos if r.get('gsoc_contributors', 0) > 0]
    gsoc_repos.sort(key=lambda x: x['gsoc_contributors'], reverse=True)
    top_335_gsoc = gsoc_repos[:335]
    
    gsoc_total = sum(r['gsoc_contributors'] for r in top_335_gsoc)
    print(f"GSoC contributors from top 335: {gsoc_total}")
    
    # Analyze actual contributors
    print("\n" + "="*80)
    print("STEP 2: ANALYZE ACTUAL CONTRIBUTORS FROM TOP 50")
    print("="*80)
    
    base_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery"
    
    hf_total, hf_4plus = analyze_contributors_from_top_50(
        "Hacktoberfest",
        base_path / "hacktoberfest" / "hacktoberfest_contributors.json",
        hf_repos
    )
    
    pr24_total, pr24_4plus = analyze_contributors_from_top_50(
        "24 Pull Requests",
        base_path / "24_pull_requests" / "24pr_contributors.json",
        pr24_repos
    )
    
    lfx_total, lfx_4plus = analyze_contributors_from_top_50(
        "LFX",
        base_path / "lfx_mentorship" / "lfx_contributors.json",
        lfx_repos,
        activity_key='issue_count'
    )
    
    # Check overlaps
    print("\n" + "="*80)
    print("STEP 3: CHECK PROJECT OVERLAPS")
    print("="*80)
    
    hf_names = {r['repo_name'] for r in hf_repos}
    pr24_names = {r['repo_name'] for r in pr24_repos}
    lfx_names = {r['repo_name'] for r in lfx_repos}
    gsoc_names = {r['repo_name'] for r in top_335_gsoc}
    
    # Calculate overlaps
    all_names = hf_names | pr24_names | lfx_names | gsoc_names
    
    overlaps = {
        'HF-24PR': len(hf_names & pr24_names),
        'HF-LFX': len(hf_names & lfx_names),
        'HF-GSoC': len(hf_names & gsoc_names),
        '24PR-LFX': len(pr24_names & lfx_names),
        '24PR-GSoC': len(pr24_names & gsoc_names),
        'LFX-GSoC': len(lfx_names & gsoc_names)
    }
    
    print(f"\nProject overlaps:")
    for pair, count in overlaps.items():
        print(f"  {pair:15s}: {count:3d} repos")
    
    print(f"\nUnique projects across all events:")
    print(f"  Total unique: {len(all_names)}")
    print(f"  GSoC: 335, HF: 50, 24PR: 50, LFX: 50")
    print(f"  Raw sum: {335 + 50 + 50 + 50} = 485")
    print(f"  Overlaps: {485 - len(all_names)}")
    
    # Add OSS4SG
    corpus_path = Path(__file__).parent / "correct_corpus.json"
    with open(corpus_path, 'r') as f:
        corpus_data = json.load(f)
    
    oss4sg_repos = [r for r in corpus_data['repos'] if r['is_oss4sg']]
    oss4sg_names = {r['repo_name'] for r in oss4sg_repos}
    
    # OSS4SG not already in all_names
    new_oss4sg = oss4sg_names - all_names
    
    print(f"\nOSS4SG projects:")
    print(f"  Total OSS4SG: {len(oss4sg_repos)}")
    print(f"  Already in events: {len(oss4sg_names & all_names)}")
    print(f"  Need to add: {len(new_oss4sg)}")
    
    final_corpus_size = len(all_names | oss4sg_names)
    
    # Final summary
    print("\n" + "="*80)
    print("FINAL CORPUS COMPOSITION")
    print("="*80)
    
    print(f"\nNew corpus:")
    print(f"  Top 335 GSoC projects")
    print(f"  Top 50 Hacktoberfest projects")
    print(f"  Top 50 24 Pull Requests projects")
    print(f"  Top 50 LFX projects")
    print(f"  All OSS4SG projects ({len(oss4sg_repos)} total, {len(new_oss4sg)} additional)")
    print(f"\n  Total unique projects: {final_corpus_size}")
    
    print(f"\n{'='*80}")
    print("CONTRIBUTOR ESTIMATES (WITH 4+ FILTER):")
    print(f"{'='*80}")
    print(f"  GSoC (top 335):     {gsoc_total:5d}")
    print(f"  LFX (top 50):         {lfx_total:5d} (no filter)")
    print(f"  Hacktoberfest:      {hf_4plus:5d}")
    print(f"  24PR:               {pr24_4plus:5d}")
    print(f"  {'─'*30}")
    print(f"  Total (estimated):  ~{gsoc_total + lfx_total + hf_4plus + pr24_4plus:5d}")
    
    print(f"\nNote: These are estimates. Actual numbers may vary due to:")
    print(f"  - Contributors working on multiple event projects")
    print(f"  - Filtering by commit count after extraction")

if __name__ == "__main__":
    main()
