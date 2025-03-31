#!/usr/bin/env python3
"""
Create correction map for truncated repo names using GitHub API
"""
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
import ssl

ssl_context = ssl.create_default_context()

def get_repo_info(owner, partial_name, token):
    """Try to find full repo name from GitHub API"""
    # Try direct fetch first (append common suffixes)
    suffixes = ['', 't', 'p', 'i', 'e', 's', 'r', 'x', 'ion', 'er', 'or', 'ing']
    
    for suffix in suffixes:
        full_name = partial_name + suffix
        url = f"https://api.github.com/repos/{owner}/{full_name}"
        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'RepoCorrectionFinder/1.0'
        }
        
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=10) as response:
                data = json.loads(response.read().decode())
                return data['full_name'].split('/', 1)[1]  # Return just repo name
        except:
            pass
        
        time.sleep(0.1)
    
    return None

def main():
    # Load config for token
    config_path = Path(__file__).parent.parent / "05_contributor_journey_extraction" / "config.json"
    with open(config_path) as f:
        config = json.load(f)
    token = config['github_tokens'][0]
    
    # Load analysis
    with open(Path(__file__).parent / "invalid_repos_analysis.json") as f:
        analysis = json.load(f)
    
    truncated = analysis['truncated'] + analysis['other']
    
    print("="*80)
    print("CREATING CORRECTION MAP")
    print("="*80)
    
    correction_map = {}
    
    for repo in sorted(truncated):
        if '/' not in repo:
            continue
        
        owner, partial = repo.split('/', 1)
        
        print(f"\nChecking: {repo}")
        
        # Try to find full name
        full_name = get_repo_info(owner, partial, token)
        
        if full_name:
            full_repo = f"{owner}/{full_name}"
            correction_map[repo] = full_repo
            print(f"  ✓ Found: {full_repo}")
        else:
            correction_map[repo] = None
            print(f"  ✗ Could not find")
        
        time.sleep(0.5)  # Be nice to API
    
    # Manual corrections for known cases
    manual_corrections = {
        'rust-lang/rus': 'rust-lang/rust',
        'godotengine/godo': 'godotengine/godot',
        'rocketchat/rocket.cha': 'rocketchat/rocket.chat',
        'apache/finerac': 'apache/fineract',
        'llvm/llvm-projec': 'llvm/llvm-project',
        'google/googletes': 'google/googletest',
        'openmf/android-clien': 'openmf/android-client',
        'openmf/mobile-walle': 'openmf/mobile-wallet',
        'openmf/fineract-clien': 'openmf/fineract-client',
        'palisadoesfoundation/talawa-ap': 'palisadoesfoundation/talawa-api',
        'philjay/mpandroidchar': 'philjay/mpandroidchart',
        'root-project/roo': 'root-project/root',
        'rubygems/rubygems.or': 'rubygems/rubygems.org',
        'apple/swif': 'apple/swift',
        'angular/flex-layou': 'angular/flex-layout',
        'ankitects/ank': 'ankitects/anki',
        'bkimminich/juice-shop': 'bkimminich/juice-shop',  # Already correct
        'blazma/hippoun': 'blazma/hippounmtb',
        'openmined/pysyf': 'openmined/pysyft',
        'openroberta/robertalab': 'openroberta/robertalab',  # Might be archived
        'fossasia/susi_fbbo': 'fossasia/susi_fbbot',
        'fossasia/susi_gitterbo': 'fossasia/susi_gitterbot',
        'fossasia/susi_kikbo': 'fossasia/susi_kikbot',
        'fossasia/susi_linebo': 'fossasia/susi_linebot',
        'fossasia/susi_slackbo': 'fossasia/susi_slackbot',
        'fossasia/susi_tweetbo': 'fossasia/susi_twitterbot',
        'fossasia/apps.loklak.or': 'fossasia/apps.loklak.org',
        'fossasia/chat.susi.a': 'fossasia/chat.susi.ai',
        'fossasia/open-even': 'fossasia/open-event',
        'fossasia/susi.a': 'fossasia/susi.ai',
        'fossasia/accounts.susi.a': 'fossasia/accounts.susi.ai',
        'milibris/flask-rest-jsonap': 'milibris/flask-rest-jsonapi',
        'rocketchat/rocket.chat.livecha': 'rocketchat/rocket.chat.livechat',
        'zulip/python-zulip-ap': 'zulip/python-zulip-api',
        'articles/which-remote-url-should-i-use': None  # GitHub docs, not a repo
    }
    
    # Merge with manual corrections
    correction_map.update(manual_corrections)
    
    # Save
    output_path = Path(__file__).parent / "repo_correction_map.json"
    with open(output_path, 'w') as f:
        json.dump(correction_map, f, indent=2)
    
    print(f"\n{'='*80}")
    print("CORRECTION MAP SUMMARY")
    print("="*80)
    
    fixable = sum(1 for v in correction_map.values() if v is not None)
    unfixable = sum(1 for v in correction_map.values() if v is None)
    
    print(f"Total truncated repos: {len(correction_map)}")
    print(f"  Fixable: {fixable}")
    print(f"  Unfixable: {unfixable}")
    
    if unfixable > 0:
        print(f"\nUnfixable repos:")
        for k, v in correction_map.items():
            if v is None:
                print(f"  - {k}")
    
    print(f"\nSaved to: {output_path}")

if __name__ == "__main__":
    main()
