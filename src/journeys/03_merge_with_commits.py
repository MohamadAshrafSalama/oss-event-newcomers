#!/usr/bin/env python3
"""
Merge Commit Data with Contributor Journeys

Enhances contributor journey CSVs with commit data from locally mined repos.

Process:
1. Load each contributor's journey CSV
2. Load commits from mined repo CSVs (match by author_email)
3. Add commit activities with full details
4. Re-sort by date
5. Update CSV file

Fields added from commits:
- lines_added (insertions)
- lines_deleted (deletions)
- files_changed
- commit subject and body
"""

import os
import sys
import json
import csv
import logging
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import glob
from tqdm import tqdm

# Setup paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.append(str(PROJECT_ROOT))

# Load configuration
with open(SCRIPT_DIR / "config.json") as f:
    CONFIG = json.load(f)

# Setup logging
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = SCRIPT_DIR / CONFIG["paths"]["log_dir"] / f"merge_{timestamp}.log"
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


def build_email_to_username_map(contributors):
    """Build mapping from email to github username"""
    email_map = {}
    
    for contributor in contributors:
        username = contributor.get('github_username', '')
        if username:
            # GitHub privacy email format
            email = f"{username}@users.noreply.github.com".lower()
            email_map[email] = username
            
            # Also map the username itself (some commits may use this)
            email_map[username.lower()] = username
    
    logger.info(f"Built email-to-username map: {len(email_map)} entries")
    return email_map


def load_contributor_csv(username, output_dir):
    """Load existing contributor journey CSV"""
    csv_file = output_dir / f"{username}_journey.csv"
    
    if not csv_file.exists():
        return []
    
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        logger.error(f"Error loading {csv_file}: {e}")
        return []


