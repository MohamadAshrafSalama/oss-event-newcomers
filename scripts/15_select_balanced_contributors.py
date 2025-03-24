#!/usr/bin/env python3
"""
Select 2,678 balanced contributors from new corpus.
"""

import json
import random
from pathlib import Path
from datetime import datetime
from collections import defaultdict

random.seed(42)

def load_corpus():
    corpus_path = Path(__file__).parent / "final_corpus_435.json"
    with open(corpus_path, 'r') as f:
        data = json.load(f)
    return {r['repo_name'] for r in data['repos']}

def filter_by_corpus(contributors, corpus_repos):
    filtered = []
    for c in contributors:
        contrib_repos = set(c.get('repos_contributed', []))
        if contrib_repos & corpus_repos:
            c_copy = c.copy()
            c_copy['corpus_repos'] = sorted(list(contrib_repos & corpus_repos))
            filtered.append(c_copy)
    return filtered

def select_gsoc(corpus_repos):
    base_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery"
    gsoc_path = base_path / "google_summer_of_code" / "gsoc_contributors.json"
    
    with open(gsoc_path, 'r') as f:
        data = json.load(f)
    
    # Filter by corpus
    filtered = filter_by_corpus(data['contributors'], corpus_repos)
    
    # Filter by 2+ repos
    filtered_2plus = [c for c in filtered if c.get('repo_count', 0) >= 2]
    
    print(f"GSoC: {len(data['contributors'])} -> {len(filtered)} in corpus -> {len(filtered_2plus)} with 2+ repos")
    
    return filtered_2plus

def select_lfx(corpus_repos):
    base_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery"
    lfx_path = base_path / "lfx_mentorship" / "lfx_contributors.json"
    
    with open(lfx_path, 'r') as f:
        data = json.load(f)
    
    # Filter by corpus
    filtered = filter_by_corpus(data['contributors'], corpus_repos)
    
    print(f"LFX: {len(data['contributors'])} -> {len(filtered)} in corpus (no filter)")
    
    return filtered

def select_24pr(corpus_repos):
    base_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery"
    pr24_path = base_path / "24_pull_requests" / "24pr_contributors.json"
    
    with open(pr24_path, 'r') as f:
        data = json.load(f)
    
    # Filter by corpus
    filtered = filter_by_corpus(data['contributors'], corpus_repos)
    
    # Filter by 4+ PRs
    filtered_4plus = [c for c in filtered if c.get('total_prs', 0) >= 4]
    
    print(f"24PR: {len(data['contributors'])} -> {len(filtered)} in corpus -> {len(filtered_4plus)} with 4+ PRs")
    
    return filtered_4plus

def select_hacktoberfest(corpus_repos, target=860):
    base_path = Path(__file__).parent.parent / "02_event_data_extraction_and_contributor_discovery"
    hf_path = base_path / "hacktoberfest" / "hacktoberfest_contributors.json"
    
    with open(hf_path, 'r') as f:
        data = json.load(f)
    
    # Filter by corpus
    filtered = filter_by_corpus(data['contributors'], corpus_repos)
    
    # Filter by 4+ PRs
    filtered_4plus = [c for c in filtered if c.get('total_prs', 0) >= 4]
    
    # Sort by PR count
    filtered_4plus.sort(key=lambda x: x.get('total_prs', 0), reverse=True)
    
    # Sample: 50% top + 50% random
    top_half = target // 2
    top_contributors = filtered_4plus[:top_half]
    
    remaining = filtered_4plus[top_half:]
    random_half = target - top_half
    
    if len(remaining) >= random_half:
        random_contributors = random.sample(remaining, random_half)
    else:
        random_contributors = remaining
    
    selected = top_contributors + random_contributors
    
    print(f"Hacktoberfest: {len(data['contributors'])} -> {len(filtered)} in corpus -> {len(filtered_4plus)} with 4+ PRs")
    print(f"  Sampled: {len(selected)} ({len(top_contributors)} top + {len(random_contributors)} random)")
    
    return selected

def main():
    print("="*80)
    print("BALANCED CONTRIBUTOR SELECTION")
    print("="*80)
    
    # Load corpus
    corpus_repos = load_corpus()
    print(f"\nCorpus: {len(corpus_repos)} repos")
    
    # Select from each event
    print("\nSelecting contributors:")
    gsoc = select_gsoc(corpus_repos)
    lfx = select_lfx(corpus_repos)
    pr24 = select_24pr(corpus_repos)
    hf = select_hacktoberfest(corpus_repos, target=860)
    
    # Combine
    all_contributors = gsoc + lfx + pr24 + hf
    
    print(f"\n{'='*80}")
    print("FINAL SELECTION:")
    print(f"{'='*80}")
    print(f"  GSoC:          {len(gsoc):5d}")
    print(f"  LFX:           {len(lfx):5d}")
    print(f"  24PR:          {len(pr24):5d}")
    print(f"  Hacktoberfest: {len(hf):5d}")
    print(f"  {'-'*30}")
    print(f"  TOTAL:         {len(all_contributors):5d}")
    
    # Save
    output_data = {
        "generated_at": datetime.now().isoformat(),
        "description": "Balanced event contributors from 435-project corpus",
        "total_contributors": len(all_contributors),
        "by_event": {
            "gsoc": len(gsoc),
            "lfx": len(lfx),
            "24pr": len(pr24),
            "hacktoberfest": len(hf)
        },
        "contributors": all_contributors
    }
    
    output_path = Path(__file__).parent.parent / "04_contributor_selection_and_organic_matching" / "outputs" / "event_contributors_final.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nSaved to: {output_path}")
    print("\nReady for journey extraction!")

if __name__ == "__main__":
    main()
