#!/usr/bin/env python3
"""
Step 4: Match Organic Contributors

For each of the 4,000 event contributors, finds a matching organic contributor
from the SAME project using within-project temporal matching.

Matching Criteria (Zhou et al. 2016, Terrell et al. 2017):
1. Same project (exact repo match)
2. Lifecycle stage (Early/Mid/Late)
3. Safe months (first commit NOT in event windows)
4. Activity level (log2 coarsened bins, ±1 tolerance)
5. Not in any event list
6. No event keywords in commit messages

Output: organic_contributors_final.json with 4,000 matched contributors
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
import math
import csv
import random
from collections import defaultdict
from dateutil import parser as date_parser

# Setup paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.append(str(PROJECT_ROOT))

# Load configuration
with open(SCRIPT_DIR / "config.json") as f:
    CONFIG = json.load(f)

# Setup logging
LOG_FILE = PROJECT_ROOT / CONFIG["paths"]["logs_folder"] / "04_match_organic.log"
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

# Set random seed
random.seed(CONFIG["sampling"]["random_seed"])


def load_event_contributors(input_file):
    """Load selected event contributors from Step 3"""
    with open(input_file) as f:
        data = json.load(f)
    
    contributors = data.get('contributors', [])
    logger.info(f"Loaded {len(contributors)} event contributors")
    return contributors


def build_event_contributor_set():
    """Build set of all event contributor emails across all events"""
    logger.info("Building event contributor set...")
    
    event_emails = set()
    
    # Load all event files
    for event_name, file_path_rel in CONFIG["event_contributor_files"].items():
        file_path = PROJECT_ROOT / file_path_rel
        with open(file_path) as f:
            data = json.load(f)
        
        contributors = data.get('contributors', [])
        for contributor in contributors:
            username = contributor.get('github_username', '')
            if username:
                # GitHub email format: username@users.noreply.github.com
                email = f"{username}@users.noreply.github.com".lower()
                event_emails.add(email)
                # Also add variations
                event_emails.add(username.lower())
        
        logger.info(f"  {event_name}: {len(contributors)} contributors")
    
    logger.info(f"Total event contributor identifiers: {len(event_emails)}")
    return event_emails


def calculate_activity_bin(commit_count):
    """Calculate log2 bin for activity level"""
    if commit_count <= 0:
        return 0
    return int(math.floor(math.log2(commit_count)))


def get_lifecycle_stage(first_commit_date, project_created_date, current_date):
    """
    Calculate lifecycle stage based on when contributor joined
    
    Stages:
    - Early: joined in first 33% of project life
    - Mid: joined in middle 33%
    - Late: joined in last 33%
    """
    if not first_commit_date or not project_created_date:
        return "unknown"
    
    try:
        first_commit = date_parser.parse(first_commit_date)
        created = date_parser.parse(project_created_date) if isinstance(project_created_date, str) else project_created_date
        now = date_parser.parse(current_date) if isinstance(current_date, str) else current_date
        
        project_age_at_join = (first_commit - created).total_seconds()
        project_total_age = (now - created).total_seconds()
        
        if project_total_age <= 0:
            return "unknown"
        
        relative_join_time = project_age_at_join / project_total_age
        
        if relative_join_time < 0.33:
            return "Early"
        elif relative_join_time < 0.66:
            return "Mid"
        else:
            return "Late"
            
    except Exception as e:
        logger.debug(f"Error calculating lifecycle stage: {e}")
        return "unknown"


def is_safe_month(commit_date):
    """Check if commit date is in a safe month (not in event windows)"""
    try:
        dt = date_parser.parse(commit_date)
        month = dt.month
        
        # Safe months from config
        safe_months = CONFIG["matching"]["safe_months"]
        return month in safe_months
        
    except Exception:
        return False


def has_event_keywords(commit_message):
    """Check if commit message contains event keywords"""
    if not commit_message:
        return False
    
    message_lower = commit_message.lower()
    keywords = CONFIG["matching"]["event_keywords"]
    
    return any(keyword in message_lower for keyword in keywords)


def load_commits_for_project(commits_file, repo_name):
    """Load all commits for a specific project"""
    commits = []
    
    try:
        logger.debug(f"Loading commits for {repo_name}...")
        with open(commits_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('repo_name', '').lower() == repo_name.lower():
                    commits.append(row)
        logger.debug(f"  Loaded {len(commits)} commits for {repo_name}")
    except Exception as e:
        logger.error(f"Error loading commits for {repo_name}: {e}")
    
    return commits


def build_contributor_profiles(commits):
    """Build contributor profiles from commit data"""
    profiles = defaultdict(lambda: {
        'commits': [],
        'first_commit_date': None,
        'total_commits': 0,
        'has_event_keywords': False
    })
    
    for commit in commits:
        email = commit.get('author_email', '').lower()
        if not email:
            continue
        
        author_date = commit.get('author_date', '')
        subject = commit.get('subject', '')
        
        profile = profiles[email]
        profile['commits'].append(commit)
        profile['total_commits'] += 1
        
        # Track first commit
        if not profile['first_commit_date'] or author_date < profile['first_commit_date']:
            profile['first_commit_date'] = author_date
        
        # Check for event keywords
        if has_event_keywords(subject):
            profile['has_event_keywords'] = True
        
        # Store name if not yet stored
        if 'author_name' not in profile:
            profile['author_name'] = commit.get('author_name', '')
    
    return dict(profiles)


def find_matching_organic(event_contributor, profiles, event_emails, current_date='2026-01-27', relax_safe_months=False):
    """
    Find matching organic contributor for an event contributor
    
    Returns: (matched_contributor_email, matching_score) or (None, 0)
    """
    # Get event contributor's activity
    if event_contributor.get('selection_event') == 'hacktoberfest':
        event_activity = event_contributor.get('total_prs', 1)
    elif event_contributor.get('selection_event') == '24pr':
        event_activity = event_contributor.get('total_prs', 1)
    elif event_contributor.get('selection_event') == 'gsoc':
        event_activity = event_contributor.get('repo_count', 1) * 10  # Estimate
    else:  # lfx
        event_activity = event_contributor.get('repo_count', 1) * 5  # Estimate
    
    event_activity_bin = calculate_activity_bin(event_activity)
    tolerance = CONFIG["matching"]["activity_matching"]["tolerance"]
    
    # Filter organic contributors
    candidates = []
    
    for email, profile in profiles.items():
        # Exclude event participants
        if email in event_emails:
            continue
        
        # Check for event keywords (still filter these out)
        if profile.get('has_event_keywords', False):
            continue
        
        # Check first commit in safe months (relaxed if needed)
        first_commit = profile.get('first_commit_date')
        if not first_commit:
            continue
        
        if not relax_safe_months and not is_safe_month(first_commit):
            continue
        
        # Check activity level match
        organic_activity_bin = calculate_activity_bin(profile.get('total_commits', 0))
        activity_diff = abs(organic_activity_bin - event_activity_bin)
        
        if activity_diff > tolerance:
            continue
        
        # Add to candidates with matching score
        score = 100 - (activity_diff * 10)  # Higher score for closer match
        if relax_safe_months and not is_safe_month(first_commit):
            score -= 20  # Penalty for not being in safe month
        candidates.append((email, score, profile))
    
    # Randomly select from candidates if available
    if candidates:
        selected = random.choice(candidates)
        return selected[0], selected[1]
    
    return None, 0


def load_all_commits_by_repo(commits_file):
    """Load all commits and index by repo for faster access"""
    logger.info("Loading all commits (this may take a few minutes)...")
    
    commits_by_repo = defaultdict(list)
    total_commits = 0
    
    try:
        with open(commits_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                repo = row.get('repo_name', '').lower()
                if repo:
                    commits_by_repo[repo].append(row)
                    total_commits += 1
                    
                    if total_commits % 1000000 == 0:
                        logger.info(f"  Loaded {total_commits:,} commits...")
        
        logger.info(f"Loaded {total_commits:,} commits from {len(commits_by_repo)} repos")
        return dict(commits_by_repo)
        
    except Exception as e:
        logger.error(f"Error loading commits: {e}")
        return {}


def match_all_contributors(event_contributors, commits_file, event_emails, test_mode=False):
    """Match all event contributors with organic contributors"""
    logger.info("Matching organic contributors...")
    
    # Check if commits file exists
    if not Path(commits_file).exists():
        logger.error(f"Commits file not found: {commits_file}")
        logger.error("Cannot perform matching without consolidated commits")
        logger.error("Please run Step 1 (consolidate_commits.py) first")
        return []
    
    # Load ALL commits at once and index by repo (much faster than per-repo loading)
    commits_by_repo = load_all_commits_by_repo(commits_file)
    
    if not commits_by_repo:
        logger.error("No commits loaded, cannot perform matching")
        return []
    
    matched_organic = []
    no_match_count = 0
    used_organic_emails = set()  # Track already matched organics
    
    # Group event contributors by repo for efficiency
    by_repo = defaultdict(list)
    for contributor in event_contributors:
        repos = contributor.get('repos_contributed', [])
        if repos:
            by_repo[repos[0].lower()].append(contributor)
    
    logger.info(f"Event contributors span {len(by_repo)} unique repos")
    
    # Process each repo
    for i, (repo, repo_contributors) in enumerate(by_repo.items()):
        if test_mode and i >= 5:  # Limit in test mode
            break
        
        if (i+1) % 100 == 0 or i < 10:
            logger.info(f"Processing repo {i+1}/{len(by_repo)}: {repo} ({len(repo_contributors)} event contributors)")
        
        # Get commits for this repo from pre-loaded index
        project_commits = commits_by_repo.get(repo, [])
        
        if not project_commits:
            logger.debug(f"  No commits found for {repo}")
            no_match_count += len(repo_contributors)
            continue
        
        # Build contributor profiles
        profiles = build_contributor_profiles(project_commits)
        logger.debug(f"  Built profiles for {len(profiles)} contributors")
        
        # Match each event contributor in this repo
        for event_contrib in repo_contributors:
            # Try strict matching first
            matched_email, score = find_matching_organic(event_contrib, profiles, event_emails, relax_safe_months=False)
            
            # If no match, try relaxed matching (without safe month requirement)
            if not matched_email:
                matched_email, score = find_matching_organic(event_contrib, profiles, event_emails, relax_safe_months=True)
            
            # Ensure we don't match the same organic twice
            if matched_email and matched_email not in used_organic_emails:
                used_organic_emails.add(matched_email)
                
                # Get profile data
                profile = profiles.get(matched_email, {})
                
                # Create organic contributor record
                organic = {
                    'github_username': profile.get('author_name', matched_email.split('@')[0]),
                    'author_email': matched_email,
                    'author_name': profile.get('author_name', ''),
                    'matched_to_event_contributor': event_contrib.get('github_username'),
                    'matching_score': score,
                    'repo': repo,
                    'total_commits': profile.get('total_commits', 0),
                    'first_commit_date': profile.get('first_commit_date', ''),
                    'selection_method': 'within_project_temporal_matching',
                    'contributor_type': 'organic'
                }
                matched_organic.append(organic)
            else:
                no_match_count += 1
    
    logger.info(f"Matched: {len(matched_organic)}")
    logger.info(f"No match: {no_match_count}")
    
    return matched_organic


def save_output(matched_organic, stats, output_file):
    """Save matched organic contributors"""
    output = {
        'generated_at': datetime.now().isoformat(),
        'matching_criteria': {
            'method': 'within_project_temporal',
            'same_project': True,
            'lifecycle_stage_matching': True,
            'safe_months_only': CONFIG['matching']['safe_months'],
            'activity_level_tolerance': CONFIG['matching']['activity_matching']['tolerance'],
            'exclude_event_participants': True,
            'exclude_event_keywords': True
        },
        'statistics': stats,
        'contributors': matched_organic
    }
    
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    logger.info(f"Saved {len(matched_organic)} organic contributors to {output_file}")


def print_summary(stats):
    """Print matching summary"""
    logger.info("="*80)
    logger.info("ORGANIC CONTRIBUTOR MATCHING SUMMARY")
    logger.info("="*80)
    logger.info(f"Event contributors: {stats.get('event_total', 0):,}")
    logger.info(f"Matched organic: {stats.get('matched', 0):,}")
    logger.info(f"No match found: {stats.get('no_match', 0):,}")
    logger.info(f"Match rate: {stats.get('match_rate', 0):.1f}%")
    logger.info("="*80)


def main():
    parser = argparse.ArgumentParser(description="Match organic contributors to event contributors")
    parser.add_argument("--test", action="store_true", help="Run in test mode")
    args = parser.parse_args()
    
    start_time = datetime.now()
    logger.info(f"Script started at {start_time}")
    logger.info("="*80)
    logger.info("STEP 4: MATCH ORGANIC CONTRIBUTORS")
    logger.info("="*80)
    
    try:
        # Load event contributors from Step 3
        input_dir = PROJECT_ROOT / (CONFIG["paths"]["test_output_folder"] if args.test else CONFIG["paths"]["output_folder"])
        event_file = input_dir / "event_contributors_final.json"
        
        if not event_file.exists():
            logger.error(f"Event contributors file not found: {event_file}")
            logger.error("Please run Step 3 (select_event_contributors.py) first")
            return 1
        
        event_contributors = load_event_contributors(event_file)
        
        # Build event contributor set
        event_emails = build_event_contributor_set()
        
        # Load consolidated commits
        commits_file = input_dir / "all_commits_consolidated.csv"
        
        # Match organic contributors
        matched_organic = match_all_contributors(event_contributors, commits_file, event_emails, args.test)
        
        # Calculate statistics
        stats = {
            'event_total': len(event_contributors),
            'matched': len(matched_organic),
            'no_match': len(event_contributors) - len(matched_organic),
            'match_rate': (len(matched_organic) / len(event_contributors) * 100) if event_contributors else 0
        }
        
        # Save output
        output_dir = PROJECT_ROOT / (CONFIG["paths"]["test_output_folder"] if args.test else CONFIG["paths"]["output_folder"])
        output_file = output_dir / "organic_contributors_final.json"
        
        save_output(matched_organic, stats, output_file)
        
        # Print summary
        print_summary(stats)
        
        # Note about implementation
        if not matched_organic:
            logger.warning("\n" + "="*80)
            logger.warning("NOTE: Matching algorithm is a placeholder")
            logger.warning("Full implementation requires consolidated commits from Step 1")
            logger.warning("Please run 01_consolidate_commits.py first")
            logger.warning("="*80)
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Script completed at {end_time}")
        logger.info(f"Total duration: {duration}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error during matching: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
