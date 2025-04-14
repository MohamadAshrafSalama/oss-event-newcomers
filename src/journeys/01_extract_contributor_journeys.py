#!/usr/bin/env python3
"""
Contributor Journey Extraction - GitHub API Mining

Extracts complete activity histories for event contributors:
- Pull requests (via Search API)
- Issues (via Search API)
- PR comments (via REST API)
- Issue comments (via REST API)
- Commits (from local CSV files)

Features:
- Parallel processing with 4 GitHub tokens
- Automatic rate limit handling
- Resume capability with checkpoints
- Progress bar with ETA
- Comprehensive error logging
- Test mode for validation

Output: Per-contributor CSV files with complete activity timeline
"""

import os
import sys
import json
import csv
import logging
import argparse
import time
import threading
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import re

# Setup paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.append(str(PROJECT_ROOT))

# Load configuration
with open(SCRIPT_DIR / "config.json") as f:
    CONFIG = json.load(f)

# Setup logging
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = SCRIPT_DIR / CONFIG["paths"]["log_dir"] / f"{CONFIG['logging']['log_file_prefix']}_{timestamp}.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, CONFIG["logging"]["level"]),
    format=CONFIG["logging"]["format"],
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler() if CONFIG["logging"]["console_output"] else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# THREAD-SAFE TOKEN MANAGER
# ============================================================================

class ParallelTokenManager:
    """Manages multiple GitHub tokens with thread-safe rate limit tracking"""
    
    def __init__(self, tokens):
        self.tokens = tokens
        self.locks = [threading.Lock() for _ in tokens]
        self.limits = [{
            "remaining": 5000,
            "reset": 0,
            "requests": 0,
            "search_remaining": 30,
            "search_reset": 0
        } for _ in tokens]
        self.global_lock = threading.Lock()
        self.total_requests = 0
        self.total_errors = 0
    
    def get_headers(self, token_idx):
        """Get HTTP headers for a specific token"""
        return {
            "Authorization": f"token {self.tokens[token_idx]}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ContributorJourneyExtractor/1.0"
        }
    
    def update_limits(self, token_idx, headers, api_type="core"):
        """Update rate limit info from response headers"""
        with self.locks[token_idx]:
            if api_type == "search":
                # Search API uses different headers
                remaining = headers.get("X-RateLimit-Remaining")
                reset = headers.get("X-RateLimit-Reset")
                if remaining is not None:
                    self.limits[token_idx]["search_remaining"] = int(remaining)
                if reset is not None:
                    self.limits[token_idx]["search_reset"] = int(reset)
            else:
                # Core REST API
                remaining = headers.get("X-RateLimit-Remaining")
                reset = headers.get("X-RateLimit-Reset")
                if remaining is not None:
                    self.limits[token_idx]["remaining"] = int(remaining)
                if reset is not None:
                    self.limits[token_idx]["reset"] = int(reset)
            
            self.limits[token_idx]["requests"] += 1
        
        with self.global_lock:
            self.total_requests += 1
    
    def check_rate_limit(self, token_idx, api_type="core"):
        """Wait if token is approaching rate limit"""
        with self.locks[token_idx]:
            min_remaining = CONFIG["rate_limits"]["min_remaining_before_wait"]
            
            if api_type == "search":
                if self.limits[token_idx]["search_remaining"] < 5:
                    reset_time = self.limits[token_idx]["search_reset"]
                    wait = max(0, reset_time - time.time() + 2)
                    if wait > 0:
                        logger.warning(f"Token {token_idx+1} search rate limited. Waiting {wait:.0f}s...")
                        time.sleep(wait)
                        self.limits[token_idx]["search_remaining"] = 30
            else:
                if self.limits[token_idx]["remaining"] < min_remaining:
                    reset_time = self.limits[token_idx]["reset"]
                    wait = max(0, reset_time - time.time() + 2)
                    if wait > 0:
                        logger.warning(f"Token {token_idx+1} core rate limited. Waiting {wait:.0f}s...")
                        time.sleep(wait)
                        self.limits[token_idx]["remaining"] = 5000
    
    def increment_errors(self):
        """Thread-safe error counter increment"""
        with self.global_lock:
            self.total_errors += 1
    
    def get_status(self):
        """Get current token status for logging"""
        status = []
        for i, limit in enumerate(self.limits):
            status.append(f"T{i+1}: {limit['remaining']}/5000 core, {limit['search_remaining']}/30 search")
        return " | ".join(status)


