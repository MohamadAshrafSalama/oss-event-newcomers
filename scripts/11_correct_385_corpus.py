#!/usr/bin/env python3
"""
Create the correct 385 project corpus:
- Top 50 HF (sorted by contributors with 4+ PRs)
- Top 50 24PR (sorted by contributors with 4+ PRs)
- Top 50 LFX (sorted by all contributors, no filter)
- Top 235 GSoC (sorted by contributors with 2+ contributions)
+ All OSS4SG projects
"""

import json
from pathlib import Path
from collections import defaultdict

def get_top_50_filtered_projects(event_name, event_key, contributors_file, activity_key='total_prs', min_activity=4):
    """
    Get top 50 projects sorted by contributors who meet the activity threshold.
    """
    
    print(f"\n{'='*80}")
    print(f"TOP 50 {event_name.upper()} PROJECTS (4+ FILTER)")
    print(f"{'='*80}")
    
    # Load all repos
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    
    # Load contributors
    with open(contributors_file, 'r') as f:
        contrib_data = json.load(f)
    
    contributors = contrib_data['contributors']
    
    # Count contributors with 4+ activity per repo
    repo_qualified_counts = defaultdict(int)
    
    for c in contributors:
        activity = c.get(activity_key, 0)
        if activity >= min_activity:
            for repo in c.get('repos_contributed', []):
                repo_qualified_counts[repo] += 1
    
    # Filter and sort repos by qualified contributor count
    event_repos = []
    for r in repos:
        repo_name = r['repo_name']
        qualified_count = repo_qualified_counts.get(repo_name, 0)
        if qualified_count > 0:  # Only include repos with at least 1 qualified contributor
            r_copy = r.copy()
            r_copy['qualified_contributors'] = qualified_count
            event_repos.append(r_copy)
    
    event_repos.sort(key=lambda x: x['qualified_contributors'], reverse=True)
    top_50 = event_repos[:50]
    
    total_qualified = sum(r['qualified_contributors'] for r in top_50)
    total_raw = sum(r.get(event_key, 0) for r in top_50)
    
    print(f"\nTotal repos with qualified contributors: {len(event_repos)}")
    print(f"\nTop 50 {event_name} projects (by 4+ contributors):")
    print(f"{'Rank':<6} {'4+':<6} {'Raw':<6} {'Repo':<50}")
    print("-"*80)
    
    for i, repo in enumerate(top_50[:20], 1):
        print(f"{i:<6} {repo['qualified_contributors']:<6} {repo.get(event_key, 0):<6} {repo['repo_name'][:48]:<50}")
    
    if len(top_50) > 20:
        print(f"  ... and {len(top_50) - 20} more")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY - Top 50 {event_name} (4+ filter):")
    print(f"  Qualified contributors (4+): {total_qualified}")
    print(f"  Raw contributors (all): {total_raw}")
    
    return top_50

def get_top_50_lfx_no_filter():
    """Get top 50 LFX projects with no filter"""
    
    print(f"\n{'='*80}")
    print("TOP 50 LFX PROJECTS (NO FILTER)")
    print(f"{'='*80}")
    
    # Load all repos
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    
    # Filter and sort by LFX contributors
    lfx_repos = [r for r in repos if r.get('lfx_contributors', 0) > 0]
    lfx_repos.sort(key=lambda x: x['lfx_contributors'], reverse=True)
    top_50 = lfx_repos[:50]
    
    total_lfx = sum(r['lfx_contributors'] for r in top_50)
    
    print(f"\nTotal repos with LFX: {len(lfx_repos)}")
    print(f"\nTop 50 LFX projects:")
    print(f"{'Rank':<6} {'LFX':<6} {'Repo':<50}")
    print("-"*80)
    
    for i, repo in enumerate(top_50[:20], 1):
        print(f"{i:<6} {repo['lfx_contributors']:<6} {repo['repo_name'][:48]:<50}")
    
    if len(top_50) > 20:
        print(f"  ... and {len(top_50) - 20} more")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY - Top 50 LFX (no filter):")
    print(f"  LFX contributors: {total_lfx}")
    
    return top_50

def get_top_235_gsoc_2plus():
    """Get top 235 GSoC projects sorted by contributors with 2+ contributions"""
    
    print(f"\n{'='*80}")
    print("TOP 235 GSoC PROJECTS (2+ CONTRIBUTIONS FILTER)")
    print(f"{'='*80}")
    
    # Load all repos
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    
    # Load GSoC contributors
    gsoc_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery" / "google_summer_of_code" / "gsoc_contributors.json"
    with open(gsoc_path, 'r') as f:
        gsoc_data = json.load(f)
    
    contributors = gsoc_data['contributors']
    
    # Count contributors with 2+ repos per repo
    # For GSoC, we use repo_count as a proxy for contribution level
    repo_qualified_counts = defaultdict(int)
    
    for c in contributors:
        repo_count = c.get('repo_count', 0)
        if repo_count >= 2:  # 2+ contributions
            for repo in c.get('repos_contributed', []):
                repo_qualified_counts[repo] += 1
    
    # Filter and sort repos
    gsoc_repos = []
    for r in repos:
        repo_name = r['repo_name']
        qualified_count = repo_qualified_counts.get(repo_name, 0)
        if qualified_count > 0:
            r_copy = r.copy()
            r_copy['qualified_contributors'] = qualified_count
            gsoc_repos.append(r_copy)
    
    gsoc_repos.sort(key=lambda x: x['qualified_contributors'], reverse=True)
    top_235 = gsoc_repos[:235]
    
    total_qualified = sum(r['qualified_contributors'] for r in top_235)
    total_raw = sum(r.get('gsoc_contributors', 0) for r in top_235)
    
    print(f"\nTotal repos with qualified GSoC: {len(gsoc_repos)}")
    print(f"\nTop 235 GSoC projects (by 2+ contributors):")
    print(f"{'Rank':<6} {'2+':<6} {'Raw':<6} {'Repo':<50}")
    print("-"*80)
    
    for i, repo in enumerate(top_235[:20], 1):
        print(f"{i:<6} {repo['qualified_contributors']:<6} {repo.get('gsoc_contributors', 0):<6} {repo['repo_name'][:48]:<50}")
    
    if len(top_235) > 20:
        print(f"  ... and {len(top_235) - 20} more")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY - Top 235 GSoC (2+ filter):")
    print(f"  Qualified contributors (2+): {total_qualified}")
    print(f"  Raw contributors (all): {total_raw}")
    
    return top_235

