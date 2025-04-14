#!/usr/bin/env python3
"""
Extract contribution-level data: (person, event, project) pairs
- PRs, Issues, Comments for each person in each project
- NO commits (will join from cloned repos later)
- Uses 10 tokens for parallel extraction
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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# SSL context
ssl_context = ssl.create_default_context()

class TokenManager:
    """Manage multiple GitHub tokens with rate limit tracking"""
    
    def __init__(self, tokens):
        self.tokens = tokens
        self.token_states = {t: {'remaining': 5000, 'reset': 0} for t in tokens}
        self.lock = Lock()
        self.current_idx = 0
    
    def get_token(self):
        """Get best available token"""
        with self.lock:
            now = time.time()
            
            # Find token with most remaining or earliest reset
            best_token = None
            best_remaining = -1
            
            for token in self.tokens:
                state = self.token_states[token]
                if state['remaining'] > best_remaining:
                    best_remaining = state['remaining']
                    best_token = token
            
            # If all exhausted, wait for first reset
            if best_remaining <= 0:
                min_reset = min(s['reset'] for s in self.token_states.values())
                wait_time = max(0, min_reset - now) + 5
                if wait_time > 0:
                    logger.info(f"All tokens exhausted, waiting {wait_time:.0f}s")
                    time.sleep(wait_time)
                # Reset all
                for token in self.tokens:
                    self.token_states[token]['remaining'] = 5000
                best_token = self.tokens[0]
            
            return best_token
    
    def update_limits(self, token, remaining, reset):
        """Update token rate limit info"""
        with self.lock:
            self.token_states[token]['remaining'] = remaining
            self.token_states[token]['reset'] = reset


class ProgressTracker:
    """Track extraction progress with resume capability"""
    
    def __init__(self, progress_file):
        self.progress_file = Path(progress_file)
        self.lock = Lock()
        self.data = self._load()
    
    def _load(self):
        if self.progress_file.exists():
            with open(self.progress_file) as f:
                return json.load(f)
        return {
            'started_at': datetime.now().isoformat(),
            'completed': [],
            'errors': [],
            'last_updated': datetime.now().isoformat()
        }
    
    def is_completed(self, contribution_id):
        return contribution_id in self.data['completed']
    
    def mark_completed(self, contribution_id):
        with self.lock:
            if contribution_id not in self.data['completed']:
                self.data['completed'].append(contribution_id)
                self._save()
    
    def mark_error(self, contribution_id, error):
        with self.lock:
            self.data['errors'].append({'id': contribution_id, 'error': str(error)})
            self._save()
    
    def _save(self):
        self.data['last_updated'] = datetime.now().isoformat()
        with open(self.progress_file, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def get_stats(self):
        return {
            'completed': len(self.data['completed']),
            'errors': len(self.data['errors'])
        }


def make_request(url, token, token_manager):
    """Make GitHub API request with rate limit handling"""
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'ContributionExtractor/1.0'
    }
    
    for attempt in range(3):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, context=ssl_context, timeout=30) as response:
                # Update rate limits
                remaining = int(response.headers.get('X-RateLimit-Remaining', 5000))
                reset = int(response.headers.get('X-RateLimit-Reset', 0))
                token_manager.update_limits(token, remaining, reset)
                
                return json.loads(response.read().decode())
        
        except HTTPError as e:
            if e.code == 404:
                return None
            elif e.code == 403:
                # Rate limit
                reset = int(e.headers.get('X-RateLimit-Reset', 0))
                wait = max(0, reset - time.time()) + 5
                logger.warning(f"Rate limited, waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            elif e.code in [500, 502, 503]:
                time.sleep(2 ** attempt)
                continue
            else:
                logger.error(f"HTTP {e.code}: {url}")
                return None
        
        except (URLError, TimeoutError) as e:
            time.sleep(2 ** attempt)
            continue
    
    return None


def fetch_paginated(base_url, token, token_manager, max_pages=10):
    """Fetch paginated results"""
    all_items = []
    
    for page in range(1, max_pages + 1):
        url = f"{base_url}&page={page}&per_page=100"
        data = make_request(url, token, token_manager)
        
        if not data or len(data) == 0:
            break
        
        all_items.extend(data)
        
        if len(data) < 100:
            break
    
    return all_items


def extract_contribution(contribution, token_manager, output_dir):
    """Extract data for one (person, project) contribution"""
    username = contribution['github_username']
    repo = contribution['repo']
    event = contribution['event']
    contribution_id = contribution['contribution_id']
    
    token = token_manager.get_token()
    
    result = {
        'contribution_id': contribution_id,
        'github_username': username,
        'repo': repo,
        'event': event,
        'extracted_at': datetime.now().isoformat(),
        'pull_requests': [],
        'issues': [],
        'issue_comments': [],
        'pr_comments': []
    }
    
    # 1. Pull Requests by this user in this repo
    pr_url = f"https://api.github.com/search/issues?q=type:pr+repo:{repo}+author:{username}"
    pr_data = make_request(pr_url, token, token_manager)
    if pr_data and 'items' in pr_data:
        for pr in pr_data['items']:
            result['pull_requests'].append({
                'number': pr['number'],
                'title': pr['title'],
                'state': pr['state'],
                'created_at': pr['created_at'],
                'updated_at': pr['updated_at'],
                'closed_at': pr.get('closed_at'),
                'merged_at': pr.get('pull_request', {}).get('merged_at')
            })
    
    # 2. Issues by this user in this repo
    issue_url = f"https://api.github.com/search/issues?q=type:issue+repo:{repo}+author:{username}"
    issue_data = make_request(issue_url, token, token_manager)
    if issue_data and 'items' in issue_data:
        for issue in issue_data['items']:
            result['issues'].append({
                'number': issue['number'],
                'title': issue['title'],
                'state': issue['state'],
                'created_at': issue['created_at'],
                'updated_at': issue['updated_at'],
                'closed_at': issue.get('closed_at'),
                'comments': issue.get('comments', 0)
            })
    
    # 3. Issue comments by this user in this repo
    comment_url = f"https://api.github.com/search/issues?q=repo:{repo}+commenter:{username}"
    comment_data = make_request(comment_url, token, token_manager)
    if comment_data and 'items' in comment_data:
        result['issue_comments'] = len(comment_data['items'])
    
    # 4. PR review comments (simplified count)
    result['pr_comments'] = len(result['pull_requests'])  # Approximate
    
    # Summary
    result['summary'] = {
        'total_prs': len(result['pull_requests']),
        'total_issues': len(result['issues']),
        'total_comments': result['issue_comments'] if isinstance(result['issue_comments'], int) else 0
    }
    
    # Save
    output_file = output_dir / f"{contribution_id}.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    return result['summary']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Test with 5 contributions')
    args = parser.parse_args()
    
    base_dir = Path(__file__).parent.parent
    
    # Load config
    config_file = Path(__file__).parent / "config.json"
    with open(config_file) as f:
        config = json.load(f)
    
    tokens = config['github_tokens']
    max_workers = config.get('max_workers', 10)
    
    # Load contributions
    contributions_file = base_dir / "04_contributor_selection_and_organic_matching" / "outputs" / "contributions_final.json"
    with open(contributions_file) as f:
        data = json.load(f)
    
    contributions = data['contributions']
    
    logger.info("="*80)
    logger.info("CONTRIBUTION-LEVEL EXTRACTION")
    logger.info("="*80)
    logger.info(f"Total contributions: {len(contributions)}")
    logger.info(f"By event: {data['by_event']}")
    logger.info(f"Tokens: {len(tokens)}")
    logger.info(f"Workers: {max_workers}")
    
    # Setup
    output_dir = Path(__file__).parent / "contributions"
    output_dir.mkdir(exist_ok=True)
    
    progress_file = Path(__file__).parent / "progress" / "contribution_progress.json"
    progress_file.parent.mkdir(exist_ok=True)
    
    token_manager = TokenManager(tokens)
    progress = ProgressTracker(progress_file)
    
    # Filter already completed
    to_process = [c for c in contributions if not progress.is_completed(c['contribution_id'])]
    
    logger.info(f"Already completed: {len(contributions) - len(to_process)}")
    logger.info(f"To process: {len(to_process)}")
    
    if args.test:
        to_process = to_process[:5]
        logger.info(f"TEST MODE: Processing only {len(to_process)}")
    
    if not to_process:
        logger.info("Nothing to process!")
        return
    
    # Process
    completed = 0
    errors = 0
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extract_contribution, c, token_manager, output_dir): c
            for c in to_process
        }
        
        for future in as_completed(futures):
            contribution = futures[future]
            cid = contribution['contribution_id']
            
            try:
                summary = future.result()
                progress.mark_completed(cid)
                completed += 1
                
                if completed % 50 == 0:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    remaining = len(to_process) - completed
                    eta = remaining / rate if rate > 0 else 0
                    logger.info(f"Progress: {completed}/{len(to_process)} ({completed/len(to_process)*100:.1f}%) | ETA: {eta/60:.0f}m")
            
            except Exception as e:
                progress.mark_error(cid, str(e))
                errors += 1
                logger.error(f"Error {cid}: {e}")
    
    # Final stats
    elapsed = time.time() - start_time
    logger.info("="*80)
    logger.info("EXTRACTION COMPLETE")
    logger.info("="*80)
    logger.info(f"Completed: {completed}")
    logger.info(f"Errors: {errors}")
    logger.info(f"Time: {elapsed/60:.1f} minutes")
    logger.info(f"Rate: {completed/elapsed*60:.1f} contributions/minute")


if __name__ == "__main__":
    main()
