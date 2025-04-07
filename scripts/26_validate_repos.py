#!/usr/bin/env python3
"""
Validate all selected repos exist via API, get sizes, filter out >10GB
"""
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
import ssl

ssl_context = ssl.create_default_context()

def get_repo_info(owner, repo, token):
    """Get repo info from GitHub API"""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'RepoValidator/1.0'
    }
    
    try:
        req = Request(url, headers=headers)
        with urlopen(req, context=ssl_context, timeout=10) as response:
            data = json.loads(response.read().decode())
            return {
                'exists': True,
                'size_kb': data.get('size', 0),
                'size_mb': round(data.get('size', 0) / 1024, 2),
                'size_gb': round(data.get('size', 0) / 1024 / 1024, 2),
                'full_name': data.get('full_name', ''),
                'default_branch': data.get('default_branch', 'main'),
                'archived': data.get('archived', False),
                'disabled': data.get('disabled', False),
                'error': None
            }
    except Exception as e:
        return {
            'exists': False,
            'size_kb': 0,
            'size_mb': 0,
            'size_gb': 0,
            'error': str(e)
        }

def main():
    # Load corpus
    corpus_path = Path(__file__).parent / "corpus_from_healthy.json"
    with open(corpus_path) as f:
        corpus = json.load(f)
    
    # Load token
    config_path = Path(__file__).parent.parent / "05_contributor_journey_extraction/config.json"
    with open(config_path) as f:
        config = json.load(f)
    token = config['github_tokens'][0]
    
    print("="*80)
    print("VALIDATING REPOS")
    print("="*80)
    print(f"\nTotal repos to validate: {len(corpus['repos'])}")
    print(f"Using token: {token[:10]}...")
    
    validated = []
    invalid = []
    too_large = []
    archived_disabled = []
    
    for i, repo in enumerate(corpus['repos'], 1):
        name = repo['repo_name']
        if '/' not in name:
            print(f"\n[{i}/{len(corpus['repos'])}] SKIP: {name} (invalid format)")
            invalid.append({'repo': name, 'reason': 'invalid format'})
            continue
        
        owner, repo_name = name.split('/', 1)
        
        print(f"\n[{i}/{len(corpus['repos'])}] Checking: {name}")
        
        info = get_repo_info(owner, repo_name, token)
        
        if not info['exists']:
            print(f"  ✗ NOT FOUND: {info['error']}")
            invalid.append({'repo': name, 'reason': info['error']})
            continue
        
        if info['archived'] or info['disabled']:
            print(f"  ⚠ ARCHIVED/DISABLED")
            archived_disabled.append({
                'repo': name,
                'archived': info['archived'],
                'disabled': info['disabled']
            })
            continue
        
        if info['size_gb'] > 10:
            print(f"  ✗ TOO LARGE: {info['size_gb']:.2f} GB")
            too_large.append({
                'repo': name,
                'size_gb': info['size_gb']
            })
            continue
        
        print(f"  ✓ OK: {info['size_mb']:.2f} MB")
        
        validated.append({
            **repo,
            'size_kb': info['size_kb'],
            'size_mb': info['size_mb'],
            'size_gb': info['size_gb'],
            'default_branch': info['default_branch']
        })
        
        time.sleep(0.1)  # Be nice to API
    
    # Sort by size (smallest first)
    validated.sort(key=lambda x: x['size_mb'])
    
    # Save validated corpus
    output = {
        'generated_at': corpus['generated_at'],
        'validated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'description': 'Validated corpus: repos exist, not archived, under 10GB, sorted by size',
        'total_repos': len(validated),
        'invalid_count': len(invalid),
        'too_large_count': len(too_large),
        'archived_disabled_count': len(archived_disabled),
        'repos': validated
    }
    
    output_path = Path(__file__).parent / "corpus_validated.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Save issues
    issues = {
        'invalid': invalid,
        'too_large': too_large,
        'archived_disabled': archived_disabled
    }
    
    issues_path = Path(__file__).parent / "validation_issues.json"
    with open(issues_path, 'w') as f:
        json.dump(issues, f, indent=2)
    
    # Print summary
    print(f"\n{'='*80}")
    print("VALIDATION SUMMARY")
    print("="*80)
    print(f"Total checked: {len(corpus['repos'])}")
    print(f"  ✓ Valid: {len(validated)}")
    print(f"  ✗ Invalid/Not found: {len(invalid)}")
    print(f"  ✗ Too large (>10GB): {len(too_large)}")
    print(f"  ⚠ Archived/Disabled: {len(archived_disabled)}")
    
    if validated:
        sizes = [r['size_mb'] for r in validated]
        print(f"\nSize range: {min(sizes):.2f} MB to {max(sizes):.2f} MB")
        print(f"Smallest 5:")
        for r in validated[:5]:
            print(f"  {r['repo_name']}: {r['size_mb']:.2f} MB")
    
    if too_large:
        print(f"\nToo large repos:")
        for r in too_large:
            print(f"  {r['repo']}: {r['size_gb']:.2f} GB")
    
    print(f"\n✓ Saved validated corpus to: {output_path}")
    print(f"✓ Saved issues to: {issues_path}")

if __name__ == "__main__":
    main()
