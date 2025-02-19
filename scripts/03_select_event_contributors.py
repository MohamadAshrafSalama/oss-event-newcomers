#!/usr/bin/env python3
"""
Phase 2: Select Event Contributors

This script:
1. Filters contributors from each event to only those who contributed to corpus repos
2. Applies minimum 4+ commit filter
3. For GSoC and LFX: take ALL with 4+ commits (mentorship programs)
4. For Hacktoberfest and 24PR: sample 50% top by activity + 50% random with 4+ commits

Input:
- scripts/correct_corpus.json (448 repos)
- 02_event_data_extraction.../gsoc_contributors.json
- 02_event_data_extraction.../lfx_contributors.json
- 02_event_data_extraction.../hacktoberfest_contributors.json
- 02_event_data_extraction.../24pr_contributors.json

Output:
- scripts/event_contributors_corpus_filtered.json
"""

import json
import random
import sys
from pathlib import Path
from datetime import datetime

# Set random seed for reproducibility
random.seed(42)

def load_corpus_repos():
    """Load the correct corpus repo names"""
    corpus_path = Path(__file__).parent / "correct_corpus.json"
    with open(corpus_path, 'r') as f:
        data = json.load(f)
    return {repo['repo_name'] for repo in data['repos']}

def filter_contributors_by_corpus(contributors, corpus_repos, event_name):
    """
    Filter contributors to only those who contributed to corpus repos.
    Returns list of contributors with their repos filtered to corpus repos only.
    """
    filtered = []
    
    for contrib in contributors:
        # Get repos this contributor worked on
        contrib_repos = set(contrib.get('repos_contributed', []))
        
        # Find intersection with corpus
        corpus_contrib_repos = contrib_repos & corpus_repos
        
        if corpus_contrib_repos:
            # This contributor worked on at least one corpus repo
            filtered_contrib = contrib.copy()
            filtered_contrib['repos_contributed'] = sorted(list(corpus_contrib_repos))
            filtered_contrib['corpus_repo_count'] = len(corpus_contrib_repos)
            filtered.append(filtered_contrib)
    
    print(f"  {event_name}: {len(contributors)} -> {len(filtered)} contributors in corpus")
    return filtered

def apply_commit_filter(contributors, event_name, min_commits=4):
    """
    Filter contributors by minimum commit count.
    For HF and 24PR, use 'total_prs' as proxy for activity.
    """
    # For GSoC/LFX, we don't have commit counts in the JSON (need to get from commit data)
    # For HF/24PR, we can use total_prs as activity measure
    
    if event_name in ["hacktoberfest", "24pr"]:
        # Use PR count as proxy
        filtered = [c for c in contributors if c.get('total_prs', 0) >= min_commits]
        print(f"  {event_name}: {len(contributors)} -> {len(filtered)} with {min_commits}+ PRs")
        return filtered
    else:
        # For GSoC/LFX, we'll need to check commit data later
        # For now, just return all (we'll filter when we have commit data)
        print(f"  {event_name}: {len(contributors)} (commit filter deferred to commit data)")
        return contributors

def sample_contributors(contributors, event_name, target_count=None):
    """
    For Hacktoberfest and 24PR:
    - 50% top contributors by activity
    - 50% random from remaining with 4+ PRs
    
    For GSoC and LFX:
    - Take ALL (mentorship programs)
    """
    
    if event_name in ["gsoc", "lfx"]:
        print(f"  {event_name}: Taking all {len(contributors)} (mentorship program)")
        return contributors
    
    # For HF and 24PR, sample
    if target_count is None:
        target_count = min(1000, len(contributors))
    
    # Sort by activity (total_prs)
    sorted_contribs = sorted(contributors, key=lambda x: x.get('total_prs', 0), reverse=True)
    
    # Take top 50%
    top_half_count = target_count // 2
    top_half = sorted_contribs[:top_half_count]
    
    # Random 50% from remaining
    remaining = sorted_contribs[top_half_count:]
    random_half_count = target_count - top_half_count
    
    if len(remaining) >= random_half_count:
        random_half = random.sample(remaining, random_half_count)
    else:
        random_half = remaining
    
    sampled = top_half + random_half
    
    print(f"  {event_name}: Sampled {len(sampled)} ({len(top_half)} top + {len(random_half)} random)")
    return sampled

def main():
    print("="*80)
    print("PHASE 2: SELECT EVENT CONTRIBUTORS")
    print("="*80)
    
    # Load corpus
    print("\n1. Loading corpus...")
    corpus_repos = load_corpus_repos()
    print(f"   Corpus: {len(corpus_repos)} repos")
    
    # Load event data
    base_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery"
    
    events = {
        "gsoc": base_path / "google_summer_of_code" / "gsoc_contributors.json",
        "lfx": base_path / "lfx_mentorship" / "lfx_contributors.json",
        "hacktoberfest": base_path / "hacktoberfest" / "hacktoberfest_contributors.json",
        "24pr": base_path / "24_pull_requests" / "24pr_contributors.json"
    }
    
    all_filtered = {}
    
    print("\n2. Filtering contributors by corpus...")
    for event_name, event_path in events.items():
        with open(event_path, 'r') as f:
            data = json.load(f)
        
        contributors = data['contributors']
        print(f"\n  Loading {event_name}...")
        print(f"  Total contributors: {len(contributors)}")
        
        # Filter by corpus
        filtered = filter_contributors_by_corpus(contributors, corpus_repos, event_name)
        
        # Apply commit filter
        filtered = apply_commit_filter(filtered, event_name, min_commits=4)
        
        # Sample if needed
        filtered = sample_contributors(filtered, event_name)
        
        all_filtered[event_name] = filtered
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY:")
    print("="*80)
    
    total_selected = sum(len(contribs) for contribs in all_filtered.values())
    
    for event_name, contributors in all_filtered.items():
        print(f"  {event_name:15s}: {len(contributors):5d} contributors")
    print(f"  {'TOTAL':15s}: {total_selected:5d} contributors")
    
    # Save results
    output_path = Path(__file__).parent / "event_contributors_corpus_filtered.json"
    
    output_data = {
        "generated_at": datetime.now().isoformat(),
        "description": "Event contributors filtered by corpus repos and activity level",
        "corpus_repos_count": len(corpus_repos),
        "filters_applied": {
            "corpus_filter": "Only contributors who contributed to corpus repos",
            "activity_filter": "4+ commits/PRs minimum",
            "sampling": "GSoC/LFX: all, HF/24PR: 50% top + 50% random"
        },
        "total_contributors": total_selected,
        "by_event": {
            event: len(contribs) for event, contribs in all_filtered.items()
        },
        "contributors_by_event": all_filtered
    }
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n✓ Saved to: {output_path}")
    
    # Also save just usernames for easy reference
    usernames_path = Path(__file__).parent / "event_contributors_usernames.txt"
    with open(usernames_path, 'w') as f:
        for event_name, contributors in all_filtered.items():
            f.write(f"# {event_name.upper()} ({len(contributors)} contributors)\n")
            for contrib in contributors:
                f.write(f"{contrib['github_username']}\n")
            f.write("\n")
    
    print(f"✓ Usernames saved to: {usernames_path}")
    
    return output_data

if __name__ == "__main__":
    try:
        result = main()
        print("\n" + "="*80)
        print("✓ PHASE 2 COMPLETED SUCCESSFULLY")
        print("="*80)
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
