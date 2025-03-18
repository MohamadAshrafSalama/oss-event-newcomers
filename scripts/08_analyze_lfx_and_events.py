#!/usr/bin/env python3
"""
Analyze LFX contributors and event distribution in our corpus.
"""

import json
from pathlib import Path
from collections import defaultdict

def analyze_lfx_projects():
    """Find top LFX projects and their contributors"""
    
    # Load all event repos
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    
    # Filter repos with LFX contributors
    lfx_repos = [r for r in repos if r.get('lfx_contributors', 0) > 0]
    
    print("="*80)
    print("LFX PROJECT ANALYSIS")
    print("="*80)
    print(f"\nTotal repos with LFX contributors: {len(lfx_repos)}")
    
    # Sort by LFX contributor count
    lfx_repos.sort(key=lambda x: x['lfx_contributors'], reverse=True)
    
    # Show top 50
    print(f"\nTop 50 LFX projects:")
    print(f"{'Rank':<6} {'LFX':<6} {'GSoC':<6} {'Repo':<50} {'In Corpus?'}")
    print("-"*80)
    
    # Load our corpus
    corpus_path = Path(__file__).parent / "correct_corpus.json"
    with open(corpus_path, 'r') as f:
        corpus_data = json.load(f)
    corpus_repos = {r['repo_name'] for r in corpus_data['repos']}
    
    total_lfx_top50 = 0
    in_corpus_count = 0
    
    for i, repo in enumerate(lfx_repos[:50], 1):
        in_corpus = repo['repo_name'] in corpus_repos
        total_lfx_top50 += repo['lfx_contributors']
        if in_corpus:
            in_corpus_count += 1
        
        marker = "✓" if in_corpus else " "
        print(f"{i:<6} {repo['lfx_contributors']:<6} {repo.get('gsoc_contributors', 0):<6} {repo['repo_name'][:48]:<50} {marker}")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY - Top 50 LFX Projects:")
    print(f"  Total LFX contributors: {total_lfx_top50}")
    print(f"  Projects already in corpus: {in_corpus_count}/50")
    print(f"  Projects NOT in corpus: {50-in_corpus_count}")
    
    return lfx_repos[:50]

def analyze_lfx_contributors_from_top50(top50_repos):
    """See how many LFX contributors we'd get from top 50 projects"""
    
    print(f"\n{'='*80}")
    print("LFX CONTRIBUTORS FROM TOP 50 PROJECTS")
    print(f"{'='*80}")
    
    # Load LFX contributors
    lfx_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery" / "lfx_mentorship" / "lfx_contributors.json"
    with open(lfx_path, 'r') as f:
        lfx_data = json.load(f)
    
    lfx_contributors = lfx_data['contributors']
    
    # Get top 50 repo names
    top50_names = {r['repo_name'] for r in top50_repos}
    
    # Filter contributors who worked on top 50
    filtered = []
    for contrib in lfx_contributors:
        contrib_repos = set(contrib.get('repos_contributed', []))
        if contrib_repos & top50_names:
            filtered_contrib = contrib.copy()
            filtered_contrib['top50_repos'] = sorted(list(contrib_repos & top50_names))
            filtered.append(filtered_contrib)
    
    print(f"Total LFX contributors: {len(lfx_contributors)}")
    print(f"Contributors from top 50 LFX projects: {len(filtered)}")
    
    # Apply 4+ issue filter (LFX has issue_count)
    filtered_4plus = [c for c in filtered if c.get('issue_count', 0) >= 4]
    
    print(f"After 4+ issues filter: {len(filtered_4plus)}")
    
    # Show distribution
    issue_counts = defaultdict(int)
    for c in filtered:
        count = c.get('issue_count', 0)
        if count >= 10:
            issue_counts['10+'] += 1
        elif count >= 4:
            issue_counts['4-9'] += 1
        else:
            issue_counts['<4'] += 1
    
    print(f"\nIssue count distribution:")
    print(f"  10+ issues: {issue_counts['10+']}")
    print(f"  4-9 issues: {issue_counts['4-9']}")
    print(f"  <4 issues: {issue_counts['<4']}")
    
    return filtered_4plus

