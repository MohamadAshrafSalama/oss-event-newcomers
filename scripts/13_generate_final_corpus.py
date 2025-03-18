#!/usr/bin/env python3
"""
Generate the final 435-project corpus with proper structure.
"""

import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

def get_qualified_repos(event_name, event_key, contributors_file, activity_key, min_activity, top_n):
    """Get top N repos sorted by qualified contributors"""
    
    # Load all repos
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    
    # Load contributors
    with open(contributors_file, 'r') as f:
        contrib_data = json.load(f)
    
    contributors = contrib_data['contributors']
    
    # Count qualified contributors per repo
    repo_qualified_counts = defaultdict(int)
    
    for c in contributors:
        activity = c.get(activity_key, 0)
        if activity >= min_activity:
            for repo in c.get('repos_contributed', []):
                repo_qualified_counts[repo] += 1
    
    # Filter and sort repos
    event_repos = []
    for r in repos:
        repo_name = r['repo_name']
        qualified_count = repo_qualified_counts.get(repo_name, 0)
        if qualified_count > 0:
            event_repos.append(r)
    
    event_repos.sort(key=lambda x: repo_qualified_counts.get(x['repo_name'], 0), reverse=True)
    return event_repos[:top_n]

def main():
    print("="*80)
    print("GENERATING FINAL 435-PROJECT CORPUS")
    print("="*80)
    
    base_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery"
    
    # Get top 50 from each event
    print("\n1. Getting top 50 Hacktoberfest projects (4+ PRs)...")
    hf_repos = get_qualified_repos(
        "Hacktoberfest",
        "hf_contributors",
        base_path / "hacktoberfest" / "hacktoberfest_contributors.json",
        "total_prs",
        4,
        50
    )
    print(f"   ✓ Got {len(hf_repos)} repos")
    
    print("\n2. Getting top 50 24PR projects (4+ PRs)...")
    pr24_repos = get_qualified_repos(
        "24PR",
        "24pr_contributors",
        base_path / "24_pull_requests" / "24pr_contributors.json",
        "total_prs",
        4,
        50
    )
    print(f"   ✓ Got {len(pr24_repos)} repos")
    
    print("\n3. Getting top 50 LFX projects (no filter)...")
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    lfx_repos = [r for r in repos if r.get('lfx_contributors', 0) > 0]
    lfx_repos.sort(key=lambda x: x['lfx_contributors'], reverse=True)
    lfx_repos = lfx_repos[:50]
    print(f"   ✓ Got {len(lfx_repos)} repos")
    
    print("\n4. Getting top 235 GSoC projects (2+ contributions)...")
    gsoc_path = base_path / "google_summer_of_code" / "gsoc_contributors.json"
    with open(gsoc_path, 'r') as f:
        gsoc_data = json.load(f)
    
    contributors = gsoc_data['contributors']
    repo_qualified_counts = defaultdict(int)
    
    for c in contributors:
        repo_count = c.get('repo_count', 0)
        if repo_count >= 2:
            for repo in c.get('repos_contributed', []):
                repo_qualified_counts[repo] += 1
    
    gsoc_repos = []
    for r in repos:
        repo_name = r['repo_name']
        qualified_count = repo_qualified_counts.get(repo_name, 0)
        if qualified_count > 0:
            gsoc_repos.append(r)
    
    gsoc_repos.sort(key=lambda x: repo_qualified_counts.get(x['repo_name'], 0), reverse=True)
    gsoc_repos = gsoc_repos[:235]
    print(f"   ✓ Got {len(gsoc_repos)} repos")
    
    # Combine and get unique
    all_repos = hf_repos + pr24_repos + lfx_repos + gsoc_repos
    unique_repos = {}
    for r in all_repos:
        if r['repo_name'] not in unique_repos:
            unique_repos[r['repo_name']] = r
    
    print(f"\n5. Combined: {len(unique_repos)} unique repos from events")
    
    # Add OSS4SG
    oss4sg_repos = [r for r in repos if r.get('is_oss4sg', False)]
    for r in oss4sg_repos:
        if r['repo_name'] not in unique_repos:
            unique_repos[r['repo_name']] = r
    
    print(f"   + OSS4SG: {len(unique_repos) - (len(all_repos) - (len(all_repos) - len(unique_repos)))} additional")
    print(f"   = Total: {len(unique_repos)} projects")
    
    # Create corpus structure
    corpus_repos = list(unique_repos.values())
    corpus_repos.sort(key=lambda x: x['repo_name'])
    
    output_data = {
        "generated_at": datetime.now().isoformat(),
        "description": "Final balanced corpus: top 50 HF + 50 24PR + 50 LFX + 235 GSoC + OSS4SG",
        "selection_criteria": {
            "hacktoberfest": "Top 50 by contributors with 4+ PRs",
            "24pr": "Top 50 by contributors with 4+ PRs",
            "lfx": "Top 50 by total contributors (no filter)",
            "gsoc": "Top 235 by contributors with 2+ contributions",
            "oss4sg": "All OSS4SG projects"
        },
        "total_repos": len(corpus_repos),
        "statistics": {
            "total_gsoc_contributors": sum(r.get('gsoc_contributors', 0) for r in corpus_repos),
            "total_hf_contributors": sum(r.get('hf_contributors', 0) for r in corpus_repos),
            "total_24pr_contributors": sum(r.get('24pr_contributors', 0) for r in corpus_repos),
            "total_lfx_contributors": sum(r.get('lfx_contributors', 0) for r in corpus_repos),
            "oss4sg_count": sum(1 for r in corpus_repos if r.get('is_oss4sg', False))
        },
        "repos": corpus_repos
    }
    
    # Save
    output_path = Path(__file__).parent / "final_corpus_435.json"
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n{'='*80}")
    print(f"✓ Corpus saved to: {output_path}")
    print(f"{'='*80}")
    print(f"  Total projects: {len(corpus_repos)}")
    print(f"  OSS4SG: {output_data['statistics']['oss4sg_count']}")
    
    # Also save repo names list
    repo_names_path = Path(__file__).parent / "final_corpus_435_repo_names.txt"
    with open(repo_names_path, 'w') as f:
        for repo in corpus_repos:
            f.write(f"{repo['repo_name']}\n")
    
    print(f"  Repo names: {repo_names_path}")
    
    return output_data

if __name__ == "__main__":
    main()
