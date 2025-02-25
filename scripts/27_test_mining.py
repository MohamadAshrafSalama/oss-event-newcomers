#!/usr/bin/env python3
"""
Test mining on 3 small repos before full run
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

def test_clone_extract(repo_name, base_dir):
    """Test clone and extract for one repo"""
    print(f"\n{'='*80}")
    print(f"Testing: {repo_name}")
    print(f"{'='*80}")
    
    owner, repo = repo_name.split('/')
    repo_dir = base_dir / "cloned" / owner / repo
    csv_path = base_dir / "extracted" / f"{owner}__{repo}.csv"
    
    # Clean up if exists
    if repo_dir.exists():
        import shutil
        shutil.rmtree(repo_dir)
    if csv_path.exists():
        csv_path.unlink()
    
    # Clone
    print(f"\n1. Cloning {repo_name}...")
    clone_url = f"https://github.com/{repo_name}.git"
    result = subprocess.run(
        ["git", "clone", "--bare", clone_url, str(repo_dir)],
        capture_output=True,
        text=True,
        timeout=300
    )
    
    if result.returncode != 0:
        print(f"  ✗ Clone failed: {result.stderr}")
        return False
    
    print(f"  ✓ Cloned successfully")
    
    # Extract commits
    print(f"\n2. Extracting commits...")
    git_log_cmd = [
        "git", "--git-dir", str(repo_dir),
        "log", "--all", "--pretty=format:%H|%an|%ae|%at|%s", "--numstat"
    ]
    
    result = subprocess.run(
        git_log_cmd,
        capture_output=True,
        text=True,
        timeout=300
    )
    
    if result.returncode != 0:
        print(f"  ✗ Git log failed: {result.stderr}")
        return False
    
    # Parse and save
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write("commit_hash,author_name,author_email,timestamp,message,files_changed,insertions,deletions\n")
        
        current_commit = None
        files_changed = 0
        insertions = 0
        deletions = 0
        
        for line in result.stdout.split('\n'):
            if '|' in line and not line.startswith('\t'):
                # Commit line
                if current_commit:
                    f.write(f"{current_commit},{files_changed},{insertions},{deletions}\n")
                
                parts = line.split('|')
                if len(parts) >= 5:
                    commit_hash = parts[0]
                    author_name = parts[1].replace(',', ' ')
                    author_email = parts[2]
                    timestamp = parts[3]
                    message = parts[4].replace(',', ' ')[:100]
                    current_commit = f"{commit_hash},{author_name},{author_email},{timestamp},{message}"
                    files_changed = 0
                    insertions = 0
                    deletions = 0
            elif '\t' in line:
                # Stat line
                parts = line.split('\t')
                if len(parts) >= 2:
                    try:
                        insertions += int(parts[0]) if parts[0] != '-' else 0
                        deletions += int(parts[1]) if parts[1] != '-' else 0
                        files_changed += 1
                    except:
                        pass
        
        # Write last commit
        if current_commit:
            f.write(f"{current_commit},{files_changed},{insertions},{deletions}\n")
    
    # Check output
    with open(csv_path) as f:
        lines = f.readlines()
    
    print(f"  ✓ Extracted {len(lines)-1} commits")
    print(f"  ✓ CSV size: {csv_path.stat().st_size / 1024:.2f} KB")
    
    # Show sample
    print(f"\n3. Sample output (first 3 lines):")
    for line in lines[:4]:
        print(f"  {line.strip()}")
    
    return True

def main():
    # Load validated corpus
    corpus_path = Path(__file__).parent / "corpus_validated.json"
    with open(corpus_path) as f:
        corpus = json.load(f)
    
    # Get 3 smallest repos
    test_repos = [r['repo_name'] for r in corpus['repos'][:3]]
    
    print("="*80)
    print("TEST MINING - 3 SMALLEST REPOS")
    print("="*80)
    print(f"\nTest repos:")
    for r in test_repos:
        print(f"  - {r}")
    
    # Test directory
    test_dir = Path(__file__).parent / "test_mining"
    test_dir.mkdir(exist_ok=True)
    
    # Test each
    results = {}
    for repo in test_repos:
        try:
            success = test_clone_extract(repo, test_dir)
            results[repo] = "✓ PASS" if success else "✗ FAIL"
        except Exception as e:
            print(f"\n  ✗ ERROR: {e}")
            results[repo] = f"✗ ERROR: {e}"
    
    # Summary
    print(f"\n{'='*80}")
    print("TEST RESULTS")
    print("="*80)
    for repo, result in results.items():
        print(f"  {repo}: {result}")
    
    passed = sum(1 for r in results.values() if "PASS" in r)
    print(f"\nPassed: {passed}/{len(results)}")
    
    if passed == len(results):
        print(f"\n✓ ALL TESTS PASSED - Ready for full mining")
        return 0
    else:
        print(f"\n✗ SOME TESTS FAILED - Fix issues before full mining")
        return 1

if __name__ == "__main__":
    sys.exit(main())
