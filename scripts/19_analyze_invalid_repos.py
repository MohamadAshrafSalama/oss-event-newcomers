#!/usr/bin/env python3
"""
Analyze and categorize all invalid/truncated repo names
"""
import json
from pathlib import Path

def main():
    # Load progress to find error repos
    with open("/Volumes/T7/Event based OSS4SG/progress.json") as f:
        progress = json.load(f)
    
    error_repos = [r for r, v in progress['repos'].items() 
                   if isinstance(v, dict) and v.get('status') == 'error']
    
    # Load contributions to understand impact
    with open("/Users/mohamadashraf/Desktop/Project/Event Based Vs Organic new conrtibutors/04_contributor_selection_and_organic_matching/outputs/contributions_final.json") as f:
        data = json.load(f)
    
    # Categorize repos
    github_internal = []
    truncated = []
    other = []
    
    internal_prefixes = ['_private/', 'auth/', 'features/', 'site-policy/', 
                         'get-started/', 'github/', 'user-attachments/']
    
    for repo in error_repos:
        if any(repo.startswith(prefix) for prefix in internal_prefixes):
            github_internal.append(repo)
        elif '/' in repo and len(repo.split('/')[1]) < 15:
            # Likely truncated if owner/name and name is very short
            truncated.append(repo)
        else:
            other.append(repo)
    
    # Count contributions per repo
    repo_contrib_count = {}
    for c in data['contributions']:
        repo = c['repo']
        repo_contrib_count[repo] = repo_contrib_count.get(repo, 0) + 1
    
    print("="*80)
    print("INVALID REPO ANALYSIS")
    print("="*80)
    
    print(f"\n1. GITHUB-INTERNAL (unfixable): {len(github_internal)} repos")
    total_unfixable = 0
    for repo in sorted(github_internal):
        count = repo_contrib_count.get(repo, 0)
        total_unfixable += count
        print(f"   {repo:50s} | {count:3d} contributions")
    print(f"   Total contributions to remove: {total_unfixable}")
    
    print(f"\n2. TRUNCATED (fixable): {len(truncated)} repos")
    total_fixable = 0
    for repo in sorted(truncated):
        count = repo_contrib_count.get(repo, 0)
        total_fixable += count
        print(f"   {repo:50s} | {count:3d} contributions")
    print(f"   Total contributions to fix: {total_fixable}")
    
    print(f"\n3. OTHER: {len(other)} repos")
    for repo in sorted(other):
        count = repo_contrib_count.get(repo, 0)
        print(f"   {repo:50s} | {count:3d} contributions")
    
    print(f"\n{'='*80}")
    print("SUMMARY")
    print("="*80)
    print(f"Total error repos: {len(error_repos)}")
    print(f"  Unfixable (GitHub-internal): {len(github_internal)} repos, {total_unfixable} contributions")
    print(f"  Fixable (truncated): {len(truncated)} repos, {total_fixable} contributions")
    print(f"  Other: {len(other)} repos")
    print(f"\nAfter fix:")
    print(f"  Contributions: {len(data['contributions'])} → {len(data['contributions']) - total_unfixable}")
    print(f"  Loss: {total_unfixable} contributions ({total_unfixable/len(data['contributions'])*100:.1f}%)")
    
    # Save categorization for next step
    result = {
        'github_internal': github_internal,
        'truncated': truncated,
        'other': other,
        'total_contributions_to_remove': total_unfixable,
        'total_contributions_to_fix': total_fixable
    }
    
    output_path = Path(__file__).parent / "invalid_repos_analysis.json"
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\nSaved analysis to: {output_path}")

if __name__ == "__main__":
    main()
