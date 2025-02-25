#!/usr/bin/env python3
"""
Generate properly formatted repos_to_process.json for the mining script.
Needs to include repo name, size info, and is_oss4sg flag.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def generate_mining_json():
    """Generate repos_to_process.json in correct format"""
    
    # Load repos to mine
    repos_to_mine_path = Path(__file__).parent / "repos_to_mine.json"
    with open(repos_to_mine_path, 'r') as f:
        repos_to_mine = json.load(f)['repos']
    
    # Add odoo/odoo if not in list (it's in corpus but was already mined, just corrupted)
    if "odoo/odoo" not in repos_to_mine:
        repos_to_mine.append("odoo/odoo")
    
    # Load corpus data (has is_oss4sg info)
    corpus_path = Path(__file__).parent / "correct_corpus.json"
    with open(corpus_path, 'r') as f:
        corpus_data = json.load(f)
    
    # Create map of repo -> is_oss4sg
    corpus_map = {repo['repo_name']: repo for repo in corpus_data['repos']}
    
    # Build repos list in correct format
    repos_formatted = []
    for repo_name in repos_to_mine:
        corpus_info = corpus_map.get(repo_name, {})
        
        repos_formatted.append({
            "repo": repo_name,
            "size_kb": 0,  # Unknown - will be determined during cloning
            "size_mb": 0.0,  # Unknown
            "is_oss4sg": corpus_info.get('is_oss4sg', False)
        })
    
    # Create output structure
    output_data = {
        "generated_at": datetime.now().isoformat(),
        "total_repos": len(repos_formatted),
        "total_size_mb": 0.0,  # Unknown until cloned
        "oss4sg_count": sum(1 for r in repos_formatted if r['is_oss4sg']),
        "conventional_count": sum(1 for r in repos_formatted if not r['is_oss4sg']),
        "repos": repos_formatted
    }
    
    # Save to T7 drive
    output_path = Path("/Volumes/T7/Event based OSS4SG/repos_to_process.json")
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"✓ Generated repos_to_process.json")
    print(f"  Path: {output_path}")
    print(f"  Total repos: {len(repos_formatted)}")
    print(f"  OSS4SG: {output_data['oss4sg_count']}")
    print(f"  Conventional: {output_data['conventional_count']}")
    
    return output_data

if __name__ == "__main__":
    try:
        generate_mining_json()
        print("\n✓ Mining JSON generated successfully!")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
