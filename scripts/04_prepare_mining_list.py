#!/usr/bin/env python3
"""
Prepare repos_to_process.json for the T7 drive mining script.
This creates the file in the correct format for clone_and_extract.py
"""

import json
import sys
from pathlib import Path

def prepare_mining_list():
    """Prepare the repos_to_process.json file for mining"""
    
    # Load repos to mine
    repos_to_mine_path = Path(__file__).parent / "repos_to_mine.json"
    with open(repos_to_mine_path, 'r') as f:
        data = json.load(f)
    
    repos_to_mine = data['repos']
    
    print(f"Preparing mining list for {len(repos_to_mine)} repos...")
    
    # Create repos_to_process.json in the same format as the original
    # The format is just a list of repo names
    output_path = Path("/Volumes/T7/Event based OSS4SG/repos_to_process_new.json")
    
    # Check if T7 is mounted
    if not output_path.parent.exists():
        print("ERROR: T7 drive not mounted at /Volumes/T7/Event based OSS4SG/")
        print("Please mount the T7 drive and try again.")
        return False
    
    with open(output_path, 'w') as f:
        json.dump(repos_to_mine, f, indent=2)
    
    print(f"✓ Saved repos_to_process_new.json to T7 drive")
    print(f"  Path: {output_path}")
    print(f"  Repos to mine: {len(repos_to_mine)}")
    
    return True

if __name__ == "__main__":
    try:
        if prepare_mining_list():
            print("\n✓ Mining list prepared successfully!")
            print("\nNext steps:")
            print("1. Navigate to T7 drive: cd /Volumes/T7/Event\\ based\\ OSS4SG/")
            print("2. Backup current repos_to_process.json:")
            print("   mv repos_to_process.json repos_to_process_old.json")
            print("3. Use new list:")
            print("   mv repos_to_process_new.json repos_to_process.json")
            print("4. Run mining script from workspace:")
            print("   python 03_consolidated_dataset/clone_and_extract.py")
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
