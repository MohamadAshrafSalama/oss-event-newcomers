#!/usr/bin/env python3
"""
Fetch repo sizes and sort by smallest first for faster mining
"""
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import ssl

ssl_context = ssl.create_default_context()

def get_repo_size(owner, repo, token):
    """Get repo size from GitHub API"""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'RepoSizeFetcher/1.0'
    }
    
    try:
        req = Request(url, headers=headers)
        with urlopen(req, context=ssl_context, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data.get('size', 0)  # Size in KB
    except HTTPError as e:
        if e.code == 404:
            return 0
        return 0
    except Exception:
        return 0

def main():
    # Load config for token
    config_path = Path(__file__).parent.parent / "05_contributor_journey_extraction" / "config.json"
    with open(config_path) as f:
        config = json.load(f)
    token = config['github_tokens'][0]
    
    # Load repos to process
    repos_file = Path("/Volumes/T7/Event based OSS4SG/repos_to_process.json")
    with open(repos_file) as f:
        data = json.load(f)
    
    print(f"Fetching sizes for {len(data['repos'])} repos...")
    
    # Fetch sizes
    for i, repo_entry in enumerate(data['repos']):
        repo = repo_entry['repo']
        if '/' not in repo:
            continue
        
        owner, repo_name = repo.split('/', 1)
        size_kb = get_repo_size(owner, repo_name, token)
        
        repo_entry['size_kb'] = size_kb
        repo_entry['size_mb'] = round(size_kb / 1024, 2)
        
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(data['repos'])} - {repo}: {size_kb} KB")
        
        time.sleep(0.1)  # Be nice to API
    
    # Sort by size (smallest first)
    data['repos'].sort(key=lambda x: x['size_mb'])
    
    # Save
    with open(repos_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\nSorted repos by size!")
    print(f"Smallest: {data['repos'][0]['repo']} ({data['repos'][0]['size_mb']} MB)")
    print(f"Largest: {data['repos'][-1]['repo']} ({data['repos'][-1]['size_mb']} MB)")
    print(f"Total size: {sum(r['size_mb'] for r in data['repos']):.1f} MB")

if __name__ == "__main__":
    main()
