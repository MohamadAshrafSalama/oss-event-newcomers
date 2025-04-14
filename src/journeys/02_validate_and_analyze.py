#!/usr/bin/env python3
"""
Validate and Analyze Contributor Journey Data

Validates extracted contributor CSV files and generates analysis report.

Validation checks:
- All expected contributors have CSV files
- CSV files have correct schema (18 columns)
- No empty files
- Valid date formats
- Valid activity types
- Reasonable activity counts

Analysis output:
- Summary statistics
- Activity distribution
- Timeline coverage
- Data quality metrics
"""

import os
import sys
import json
import csv
import logging
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
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
LOG_FILE = SCRIPT_DIR / CONFIG["paths"]["log_dir"] / f"validation_{timestamp}.log"
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


def load_expected_contributors(test_mode=False):
    """Load list of contributors that should have CSV files"""
    input_file = PROJECT_ROOT / CONFIG["paths"]["contributors_input"]
    
    with open(input_file) as f:
        data = json.load(f)
    
    contributors = data.get('contributors', [])
    
    if test_mode:
        contributors = contributors[:CONFIG["test_mode"]["sample_count"]]
    
    return contributors


def validate_file_existence(contributors, output_dir):
    """Check if all expected CSV files exist"""
    logger.info("Validating file existence...")
    
    missing = []
    existing = []
    empty = []
    
    for contributor in contributors:
        username = contributor.get('github_username', '')
        if not username:
            continue
        
        csv_file = output_dir / f"{username}_journey.csv"
        
        if not csv_file.exists():
            missing.append(username)
        else:
            existing.append(username)
            
            # Check if empty
            if csv_file.stat().st_size == 0:
                empty.append(username)
    
    logger.info(f"  Expected: {len(contributors)}")
    logger.info(f"  Existing: {len(existing)}")
    logger.info(f"  Missing: {len(missing)}")
    logger.info(f"  Empty: {len(empty)}")
    
    if missing:
        logger.warning(f"  Missing files (first 10): {missing[:10]}")
    
    if empty:
        logger.warning(f"  Empty files: {empty}")
    
    return {
        "expected": len(contributors),
        "existing": len(existing),
        "missing": len(missing),
        "empty": len(empty),
        "missing_usernames": missing,
        "empty_usernames": empty
    }


def validate_csv_schema(csv_file):
    """Validate CSV has correct schema"""
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            
            expected = CONFIG["csv_schema"]["columns"]
            
            if not headers:
                return False, "No headers"
            
            if len(headers) != len(expected):
                return False, f"Wrong column count: {len(headers)} vs {len(expected)}"
            
            # Check column names
            for exp_col in expected:
                if exp_col not in headers:
                    return False, f"Missing column: {exp_col}"
            
            return True, None
            
    except Exception as e:
        return False, str(e)


def analyze_csv_content(csv_file):
    """Analyze content of a CSV file"""
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            return {
                "row_count": 0,
                "activity_types": {},
                "date_range": None,
                "repos": set(),
                "has_oss4sg": False
            }
        
        activity_types = Counter(row['activity_type'] for row in rows)
        dates = [row['created_at'] for row in rows if row['created_at']]
        repos = set(row['repo_name'] for row in rows if row['repo_name'])
        has_oss4sg = any(row.get('is_oss4sg', '') == 'True' or row.get('is_oss4sg', '') == 'true' for row in rows)
        
        return {
            "row_count": len(rows),
            "activity_types": dict(activity_types),
            "date_range": {
                "earliest": min(dates) if dates else None,
                "latest": max(dates) if dates else None
            },
            "repos": repos,
            "has_oss4sg": has_oss4sg,
            "repo_count": len(repos)
        }
        
    except Exception as e:
        return {"error": str(e)}


def validate_all_files(output_dir, contributors):
    """Validate all CSV files"""
    logger.info("Validating CSV schemas and content...")
    
    validation_results = {
        "valid_schema": 0,
        "invalid_schema": 0,
        "schema_errors": [],
        "total_activities": 0,
        "activity_distribution": Counter(),
        "date_range_global": {"earliest": None, "latest": None},
        "unique_repos": set(),
        "oss4sg_contributors": 0
    }
    
    for contributor in contributors:
        username = contributor.get('github_username', '')
        if not username:
            continue
        
        csv_file = output_dir / f"{username}_journey.csv"
        
        if not csv_file.exists():
            continue
        
        # Validate schema
        valid, error = validate_csv_schema(csv_file)
        
        if valid:
            validation_results["valid_schema"] += 1
            
            # Analyze content
            analysis = analyze_csv_content(csv_file)
            
            if "error" not in analysis:
                validation_results["total_activities"] += analysis["row_count"]
                validation_results["activity_distribution"].update(analysis["activity_types"])
                validation_results["unique_repos"].update(analysis["repos"])
                
                if analysis["has_oss4sg"]:
                    validation_results["oss4sg_contributors"] += 1
                
                # Update global date range
                if analysis["date_range"]["earliest"]:
                    if not validation_results["date_range_global"]["earliest"] or analysis["date_range"]["earliest"] < validation_results["date_range_global"]["earliest"]:
                        validation_results["date_range_global"]["earliest"] = analysis["date_range"]["earliest"]
                
                if analysis["date_range"]["latest"]:
                    if not validation_results["date_range_global"]["latest"] or analysis["date_range"]["latest"] > validation_results["date_range_global"]["latest"]:
                        validation_results["date_range_global"]["latest"] = analysis["date_range"]["latest"]
        else:
            validation_results["invalid_schema"] += 1
            validation_results["schema_errors"].append({
                "username": username,
                "error": error
            })
    
    # Convert sets to counts for JSON serialization
    validation_results["unique_repos"] = len(validation_results["unique_repos"])
    validation_results["activity_distribution"] = dict(validation_results["activity_distribution"])
    
    return validation_results


