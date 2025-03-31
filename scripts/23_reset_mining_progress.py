#!/usr/bin/env python3
"""
Reset mining progress for corrected repos and update repos_to_process
"""
import json
from pathlib import Path
from datetime import datetime

def main():
    # Load corrected corpus
    with open(Path(__file__).parent / "final_corpus_435.json") as f:
        corpus = json.load(f)
    corpus_repos = {r['repo_name'] for r in corpus['repos']}
    
    print("="*80)
    print("RESETTING MINING PROGRESS")
    print("="*80)
    print(f"Corrected corpus: {len(corpus_repos)} repos")
    
    # Check what's already mined
    csv_dir = Path("/Volumes/T7/Event based OSS4SG/extracted")
    already_mined = set()
    if csv_dir.exists():
        for f in csv_dir.glob("*.csv"):
            if f.stat().st_size > 0:
                repo = f.stem.replace('__', '/')
                already_mined.add(repo)
    
    # Find repos to mine
    to_mine = corpus_repos - already_mined
    
    print(f"\nAlready mined: {len(already_mined)} repos")
    print(f"Need to mine: {len(to_mine)} repos")
    
    # Create new repos_to_process.json
    repos_list = []
    for repo in sorted(to_mine):
        repos_list.append({
            'repo': repo,
            'size_kb': 0,
            'size_mb': 0,
            'is_oss4sg': False
        })
    
    output = {
        'generated_at': datetime.now().isoformat(),
        'description': 'Repos to mine after corrections',
        'total_repos': len(repos_list),
        'oss4sg_count': 0,
        'repos': repos_list
    }
    
    # Save
    output_path = Path("/Volumes/T7/Event based OSS4SG/repos_to_process.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n✓ Updated repos_to_process.json: {len(repos_list)} repos to mine")
    
    # Reset progress.json
    repos_status = {}
    for repo in to_mine:
        repos_status[repo] = {'status': 'pending'}
    
    progress = {
        'started_at': datetime.now().isoformat(),
        'stats': {
            'total': len(to_mine),
            'cloned': 0,
            'extracted': 0,
            'errors': 0
        },
        'repos': repos_status,
        'errors': []
    }
    
    progress_path = Path("/Volumes/T7/Event based OSS4SG/progress.json")
    with open(progress_path, 'w') as f:
        json.dump(progress, f, indent=2)
    
    print(f"✓ Reset progress.json for {len(to_mine)} repos")
    
    print(f"\n{'='*80}")
    print(f"READY TO RESUME MINING")
    print(f"{'='*80}")
    print(f"Corpus: {len(corpus_repos)} repos")
    print(f"Already done: {len(already_mined)} repos")
    print(f"To mine: {len(to_mine)} repos")

if __name__ == "__main__":
    main()
