#!/usr/bin/env python3
"""
Cleanup and verification before starting new mining:
1. Compare new corpus vs currently mined repos
2. Delete unnecessary repos/CSVs from T7
3. Verify what still needs to be mined
4. Clean up old journey extraction files
"""

import json
import shutil
from pathlib import Path
from datetime import datetime

def load_new_corpus():
    """Load the new 435-project corpus"""
    corpus_path = Path(__file__).parent / "final_corpus_435.json"
    with open(corpus_path, 'r') as f:
        data = json.load(f)
    return {r['repo_name'] for r in data['repos']}

def get_currently_mined_repos():
    """Get list of currently mined repos from T7"""
    t7_base = Path("/Volumes/T7/Event based OSS4SG")
    
    if not t7_base.exists():
        print("ERROR: T7 drive not mounted")
        return set(), set()
    
    # Check cloned repos
    repos_dir = t7_base / "repos"
    cloned = set()
    if repos_dir.exists():
        for repo_dir in repos_dir.iterdir():
            if repo_dir.is_dir() and not repo_dir.name.startswith('.'):
                # Convert back: odoo__odoo -> odoo/odoo
                repo_name = repo_dir.name.replace('__', '/')
                cloned.add(repo_name)
    
    # Check extracted CSVs
    extracted_dir = t7_base / "extracted"
    extracted = set()
    if extracted_dir.exists():
        for csv_file in extracted_dir.glob("*.csv"):
            if csv_file.name != 'all_commits.csv':
                # Convert back: odoo__odoo.csv -> odoo/odoo
                repo_name = csv_file.stem.replace('__', '/')
                extracted.add(repo_name)
    
    return cloned, extracted

def cleanup_unnecessary_repos(new_corpus, currently_cloned, currently_extracted):
    """Delete repos that are not in new corpus"""
    
    print("\n" + "="*80)
    print("CLEANUP ANALYSIS")
    print("="*80)
    
    # Repos to delete
    to_delete_cloned = currently_cloned - new_corpus
    to_delete_extracted = currently_extracted - new_corpus
    
    # Repos to keep
    to_keep_cloned = currently_cloned & new_corpus
    to_keep_extracted = currently_extracted & new_corpus
    
    # Repos still needed
    to_mine = new_corpus - currently_extracted
    
    print(f"\nNew corpus: {len(new_corpus)} repos")
    print(f"Currently cloned: {len(currently_cloned)} repos")
    print(f"Currently extracted: {len(currently_extracted)} CSVs")
    
    print(f"\n{'-'*80}")
    print("CLEANUP PLAN:")
    print(f"  Keep cloned repos: {len(to_keep_cloned)}")
    print(f"  Delete cloned repos: {len(to_delete_cloned)}")
    print(f"  Keep extracted CSVs: {len(to_keep_extracted)}")
    print(f"  Delete extracted CSVs: {len(to_delete_extracted)}")
    
    print(f"\n{'-'*80}")
    print("MINING PLAN:")
    print(f"  Already mined (keep): {len(to_keep_extracted)}")
    print(f"  Need to mine: {len(to_mine)}")
    
    print(f"\n{'-'*80}")
    print("SPACE SAVINGS:")
    print(f"  Will free space by deleting {len(to_delete_cloned)} repos")
    print(f"  and {len(to_delete_extracted)} CSVs")
    print(f"  (Size calculation skipped for speed)")
    
    return {
        'to_delete_cloned': to_delete_cloned,
        'to_delete_extracted': to_delete_extracted,
        'to_keep_extracted': to_keep_extracted,
        'to_mine': to_mine
    }

def perform_cleanup(cleanup_plan, dry_run=False):
    """Actually delete the unnecessary files"""
    
    if dry_run:
        print("\n[DRY RUN - No files will be deleted]")
        return
    
    print("\n" + "="*80)
    print("PERFORMING CLEANUP")
    print("="*80)
    
    t7_base = Path("/Volumes/T7/Event based OSS4SG")
    
    # Delete cloned repos
    print(f"\nDeleting {len(cleanup_plan['to_delete_cloned'])} cloned repos...")
    deleted_cloned = 0
    for repo_name in cleanup_plan['to_delete_cloned']:
        repo_dir = t7_base / "repos" / repo_name.replace('/', '__')
        if repo_dir.exists():
            try:
                shutil.rmtree(repo_dir)
                deleted_cloned += 1
                if deleted_cloned % 10 == 0:
                    print(f"  Deleted {deleted_cloned}/{len(cleanup_plan['to_delete_cloned'])} repos...")
            except Exception as e:
                print(f"  Warning: Could not delete {repo_name}: {e}")
    
    print(f"  Deleted {deleted_cloned} repos")
    
    # Delete extracted CSVs
    print(f"\nDeleting {len(cleanup_plan['to_delete_extracted'])} extracted CSVs...")
    deleted_extracted = 0
    for repo_name in cleanup_plan['to_delete_extracted']:
        csv_file = t7_base / "extracted" / f"{repo_name.replace('/', '__')}.csv"
        if csv_file.exists():
            try:
                csv_file.unlink()
                deleted_extracted += 1
                if deleted_extracted % 10 == 0:
                    print(f"  Deleted {deleted_extracted}/{len(cleanup_plan['to_delete_extracted'])} CSVs...")
            except Exception as e:
                print(f"  Warning: Could not delete {repo_name}.csv: {e}")
    
    print(f"  Deleted {deleted_extracted} CSVs")
    
    # Update progress.json
    progress_file = t7_base / "progress.json"
    if progress_file.exists():
        with open(progress_file, 'r') as f:
            progress = json.load(f)
        
        # Remove deleted repos from progress
        repos_to_remove = cleanup_plan['to_delete_cloned'] | cleanup_plan['to_delete_extracted']
        for repo_name in repos_to_remove:
            if repo_name in progress['repos']:
                del progress['repos'][repo_name]
        
        # Update stats
        progress['stats']['total'] = len(progress['repos'])
        progress['last_updated'] = datetime.now().isoformat()
        
        with open(progress_file, 'w') as f:
            json.dump(progress, f, indent=2)
        
        print(f"\n  Updated progress.json (removed {len(repos_to_remove)} repos)")
    
    print("\n  Cleanup complete")

