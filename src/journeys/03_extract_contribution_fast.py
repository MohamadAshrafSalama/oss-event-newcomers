#!/usr/bin/env python3
"""
Fast contribution extraction using regular API (5000/hr) not Search API (30/min).
Extracts: PRs, Issues for each (person, project) pair.
NO commits - join from cloned repos later.
"""

import json
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import ssl

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ssl_context = ssl.create_default_context()


class TokenManager:
    """Manage 10 tokens efficiently"""
    
    def __init__(self, tokens):
        self.tokens = tokens
        self.states = {t: {'remaining': 5000, 'reset': 0} for t in tokens}
        self.lock = Lock()
        self.idx = 0
    
    def get_token(self):
        with self.lock:
            # Round robin with rate limit check
            for _ in range(len(self.tokens)):
                token = self.tokens[self.idx]
                self.idx = (self.idx + 1) % len(self.tokens)
                
                state = self.states[token]
                if state['remaining'] > 10:
                    return token
                elif state['reset'] > 0 and time.time() > state['reset']:
                    state['remaining'] = 5000
                    return token
            
            # All low - wait for first reset
            min_reset = min(s['reset'] for s in self.states.values() if s['reset'] > 0)
            if min_reset > 0:
                wait = max(0, min_reset - time.time()) + 2
                if wait > 0 and wait < 3600:
                    logger.info(f"Tokens low, waiting {wait:.0f}s")
                    time.sleep(wait)
            
            # Reset all and return first
            for t in self.tokens:
                self.states[t]['remaining'] = 5000
            return self.tokens[0]
    
    def update(self, token, remaining, reset):
        with self.lock:
            self.states[token]['remaining'] = remaining
            self.states[token]['reset'] = reset


class Progress:
    """Track progress with resume"""
    
    def __init__(self, path):
        self.path = Path(path)
        self.lock = Lock()
        self.data = self._load()
    
    def _load(self):
        if self.path.exists():
            with open(self.path) as f:
                return json.load(f)
        return {'completed': set(), 'errors': []}
    
    def _save(self):
        save_data = {
            'completed': list(self.data['completed']),
            'errors': self.data['errors'],
            'updated': datetime.now().isoformat()
        }
        with open(self.path, 'w') as f:
            json.dump(save_data, f)
    
    def is_done(self, cid):
        return cid in self.data['completed']
    
    def done(self, cid):
        with self.lock:
            self.data['completed'].add(cid)
            if len(self.data['completed']) % 100 == 0:
                self._save()
    
    def error(self, cid, err):
        with self.lock:
            self.data['errors'].append({'id': cid, 'error': str(err)[:200]})
    
    def save(self):
        with self.lock:
            self._save()
    
    def count(self):
        return len(self.data['completed'])


def api_get(url, token, token_mgr, retries=3):
    """Make API request"""
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Extractor/1.0'
    }
    
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=30) as resp:
                remaining = int(resp.headers.get('X-RateLimit-Remaining', 5000))
                reset = int(resp.headers.get('X-RateLimit-Reset', 0))
                token_mgr.update(token, remaining, reset)
                return json.loads(resp.read().decode())
        
        except HTTPError as e:
            if e.code == 404:
                return None
            elif e.code == 403:
                reset = int(e.headers.get('X-RateLimit-Reset', 0))
                wait = max(0, reset - time.time()) + 2
                logger.debug(f"Rate limit, wait {wait:.0f}s")
                time.sleep(min(wait, 60))
            elif e.code in [500, 502, 503]:
                time.sleep(2 ** attempt)
            else:
                return None
        except Exception:
            time.sleep(2 ** attempt)
    
    return None


def get_user_prs(owner, repo, username, token, token_mgr):
    """Get PRs by user in repo"""
    # Get all PRs (paginated) and filter by author
    prs = []
    page = 1
    while page <= 10:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=all&per_page=100&page={page}"
        data = api_get(url, token, token_mgr)
        if not data:
            break
        
        for pr in data:
            if pr.get('user', {}).get('login', '').lower() == username.lower():
                prs.append({
                    'number': pr['number'],
                    'title': pr['title'][:100],
                    'state': pr['state'],
                    'created_at': pr['created_at'],
                    'merged_at': pr.get('merged_at')
                })
        
        if len(data) < 100:
            break
        page += 1
    
    return prs


