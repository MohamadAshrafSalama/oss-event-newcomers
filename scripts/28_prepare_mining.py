#!/usr/bin/env python3
"""
Prepare repos_to_process.json for mining validated corpus
"""
import json
from pathlib import Path
from datetime import datetime

def main():
    # Load validated corpus
    corpus_path = Path(__file__).parent / "corpus_validated.json"
    with open(corpus_path) as f:
        corpus = json.load(f)
    
    # Check what's already mined on T7
    t7_extracted = Path("/Volumes/T7/Event based OSS4SG/extracted")
    already_mined = set()
    
    if t7_extracted.exists():
        for csv_file in t7_extracted.glob("*.csv"):
            if csv_file.stat().st_size > 100:  # Non-empty
                repo_name = csv_file.stem.replace('__', '/')
                already_mined.add(repo_name)
    
    print("="*80)
    print("PREPARING MINING LIST")
    print("="*80)
    print(f"\nTotal repos in corpus: {len(corpus['repos'])}")
    print(f"Already mined: {len(already_mined)}")
    
    # Find repos to mine
    to_mine = []
    for repo in corpus['repos']:
        name = repo['repo_name']
        if name not in already_mined:
            to_mine.append({
                'repo': name,
                'size_kb': 0,
                'size_mb': 0,
                'is_oss4sg': repo.get('is_oss4sg', False),
                'commits': repo.get('commits', 0)
            })
    
    # Already sorted by commits in corpus_validated.json
    print(f"Need to mine: {len(to_mine)}")
    
    # Save to T7
    output = {
        'generated_at': datetime.now().isoformat(),
        'description': 'Repos to mine from validated healthy corpus, sorted by commits (smallest first)',
        'total_repos': len(to_mine),
        'oss4sg_count': sum(1 for r in to_mine if r.get('is_oss4sg')),
        'repos': to_mine
    }
    
    output_path = Path("/Volumes/T7/Event based OSS4SG/repos_to_process.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Reset progress.json
    progress = {
        'started_at': datetime.now().isoformat(),
        'stats': {
            'total': len(to_mine),
            'cloned': 0,
            'extracted': 0,
            'errors': 0
        },
        'repos': {r['repo']: {'status': 'pending'} for r in to_mine},
        'errors': []
    }
    
    progress_path = Path("/Volumes/T7/Event based OSS4SG/progress.json")
    with open(progress_path, 'w') as f:
        json.dump(progress, f, indent=2)
    
    # Print info
    print(f"\n{'='*80}")
    print("MINING SETUP READY")
    print("="*80)
    print(f"Repos to mine: {len(to_mine)}")
    print(f"Already mined (will keep): {len(already_mined)}")
    print(f"Total after mining: {len(corpus['repos'])}")
    
    if to_mine:
        print(f"\nFirst 5 to mine:")
        for r in to_mine[:5]:
            print(f"  {r['repo']}: {r['commits']:,} commits")
    
    print(f"\n✓ Saved to: {output_path}")
    print(f"✓ Reset progress: {progress_path}")

if __name__ == "__main__":
    main()
