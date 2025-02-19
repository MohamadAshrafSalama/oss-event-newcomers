#!/usr/bin/env python3
"""
Compare the correct corpus (448 repos) with currently mined repos (424)
to identify:
1. Repos that need to be mined (in corpus but not mined)
2. Repos unnecessarily mined (mined but not in corpus)
3. Repos correctly mined (in both)
"""

import json
import sys
from pathlib import Path

def load_correct_corpus():
    """Load the correct corpus we just generated"""
    corpus_path = Path(__file__).parent / "correct_corpus.json"
    with open(corpus_path, 'r') as f:
        data = json.load(f)
    return {repo['repo_name'] for repo in data['repos']}

def load_current_mined_repos():
    """Load the list of currently mined repos from T7 drive"""
    # Try to read from progress.json on T7
    t7_progress = Path("/Volumes/T7/Event based OSS4SG/progress.json")
    
    if not t7_progress.exists():
        print("WARNING: Cannot access T7 drive progress.json")
        print("Attempting to read from local reports...")
        
        # Try to find from local verification report
        report_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "reports" / "csv_verification.json"
        if report_path.exists():
            with open(report_path, 'r') as f:
                data = json.load(f)
                return {repo['repo_name'] for repo in data.get('repos', [])}
        else:
            print("ERROR: Cannot find any record of mined repos")
            return set()
    
    with open(t7_progress, 'r') as f:
        progress = json.load(f)
    
    return set(progress['repos'].keys())

def compare_repos():
    """Compare correct corpus with currently mined repos"""
    
    print("="*80)
    print("MINING GAP ANALYSIS")
    print("="*80)
    
    # Load both sets
    correct_corpus = load_correct_corpus()
    currently_mined = load_current_mined_repos()
    
    print(f"\nCorrect corpus repos: {len(correct_corpus)}")
    print(f"Currently mined repos: {len(currently_mined)}")
    
    # Calculate gaps
    repos_to_mine = correct_corpus - currently_mined  # In corpus but not mined
    repos_unnecessary = currently_mined - correct_corpus  # Mined but not in corpus
    repos_correct = correct_corpus & currently_mined  # In both (correctly mined)
    
    print(f"\n{'='*80}")
    print("RESULTS:")
    print(f"{'='*80}")
    print(f"Correctly mined:       {len(repos_correct)} repos ✓")
    print(f"Need to mine:          {len(repos_to_mine)} repos (missing)")
    print(f"Unnecessarily mined:   {len(repos_unnecessary)} repos (extra)")
    
    # Save results
    output_dir = Path(__file__).parent
    
    # Repos to mine
    to_mine_path = output_dir / "repos_to_mine.json"
    with open(to_mine_path, 'w') as f:
        json.dump({
            "count": len(repos_to_mine),
            "repos": sorted(list(repos_to_mine))
        }, f, indent=2)
    print(f"\nRepos to mine saved to: {to_mine_path}")
    
    # Show first 20 repos to mine
    if repos_to_mine:
        print(f"\nFirst 20 repos to mine:")
        for i, repo in enumerate(sorted(list(repos_to_mine))[:20], 1):
            print(f"  {i:3d}. {repo}")
        if len(repos_to_mine) > 20:
            print(f"  ... and {len(repos_to_mine) - 20} more")
    
    # Unnecessary repos
    unnecessary_path = output_dir / "repos_unnecessary.json"
    with open(unnecessary_path, 'w') as f:
        json.dump({
            "count": len(repos_unnecessary),
            "repos": sorted(list(repos_unnecessary))
        }, f, indent=2)
    print(f"\nUnnecessary repos saved to: {unnecessary_path}")
    
    # Show first 20 unnecessary repos
    if repos_unnecessary:
        print(f"\nFirst 20 unnecessarily mined repos:")
        for i, repo in enumerate(sorted(list(repos_unnecessary))[:20], 1):
            print(f"  {i:3d}. {repo}")
        if len(repos_unnecessary) > 20:
            print(f"  ... and {len(repos_unnecessary) - 20} more")
    
    # Correctly mined
    correct_path = output_dir / "repos_correctly_mined.json"
    with open(correct_path, 'w') as f:
        json.dump({
            "count": len(repos_correct),
            "repos": sorted(list(repos_correct))
        }, f, indent=2)
    print(f"\nCorrectly mined repos saved to: {correct_path}")
    
    # Generate new repos_to_process.json for mining
    repos_to_process_path = output_dir / "repos_to_process_new.json"
    with open(repos_to_process_path, 'w') as f:
        json.dump({
            "description": "Repos to mine for correct corpus (only missing ones)",
            "total": len(repos_to_mine),
            "repos": sorted(list(repos_to_mine))
        }, f, indent=2)
    print(f"\nNew repos_to_process.json saved to: {repos_to_process_path}")
    
    print(f"\n{'='*80}")
    print("SUMMARY:")
    print(f"{'='*80}")
    print(f"✓ {len(repos_correct)} repos already mined correctly - no action needed")
    print(f"⚠ {len(repos_to_mine)} repos need to be mined")
    print(f"ℹ {len(repos_unnecessary)} repos were unnecessarily mined (can ignore for now)")
    print(f"\nNext step: Mine the {len(repos_to_mine)} missing repos using clone_and_extract.py")
    
    return {
        "to_mine": len(repos_to_mine),
        "unnecessary": len(repos_unnecessary),
        "correct": len(repos_correct)
    }

if __name__ == "__main__":
    try:
        results = compare_repos()
        print("\n✓ Gap analysis completed successfully!")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error in gap analysis: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