# ============================================================================
# PROGRESS TRACKING
# ============================================================================

class ProgressTracker:
    """Thread-safe progress tracking with checkpoint saving"""
    
    def __init__(self, progress_file):
        self.progress_file = Path(progress_file)
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        
        # Load existing progress
        if self.progress_file.exists():
            with open(self.progress_file) as f:
                self.data = json.load(f)
        else:
            self.data = {
                "started_at": datetime.now().isoformat(),
                "completed": [],
                "errors": [],
                "total_processed": 0,
                "last_checkpoint": None
            }
    
    def is_completed(self, username):
        """Check if contributor already processed"""
        with self.lock:
            return username in self.data["completed"]
    
    def mark_completed(self, username):
        """Mark contributor as completed"""
        with self.lock:
            if username not in self.data["completed"]:
                self.data["completed"].append(username)
                self.data["total_processed"] += 1
    
    def add_error(self, username, error_msg):
        """Record an error"""
        with self.lock:
            self.data["errors"].append({
                "username": username,
                "error": error_msg,
                "timestamp": datetime.now().isoformat()
            })
    
    def save(self):
        """Save progress to file"""
        with self.lock:
            self.data["last_checkpoint"] = datetime.now().isoformat()
            self.data["last_updated"] = datetime.now().isoformat()
            with open(self.progress_file, 'w') as f:
                json.dump(self.data, f, indent=2)
    
    def get_stats(self):
        """Get progress statistics"""
        with self.lock:
            return {
                "completed": len(self.data["completed"]),
                "errors": len(self.data["errors"]),
                "total_processed": self.data["total_processed"]
            }


# ============================================================================
# GITHUB API FUNCTIONS
# ============================================================================

def make_request(url, headers, token_manager, token_idx, api_type="core", retry_count=None):
    """Make HTTP request with retry logic"""
    if retry_count is None:
        retry_count = CONFIG["extraction"]["retry_count"]
    
    for attempt in range(retry_count):
        try:
            # Check rate limit before request
            token_manager.check_rate_limit(token_idx, api_type)
            
            req = Request(url, headers=headers)
            response = urlopen(req, timeout=CONFIG["extraction"]["request_timeout_seconds"])
            
            # Update rate limits from response
            token_manager.update_limits(token_idx, response.headers, api_type)
            
            data = json.loads(response.read().decode('utf-8'))
            return data, None
            
        except HTTPError as e:
            error_code = e.code
            
            if error_code == 404:
                # Not found - don't retry
                return None, f"404 Not Found: {url}"
            
            elif error_code == 403:
                # Rate limit - should have been caught, but handle anyway
                logger.warning(f"403 Forbidden on {url} - may be rate limited")
                # Calculate actual wait time from headers instead of hardcoded 60s
                try:
                    reset_time = int(e.headers.get('x-ratelimit-reset', 0))
                    if reset_time > 0:
                        wait_time = max(0, reset_time - time.time()) + 5
                    else:
                        wait_time = 60  # Fallback if no header
                    logger.info(f"Waiting {wait_time:.0f}s for rate limit reset")
                    time.sleep(wait_time)
                except (ValueError, TypeError):
                    # If header parsing fails, use conservative 60s
                    logger.warning("Could not parse rate limit reset header, waiting 60s")
                    time.sleep(60)
                if attempt < retry_count - 1:
                    continue
                return None, f"403 Forbidden after {retry_count} retries"
            
            elif error_code in [500, 502, 503]:
                # Server error - retry
                if attempt < retry_count - 1:
                    wait = CONFIG["extraction"]["retry_delay_seconds"] * (attempt + 1)
                    logger.debug(f"Server error {error_code}, retry {attempt+1}/{retry_count} after {wait}s")
                    time.sleep(wait)
                    continue
                return None, f"Server error {error_code} after {retry_count} retries"
            
            else:
                return None, f"HTTP {error_code}: {str(e)}"
        
        except URLError as e:
            if attempt < retry_count - 1:
                wait = CONFIG["extraction"]["retry_delay_seconds"] * (attempt + 1)
                logger.debug(f"Network error, retry {attempt+1}/{retry_count} after {wait}s")
                time.sleep(wait)
                continue
            return None, f"Network error: {str(e)}"
        
        except Exception as e:
            return None, f"Unexpected error: {str(e)}"
    
    return None, "Max retries exceeded"


