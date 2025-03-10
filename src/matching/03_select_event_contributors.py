#!/usr/bin/env python3
"""
Step 3: Select Event Contributors

Selects 4,000 event contributors:
- Mentorship: All GSoC (1,750) + All LFX (251) = 2,001
- Non-mentorship: Sample 1,000 from Hacktoberfest + 1,000 from 24PR = 2,000

Sampling strategy for non-mentorship:
- Exclude one-time contributors (1 commit/PR only)
- Stratified random sampling by activity level (log2 bins)
- Random selection within strata

Output: event_contributors_final.json with 4,000 contributors
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
import math
import random
from collections import defaultdict

# Setup paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.append(str(PROJECT_ROOT))

# Load configuration
with open(SCRIPT_DIR / "config.json") as f:
    CONFIG = json.load(f)

# Setup logging
LOG_FILE = PROJECT_ROOT / CONFIG["paths"]["logs_folder"] / "03_select_event.log"
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

# Set random seed for reproducibility
random.seed(CONFIG["sampling"]["random_seed"])


def load_event_contributors(event_name):
    """Load contributor data for a specific event"""
    file_path = PROJECT_ROOT / CONFIG["event_contributor_files"][event_name]
    
    with open(file_path) as f:
        data = json.load(f)
    
    logger.info(f"Loaded {event_name}: {len(data.get('contributors', []))} contributors")
    return data


def calculate_activity_bin(commit_count):
    """Calculate log2 bin for activity stratification"""
    if commit_count <= 0:
        return 0
    return int(math.floor(math.log2(commit_count)))


def select_all_mentorship():
    """Select all contributors from mentorship events (GSoC and LFX)"""
    logger.info("Selecting all mentorship contributors...")
    
    # Load GSoC
    gsoc_data = load_event_contributors('gsoc')
    gsoc_contributors = gsoc_data.get('contributors', [])
    
    # Add event and selection metadata
    for contributor in gsoc_contributors:
        contributor['selection_event'] = 'gsoc'
        contributor['selection_method'] = 'all'
        contributor['is_mentorship'] = True
    
    # Load LFX
    lfx_data = load_event_contributors('lfx')
    lfx_contributors = lfx_data.get('contributors', [])
    
    # Add event and selection metadata
    for contributor in lfx_contributors:
        contributor['selection_event'] = 'lfx'
        contributor['selection_method'] = 'all'
        contributor['is_mentorship'] = True
    
    all_mentorship = gsoc_contributors + lfx_contributors
    
    logger.info(f"Selected {len(gsoc_contributors)} GSoC + {len(lfx_contributors)} LFX = {len(all_mentorship)} mentorship contributors")
    
    return all_mentorship


def stratified_sample_by_activity(contributors, target_count, event_name):
    """
    Stratified random sampling by activity level (log2 bins)
    
    Steps:
    1. Exclude one-time contributors
    2. Group by activity bin
    3. Calculate proportional sample size per bin
    4. Random sample from each bin
    """
    logger.info(f"Stratified sampling {target_count} from {event_name}...")
    
    # Step 1: Filter to multi-commit contributors
    min_commits = CONFIG["sampling"]["min_commits_for_sampling"]
    
    if event_name == 'hacktoberfest':
        # Use total_prs for Hacktoberfest
        multi_contributors = [c for c in contributors if c.get('total_prs', 0) >= min_commits]
        activity_field = 'total_prs'
    else:
        # Use total_prs for 24PR
        multi_contributors = [c for c in contributors if c.get('total_prs', 0) >= min_commits]
        activity_field = 'total_prs'
    
    logger.info(f"  Total contributors: {len(contributors)}")
    logger.info(f"  Multi-commit (>={min_commits}): {len(multi_contributors)}")
    
    if len(multi_contributors) < target_count:
        logger.warning(f"  WARNING: Only {len(multi_contributors)} available, target is {target_count}")
        logger.warning(f"  Taking all available multi-commit contributors")
        return multi_contributors
    
    # Step 2: Group by activity bin
    bins = defaultdict(list)
    for contributor in multi_contributors:
        activity = contributor.get(activity_field, 0)
        bin_num = calculate_activity_bin(activity)
        bins[bin_num].append(contributor)
    
    logger.info(f"  Activity bins: {len(bins)}")
    for bin_num in sorted(bins.keys()):
        logger.info(f"    Bin {bin_num}: {len(bins[bin_num])} contributors")
    
    # Step 3: Calculate proportional sample sizes
    total_available = len(multi_contributors)
    sample_sizes = {}
    
    for bin_num, bin_contributors in bins.items():
        proportion = len(bin_contributors) / total_available
        sample_size = int(round(proportion * target_count))
        # Ensure we sample at least 1 if bin is non-empty
        sample_size = max(1, min(sample_size, len(bin_contributors)))
        sample_sizes[bin_num] = sample_size
    
    # Adjust to hit exact target (may be off due to rounding)
    total_sampled = sum(sample_sizes.values())
    if total_sampled != target_count:
        diff = target_count - total_sampled
        # Adjust the largest bin
        largest_bin = max(bins.keys(), key=lambda b: len(bins[b]))
        sample_sizes[largest_bin] = max(1, sample_sizes[largest_bin] + diff)
    
    logger.info(f"  Sample sizes per bin:")
    for bin_num in sorted(sample_sizes.keys()):
        logger.info(f"    Bin {bin_num}: {sample_sizes[bin_num]} / {len(bins[bin_num])}")
    
    # Step 4: Random sample from each bin
    selected = []
    for bin_num, sample_size in sample_sizes.items():
        bin_sample = random.sample(bins[bin_num], sample_size)
        selected.extend(bin_sample)
    
    # Add selection metadata
    for contributor in selected:
        contributor['selection_event'] = event_name
        contributor['selection_method'] = 'stratified_sample'
        contributor['is_mentorship'] = False
        contributor['activity_bin'] = calculate_activity_bin(contributor.get(activity_field, 0))
    
    logger.info(f"  Selected: {len(selected)} contributors")
    
    return selected


def select_hacktoberfest_sample(target_count):
    """Sample contributors from Hacktoberfest"""
    hf_data = load_event_contributors('hacktoberfest')
    contributors = hf_data.get('contributors', [])
    
    return stratified_sample_by_activity(contributors, target_count, 'hacktoberfest')


def select_24pr_sample(target_count):
    """Sample contributors from 24 Pull Requests"""
    pr24_data = load_event_contributors('24pr')
    contributors = pr24_data.get('contributors', [])
    
    return stratified_sample_by_activity(contributors, target_count, '24pr')


def generate_summary(all_contributors):
    """Generate selection summary statistics"""
    summary = {
        'total_selected': len(all_contributors),
        'by_event': {},
        'by_type': {
            'mentorship': 0,
            'non_mentorship': 0
        },
        'activity_distribution': defaultdict(int)
    }
    
    # Count by event
    for contributor in all_contributors:
        event = contributor.get('selection_event', 'unknown')
        summary['by_event'][event] = summary['by_event'].get(event, 0) + 1
        
        # Count by type
        if contributor.get('is_mentorship', False):
            summary['by_type']['mentorship'] += 1
        else:
            summary['by_type']['non_mentorship'] += 1
        
        # Activity distribution (for non-mentorship)
        if 'activity_bin' in contributor:
            summary['activity_distribution'][contributor['activity_bin']] += 1
    
    # Convert defaultdict to regular dict for JSON serialization
    summary['activity_distribution'] = dict(summary['activity_distribution'])
    
    return summary


def save_output(all_contributors, summary, output_file):
    """Save selected contributors to JSON"""
    output = {
        'generated_at': datetime.now().isoformat(),
        'selection_criteria': {
            'mentorship_events': 'all contributors',
            'non_mentorship_events': 'stratified sample (>1 commit)',
            'random_seed': CONFIG['sampling']['random_seed']
        },
        'summary': summary,
        'contributors': all_contributors
    }
    
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    logger.info(f"Saved {len(all_contributors)} contributors to {output_file}")


def print_summary(summary):
    """Print human-readable summary"""
    logger.info("="*80)
    logger.info("EVENT CONTRIBUTOR SELECTION SUMMARY")
    logger.info("="*80)
    logger.info(f"\nTotal Selected: {summary['total_selected']:,}")
    
    logger.info("\nBy Event:")
    for event, count in sorted(summary['by_event'].items()):
        logger.info(f"  {event}: {count:,}")
    
    logger.info("\nBy Type:")
    logger.info(f"  Mentorship: {summary['by_type']['mentorship']:,}")
    logger.info(f"  Non-mentorship: {summary['by_type']['non_mentorship']:,}")
    
    if summary['activity_distribution']:
        logger.info("\nActivity Distribution (log2 bins):")
        for bin_num in sorted(summary['activity_distribution'].keys()):
            count = summary['activity_distribution'][bin_num]
            logger.info(f"  Bin {bin_num}: {count:,}")
    
    logger.info("="*80)


def main():
    parser = argparse.ArgumentParser(description="Select 4,000 event contributors")
    parser.add_argument("--test", action="store_true", help="Run in test mode (smaller sample)")
    args = parser.parse_args()
    
    start_time = datetime.now()
    logger.info(f"Script started at {start_time}")
    logger.info("="*80)
    logger.info("STEP 3: SELECT EVENT CONTRIBUTORS")
    logger.info("="*80)
    
    try:
        # Adjust targets for test mode
        if args.test:
            hf_target = 50
            pr24_target = 50
            logger.info("TEST MODE: Using smaller sample sizes")
        else:
            hf_target = CONFIG['target_counts']['hacktoberfest']
            pr24_target = CONFIG['target_counts']['24pr']
        
        # Select mentorship (all)
        mentorship_contributors = select_all_mentorship()
        
        # Sample non-mentorship
        hf_contributors = select_hacktoberfest_sample(hf_target)
        pr24_contributors = select_24pr_sample(pr24_target)
        
        # Combine all
        all_contributors = mentorship_contributors + hf_contributors + pr24_contributors
        
        # Generate summary
        summary = generate_summary(all_contributors)
        
        # Save output
        output_dir = PROJECT_ROOT / (CONFIG["paths"]["test_output_folder"] if args.test else CONFIG["paths"]["output_folder"])
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "event_contributors_final.json"
        
        save_output(all_contributors, summary, output_file)
        
        # Print summary
        print_summary(summary)
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Script completed at {end_time}")
        logger.info(f"Total duration: {duration}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error during selection: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
