#!/usr/bin/env python3
"""
Phase B: Combine individual journey files into complete_contributor_journeys.json.

Reads per-contributor JSON files from:
  - 05_contributor_journey_extraction/contributions/ (event)
  - 05_contributor_journey_extraction/organic_contributions/ (organic)

Produces:
  - 06_final_dataset/complete_contributor_journeys.json

Memory-safe: processes one file at a time.
"""

import json, os, sys
from datetime import datetime

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENT_DIR = os.path.join(BASE, "05_contributor_journey_extraction", "contributions")
ORGANIC_DIR = os.path.join(BASE, "05_contributor_journey_extraction", "organic_contributions")
OUTPUT_PATH = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")


def load_journey(path):
    """Load a single journey JSON file."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        return None


def main():
    print("=" * 60)
    print("PHASE B: Combine Journey Data")
    print("=" * 60)

    # Load v4 corpus
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "event_contributors_v2.json")) as f:
        events = json.load(f)["contributions"]
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "organic_matches_v2.json")) as f:
        matches = json.load(f)["matches"]

    print(f"  V4 corpus: {len(events)} events, {len(matches)} organic")

    # Build index of existing files
    event_files = {f.replace(".json", ""): os.path.join(EVENT_DIR, f)
                   for f in os.listdir(EVENT_DIR) if f.endswith(".json")}
    organic_files = {f.replace(".json", ""): os.path.join(ORGANIC_DIR, f)
                     for f in os.listdir(ORGANIC_DIR) if f.endswith(".json")}

    # Process event contributors
    event_journeys = []
    missing_events = 0
    for e in events:
        cid = e["contribution_id"]
        path = event_files.get(cid)
        if not path:
            missing_events += 1
            # Create minimal entry with no PR/issue data
            event_journeys.append({
                "contributor_type": "event",
                "github_username": e["github_username"],
                "repo": e["repo"],
                "event": e["event"],
                "contribution_id": cid,
                "activity": e.get("effective_commits", e.get("activity", 0)),
                "pull_requests": [],
                "issues": [],
                "commits": [],
                "pr_count": 0,
                "issue_count": 0,
                "commit_count": e.get("effective_commits", e.get("activity", 0)),
            })
            continue

        data = load_journey(path)
        if not data:
            missing_events += 1
            continue

        event_journeys.append({
            "contributor_type": "event",
            "github_username": e["github_username"],
            "repo": e["repo"],
            "event": e["event"],
            "contribution_id": cid,
            "activity": e.get("effective_commits", e.get("activity", 0)),
            "pull_requests": data.get("pull_requests", []),
            "issues": data.get("issues", []),
            "commits": data.get("commits", []),
            "pr_count": len(data.get("pull_requests", [])),
            "issue_count": len(data.get("issues", [])),
            "commit_count": e.get("effective_commits", e.get("activity", 0)),
        })

    print(f"  Event journeys: {len(event_journeys)} (missing files: {missing_events})")

    # Process organic contributors
    organic_journeys = []
    missing_organics = 0
    for m in matches:
        eid = m["event_contribution_id"]
        # Check both naming conventions
        path = organic_files.get(eid) or organic_files.get(f"organic__{eid}")
        if not path:
            missing_organics += 1
            organic_journeys.append({
                "contributor_type": "organic",
                "organic_email": m.get("organic_email", ""),
                "organic_name": m.get("organic_name", ""),
                "repo": m["repo"],
                "matched_event_contribution_id": eid,
                "organic_commits": m.get("organic_commits", 0),
                "pull_requests": [],
                "issues": [],
                "commits": [],
                "pr_count": 0,
                "issue_count": 0,
                "commit_count": m.get("organic_commits", 0),
            })
            continue

        data = load_journey(path)
        if not data:
            missing_organics += 1
            continue

        organic_journeys.append({
            "contributor_type": "organic",
            "organic_email": m.get("organic_email", ""),
            "organic_name": m.get("organic_name", ""),
            "repo": m["repo"],
            "matched_event_contribution_id": eid,
            "organic_commits": m.get("organic_commits", 0),
            "github_username": data.get("github_username"),
            "pull_requests": data.get("pull_requests", []),
            "issues": data.get("issues", []),
            "commits": data.get("commits", []),
            "pr_count": len(data.get("pull_requests", [])),
            "issue_count": len(data.get("issues", [])),
            "commit_count": m.get("organic_commits", 0),
        })

    print(f"  Organic journeys: {len(organic_journeys)} (missing files: {missing_organics})")

    # Build combined dataset
    from collections import Counter
    ev_breakdown = Counter(j["event"] for j in event_journeys)

    combined = {
        "generated_at": datetime.now().isoformat(),
        "description": "Complete contributor journey dataset with PRs, issues, and commits",
        "summary": {
            "total_journeys": len(event_journeys) + len(organic_journeys),
            "event_journeys": len(event_journeys),
            "organic_journeys": len(organic_journeys),
            "event_breakdown": dict(ev_breakdown),
            "repos_used": len(set(j["repo"] for j in event_journeys)),
            "event_with_prs": sum(1 for j in event_journeys if j["pr_count"] > 0),
            "organic_with_prs": sum(1 for j in organic_journeys if j["pr_count"] > 0),
        },
        "event_journeys": event_journeys,
        "organic_journeys": organic_journeys,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(combined, f, indent=2, default=str)

    size_mb = os.path.getsize(OUTPUT_PATH) / 1024 / 1024
    print(f"\n  Saved: {OUTPUT_PATH} ({size_mb:.1f} MB)")
    print(f"  Total: {combined['summary']['total_journeys']} journeys")
    print(f"  Event with PRs: {combined['summary']['event_with_prs']}")
    print(f"  Organic with PRs: {combined['summary']['organic_with_prs']}")
    print(f"\nPHASE B COMPLETE")


if __name__ == "__main__":
    main()