def get_user_issues(owner, repo, username, token, token_mgr):
    """Get issues by user in repo"""
    issues = []
    page = 1
    while page <= 10:
        url = f"https://api.github.com/repos/{owner}/{repo}/issues?state=all&per_page=100&page={page}"
        data = api_get(url, token, token_mgr)
        if not data:
            break
        
        for issue in data:
            # Skip PRs (they appear in issues endpoint)
            if 'pull_request' in issue:
                continue
            if issue.get('user', {}).get('login', '').lower() == username.lower():
                issues.append({
                    'number': issue['number'],
                    'title': issue['title'][:100],
                    'state': issue['state'],
                    'created_at': issue['created_at'],
                    'comments': issue.get('comments', 0)
                })
        
        if len(data) < 100:
            break
        page += 1
    
    return issues


def extract_one(contrib, token_mgr, output_dir):
    """Extract one contribution"""
    username = contrib['github_username']
    repo = contrib['repo']
    event = contrib['event']
    cid = contrib['contribution_id']
    
    if '/' not in repo:
        return {'prs': 0, 'issues': 0}
    
    owner, repo_name = repo.split('/', 1)
    token = token_mgr.get_token()
    
    # Get PRs and Issues
    prs = get_user_prs(owner, repo_name, username, token, token_mgr)
    issues = get_user_issues(owner, repo_name, username, token, token_mgr)
    
    result = {
        'contribution_id': cid,
        'github_username': username,
        'repo': repo,
        'event': event,
        'extracted_at': datetime.now().isoformat(),
        'pull_requests': prs,
        'issues': issues,
        'summary': {
            'total_prs': len(prs),
            'total_issues': len(issues)
        }
    }
    
    # Save
    out_file = output_dir / f"{cid}.json"
    with open(out_file, 'w') as f:
        json.dump(result, f)
    
    return result['summary']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--workers', type=int, default=10)
    args = parser.parse_args()
    
    base = Path(__file__).parent.parent
    
    # Config
    with open(Path(__file__).parent / "config.json") as f:
        config = json.load(f)
    tokens = config['github_tokens']
    
    # Contributions
    with open(base / "04_contributor_selection_and_organic_matching/outputs/contributions_final.json") as f:
        data = json.load(f)
    contributions = data['contributions']
    
    logger.info("="*70)
    logger.info("CONTRIBUTION EXTRACTION (Fast - Regular API)")
    logger.info("="*70)
    logger.info(f"Total: {len(contributions)}")
    logger.info(f"By event: {data['by_event']}")
    logger.info(f"Tokens: {len(tokens)}, Workers: {args.workers}")
    
    # Setup
    output_dir = Path(__file__).parent / "contributions"
    output_dir.mkdir(exist_ok=True)
    
    progress_file = Path(__file__).parent / "progress" / "contribution_progress.json"
    progress_file.parent.mkdir(exist_ok=True)
    
    token_mgr = TokenManager(tokens)
    progress = Progress(progress_file)
    
    # Filter
    to_do = [c for c in contributions if not progress.is_done(c['contribution_id'])]
    
    logger.info(f"Done: {progress.count()}, Todo: {len(to_do)}")
    
    if args.test:
        to_do = to_do[:10]
        logger.info(f"TEST: {len(to_do)}")
    
    if not to_do:
        logger.info("Nothing to do!")
        return
    
    # Process
    done = 0
    errors = 0
    start = time.time()
    
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(extract_one, c, token_mgr, output_dir): c for c in to_do}
        
        for f in as_completed(futures):
            c = futures[f]
            cid = c['contribution_id']
            
            try:
                summary = f.result()
                progress.done(cid)
                done += 1
                
                if done % 50 == 0:
                    elapsed = time.time() - start
                    rate = done / elapsed * 60
                    remaining = len(to_do) - done
                    eta = remaining / (done / elapsed) if done > 0 else 0
                    logger.info(f"{done}/{len(to_do)} ({done/len(to_do)*100:.1f}%) | {rate:.0f}/min | ETA: {eta/60:.0f}m")
            
            except Exception as e:
                progress.error(cid, e)
                errors += 1
    
    progress.save()
    
    elapsed = time.time() - start
    logger.info("="*70)
    logger.info(f"DONE: {done}, Errors: {errors}, Time: {elapsed/60:.1f}m")
    logger.info("="*70)


if __name__ == "__main__":
    main()
