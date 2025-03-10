#!/usr/bin/env python3
"""
Step 5: Filter Bot Accounts

Applies bot detection heuristics (Dey et al. 2020) to remove bot accounts
from both event and organic contributor datasets.

Bot indicators:
- Username patterns: bot, ci, automation, jenkins, dependabot, etc.
- Email patterns: noreply, github-actions, bots@, etc.

Updates both event_contributors_final.json and organic_contributors_final.json
Creates combined all_contributors_8k.json
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
import re

# Setup paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.append(str(PROJECT_ROOT))

# Load configuration
with open(SCRIPT_DIR / "config.json") as f:
    CONFIG = json.load(f)

# Setup logging
LOG_FILE = PROJECT_ROOT / CONFIG["paths"]["logs_folder"] / "05_filter_bots.log"
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


def is_likely_bot(username, email):
    """
    Determine if contributor is likely a bot based on username and email
    
    Based on Dey et al. (2020) heuristics:
    - Username contains bot indicators
    - Email contains bot indicators
    """
    if not username:
        username = ""
    if not email:
        email = ""
    
    username_lower = username.lower()
    email_lower = email.lower()
    
    # Check username patterns
    username_patterns = CONFIG["bot_filtering"]["username_patterns"]
    for pattern in username_patterns:
        if pattern in username_lower:
            return True, f"username contains '{pattern}'"
    
    # Check email patterns
    email_patterns = CONFIG["bot_filtering"]["email_patterns"]
    for pattern in email_patterns:
        if pattern in email_lower:
            return True, f"email contains '{pattern}'"
    
    # Special case: [bot] in username
    if '[bot]' in username_lower or '(bot)' in username_lower:
        return True, "username contains [bot] or (bot)"
    
    return False, None


def filter_bots_from_list(contributors, contributor_type):
    """Filter bots from a contributor list"""
    logger.info(f"Filtering bots from {contributor_type}...")
    logger.info(f"  Initial count: {len(contributors)}")
    
    non_bots = []
    bots_detected = []
    
    for contributor in contributors:
        username = contributor.get('github_username', '')
        email = contributor.get('author_email', '')
        
        # If no email, try to construct from username
        if not email and username:
            email = f"{username}@users.noreply.github.com"
        
        is_bot, reason = is_likely_bot(username, email)
        
        if is_bot:
            bots_detected.append({
                'username': username,
                'email': email,
                'reason': reason
            })
        else:
            non_bots.append(contributor)
    
    logger.info(f"  Bots detected: {len(bots_detected)}")
    logger.info(f"  Non-bots: {len(non_bots)}")
    
    # Log some examples of detected bots
    if bots_detected:
        logger.info(f"  Example bots:")
        for bot in bots_detected[:10]:
            logger.info(f"    - {bot['username']} ({bot['reason']})")
    
    return non_bots, bots_detected


def load_contributors(file_path):
    """Load contributors from JSON file"""
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return None
    
    with open(file_path) as f:
        data = json.load(f)
    
    return data


def save_contributors(data, file_path):
    """Save contributors to JSON file"""
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    logger.info(f"Saved to {file_path}")


def create_combined_dataset(event_data, organic_data, output_file):
    """Create combined dataset of all 8,000 contributors"""
    
    event_contributors = event_data.get('contributors', [])
    organic_contributors = organic_data.get('contributors', [])
    
    # Add contributor type
    for contributor in event_contributors:
        contributor['contributor_type'] = 'event'
    
    for contributor in organic_contributors:
        contributor['contributor_type'] = 'organic'
    
    combined = {
        'generated_at': datetime.now().isoformat(),
        'description': 'Combined dataset of event and organic contributors after bot filtering',
        'total_contributors': len(event_contributors) + len(organic_contributors),
        'event_contributors': len(event_contributors),
        'organic_contributors': len(organic_contributors),
        'contributors': event_contributors + organic_contributors
    }
    
    with open(output_file, 'w') as f:
        json.dump(combined, f, indent=2)
    
    logger.info(f"Created combined dataset: {output_file}")
    logger.info(f"  Event: {len(event_contributors):,}")
    logger.info(f"  Organic: {len(organic_contributors):,}")
    logger.info(f"  Total: {combined['total_contributors']:,}")


def generate_bot_report(event_bots, organic_bots, output_file):
    """Generate detailed bot detection report"""
    
    # Count by reason
    from collections import Counter
    
    event_reasons = Counter(bot['reason'] for bot in event_bots)
    organic_reasons = Counter(bot['reason'] for bot in organic_bots)
    
    report = {
        'generated_at': datetime.now().isoformat(),
        'total_bots_detected': len(event_bots) + len(organic_bots),
        'event_bots': len(event_bots),
        'organic_bots': len(organic_bots),
        'detection_patterns_used': {
            'username_patterns': CONFIG['bot_filtering']['username_patterns'],
            'email_patterns': CONFIG['bot_filtering']['email_patterns']
        },
        'event_bots_by_reason': dict(event_reasons),
        'organic_bots_by_reason': dict(organic_reasons),
        'event_bot_examples': event_bots[:50],  # First 50 examples
        'organic_bot_examples': organic_bots[:50]
    }
    
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"Bot detection report saved: {output_file}")


def print_summary(event_before, event_after, organic_before, organic_after, event_bots, organic_bots):
    """Print filtering summary"""
    logger.info("="*80)
    logger.info("BOT FILTERING SUMMARY")
    logger.info("="*80)
    
    logger.info("\nEVENT CONTRIBUTORS:")
    logger.info(f"  Before: {event_before:,}")
    logger.info(f"  Bots removed: {len(event_bots):,} ({len(event_bots)/event_before*100 if event_before > 0 else 0:.1f}%)")
    logger.info(f"  After: {event_after:,}")
    
    logger.info("\nORGANIC CONTRIBUTORS:")
    logger.info(f"  Before: {organic_before:,}")
    logger.info(f"  Bots removed: {len(organic_bots):,} ({len(organic_bots)/organic_before*100 if organic_before > 0 else 0:.1f}%)")
    logger.info(f"  After: {organic_after:,}")
    
    logger.info("\nTOTAL:")
    logger.info(f"  Before: {event_before + organic_before:,}")
    logger.info(f"  Bots removed: {len(event_bots) + len(organic_bots):,}")
    logger.info(f"  After: {event_after + organic_after:,}")
    
    logger.info("="*80)


def main():
    parser = argparse.ArgumentParser(description="Filter bot accounts from contributor datasets")
    parser.add_argument("--test", action="store_true", help="Run in test mode")
    args = parser.parse_args()
    
    start_time = datetime.now()
    logger.info(f"Script started at {start_time}")
    logger.info("="*80)
    logger.info("STEP 5: FILTER BOT ACCOUNTS")
    logger.info("="*80)
    
    if not CONFIG["bot_filtering"]["enabled"]:
        logger.warning("Bot filtering is DISABLED in config")
        logger.warning("Skipping bot filtering")
        return 0
    
    try:
        # Determine input/output directory
        data_dir = PROJECT_ROOT / (CONFIG["paths"]["test_output_folder"] if args.test else CONFIG["paths"]["output_folder"])
        
        # Load event contributors
        event_file = data_dir / "event_contributors_final.json"
        event_data = load_contributors(event_file)
        
        if not event_data:
            logger.error("Failed to load event contributors")
            return 1
        
        # Load organic contributors
        organic_file = data_dir / "organic_contributors_final.json"
        organic_data = load_contributors(organic_file)
        
        if not organic_data:
            logger.error("Failed to load organic contributors")
            return 1
        
        # Store before counts
        event_before = len(event_data.get('contributors', []))
        organic_before = len(organic_data.get('contributors', []))
        
        # Filter bots from event contributors
        event_filtered, event_bots = filter_bots_from_list(
            event_data.get('contributors', []),
            "event contributors"
        )
        
        # Filter bots from organic contributors
        organic_filtered, organic_bots = filter_bots_from_list(
            organic_data.get('contributors', []),
            "organic contributors"
        )
        
        # Update datasets
        event_data['contributors'] = event_filtered
        event_data['bot_filtering'] = {
            'applied': True,
            'bots_removed': len(event_bots),
            'timestamp': datetime.now().isoformat()
        }
        
        organic_data['contributors'] = organic_filtered
        organic_data['bot_filtering'] = {
            'applied': True,
            'bots_removed': len(organic_bots),
            'timestamp': datetime.now().isoformat()
        }
        
        # Save updated files
        save_contributors(event_data, event_file)
        save_contributors(organic_data, organic_file)
        
        # Create combined dataset
        combined_file = data_dir / "all_contributors_8k.json"
        create_combined_dataset(event_data, organic_data, combined_file)
        
        # Generate bot detection report
        bot_report_file = data_dir / "bot_detection_report.json"
        generate_bot_report(event_bots, organic_bots, bot_report_file)
        
        # Print summary
        print_summary(
            event_before, len(event_filtered),
            organic_before, len(organic_filtered),
            event_bots, organic_bots
        )
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Script completed at {end_time}")
        logger.info(f"Total duration: {duration}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error during bot filtering: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
