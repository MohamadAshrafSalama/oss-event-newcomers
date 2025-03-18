#!/usr/bin/env python3
"""
Detailed analysis of corpus composition and contributor counts.
"""

import json
from pathlib import Path
from collections import defaultdict

def analyze_bottom_50_gsoc():
    """Analyze the bottom 50 GSoC projects (from 385)"""
    
    print("="*80)
    print("BOTTOM 50 GSoC PROJECTS ANALYSIS")
    print("="*80)
    
    # Load all event repos
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    
    # Filter repos with GSoC contributors
    gsoc_repos = [r for r in repos if r.get('gsoc_contributors', 0) > 0]
    gsoc_repos.sort(key=lambda x: x['gsoc_contributors'], reverse=True)
    
    # Bottom 50 from top 385
    bottom_50 = gsoc_repos[335:385]
    
    print(f"\nBottom 50 GSoC projects (ranks 336-385):")
    print(f"{'Rank':<6} {'GSoC':<6} {'HF':<6} {'24PR':<6} {'Repo':<50}")
    print("-"*80)
    
    total_gsoc_bottom = 0
    total_hf_bottom = 0
    total_24pr_bottom = 0
    
    for i, repo in enumerate(bottom_50, 336):
        total_gsoc_bottom += repo['gsoc_contributors']
        total_hf_bottom += repo.get('hf_contributors', 0)
        total_24pr_bottom += repo.get('24pr_contributors', 0)
        print(f"{i:<6} {repo['gsoc_contributors']:<6} {repo.get('hf_contributors', 0):<6} {repo.get('24pr_contributors', 0):<6} {repo['repo_name'][:48]:<50}")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY - Bottom 50 GSoC Projects:")
    print(f"  GSoC contributors: {total_gsoc_bottom}")
    print(f"  HF contributors: {total_hf_bottom}")
    print(f"  24PR contributors: {total_24pr_bottom}")
    print(f"  Total event contributors: {total_gsoc_bottom + total_hf_bottom + total_24pr_bottom}")
    
    return bottom_50

def analyze_top_385_events():
    """Analyze HF and 24PR contributors in top 385 GSoC projects"""
    
    print(f"\n{'='*80}")
    print("TOP 385 GSoC PROJECTS - EVENT BREAKDOWN")
    print(f"{'='*80}")
    
    # Load all event repos
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    
    # Get top 385 GSoC
    gsoc_repos = [r for r in repos if r.get('gsoc_contributors', 0) > 0]
    gsoc_repos.sort(key=lambda x: x['gsoc_contributors'], reverse=True)
    top_385 = gsoc_repos[:385]
    top_385_names = {r['repo_name'] for r in top_385}
    
    # Summary stats
    total_gsoc = sum(r['gsoc_contributors'] for r in top_385)
    total_hf_raw = sum(r.get('hf_contributors', 0) for r in top_385)
    total_24pr_raw = sum(r.get('24pr_contributors', 0) for r in top_385)
    
    print(f"\nRaw contributor counts (without filter):")
    print(f"  GSoC: {total_gsoc}")
    print(f"  Hacktoberfest: {total_hf_raw}")
    print(f"  24PR: {total_24pr_raw}")
    print(f"  Total: {total_gsoc + total_hf_raw + total_24pr_raw}")
    
    # Now filter actual contributors by corpus
    print(f"\n{'='*80}")
    print("FILTERING CONTRIBUTORS BY ACTIVITY LEVEL")
    print(f"{'='*80}")
    
    # Load HF contributors
    hf_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery" / "hacktoberfest" / "hacktoberfest_contributors.json"
    with open(hf_path, 'r') as f:
        hf_data = json.load(f)
    
    # Load 24PR contributors
    pr24_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery" / "24_pull_requests" / "24pr_contributors.json"
    with open(pr24_path, 'r') as f:
        pr24_data = json.load(f)
    
    # Filter by top 385 GSoC repos
    def filter_by_repos_and_activity(contributors, corpus_repos):
        filtered = []
        activity_dist = {1: 0, 2: 0, 3: 0, '4+': 0}
        
        for c in contributors:
            contrib_repos = set(c.get('repos_contributed', []))
            if contrib_repos & corpus_repos:
                prs = c.get('total_prs', 0)
                filtered.append((c, prs))
                
                if prs == 1:
                    activity_dist[1] += 1
                elif prs == 2:
                    activity_dist[2] += 1
                elif prs == 3:
                    activity_dist[3] += 1
                elif prs >= 4:
                    activity_dist['4+'] += 1
        
        return filtered, activity_dist
    
    hf_filtered, hf_dist = filter_by_repos_and_activity(hf_data['contributors'], top_385_names)
    pr24_filtered, pr24_dist = filter_by_repos_and_activity(pr24_data['contributors'], top_385_names)
    
    print(f"\nHacktoberfest in top 385 GSoC projects:")
    print(f"  Total in corpus: {len(hf_filtered)}")
    print(f"  Activity distribution:")
    print(f"    1 PR:  {hf_dist[1]:5d}")
    print(f"    2 PRs: {hf_dist[2]:5d}")
    print(f"    3 PRs: {hf_dist[3]:5d}")
    print(f"    4+ PRs: {hf_dist['4+']:5d}")
    print(f"  With 4+ filter: {hf_dist['4+']}")
    
    print(f"\n24 Pull Requests in top 385 GSoC projects:")
    print(f"  Total in corpus: {len(pr24_filtered)}")
    print(f"  Activity distribution:")
    print(f"    1 PR:  {pr24_dist[1]:5d}")
    print(f"    2 PRs: {pr24_dist[2]:5d}")
    print(f"    3 PRs: {pr24_dist[3]:5d}")
    print(f"    4+ PRs: {pr24_dist['4+']:5d}")
    print(f"  With 4+ filter: {pr24_dist['4+']}")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY:")
    print(f"{'='*80}")
    print(f"Without filter:")
    print(f"  HF: {len(hf_filtered)}, 24PR: {len(pr24_filtered)}, Total: {len(hf_filtered) + len(pr24_filtered)}")
    print(f"\nWith 4+ PR filter:")
    print(f"  HF: {hf_dist['4+']}, 24PR: {pr24_dist['4+']}, Total: {hf_dist['4+'] + pr24_dist['4+']}")
    
    return {
        'hf_total': len(hf_filtered),
        'hf_4plus': hf_dist['4+'],
        'hf_dist': hf_dist,
        'pr24_total': len(pr24_filtered),
        'pr24_4plus': pr24_dist['4+'],
        'pr24_dist': pr24_dist
    }