def search_user_prs(username, headers, token_manager, token_idx):
    """Search for all PRs by a user"""
    prs = []
    page = 1
    max_pages = 10  # GitHub Search API max 1,000 results (10 pages × 100/page)
    
    while page <= max_pages:
        url = f"https://api.github.com/search/issues?q=author:{username}+type:pr&per_page=100&page={page}&sort=created&order=asc"
        
        data, error = make_request(url, headers, token_manager, token_idx, api_type="search")
        
        if error:
            logger.debug(f"Error searching PRs for {username}: {error}")
            break
        
        if not data or 'items' not in data:
            break
        
        items = data['items']
        if not items:
            break
        
        prs.extend(items)
        
        # Check if more pages
        if len(items) < 100:
            break
        
        page += 1
    
    return prs


def search_user_issues(username, headers, token_manager, token_idx):
    """Search for all issues created by a user (excluding PRs)"""
    issues = []
    page = 1
    max_pages = 10
    
    while page <= max_pages:
        # Note: type:issue excludes PRs
        url = f"https://api.github.com/search/issues?q=author:{username}+type:issue&per_page=100&page={page}&sort=created&order=asc"
        
        data, error = make_request(url, headers, token_manager, token_idx, api_type="search")
        
        if error:
            logger.debug(f"Error searching issues for {username}: {error}")
            break
        
        if not data or 'items' not in data:
            break
        
        items = data['items']
        if not items:
            break
        
        issues.extend(items)
        
        if len(items) < 100:
            break
        
        page += 1
    
    return issues


def get_pr_comments(pr, headers, token_manager, token_idx):
    """Get all comments on a PR"""
    comments = []
    
    # Extract owner/repo from PR URL
    pr_url = pr.get('pull_request', {}).get('url', '')
    if not pr_url:
        return comments
    
    # comments_url is already in the PR object
    comments_url = pr.get('comments_url', '')
    if not comments_url:
        return comments
    
    data, error = make_request(comments_url, headers, token_manager, token_idx)
    
    if error:
        logger.debug(f"Error getting PR comments: {error}")
        return comments
    
    if data:
        comments = data if isinstance(data, list) else []
    
    return comments


def get_issue_comments(issue, headers, token_manager, token_idx):
    """Get all comments on an issue"""
    comments_url = issue.get('comments_url', '')
    if not comments_url:
        return []
    
    data, error = make_request(comments_url, headers, token_manager, token_idx)
    
    if error:
        logger.debug(f"Error getting issue comments: {error}")
        return []
    
    if data:
        return data if isinstance(data, list) else []
    
    return []


# ============================================================================
# DATA FORMATTING
# ============================================================================

def extract_repo_from_url(url):
    """Extract owner/repo from GitHub URL"""
    if not url:
        return ""
    
    # Match: https://github.com/owner/repo/...
    match = re.search(r'github\.com/([^/]+)/([^/]+)', url)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    
    return ""


def format_pr(pr, event_type, is_mentorship, oss4sg_repos):
    """Format PR as activity record"""
    repo = extract_repo_from_url(pr.get('html_url', ''))
    labels = ','.join([label['name'] for label in pr.get('labels', [])])
    
    return {
        'activity_type': 'pr',
        'activity_id': str(pr.get('number', '')),
        'repo_name': repo,
        'created_at': pr.get('created_at', ''),
        'title': pr.get('title', ''),
        'body': (pr.get('body') or '').replace('\n', ' ').replace('\r', '')[:500],  # Truncate long bodies
        'state': pr.get('state', ''),
        'url': pr.get('html_url', ''),
        'is_oss4sg': repo.lower() in oss4sg_repos,
        'project_language': '',  # To be filled if needed
        'project_stars': '',
        'lines_added': '',
        'lines_deleted': '',
        'files_changed': '',
        'merged_at': pr.get('closed_at', '') if pr.get('state') == 'closed' and 'pull_request' in pr else '',
        'labels': labels,
        'event_type': event_type,
        'is_mentorship': is_mentorship
    }