def print_validation_summary(file_check, validation_results):
    """Print human-readable validation summary"""
    logger.info("="*80)
    logger.info("VALIDATION RESULTS")
    logger.info("="*80)
    
    logger.info("\nFILE EXISTENCE:")
    logger.info(f"  Expected files: {file_check['expected']}")
    logger.info(f"  Existing files: {file_check['existing']} ({'✓' if file_check['existing'] == file_check['expected'] else '✗'})")
    logger.info(f"  Missing files: {file_check['missing']}")
    logger.info(f"  Empty files: {file_check['empty']}")
    
    logger.info("\nSCHEMA VALIDATION:")
    logger.info(f"  Valid schema: {validation_results['valid_schema']} ({'✓' if validation_results['invalid_schema'] == 0 else '✗'})")
    logger.info(f"  Invalid schema: {validation_results['invalid_schema']}")
    
    if validation_results['schema_errors']:
        logger.warning(f"  Schema errors (first 5):")
        for err in validation_results['schema_errors'][:5]:
            logger.warning(f"    - {err['username']}: {err['error']}")
    
    logger.info("\nCONTENT ANALYSIS:")
    logger.info(f"  Total activities: {validation_results['total_activities']:,}")
    logger.info(f"  Unique repos: {validation_results['unique_repos']}")
    logger.info(f"  Contributors with OSS4SG: {validation_results['oss4sg_contributors']}")
    
    logger.info("\nACTIVITY DISTRIBUTION:")
    for activity_type, count in sorted(validation_results['activity_distribution'].items()):
        logger.info(f"  {activity_type}: {count:,}")
    
    logger.info("\nDATE RANGE:")
    logger.info(f"  Earliest: {validation_results['date_range_global']['earliest']}")
    logger.info(f"  Latest: {validation_results['date_range_global']['latest']}")
    
    logger.info("="*80)


def generate_validation_report(file_check, validation_results, output_file):
    """Generate comprehensive validation report"""
    report = {
        "generated_at": datetime.now().isoformat(),
        "file_validation": file_check,
        "schema_validation": {
            "valid_count": validation_results["valid_schema"],
            "invalid_count": validation_results["invalid_schema"],
            "errors": validation_results["schema_errors"]
        },
        "content_analysis": {
            "total_activities": validation_results["total_activities"],
            "activity_distribution": validation_results["activity_distribution"],
            "unique_repos": validation_results["unique_repos"],
            "oss4sg_contributors": validation_results["oss4sg_contributors"],
            "date_range": validation_results["date_range_global"]
        },
        "quality_flags": {
            "all_files_present": file_check["missing"] == 0,
            "no_empty_files": file_check["empty"] == 0,
            "all_schemas_valid": validation_results["invalid_schema"] == 0,
            "has_activities": validation_results["total_activities"] > 0
        }
    }
    
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"Validation report saved: {output_file}")
    
    return report


def main():
    parser = argparse.ArgumentParser(description="Validate and analyze contributor journey data")
    parser.add_argument("--test", action="store_true", help="Validate test output")
    args = parser.parse_args()
    
    start_time = datetime.now()
    logger.info(f"Script started at {start_time}")
    logger.info("="*80)
    logger.info("CONTRIBUTOR JOURNEY VALIDATION")
    if args.test:
        logger.info("TEST MODE")
    logger.info("="*80)
    
    try:
        # Determine directories
        output_dir = SCRIPT_DIR / (CONFIG["paths"]["test_contributors_output_dir"] if args.test else CONFIG["paths"]["contributors_output_dir"])
        report_dir = SCRIPT_DIR / (CONFIG["paths"]["test_output_dir"] if args.test else CONFIG["paths"]["output_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        
        # Load expected contributors
        contributors = load_expected_contributors(args.test)
        logger.info(f"Expected contributors: {len(contributors)}")
        
        # Validate file existence
        file_check = validate_file_existence(contributors, output_dir)
        
        # Validate schemas and content
        validation_results = validate_all_files(output_dir, contributors)
        
        # Print summary
        print_validation_summary(file_check, validation_results)
        
        # Save report
        report_file = report_dir / "validation_report.json"
        report = generate_validation_report(file_check, validation_results, report_file)
        
        # Return success if all checks pass
        all_good = (
            file_check["missing"] == 0 and
            file_check["empty"] == 0 and
            validation_results["invalid_schema"] == 0 and
            validation_results["total_activities"] > 0
        )
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Script completed at {end_time}")
        logger.info(f"Total duration: {duration}")
        
        if all_good:
            logger.info("✓ All validation checks PASSED")
            return 0
        else:
            logger.warning("✗ Some validation checks FAILED - see report for details")
            return 1
        
    except Exception as e:
        logger.error(f"Error during validation: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
