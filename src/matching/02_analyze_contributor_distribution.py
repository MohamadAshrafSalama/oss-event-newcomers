#!/usr/bin/env python3
"""
Step 2: Analyze Contributor Distribution

Analyzes one-time vs multi-commit contributors for Hacktoberfest and 24PR
to inform sampling strategy for selecting 1,000 from each event.

Metrics calculated:
- Total contributors
- One-time contributors (1 commit/PR only)
- Multi-commit contributors (>1)
- Distribution by commit count bins
- Percentage breakdown

Output helps decide sampling strategy for Step 3.
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime
from collections import Counter
import math

# Setup paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.append(str(PROJECT_ROOT))

# Load configuration
with open(SCRIPT_DIR / "config.json") as f:
    CONFIG = json.load(f)

# Setup logging
LOG_FILE = PROJECT_ROOT / CONFIG["paths"]["logs_folder"] / "02_analyze_distribution.log"
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


def load_event_contributors(event_name):
    """Load contributor data for a specific event"""
    file_path = PROJECT_ROOT / CONFIG["event_contributor_files"][event_name]
    
    if not file_path.exists():
        logger.error(f"Contributor file not found: {file_path}")
        return None
    
    with open(file_path) as f:
        data = json.load(f)
    
    logger.info(f"Loaded {event_name} data: {len(data.get('contributors', []))} contributors")
    return data


def calculate_commit_bins(commit_count):
    """Calculate log2 bin for commit count (for activity stratification)"""
    if commit_count <= 0:
        return 0
    return int(math.floor(math.log2(commit_count)))


def analyze_hacktoberfest(contributors_data):
    """Analyze Hacktoberfest contributor distribution"""
    logger.info("Analyzing Hacktoberfest contributors...")
    
    contributors = contributors_data.get('contributors', [])
    
    # Extract PR counts per contributor
    pr_counts = []
    first_time_count = 0
    
    for contributor in contributors:
        total_prs = contributor.get('total_prs', 0)
        first_contributions = contributor.get('first_contributions', 0)
        
        pr_counts.append(total_prs)
        if first_contributions > 0:
            first_time_count += 1
    
    # Calculate statistics
    total = len(pr_counts)
    one_time = sum(1 for count in pr_counts if count == 1)
    multi = sum(1 for count in pr_counts if count > 1)
    
    # Bin distribution
    bins = {
        '1': 0,
        '2-5': 0,
        '6-10': 0,
        '11-50': 0,
        '51+': 0
    }
    
    for count in pr_counts:
        if count == 1:
            bins['1'] += 1
        elif 2 <= count <= 5:
            bins['2-5'] += 1
        elif 6 <= count <= 10:
            bins['6-10'] += 1
        elif 11 <= count <= 50:
            bins['11-50'] += 1
        else:
            bins['51+'] += 1
    
    # Log2 bins for stratification
    log2_bins = Counter(calculate_commit_bins(count) for count in pr_counts)
    
    analysis = {
        'event': 'hacktoberfest',
        'total_contributors': total,
        'one_time_contributors': one_time,
        'multi_contributors': multi,
        'first_time_contributors': first_time_count,
        'percentages': {
            'one_time_pct': (one_time / total * 100) if total > 0 else 0,
            'multi_pct': (multi / total * 100) if total > 0 else 0,
            'first_time_pct': (first_time_count / total * 100) if total > 0 else 0
        },
        'pr_count_distribution': bins,
        'log2_bins': dict(log2_bins),
        'statistics': {
            'min_prs': min(pr_counts) if pr_counts else 0,
            'max_prs': max(pr_counts) if pr_counts else 0,
            'avg_prs': sum(pr_counts) / len(pr_counts) if pr_counts else 0,
            'median_prs': sorted(pr_counts)[len(pr_counts)//2] if pr_counts else 0
        },
        'sampling_pool': {
            'available_for_sampling': multi,
            'target': CONFIG['target_counts']['hacktoberfest'],
            'sufficient': multi >= CONFIG['target_counts']['hacktoberfest']
        }
    }
    
    return analysis


def analyze_24pr(contributors_data):
    """Analyze 24 Pull Requests contributor distribution"""
    logger.info("Analyzing 24 Pull Requests contributors...")
    
    contributors = contributors_data.get('contributors', [])
    
    # Extract PR counts per contributor
    pr_counts = []
    
    for contributor in contributors:
        total_prs = contributor.get('total_prs', 0)
        pr_counts.append(total_prs)
    
    # Calculate statistics
    total = len(pr_counts)
    one_time = sum(1 for count in pr_counts if count == 1)
    multi = sum(1 for count in pr_counts if count > 1)
    
    # Bin distribution
    bins = {
        '1': 0,
        '2-5': 0,
        '6-10': 0,
        '11-50': 0,
        '51+': 0
    }
    
    for count in pr_counts:
        if count == 1:
            bins['1'] += 1
        elif 2 <= count <= 5:
            bins['2-5'] += 1
        elif 6 <= count <= 10:
            bins['6-10'] += 1
        elif 11 <= count <= 50:
            bins['11-50'] += 1
        else:
            bins['51+'] += 1
    
    # Log2 bins for stratification
    log2_bins = Counter(calculate_commit_bins(count) for count in pr_counts)
    
    analysis = {
        'event': '24_pull_requests',
        'total_contributors': total,
        'one_time_contributors': one_time,
        'multi_contributors': multi,
        'percentages': {
            'one_time_pct': (one_time / total * 100) if total > 0 else 0,
            'multi_pct': (multi / total * 100) if total > 0 else 0
        },
        'pr_count_distribution': bins,
        'log2_bins': dict(log2_bins),
        'statistics': {
            'min_prs': min(pr_counts) if pr_counts else 0,
            'max_prs': max(pr_counts) if pr_counts else 0,
            'avg_prs': sum(pr_counts) / len(pr_counts) if pr_counts else 0,
            'median_prs': sorted(pr_counts)[len(pr_counts)//2] if pr_counts else 0
        },
        'sampling_pool': {
            'available_for_sampling': multi,
            'target': CONFIG['target_counts']['24pr'],
            'sufficient': multi >= CONFIG['target_counts']['24pr']
        }
    }
    
    return analysis


def analyze_mentorship_events():
    """Analyze GSoC and LFX (mentorship events - take all)"""
    logger.info("Analyzing mentorship events (GSoC and LFX)...")
    
    # Load GSoC
    gsoc_data = load_event_contributors('gsoc')
    gsoc_count = len(gsoc_data.get('contributors', [])) if gsoc_data else 0
    
    # Load LFX
    lfx_data = load_event_contributors('lfx')
    lfx_count = len(lfx_data.get('contributors', [])) if lfx_data else 0
    
    analysis = {
        'gsoc': {
            'event': 'google_summer_of_code',
            'total_contributors': gsoc_count,
            'selection_method': 'take_all',
            'target': gsoc_count
        },
        'lfx': {
            'event': 'lfx_mentorship',
            'total_contributors': lfx_count,
            'selection_method': 'take_all',
            'target': lfx_count
        },
        'mentorship_total': gsoc_count + lfx_count
    }
    
    return analysis


def generate_report(hf_analysis, pr24_analysis, mentorship_analysis, output_file):
    """Generate comprehensive distribution analysis report"""
    
    report = {
        'generated_at': datetime.now().isoformat(),
        'summary': {
            'hacktoberfest': {
                'total': hf_analysis['total_contributors'],
                'one_time': hf_analysis['one_time_contributors'],
                'multi': hf_analysis['multi_contributors'],
                'multi_pct': hf_analysis['percentages']['multi_pct'],
                'target': CONFIG['target_counts']['hacktoberfest'],
                'sufficient': hf_analysis['sampling_pool']['sufficient']
            },
            '24_pull_requests': {
                'total': pr24_analysis['total_contributors'],
                'one_time': pr24_analysis['one_time_contributors'],
                'multi': pr24_analysis['multi_contributors'],
                'multi_pct': pr24_analysis['percentages']['multi_pct'],
                'target': CONFIG['target_counts']['24pr'],
                'sufficient': pr24_analysis['sampling_pool']['sufficient']
            },
            'mentorship': {
                'gsoc': mentorship_analysis['gsoc']['total_contributors'],
                'lfx': mentorship_analysis['lfx']['total_contributors'],
                'total': mentorship_analysis['mentorship_total']
            },
            'grand_total': {
                'event_target': CONFIG['target_counts']['total_event'],
                'organic_target': CONFIG['target_counts']['total_organic'],
                'grand_total': CONFIG['target_counts']['grand_total']
            }
        },
        'detailed_analysis': {
            'hacktoberfest': hf_analysis,
            '24_pull_requests': pr24_analysis,
            'mentorship': mentorship_analysis
        },
        'recommendations': {
            'hacktoberfest': 'Sample from multi-commit contributors using stratified random sampling' if hf_analysis['sampling_pool']['sufficient'] else 'WARNING: Insufficient multi-commit contributors',
            '24_pull_requests': 'Sample from multi-commit contributors using stratified random sampling' if pr24_analysis['sampling_pool']['sufficient'] else 'WARNING: Insufficient multi-commit contributors',
            'mentorship': 'Take all contributors from both GSoC and LFX'
        }
    }
    
    # Save report
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    return report


def print_summary(report):
    """Print human-readable summary"""
    logger.info("="*80)
    logger.info("DISTRIBUTION ANALYSIS SUMMARY")
    logger.info("="*80)
    
    summary = report['summary']
    
    logger.info("\nHACKTOBERFEST:")
    logger.info(f"  Total: {summary['hacktoberfest']['total']:,}")
    logger.info(f"  One-time: {summary['hacktoberfest']['one_time']:,} ({100-summary['hacktoberfest']['multi_pct']:.1f}%)")
    logger.info(f"  Multi-commit: {summary['hacktoberfest']['multi']:,} ({summary['hacktoberfest']['multi_pct']:.1f}%)")
    logger.info(f"  Target: {summary['hacktoberfest']['target']:,}")
    logger.info(f"  Sufficient pool: {'YES' if summary['hacktoberfest']['sufficient'] else 'NO'}")
    
    logger.info("\n24 PULL REQUESTS:")
    logger.info(f"  Total: {summary['24_pull_requests']['total']:,}")
    logger.info(f"  One-time: {summary['24_pull_requests']['one_time']:,} ({100-summary['24_pull_requests']['multi_pct']:.1f}%)")
    logger.info(f"  Multi-commit: {summary['24_pull_requests']['multi']:,} ({summary['24_pull_requests']['multi_pct']:.1f}%)")
    logger.info(f"  Target: {summary['24_pull_requests']['target']:,}")
    logger.info(f"  Sufficient pool: {'YES' if summary['24_pull_requests']['sufficient'] else 'NO'}")
    
    logger.info("\nMENTORSHIP (take all):")
    logger.info(f"  GSoC: {summary['mentorship']['gsoc']:,}")
    logger.info(f"  LFX: {summary['mentorship']['lfx']:,}")
    logger.info(f"  Total: {summary['mentorship']['total']:,}")
    
    logger.info("\nGRAND TOTAL TARGET:")
    logger.info(f"  Event contributors: {summary['grand_total']['event_target']:,}")
    logger.info(f"  Organic contributors: {summary['grand_total']['organic_target']:,}")
    logger.info(f"  Total: {summary['grand_total']['grand_total']:,}")
    logger.info("="*80)


def main():
    parser = argparse.ArgumentParser(description="Analyze contributor distribution for sampling")
    parser.add_argument("--test", action="store_true", help="Run in test mode")
    args = parser.parse_args()
    
    start_time = datetime.now()
    logger.info(f"Script started at {start_time}")
    logger.info("="*80)
    logger.info("STEP 2: CONTRIBUTOR DISTRIBUTION ANALYSIS")
    logger.info("="*80)
    
    try:
        # Load event data
        hf_data = load_event_contributors('hacktoberfest')
        pr24_data = load_event_contributors('24pr')
        
        if not hf_data or not pr24_data:
            logger.error("Failed to load event contributor data")
            return 1
        
        # Analyze distributions
        hf_analysis = analyze_hacktoberfest(hf_data)
        pr24_analysis = analyze_24pr(pr24_data)
        mentorship_analysis = analyze_mentorship_events()
        
        # Generate report
        output_dir = PROJECT_ROOT / (CONFIG["paths"]["test_output_folder"] if args.test else CONFIG["paths"]["output_folder"])
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "contributor_distribution_analysis.json"
        
        report = generate_report(hf_analysis, pr24_analysis, mentorship_analysis, output_file)
        
        # Print summary
        print_summary(report)
        
        logger.info(f"\nReport saved to: {output_file}")
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Script completed at {end_time}")
        logger.info(f"Total duration: {duration}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error during analysis: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