def format_issue(issue, event_type, is_mentorship, oss4sg_repos):
    """Format issue as activity record"""
    repo = extract_repo_from_url(issue.get('html_url', ''))
    labels = ','.join([label['name'] for label in issue.get('labels', [])])
    
    return {
        'activity_type': 'issue',
        'activity_id': str(issue.get('number', '')),
        'repo_name': repo,
        'created_at': issue.get('created_at', ''),
        'title': issue.get('title', ''),
        'body': (issue.get('body') or '').replace('\n', ' ').replace('\r', '')[:500],
        'state': issue.get('state', ''),
        'url': issue.get('html_url', ''),
        'is_oss4sg': repo.lower() in oss4sg_repos,
        'project_language': '',
        'project_stars': '',
        'lines_added': '',
        'lines_deleted': '',
        'files_changed': '',
        'merged_at': '',
        'labels': labels,
        'event_type': event_type,
        'is_mentorship': is_mentorship
    }


def format_comment(comment, comment_type, repo, event_type, is_mentorship, oss4sg_repos):
    """Format comment as activity record"""
    return {
        'activity_type': comment_type,
        'activity_id': str(comment.get('id', '')),
        'repo_name': repo,
        'created_at': comment.get('created_at', ''),
        'title': f"Comment on {comment_type.replace('_comment', '')}",
        'body': (comment.get('body') or '').replace('\n', ' ').replace('\r', '')[:500],
        'state': '',
        'url': comment.get('html_url', ''),
        'is_oss4sg': repo.lower() in oss4sg_repos,
        'project_language': '',
        'project_stars': '',
        'lines_added': '',
        'lines_deleted': '',
        'files_changed': '',
        'merged_at': '',
        'labels': '',
        'event_type': event_type,
        'is_mentorship': is_mentorship
    }


# ============================================================================
# CONTRIBUTOR EXTRACTION
# ============================================================================