def analyze_top_50_lfx_detailed():
    """Get detailed LFX analysis with all contributors (no threshold)"""
    
    print(f"\n{'='*80}")
    print("TOP 50 LFX PROJECTS - ALL CONTRIBUTORS (NO THRESHOLD)")
    print(f"{'='*80}")
    
    # Load all event repos
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    
    # Filter repos with LFX contributors
    lfx_repos = [r for r in repos if r.get('lfx_contributors', 0) > 0]
    lfx_repos.sort(key=lambda x: x['lfx_contributors'], reverse=True)
    top_50 = lfx_repos[:50]
    top_50_names = {r['repo_name'] for r in top_50}
    
    # Load LFX contributors
    lfx_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery" / "lfx_mentorship" / "lfx_contributors.json"
    with open(lfx_path, 'r') as f:
        lfx_data = json.load(f)
    
    # Filter by top 50
    filtered = []
    issue_dist = {1: 0, 2: 0, 3: 0, '4+': 0}
    
    for c in lfx_data['contributors']:
        contrib_repos = set(c.get('repos_contributed', []))
        if contrib_repos & top_50_names:
            issues = c.get('issue_count', 0)
            filtered.append(c)
            
            if issues == 1:
                issue_dist[1] += 1
            elif issues == 2:
                issue_dist[2] += 1
            elif issues == 3:
                issue_dist[3] += 1
            elif issues >= 4:
                issue_dist['4+'] += 1
    
    print(f"\nLFX contributors from top 50 projects:")
    print(f"  Total: {len(filtered)}")
    print(f"  Activity distribution (by issue count):")
    print(f"    1 issue:  {issue_dist[1]:5d}")
    print(f"    2 issues: {issue_dist[2]:5d}")
    print(f"    3 issues: {issue_dist[3]:5d}")
    print(f"    4+ issues: {issue_dist['4+']:5d}")
    
    print(f"\n  With no threshold: {len(filtered)}")
    print(f"  With 2+ threshold: {issue_dist[2] + issue_dist[3] + issue_dist['4+']}")
    print(f"  With 4+ threshold: {issue_dist['4+']}")
    
    return {
        'total': len(filtered),
        'dist': issue_dist
    }

def main():
    # Analyze bottom 50 GSoC
    bottom_50 = analyze_bottom_50_gsoc()
    
    # Analyze top 385 GSoC with HF and 24PR
    top_385_stats = analyze_top_385_events()
    
    # Analyze top 50 LFX
    lfx_stats = analyze_top_50_lfx_detailed()
    
    print(f"\n{'='*80}")
    print("FINAL COMPARISON")
    print(f"{'='*80}")
    
    print(f"\nOption: Replace bottom 50 GSoC with top 50 LFX")
    bottom_50_gsoc_count = sum(r['gsoc_contributors'] for r in bottom_50)
    print(f"  Bottom 50 GSoC contributors: {bottom_50_gsoc_count}")
    print(f"  Top 50 LFX contributors (all): {lfx_stats['total']}")
    print(f"  Net change: +{lfx_stats['total'] - bottom_50_gsoc_count} contributors")

if __name__ == "__main__":
    main()
