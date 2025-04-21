#!/usr/bin/env python3
"""Quick restart script for extraction"""
import subprocess
import os
import sys

os.chdir("/Users/mohamadashraf/Desktop/Project/Event Based Vs Organic new conrtibutors/05_contributor_journey_extraction")

# Start the extraction
process = subprocess.Popen(
    [sys.executable, "01_extract_contributor_journeys.py"],
    stdout=open("restart_output.log", "w"),
    stderr=subprocess.STDOUT,
    start_new_session=True
)

print(f"Started extraction with PID: {process.pid}")

# Save PID
with open("new_run.pid", "w") as f:
    f.write(str(process.pid))

print("Process started in background. Check restart_output.log for output.")