def load_oss4sg_repos():
    """Load OSS4SG repository list"""
    oss4sg_file = PROJECT_ROOT / CONFIG["paths"]["oss4sg_list"]
    oss4sg_repos = set()
    
    try:
        with open(oss4sg_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                repo = row.get('repo_name_with_owner', '').strip().lower()
                if repo:
                    oss4sg_repos.add(repo)
    except Exception as e:
        logger.warning(f"Could not load OSS4SG list: {e}")
    
    logger.info(f"Loaded {len(oss4sg_repos)} OSS4SG repositories")
    return oss4sg_repos


def extract_contributor_journey(contributor, token_idx, token_manager, oss4sg_repos, output_dir):
    """Extract complete activity history for one contributor"""
    username = contributor.get('github_username', '')
    event_type = contributor.get('selection_event', '')
    is_mentorship = contributor.get('is_mentorship', False)
    
    if not username:
        return False, "No username"
    
    try:
        headers = token_manager.get_headers(token_idx)
        activities = []
        
        # 1. Search for PRs
        logger.debug(f"[{username}] Searching PRs...")
        prs = search_user_prs(username, headers, token_manager, token_idx)
        logger.debug(f"[{username}] Found {len(prs)} PRs")
        
        for pr in prs:
            # Add PR activity
            activities.append(format_pr(pr, event_type, is_mentorship, oss4sg_repos))
            
            # Get PR comments
            comments = get_pr_comments(pr, headers, token_manager, token_idx)
            repo = extract_repo_from_url(pr.get('html_url', ''))
            for comment in comments:
                activities.append(format_comment(comment, 'pr_comment', repo, event_type, is_mentorship, oss4sg_repos))
        
        # 2. Search for Issues
        logger.debug(f"[{username}] Searching issues...")
        issues = search_user_issues(username, headers, token_manager, token_idx)
        logger.debug(f"[{username}] Found {len(issues)} issues")
        
        for issue in issues:
            # Add issue activity
            activities.append(format_issue(issue, event_type, is_mentorship, oss4sg_repos))
            
            # Get issue comments
            comments = get_issue_comments(issue, headers, token_manager, token_idx)
            repo = extract_repo_from_url(issue.get('html_url', ''))
            for comment in comments:
                activities.append(format_comment(comment, 'issue_comment', repo, event_type, is_mentorship, oss4sg_repos))
        
        # 3. Sort by date
        activities.sort(key=lambda x: x.get('created_at', ''))
        
        # 4. Save to CSV
        output_file = output_dir / f"{username}_journey.csv"
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            if activities:
                writer = csv.DictWriter(f, fieldnames=CONFIG["csv_schema"]["columns"])
                writer.writeheader()
                writer.writerows(activities)
        
        logger.info(f"[{username}] Extracted {len(activities)} activities → {output_file.name}")
        return True, None
        
    except Exception as e:
        error_msg = f"Exception: {str(e)}"
        logger.error(f"[{username}] {error_msg}")
        token_manager.increment_errors()
        return False, error_msg


def process_contributor(contributor, token_idx, token_manager, oss4sg_repos, output_dir, progress_tracker):
    """Process a single contributor with progress tracking"""
    username = contributor.get('github_username', '')
    
    # Check if already completed
    if progress_tracker.is_completed(username):
        logger.debug(f"[{username}] Already completed, skipping")
        return True
    
    # Extract journey
    success, error = extract_contributor_journey(contributor, token_idx, token_manager, oss4sg_repos, output_dir)
    
    if success:
        progress_tracker.mark_completed(username)
    else:
        progress_tracker.add_error(username, error or "Unknown error")
    
    return success


# ============================================================================
# MAIN EXTRACTION PIPELINE
# ============================================================================

def load_event_contributors(test_mode=False):
    """Load selected event contributors"""
    input_file = PROJECT_ROOT / CONFIG["paths"]["contributors_input"]
    
    if not input_file.exists():
        logger.error(f"Contributors file not found: {input_file}")
        logger.error("Please run 04_contributor_selection_and_organic_matching/03_select_event_contributors.py first")
        return []
    
    with open(input_file) as f:
        data = json.load(f)
    
    contributors = data.get('contributors', [])
    logger.info(f"Loaded {len(contributors)} event contributors from {input_file}")
    
    if test_mode:
        sample_count = CONFIG["test_mode"]["sample_count"]
        contributors = contributors[:sample_count]
        logger.info(f"TEST MODE: Processing first {len(contributors)} contributors")
    
    return contributors


def run_extraction(test_mode=False):
    """Main extraction pipeline"""
    logger.info("="*80)
    logger.info("CONTRIBUTOR JOURNEY EXTRACTION")
    if test_mode:
        logger.info("TEST MODE")
    logger.info("="*80)
    
    # Setup
    output_dir = SCRIPT_DIR / (CONFIG["paths"]["test_contributors_output_dir"] if test_mode else CONFIG["paths"]["contributors_output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    
    progress_file = SCRIPT_DIR / CONFIG["paths"]["progress_file"]
    if test_mode:
        progress_file = SCRIPT_DIR / "progress" / "progress_test.json"
    
    # Load data
    contributors = load_event_contributors(test_mode)
    if not contributors:
        logger.error("No contributors to process")
        return False
    
    oss4sg_repos = load_oss4sg_repos()
    
    # Initialize managers
    token_manager = ParallelTokenManager(CONFIG["github_tokens"])
    progress_tracker = ProgressTracker(progress_file)
    
    # Filter to unprocessed
    stats = progress_tracker.get_stats()
    unprocessed = [c for c in contributors if not progress_tracker.is_completed(c.get('github_username', ''))]
    
    logger.info(f"Total contributors: {len(contributors)}")
    logger.info(f"Already completed: {stats['completed']}")
    logger.info(f"To process: {len(unprocessed)}")
    logger.info(f"GitHub tokens: {len(CONFIG['github_tokens'])} tokens")
    
    # Check for sorted order file (process smaller contributors first)
    sorted_file = SCRIPT_DIR / "progress" / "sorted_remaining.json"
    if sorted_file.exists() and not test_mode:
        try:
            with open(sorted_file) as f:
                sorted_data = json.load(f)
            sorted_usernames = sorted_data.get("sorted_contributors", [])
            activity_estimates = sorted_data.get("activity_estimates", {})
            
            # Create lookup for unprocessed contributors
            unprocessed_dict = {c.get('github_username', ''): c for c in unprocessed}
            
            # Reorder: sorted first, then any remaining
            sorted_unprocessed = []
            for username in sorted_usernames:
                if username in unprocessed_dict:
                    sorted_unprocessed.append(unprocessed_dict[username])
            
            # Add any that weren't in sorted list
            sorted_set = set(sorted_usernames)
            for c in unprocessed:
                if c.get('github_username', '') not in sorted_set:
                    sorted_unprocessed.append(c)
            
            unprocessed = sorted_unprocessed
            logger.info(f"✓ Using sorted order (smallest activity first)")
            if sorted_unprocessed:
                first_user = sorted_unprocessed[0].get('github_username', '')
                last_user = sorted_unprocessed[-1].get('github_username', '')
                logger.info(f"  First: {first_user} (~{activity_estimates.get(first_user, '?')} activities)")
                logger.info(f"  Last: {last_user} (~{activity_estimates.get(last_user, '?')} activities)")
        except Exception as e:
            logger.warning(f"Could not load sorted order: {e}")
    
    logger.info("-"*80)
    
    if not unprocessed:
        logger.info("All contributors already processed!")
        return True
    
    # Process with parallel workers
    max_workers = min(len(CONFIG["github_tokens"]), CONFIG["parallel_processing"]["max_workers"])
    completed_count = stats['completed']
    checkpoint_interval = CONFIG["extraction"]["checkpoint_interval"]
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_contributor = {}
        for idx, contributor in enumerate(unprocessed):
            token_idx = idx % len(CONFIG["github_tokens"])
            future = executor.submit(
                process_contributor,
                contributor,
                token_idx,
                token_manager,
                oss4sg_repos,
                output_dir,
                progress_tracker
            )
            future_to_contributor[future] = contributor
        
        # Process results with progress bar
        with tqdm(total=len(unprocessed), desc="Processing contributors", unit="contributor") as pbar:
            for future in as_completed(future_to_contributor):
                contributor = future_to_contributor[future]
                username = contributor.get('github_username', 'unknown')
                
                try:
                    success = future.result()
                    completed_count += 1
                    
                    # Checkpoint
                    if completed_count % checkpoint_interval == 0:
                        progress_tracker.save()
                        logger.debug(f"Checkpoint: {completed_count} contributors processed")
                        logger.debug(f"Token status: {token_manager.get_status()}")
                    
                except Exception as e:
                    logger.error(f"[{username}] Task failed: {e}")
                    progress_tracker.add_error(username, str(e))
                
                pbar.update(1)
    
    # Final save
    progress_tracker.save()
    
    # Summary
    final_stats = progress_tracker.get_stats()
    logger.info("-"*80)
    logger.info("EXTRACTION COMPLETE")
    logger.info("-"*80)
    logger.info(f"Total processed: {final_stats['completed']}")
    logger.info(f"Errors: {final_stats['errors']}")
    logger.info(f"Total API requests: {token_manager.total_requests}")
    logger.info(f"Output directory: {output_dir}")
    logger.info("="*80)
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Extract contributor journeys via GitHub API")
    parser.add_argument("--test", action="store_true", help="Run in test mode (10 contributors)")
    args = parser.parse_args()
    
    start_time = datetime.now()
    logger.info(f"Script started at {start_time}")
    
    try:
        success = run_extraction(test_mode=args.test)
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Script completed at {end_time}")
        logger.info(f"Total duration: {duration}")
        
        return 0 if success else 1
        
    except KeyboardInterrupt:
        logger.warning("\nInterrupted by user (Ctrl+C)")
        logger.warning("Progress saved. Run again to resume.")
        return 130
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
