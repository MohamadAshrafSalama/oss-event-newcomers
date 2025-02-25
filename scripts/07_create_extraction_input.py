#!/usr/bin/env python3
"""
Convert our filtered contributors to the format expected by journey extraction script.
"""

import json
from pathlib import Path
from datetime import datetime

def convert_to_extraction_format():
    """Convert filtered contributors to extraction format"""
    
    # Load our filtered data
    input_path = Path(__file__).parent / "event_contributors_corpus_filtered.json"
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    # Combine all event contributors into single list
    all_contributors = []
    
    for event_name in ['gsoc', 'lfx', 'hacktoberfest', '24pr']:
        event_contribs = data['contributors_by_event'][event_name]
        all_contributors.extend(event_contribs)
    
    # Create output format
    output_data = {
        "generated_at": datetime.now().isoformat(),
        "description": "Event contributors filtered by correct corpus (top 385 GSoC + OSS4SG)",
        "total_contributors": len(all_contributors),
        "by_event": data['by_event'],
        "contributors": all_contributors
    }
    
    # Save to expected location
    output_path = Path(__file__).parent.parent / "04_contributor_selection_and_organic_matching" / "outputs" / "event_contributors_final.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"✓ Created extraction input file")
    print(f"  Path: {output_path}")
    print(f"  Total contributors: {len(all_contributors)}")
    print(f"  By event:")
    for event, count in data['by_event'].items():
        print(f"    {event:15s}: {count:5d}")
    
    return output_data

if __name__ == "__main__":
    convert_to_extraction_format()