def cleanup_old_journey_files():
    """Clean up old journey extraction files"""
    
    print("\n" + "="*80)
    print("JOURNEY FILES CLEANUP")
    print("="*80)
    
    journey_dir = Path(__file__).parent.parent / "05_contributor_journey_extraction" / "outputs" / "contributors"
    
    if not journey_dir.exists():
        print("  No old journey files found")
        return
    
    journey_files = list(journey_dir.glob("*_journey.csv"))
    
    print(f"\nFound {len(journey_files)} old journey files")
    print("These will be regenerated with the new 2,678 contributors")
    
    # Don't delete yet - will be overwritten during extraction
    print("  Files will be overwritten during new extraction")
    print("  (Keeping old files as backup until new extraction completes)")

def generate_repos_to_process(to_mine):
    """Generate repos_to_process.json for mining"""
    
    print("\n" + "="*80)
    print("GENERATING REPOS TO PROCESS")
    print("="*80)
    
    # Load full repo data
    consolidated_path = Path(__file__).parent.parent / "03_consolidated_dataset" / "all_event_repos_consolidated.json"
    with open(consolidated_path, 'r') as f:
        data = json.load(f)
    
    repos = data['repos']
    repo_map = {r['repo_name']: r for r in repos}
    
    # Create repos_to_process list
    repos_to_process = []
    for repo_name in sorted(to_mine):
        repo_data = repo_map.get(repo_name, {})
        repos_to_process.append({
            "repo": repo_name,
            "size_kb": 0,  # Unknown until cloned
            "size_mb": 0.0,
            "is_oss4sg": repo_data.get('is_oss4sg', False)
        })
    
    output_data = {
        "generated_at": datetime.now().isoformat(),
        "total_repos": len(repos_to_process),
        "total_size_mb": 0.0,
        "oss4sg_count": sum(1 for r in repos_to_process if r['is_oss4sg']),
        "conventional_count": sum(1 for r in repos_to_process if not r['is_oss4sg']),
        "repos": repos_to_process
    }
    
    # Save to T7
    t7_path = Path("/Volumes/T7/Event based OSS4SG/repos_to_process.json")
    with open(t7_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"  Generated repos_to_process.json")
    print(f"  Location: {t7_path}")
    print(f"  Repos to mine: {len(repos_to_process)}")
    print(f"  OSS4SG: {output_data['oss4sg_count']}")

def main():
    print("="*80)
    print("CLEANUP AND VERIFICATION")
    print("="*80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Load new corpus
    print("\n1. Loading new 435-project corpus...")
    new_corpus = load_new_corpus()
    print(f"   Loaded {len(new_corpus)} repos")
    
    # Get currently mined
    print("\n2. Scanning T7 drive for currently mined repos...")
    currently_cloned, currently_extracted = get_currently_mined_repos()
    print(f"   Found {len(currently_cloned)} cloned repos")
    print(f"   Found {len(currently_extracted)} extracted CSVs")
    
    # Analyze cleanup
    print("\n3. Analyzing cleanup requirements...")
    cleanup_plan = cleanup_unnecessary_repos(new_corpus, currently_cloned, currently_extracted)
    
    # Confirm
    print("\n" + "="*80)
    print("READY TO PROCEED")
    print("="*80)
    print("\nThis will:")
    print(f"  1. Delete {len(cleanup_plan['to_delete_cloned'])} unnecessary cloned repos")
    print(f"  2. Delete {len(cleanup_plan['to_delete_extracted'])} unnecessary CSVs")
    print(f"  3. Keep {len(cleanup_plan['to_keep_extracted'])} already-mined repos")
    print(f"  4. Prepare to mine {len(cleanup_plan['to_mine'])} new repos")
    
    response = input("\nProceed with cleanup? (yes/no): ").strip().lower()
    
    if response == 'yes':
        perform_cleanup(cleanup_plan, dry_run=False)
        cleanup_old_journey_files()
        generate_repos_to_process(cleanup_plan['to_mine'])
        
        print("\n" + "="*80)
        print("CLEANUP COMPLETE")
        print("="*80)
        print("\nSummary:")
        print(f"  Repos ready for mining: {len(cleanup_plan['to_mine'])}")
        print(f"  Repos already mined: {len(cleanup_plan['to_keep_extracted'])}")
        print(f"  Total corpus: {len(new_corpus)}")
        print("\nNext steps:")
        print("  1. Run contributor selection script")
        print("  2. Start commit mining (will mine only the needed repos)")
        print("  3. Start journey extraction")
    else:
        print("\nCleanup cancelled")
    
    return cleanup_plan

if __name__ == "__main__":
    main()
