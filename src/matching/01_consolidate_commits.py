#!/usr/bin/env python3
"""
Step 1: Consolidate Commits from Per-Repo CSVs

This script merges all per-repo commit CSVs from the external drive into
a single consolidated CSV with only the fields needed for matching.

Fields extracted:
- repo_name
- author_email (primary identifier)
- author_name (fallback)
- author_date (for lifecycle stage)
- subject (for event detection)

Features:
- Resumable (tracks progress in JSON)
- Progress bars
- Test mode
- Detailed logging
"""

import os
import sys
import json
import csv
import logging
import argparse
from pathlib import Path
from datetime import datetime
from tqdm import tqdm
import glob

# Setup paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.append(str(PROJECT_ROOT))

# Load configuration
with open(SCRIPT_DIR / "config.json") as f:
    CONFIG = json.load(f)

# Setup logging
LOG_FILE = PROJECT_ROOT / CONFIG["paths"]["logs_folder"] / "01_consolidate_commits.log"
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


def load_progress(progress_file):
    """Load progress from JSON file"""
    if progress_file.exists():
        with open(progress_file) as f:
            return json.load(f)
    return {"processed_files": [], "total_commits": 0, "total_files": 0}


def save_progress(progress_file, progress):
    """Save progress to JSON file"""
    with open(progress_file, 'w') as f:
        json.dump(progress, f, indent=2)


def get_csv_files(extracted_dir, test_mode=False):
    """Get list of CSV files to process"""
    pattern = os.path.join(extracted_dir, "*.csv")
    all_files = sorted(glob.glob(pattern))
    
    if test_mode:
        sample_size = CONFIG["test_mode"]["sample_repos"]
        all_files = all_files[:sample_size]
        logger.info(f"TEST MODE: Processing only {len(all_files)} files")
    
    return all_files


def normalize_email(email):
    """Normalize email address for consistent matching"""
    if not email or email == "":
        return None
    return email.lower().strip()


def extract_repo_name_from_filename(filepath):
    """Extract repo name from CSV filename (format: owner__repo.csv)"""
    filename = Path(filepath).stem  # Remove .csv
    # Convert owner__repo back to owner/repo
    return filename.replace("__", "/")


def process_csv_file(filepath, output_writer, stats):
    """Process a single CSV file and extract required fields"""
    repo_name = extract_repo_name_from_filename(filepath)
    commits_processed = 0
    commits_skipped = 0
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Extract required fields
                author_email = normalize_email(row.get('author_email', ''))
                author_name = row.get('author_name', '').strip()
                author_date = row.get('author_date', '').strip()
                subject = row.get('subject', '').strip()
                
                # Skip if no author email (can't identify contributor)
                if not author_email:
                    commits_skipped += 1
                    continue
                
                # Write consolidated record
                output_writer.writerow({
                    'repo_name': repo_name,
                    'author_email': author_email,
                    'author_name': author_name,
                    'author_date': author_date,
                    'subject': subject
                })
                
                commits_processed += 1
        
        stats['total_commits'] += commits_processed
        stats['skipped_commits'] += commits_skipped
        stats['successful_files'] += 1
        
        return True, commits_processed
        
    except Exception as e:
        logger.error(f"Error processing {filepath}: {e}")
        stats['failed_files'] += 1
        return False, 0


def consolidate_commits(test_mode=False):
    """Main consolidation function"""
    logger.info("="*80)
    logger.info("STEP 1: CONSOLIDATE COMMITS")
    logger.info("="*80)
    
    # Setup paths
    extracted_dir = CONFIG["paths"]["extracted_commits"]
    output_dir = PROJECT_ROOT / (CONFIG["paths"]["test_output_folder"] if test_mode else CONFIG["paths"]["output_folder"])
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / "all_commits_consolidated.csv"
    progress_file = output_dir / "consolidate_progress.json"
    
    # Check if external drive is mounted
    if not Path(extracted_dir).exists():
        logger.error(f"External drive not found: {extracted_dir}")
        logger.error("Please mount the external drive and try again")
        return False
    
    # Get list of CSV files
    csv_files = get_csv_files(extracted_dir, test_mode)
    logger.info(f"Found {len(csv_files)} CSV files to process")
    
    # Load progress
    progress = load_progress(progress_file)
    processed_set = set(progress.get("processed_files", []))
    
    # Filter to unprocessed files
    files_to_process = [f for f in csv_files if f not in processed_set]
    logger.info(f"Already processed: {len(processed_set)} files")
    logger.info(f"Remaining to process: {len(files_to_process)} files")
    
    if not files_to_process:
        logger.info("All files already processed!")
        return True
    
    # Statistics
    stats = {
        'total_commits': progress.get("total_commits", 0),
        'skipped_commits': 0,
        'successful_files': progress.get("total_files", 0),
        'failed_files': 0
    }
    
    # Open output file in append mode
    mode = 'a' if output_file.exists() else 'w'
    write_header = not output_file.exists()
    
    with open(output_file, mode, newline='', encoding='utf-8') as f:
        fieldnames = ['repo_name', 'author_email', 'author_name', 'author_date', 'subject']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        if write_header:
            writer.writeheader()
        
        # Process each file
        for filepath in tqdm(files_to_process, desc="Processing CSV files", disable=not CONFIG["performance"]["progress_bar"]):
            success, commit_count = process_csv_file(filepath, writer, stats)
            
            if success:
                # Update progress
                processed_set.add(filepath)
                progress["processed_files"] = list(processed_set)
                progress["total_commits"] = stats['total_commits']
                progress["total_files"] = stats['successful_files']
                
                # Save progress periodically
                if stats['successful_files'] % CONFIG["resume"]["checkpoint_interval"] == 0:
                    save_progress(progress_file, progress)
                    logger.info(f"Checkpoint: {stats['successful_files']} files, {stats['total_commits']} commits")
    
    # Final save
    save_progress(progress_file, progress)
    
    # Summary
    logger.info("="*80)
    logger.info("CONSOLIDATION COMPLETE")
    logger.info("="*80)
    logger.info(f"Successful files: {stats['successful_files']}")
    logger.info(f"Failed files: {stats['failed_files']}")
    logger.info(f"Total commits: {stats['total_commits']:,}")
    logger.info(f"Skipped commits (no email): {stats['skipped_commits']:,}")
    logger.info(f"Output file: {output_file}")
    logger.info(f"Output size: {output_file.stat().st_size / 1024 / 1024:.2f} MB")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Consolidate commit CSVs from per-repo files")
    parser.add_argument("--test", action="store_true", help="Run in test mode (sample data only)")
    args = parser.parse_args()
    
    start_time = datetime.now()
    logger.info(f"Script started at {start_time}")
    
    success = consolidate_commits(test_mode=args.test)
    
    end_time = datetime.now()
    duration = end_time - start_time
    logger.info(f"Script completed at {end_time}")
    logger.info(f"Total duration: {duration}")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
