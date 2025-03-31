#!/usr/bin/env python3
"""
Fix truncated repo names in corpus
"""
import json
from pathlib import Path
from datetime import datetime

def main():
    # Load corpus
    corpus_path = Path(__file__).parent / "final_corpus_435.json"
    with open(corpus_path) as f:
        corpus = json.load(f)
    
    # Load correction map
    with open(Path(__file__).parent / "repo_correction_map.json") as f:
        correction_map = json.load(f)
    
    print("="*80)
    print("FIXING CORPUS")
    print("="*80)
    
    fixed_count = 0
    removed_count = 0
    
    fixed_repos = []
    for repo_entry in corpus['repos']:
        repo_name = repo_entry['repo_name']
        
        # Check if needs correction
        if repo_name in correction_map:
            corrected = correction_map[repo_name]
            if corrected:
                print(f"Fix: {repo_name} → {corrected}")
                repo_entry['repo_name'] = corrected
                fixed_count += 1
                fixed_repos.append(repo_entry)
            else:
                print(f"Remove: {repo_name} (unfixable)")
                removed_count += 1
                # Don't add to fixed_repos
        else:
            fixed_repos.append(repo_entry)
    
    # Check for GitHub-internal in corpus
    github_internal = ['_private/browser', 'auth/github', 'features/actions', 
                       'site-policy/github-terms', 'site-policy/privacy-policies',
                       'get-started/accessibility', 'github/collec', 'user-attachments/assets']
    
    for gi in github_internal:
        found = [r for r in fixed_repos if r['repo_name'] == gi]
        if found:
            print(f"Remove: {gi} (GitHub-internal)")
            fixed_repos = [r for r in fixed_repos if r['repo_name'] != gi]
            removed_count += 1
    
    # Update corpus
    corpus['repos'] = fixed_repos
    corpus['total_repos'] = len(fixed_repos)
    corpus['generated_at'] = datetime.now().isoformat()
    
    # Save
    with open(corpus_path, 'w') as f:
        json.dump(corpus, f, indent=2)
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Original repos: {len(corpus['repos']) + fixed_count + removed_count}")
    print(f"  Fixed truncated: {fixed_count}")
    print(f"  Removed unfixable: {removed_count}")
    print(f"  Final repos: {len(fixed_repos)}")
    
    print(f"\n✓ Updated: {corpus_path}")

if __name__ == "__main__":
    main()