def load_commits_for_contributor(username, email_map, commits_dir):
    """Load all commits by a contributor from repo CSVs"""
    commits = []
    
    # Get possible email addresses for this user
    possible_emails = [
        f"{username}@users.noreply.github.com".lower(),
        username.lower()
    ]
    
    # Find all repo CSVs
    pattern = os.path.join(commits_dir, "*.csv")
    csv_files = glob.glob(pattern)
    
    for csv_file in csv_files:
        try:
            with open(csv_file, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    author_email = (row.get('author_email') or '').lower()
                    author_name = (row.get('author_name') or '').lower()
                    
                    # Check if this commit is by our contributor
                    if author_email in possible_emails or author_name == username.lower():
                        commits.append(row)
        
        except Exception as e:
            logger.debug(f"Error reading {csv_file}: {e}")
            continue
    
    return commits


def format_commit_as_activity(commit_row, event_type, is_mentorship, oss4sg_repos):
    """Format commit from CSV as activity record"""
    repo = commit_row.get('repo_name', '')
    
    return {
        'activity_type': 'commit',
        'activity_id': commit_row.get('commit_hash', ''),
        'repo_name': repo,
        'created_at': commit_row.get('author_date', ''),
        'title': commit_row.get('subject', ''),
        'body': (commit_row.get('body') or '').replace('\n', ' ').replace('\r', '')[:500],
        'state': '',
        'url': f"https://github.com/{repo}/commit/{commit_row.get('commit_hash', '')}",
        'is_oss4sg': repo.lower() in oss4sg_repos,
        'project_language': '',
        'project_stars': '',
        'lines_added': commit_row.get('insertions', ''),
        'lines_deleted': commit_row.get('deletions', ''),
        'files_changed': commit_row.get('files_changed', ''),
        'merged_at': '',
        'labels': '',
        'event_type': event_type,
        'is_mentorship': str(is_mentorship)
    }


def merge_contributor_data(username, contributor, email_map, commits_dir, oss4sg_repos, output_dir):
    """Merge API data with commit data for one contributor"""
    try:
        # Load existing journey CSV (from API extraction)
        api_activities = load_contributor_csv(username, output_dir)
        
        # Load commits from repo CSVs
        commits = load_commits_for_contributor(username, email_map, commits_dir)
        
        if not commits:
            logger.debug(f"[{username}] No commits found in mined repos")
            return True, len(api_activities)
        
        logger.debug(f"[{username}] Found {len(commits)} commits")
        
        # Format commits as activities
        event_type = contributor.get('selection_event', '')
        is_mentorship = contributor.get('is_mentorship', False)
        
        commit_activities = [
            format_commit_as_activity(commit, event_type, is_mentorship, oss4sg_repos)
            for commit in commits
        ]
        
        # Combine API and commit activities
        all_activities = api_activities + commit_activities
        
        # Sort by date
        all_activities.sort(key=lambda x: x.get('created_at', ''))
        
        # Save updated CSV
        csv_file = output_dir / f"{username}_journey.csv"
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            if all_activities:
                writer = csv.DictWriter(f, fieldnames=CONFIG["csv_schema"]["columns"])
                writer.writeheader()
                writer.writerows(all_activities)
        
        logger.info(f"[{username}] Merged: {len(api_activities)} API + {len(commit_activities)} commits = {len(all_activities)} total")
        return True, len(all_activities)
        
    except Exception as e:
        logger.error(f"[{username}] Error during merge: {e}")
        return False, 0


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


def run_merge(test_mode=False):
    """Main merge pipeline"""
    logger.info("="*80)
    logger.info("MERGE COMMIT DATA WITH CONTRIBUTOR JOURNEYS")
    if test_mode:
        logger.info("TEST MODE")
    logger.info("="*80)
    
    # Setup paths
    output_dir = SCRIPT_DIR / (CONFIG["paths"]["test_contributors_output_dir"] if test_mode else CONFIG["paths"]["contributors_output_dir"])
    commits_dir = CONFIG["paths"]["commits_dir"]
    
    # Check if commits directory exists
    if not Path(commits_dir).exists():
        logger.error(f"Commits directory not found: {commits_dir}")
        logger.error("Please ensure external drive is mounted")
        return False
    
    # Load contributors
    input_file = PROJECT_ROOT / CONFIG["paths"]["contributors_input"]
    with open(input_file) as f:
        data = json.load(f)
    
    contributors = data.get('contributors', [])
    
    if test_mode:
        contributors = contributors[:CONFIG["test_mode"]["sample_count"]]
    
    logger.info(f"Processing {len(contributors)} contributors")
    
    # Build email mapping
    email_map = build_email_to_username_map(contributors)
    
    # Load OSS4SG repos
    oss4sg_repos = load_oss4sg_repos()
    
    # Process each contributor
    success_count = 0
    error_count = 0
    total_activities = 0
    
    for contributor in tqdm(contributors, desc="Merging commit data", unit="contributor"):
        username = contributor.get('github_username', '')
        if not username:
            continue
        
        success, activity_count = merge_contributor_data(
            username, contributor, email_map, commits_dir, oss4sg_repos, output_dir
        )
        
        if success:
            success_count += 1
            total_activities += activity_count
        else:
            error_count += 1
    
    # Summary
    logger.info("-"*80)
    logger.info("MERGE COMPLETE")
    logger.info("-"*80)
    logger.info(f"Successful: {success_count}")
    logger.info(f"Errors: {error_count}")
    logger.info(f"Total activities: {total_activities:,}")
    logger.info(f"Avg activities per contributor: {total_activities/success_count if success_count > 0 else 0:.1f}")
    logger.info("="*80)
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Merge commit data with contributor journeys")
    parser.add_argument("--test", action="store_true", help="Run on test output")
    args = parser.parse_args()
    
    start_time = datetime.now()
    logger.info(f"Script started at {start_time}")
    
    try:
        success = run_merge(test_mode=args.test)
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Script completed at {end_time}")
        logger.info(f"Total duration: {duration}")
        
        return 0 if success else 1
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
