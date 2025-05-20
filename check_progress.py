#!/usr/bin/env python3
import json
import os
import subprocess
from pathlib import Path
from datetime import datetime

# Check if process is running
try:
    result = subprocess.run(['ps', '-p', '86233'], capture_output=True, text=True)
    if result.returncode == 0:
        print("✅ Process 86233 is RUNNING")
    else:
        print("❌ Process 86233 is NOT RUNNING")
except Exception as e:
    print(f"Error checking process: {e}")

# Read progress
progress_file = Path("/Users/mohamadashraf/Desktop/Project/Event Based Vs Organic new conrtibutors/05_contributor_journey_extraction/progress/progress.json")
if progress_file.exists():
    with open(progress_file) as f:
        data = json.load(f)
    
    print(f"\n📊 Progress:")
    print(f"  Started: {data.get('started_at', 'N/A')}")
    print(f"  Completed: {len(data.get('completed', []))}")
    print(f"  Errors: {len(data.get('errors', []))}")
    print(f"  Last checkpoint: {data.get('last_checkpoint', 'N/A')}")
    print(f"  Total processed: {data.get('total_processed', 'N/A')}")
else:
    print("❌ Progress file not found")

# Count CSV files
csv_dir = Path("/Users/mohamadashraf/Desktop/Project/Event Based Vs Organic new conrtibutors/05_contributor_journey_extraction/outputs/contributors")
if csv_dir.exists():
    csv_count = len(list(csv_dir.glob("*.csv")))
    print(f"\n📁 CSV files: {csv_count}")
else:
    print("❌ CSV directory not found")

# Check latest log
log_dir = Path("/Users/mohamadashraf/Desktop/Project/Event Based Vs Organic new conrtibutors/05_contributor_journey_extraction/logs")
if log_dir.exists():
    log_files = list(log_dir.glob("extraction_*.log"))
    if log_files:
        latest_log = max(log_files, key=lambda p: p.stat().st_mtime)
        print(f"\n📝 Latest log: {latest_log.name}")
        
        # Read last 20 lines
        with open(latest_log) as f:
            lines = f.readlines()
            print("\n🔍 Last 20 log lines:")
            for line in lines[-20:]:
                print(f"  {line.rstrip()}")