def main():
    print("="*80)
    print("CORRECT 385 PROJECT CORPUS")
    print("="*80)
    
    base_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery"
    
    # Get top 50 from each event
    hf_top50 = get_top_50_filtered_projects(
        "Hacktoberfest",
        "hf_contributors",
        base_path / "hacktoberfest" / "hacktoberfest_contributors.json"
    )
    
    pr24_top50 = get_top_50_filtered_projects(
        "24 Pull Requests",
        "24pr_contributors",
        base_path / "24_pull_requests" / "24pr_contributors.json"
    )
    
    lfx_top50 = get_top_50_lfx_no_filter()
    
    gsoc_top235 = get_top_235_gsoc_2plus()
    
    # Combine
    all_repos = hf_top50 + pr24_top50 + lfx_top50 + gsoc_top235
    
    # Check for duplicates
    repo_names = [r['repo_name'] for r in all_repos]
    unique_names = set(repo_names)
    
    print(f"\n{'='*80}")
    print("OVERLAP CHECK")
    print(f"{'='*80}")
    print(f"Raw sum: 50 + 50 + 50 + 235 = 385")
    print(f"Unique repos: {len(unique_names)}")
    print(f"Duplicates: {len(repo_names) - len(unique_names)}")
    
    # Check overlaps
    hf_names = {r['repo_name'] for r in hf_top50}
    pr24_names = {r['repo_name'] for r in pr24_top50}
    lfx_names = {r['repo_name'] for r in lfx_top50}
    gsoc_names = {r['repo_name'] for r in gsoc_top235}
    
    print(f"\nOverlaps:")
    print(f"  HF ∩ 24PR: {len(hf_names & pr24_names)}")
    print(f"  HF ∩ LFX: {len(hf_names & lfx_names)}")
    print(f"  HF ∩ GSoC: {len(hf_names & gsoc_names)}")
    print(f"  24PR ∩ LFX: {len(pr24_names & lfx_names)}")
    print(f"  24PR ∩ GSoC: {len(pr24_names & gsoc_names)}")
    print(f"  LFX ∩ GSoC: {len(lfx_names & gsoc_names)}")
    
    # Add OSS4SG
    print(f"\n{'='*80}")
    print("OSS4SG PROJECTS")
    print(f"{'='*80}")
    
    # Load all repos to find OSS4SG
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    all_repos_data = data['repos']
    oss4sg_repos = [r for r in all_repos_data if r.get('is_oss4sg', False)]
    oss4sg_names = {r['repo_name'] for r in oss4sg_repos}
    
    # OSS4SG not in the 385
    already_in = oss4sg_names & unique_names
    need_to_add = oss4sg_names - unique_names
    
    print(f"Total OSS4SG: {len(oss4sg_repos)}")
    print(f"Already in 385: {len(already_in)}")
    print(f"Need to add: {len(need_to_add)}")
    
    final_corpus_size = len(unique_names | oss4sg_names)
    
    # Final summary
    print(f"\n{'='*80}")
    print("FINAL CORPUS SUMMARY")
    print(f"{'='*80}")
    
    print(f"\nComposition:")
    print(f"  Top 50 Hacktoberfest (4+ PRs)")
    print(f"  Top 50 24 Pull Requests (4+ PRs)")
    print(f"  Top 50 LFX (no filter)")
    print(f"  Top 235 GSoC (2+ contributions)")
    print(f"  ─────────────────────")
    print(f"  Subtotal: {len(unique_names)} unique projects")
    print(f"  + OSS4SG: {len(need_to_add)} additional")
    print(f"  ─────────────────────")
    print(f"  TOTAL: {final_corpus_size} projects")
    
    # Get contributor counts
    print(f"\n{'='*80}")
    print("CONTRIBUTOR ESTIMATES")
    print(f"{'='*80}")
    
    hf_qualified = sum(r.get('qualified_contributors', 0) for r in hf_top50)
    pr24_qualified = sum(r.get('qualified_contributors', 0) for r in pr24_top50)
    lfx_total = sum(r.get('lfx_contributors', 0) for r in lfx_top50)
    gsoc_qualified = sum(r.get('qualified_contributors', 0) for r in gsoc_top235)
    
    print(f"  Hacktoberfest (4+ PRs):  {hf_qualified:5d}")
    print(f"  24PR (4+ PRs):           {pr24_qualified:5d}")
    print(f"  LFX (no filter):         {lfx_total:5d}")
    print(f"  GSoC (2+ contributions): {gsoc_qualified:5d}")
    print(f"  ─────────────────────────────")
    print(f"  TOTAL (estimated):       {hf_qualified + pr24_qualified + lfx_total + gsoc_qualified:5d}")
    
    print(f"\nNote: Actual numbers will be different after:")
    print(f"  - Filtering contributors to only those in corpus repos")
    print(f"  - Removing duplicates (contributors in multiple events)")

if __name__ == "__main__":
    main()
