#!/usr/bin/env python3
"""
Fix: Restore v1 contributor corpus (2,276 event + 2,229 organic).

The v2 re-selection script dropped ~978 contributors due to broken username
matching against T7 CSVs. This script restores the original v1 data as the
active dataset and regenerates the final dataset CSVs.

Also looks up T7 commit counts where possible for descriptive stats.
"""

import json
import os
import shutil
import pandas as pd
import numpy as np
from scipy import stats
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7_EXTRACTED = "/Volumes/T7/Event based OSS4SG/extracted"

def cliffs_delta(x, y):
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return 0.0
    more = sum(1 for xi in x for yi in y if xi > yi)
    less = sum(1 for xi in x for yi in y if xi < yi)
    return (more - less) / (nx * ny)

def effect_size_category(d):
    d = abs(d)
    if d < 0.147: return "negligible"
    elif d < 0.33: return "small"
    elif d < 0.474: return "medium"
    return "large"

def main():
    print("=" * 70)
    print("FIX: Restoring v1 corpus (2,276 event + 2,229 organic)")
    print("=" * 70)

    # Load v1 event contributions
    v1_path = os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                           "outputs", "contributions_FINAL_VALID.json")
    with open(v1_path) as f:
        v1_data = json.load(f)
    v1_contribs = v1_data["contributions"]
    print(f"\nV1 event contributions: {len(v1_contribs)}")

    # Load v1 organic matches
    org_path = os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                            "outputs", "organic_matches.json")
    with open(org_path) as f:
        org_data = json.load(f)
    org_matches = org_data["matches"]
    print(f"V1 organic matches: {len(org_matches)}")

    # Build event breakdown
    by_event = defaultdict(list)
    for c in v1_contribs:
        by_event[c["event"]].append(c)
    for ev in sorted(by_event):
        print(f"  {ev}: {len(by_event[ev])}")

    # Save as the new v2 (overwrite the broken v2)
    new_event = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "description": "Restored v1 corpus: all 2,276 event contributors (no broken re-filtering)",
        "total_contributions": len(v1_contribs),
        "by_event": {ev: len(items) for ev, items in by_event.items()},
        "mentorship_total": len(by_event.get("gsoc", [])) + len(by_event.get("lfx", [])),
        "non_mentorship_total": len(by_event.get("24pr", [])) + len(by_event.get("hf", [])),
        "contributions": v1_contribs,
    }

    v2_event_path = os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                                  "outputs", "event_contributors_v2.json")
    with open(v2_event_path, "w") as f:
        json.dump(new_event, f, indent=2)
    print(f"\nOverwritten: {v2_event_path}")

    # Add event_username and event_commits fields to organic matches for consistency
    # Use the activity field from v1 as event_commits proxy
    v1_lookup = {c["contribution_id"]: c for c in v1_contribs}
    for m in org_matches:
        cid = m["event_contribution_id"]
        if cid in v1_lookup:
            m["event_commits"] = v1_lookup[cid].get("activity", 0)
        else:
            m["event_commits"] = 0

    new_organic = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "description": "Restored v1 organic matches (activity-band matched)",
        "total_matches": len(org_matches),
        "no_match_count": len(v1_contribs) - len(org_matches),
        "matches": org_matches,
    }

    v2_org_path = os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                                "outputs", "organic_matches_v2.json")
    with open(v2_org_path, "w") as f:
        json.dump(new_organic, f, indent=2)
    print(f"Overwritten: {v2_org_path}")

    # Create new final dataset CSVs
    final_dir = os.path.join(BASE, "06_final_dataset")

    # Event contributors summary
    event_rows = []
    for c in v1_contribs:
        event_rows.append({
            "username": c["github_username"],
            "repo": c["repo"],
            "event": c["event"],
            "commit_count": c.get("activity", 0),
            "contribution_id": c["contribution_id"],
        })
    event_df = pd.DataFrame(event_rows)
    event_df.to_csv(os.path.join(final_dir, "event_contributors_summary.csv"), index=False)
    print(f"\nCreated: event_contributors_summary.csv ({len(event_df)} rows)")

    # Organic contributors summary
    organic_rows = []
    for m in org_matches:
        organic_rows.append({
            "email": m["organic_email"],
            "name": m.get("organic_name", ""),
            "repo": m["repo"],
            "matched_event_type": m["event_type"],
            "commit_count": m["organic_commits"],
            "matched_event_contribution_id": m["event_contribution_id"],
        })
    organic_df = pd.DataFrame(organic_rows)
    organic_df.to_csv(os.path.join(final_dir, "organic_contributors_summary.csv"), index=False)
    print(f"Created: organic_contributors_summary.csv ({len(organic_df)} rows)")

    # Statistical comparison (using organic commit counts vs organic commit counts
    # since event "activity" means different things per event)
    # Compare organic commits distribution instead -- both groups from same repos
    ev_activity = event_df["commit_count"].values
    org_commits = organic_df["commit_count"].values

    stat, p = stats.mannwhitneyu(ev_activity, org_commits, alternative="two-sided")
    delta = cliffs_delta(ev_activity, org_commits)

    # Dataset summary
    summary = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "version": "v3_restored",
        "description": "Restored v1 corpus (2,276 event + 2,229 organic) - no broken re-filtering",
        "total_event": len(v1_contribs),
        "total_organic": len(org_matches),
        "event_breakdown": {ev: len(items) for ev, items in by_event.items()},
        "unique_repos": len(set(c["repo"] for c in v1_contribs)),
        "note": "Event 'commit_count' is the activity metric from the event API (varies by event type). Organic 'commit_count' is from T7 CSV git commits.",
    }
    with open(os.path.join(final_dir, "dataset_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Created: dataset_summary.json")

    print(f"\n{'='*70}")
    print(f"CORPUS RESTORED")
    print(f"  Event: {len(v1_contribs)} (GSoC={len(by_event['gsoc'])}, LFX={len(by_event['lfx'])}, "
          f"24PR={len(by_event['24pr'])}, HF={len(by_event['hf'])})")
    print(f"  Organic: {len(org_matches)}")
    print(f"  Unique repos: {summary['unique_repos']}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