def analyze_current_corpus_events():
    """Analyze HF and 24PR contributors in our current corpus"""
    
    print(f"\n{'='*80}")
    print("EVENT CONTRIBUTORS IN CURRENT CORPUS")
    print(f"{'='*80}")
    
    # Load our corpus
    corpus_path = Path(__file__).parent / "correct_corpus.json"
    with open(corpus_path, 'r') as f:
        corpus_data = json.load(f)
    
    corpus_repos = {r['repo_name'] for r in corpus_data['repos']}
    
    # Load HF contributors
    hf_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery" / "hacktoberfest" / "hacktoberfest_contributors.json"
    with open(hf_path, 'r') as f:
        hf_data = json.load(f)
    
    # Load 24PR contributors
    pr24_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery" / "24_pull_requests" / "24pr_contributors.json"
    with open(pr24_path, 'r') as f:
        pr24_data = json.load(f)
    
    # Filter by corpus
    def filter_by_corpus(contributors, corpus_repos):
        filtered = []
        for c in contributors:
            contrib_repos = set(c.get('repos_contributed', []))
            if contrib_repos & corpus_repos:
                filtered.append(c)
        return filtered
    
    hf_in_corpus = filter_by_corpus(hf_data['contributors'], corpus_repos)
    pr24_in_corpus = filter_by_corpus(pr24_data['contributors'], corpus_repos)
    
    # Apply 4+ filter
    hf_4plus = [c for c in hf_in_corpus if c.get('total_prs', 0) >= 4]
    pr24_4plus = [c for c in pr24_in_corpus if c.get('total_prs', 0) >= 4]
    
    print(f"\nHacktoberfest:")
    print(f"  Total contributors: {len(hf_data['contributors'])}")
    print(f"  In corpus: {len(hf_in_corpus)}")
    print(f"  With 4+ PRs: {len(hf_4plus)}")
    print(f"  Currently selected: 564")
    
    print(f"\n24 Pull Requests:")
    print(f"  Total contributors: {len(pr24_data['contributors'])}")
    print(f"  In corpus: {len(pr24_in_corpus)}")
    print(f"  With 4+ PRs: {len(pr24_4plus)}")
    print(f"  Currently selected: 142")
    
    print(f"\n{'='*80}")
    print("RECOMMENDATION:")
    print(f"{'='*80}")
    
    return {
        'hf_total': len(hf_in_corpus),
        'hf_4plus': len(hf_4plus),
        'pr24_total': len(pr24_in_corpus),
        'pr24_4plus': len(pr24_4plus)
    }

def main():
    # Analyze LFX
    top50_lfx = analyze_lfx_projects()
    lfx_filtered = analyze_lfx_contributors_from_top50(top50_lfx)
    
    # Analyze current corpus events
    corpus_events = analyze_current_corpus_events()
    
    # Load current corpus repos
    corpus_path = Path(__file__).parent / "correct_corpus.json"
    with open(corpus_path, 'r') as f:
        corpus_data = json.load(f)
    corpus_repos = {r['repo_name'] for r in corpus_data['repos']}
    
    new_lfx_projects = len([r for r in top50_lfx if r['repo_name'] not in corpus_repos])
    
    print(f"\nPOSSIBLE ADJUSTMENTS:")
    print(f"-"*80)
    print(f"Option 1: Add top 50 LFX projects to corpus")
    print(f"  - Would add {new_lfx_projects} new projects (0 already in corpus)")
    print(f"  - Would gain ~{len(lfx_filtered)} LFX contributors (with 4+ issues)")
    print(f"  - Total projects: 448 + {new_lfx_projects} = {448 + new_lfx_projects} projects")
    print(f"  - Total contributors: 1,651 + {len(lfx_filtered)} = {1651 + len(lfx_filtered)}")
    
    print(f"\nOption 2: Replace lowest GSoC with top LFX projects")
    print(f"  - Replace bottom 50 GSoC projects with top 50 LFX")
    print(f"  - Keep total at 448 projects (385 GSoC → 335 GSoC + 50 LFX + 63 OSS4SG)")
    print(f"  - Would need to recompute contributor counts")
    
    print(f"\nOption 3: Keep current corpus, just add LFX from overlapping projects")
    print(f"  - Some LFX projects may already be in corpus via GSoC")
    print(f"  - Check overlap and add those LFX contributors")

if __name__ == "__main__":
    main()
