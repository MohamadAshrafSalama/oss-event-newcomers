#!/usr/bin/env python3
"""
Generate the correct project corpus:
- Top 385 repos by GSoC contributor count
- All OSS4SG projects (73 from consolidated data)
- Remove duplicates, save to JSON
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def load_all_event_repos():
    """Load the consolidated event repos data"""
    file_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    
    print(f"Loading event repos from: {file_path}")
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    print(f"Total repos in file: {data['total_repos']}")
    print(f"Total OSS4SG repos: {data['total_oss4sg']}")
    
    return data['repos']

def generate_corpus():
    """Generate the correct project corpus"""
    
    # Load all repos
    all_repos = load_all_event_repos()
    
    # Step 1: Filter repos with GSoC contributors
    gsoc_repos = [r for r in all_repos if r.get('gsoc_contributors', 0) > 0]
    print(f"\nRepos with GSoC contributors: {len(gsoc_repos)}")
    
    # Step 2: Sort by GSoC contributor count (descending)
    gsoc_repos.sort(key=lambda x: x['gsoc_contributors'], reverse=True)
    
    # Step 3: Take top 385
    top_385_gsoc = gsoc_repos[:385]
    print(f"Top 385 GSoC repos selected")
    print(f"  - Top repo: {top_385_gsoc[0]['repo_name']} ({top_385_gsoc[0]['gsoc_contributors']} GSoC contributors)")
    print(f"  - 385th repo: {top_385_gsoc[384]['repo_name']} ({top_385_gsoc[384]['gsoc_contributors']} GSoC contributors)")
    
    # Step 4: Get all OSS4SG projects
    oss4sg_repos = [r for r in all_repos if r.get('is_oss4sg', False)]
    print(f"\nTotal OSS4SG repos: {len(oss4sg_repos)}")
    
    # Step 5: Find OSS4SG repos NOT in top 385 GSoC
    top_385_names = {r['repo_name'] for r in top_385_gsoc}
    oss4sg_not_in_top = [r for r in oss4sg_repos if r['repo_name'] not in top_385_names]
    
    print(f"OSS4SG repos already in top 385 GSoC: {len(oss4sg_repos) - len(oss4sg_not_in_top)}")
    print(f"OSS4SG repos to add: {len(oss4sg_not_in_top)}")
    
    # Step 6: Combine
    final_corpus = top_385_gsoc + oss4sg_not_in_top
    
    print(f"\n{'='*60}")
    print(f"FINAL CORPUS")
    print(f"{'='*60}")
    print(f"Total repos: {len(final_corpus)}")
    print(f"  - Top 385 GSoC: 385")
    print(f"  - Additional OSS4SG: {len(oss4sg_not_in_top)}")
    print(f"  - OSS4SG overlap with top 385: {len(oss4sg_repos) - len(oss4sg_not_in_top)}")
    
    # Calculate statistics
    total_gsoc_contributors = sum(r['gsoc_contributors'] for r in final_corpus)
    total_event_contributors = sum(r['total_event_contributors'] for r in final_corpus)
    oss4sg_count = sum(1 for r in final_corpus if r['is_oss4sg'])
    
    print(f"\nStatistics:")
    print(f"  - Total GSoC contributors: {total_gsoc_contributors}")
    print(f"  - Total event contributors: {total_event_contributors}")
    print(f"  - OSS4SG projects in corpus: {oss4sg_count}")
    
    # Step 7: Save to file
    output_data = {
        "generated_at": datetime.now().isoformat(),
        "description": "Correct project corpus: top 385 repos by GSoC contributors + all OSS4SG projects",
        "selection_criteria": {
            "top_gsoc_count": 385,
            "oss4sg_added": len(oss4sg_not_in_top),
            "oss4sg_overlap": len(oss4sg_repos) - len(oss4sg_not_in_top)
        },
        "total_repos": len(final_corpus),
        "statistics": {
            "total_gsoc_contributors": total_gsoc_contributors,
            "total_event_contributors": total_event_contributors,
            "oss4sg_count": oss4sg_count
        },
        "repos": final_corpus
    }
    
    output_path = Path(__file__).parent.parent / "scripts" / "correct_corpus.json"
    output_path.parent.mkdir(exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Corpus saved to: {output_path}")
    print(f"{'='*60}")
    
    # Also save just the repo names for easy processing
    repo_names_path = Path(__file__).parent.parent / "scripts" / "correct_corpus_repo_names.txt"
    with open(repo_names_path, 'w') as f:
        for repo in final_corpus:
            f.write(f"{repo['repo_name']}\n")
    
    print(f"Repo names list saved to: {repo_names_path}")
    
    return output_data

if __name__ == "__main__":
    try:
        corpus = generate_corpus()
        print("\n✓ Corpus generation completed successfully!")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error generating corpus: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
