#!/usr/bin/env python3
"""
BUILD CORPUS FROM T7 DATA — MEMORY-SAFE, BATCH-BY-BATCH.

Processes ONE repo at a time, saves progress after each batch.
Keeps memory under ~1GB. Resumable if interrupted.

3 steps run as separate commands:
  Step A: python3 46_build_corpus.py step_a   (select events, ~2 min)
  Step B: python3 46_build_corpus.py step_b   (lookup T7 commits + match organics, ~10 min)
  Step C: python3 46_build_corpus.py step_c   (verify stats + save final, ~1 min)

Or run all: python3 46_build_corpus.py all
"""

import json
import os
import sys
import gc
import random
import numpy as np
import pandas as pd
from scipy import stats
from collections import Counter, defaultdict

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7 = "/Volumes/T7/Event based OSS4SG/extracted"
PROGRESS_DIR = os.path.join(BASE, "06_final_dataset", "build_progress")
SEED = 42
MIN_COMMITS = 3

BOT_PATTERNS = [
    "[bot]", "bot@", "dependabot", "renovate", "greenkeeper", "github-actions",
    "noreply@github.com", "snyk-bot", "codecov", "semantic-release", "mergify",
    "allcontributors", "imgbot", "netlify", "vercel", "auto-merge", "ci-bot",
    "release-bot"
]


def is_bot(s):
    s = str(s).lower()
    return any(p in s for p in BOT_PATTERNS)


def cliffs_delta(x, y):
    nx, ny = len(x), len(y)
    if nx == 0 or ny == 0:
        return 0.0
    # Use sampling for large arrays to avoid O(n*m) explosion
    if nx * ny > 10_000_000:
        sample_size = 3000
        x = list(np.random.choice(x, min(sample_size, nx), replace=False))
        y = list(np.random.choice(y, min(sample_size, ny), replace=False))
        nx, ny = len(x), len(y)
    more = sum(1 for xi in x for yi in y if xi > yi)
    less = sum(1 for xi in x for yi in y if xi < yi)
    return (more - less) / (nx * ny)


def effect_cat(d):
    d = abs(d)
    if d < 0.147: return "negligible"
    elif d < 0.33: return "small"
    elif d < 0.474: return "medium"
    return "large"


def find_user_commits(df, username):
    """Find commit count for a GitHub username in a repo DataFrame."""
    if df is None or len(df) == 0:
        return 0
    uname = username.lower().strip()
    if not uname or len(uname) < 2:
        return 0
    m1 = df["email"].str.contains(f"{uname}@users.noreply.github.com", na=False, regex=False)
    m2 = df["email"].str.contains(f"+{uname}@users.noreply.github.com", na=False, regex=False)
    m3 = df["email"].apply(
        lambda e: e.split("@")[0].replace("+", "").strip() == uname if "@" in str(e) else False)
    m4 = df["name"].str.strip() == uname
    return int((m1 | m2 | m3 | m4).sum())


def load_repo(csv_path):
    """Load a T7 repo CSV — only the columns we need."""
    try:
        df = pd.read_csv(csv_path, usecols=["author_name", "author_email"])
        df.columns = ["name", "email"]
        df["email"] = df["email"].str.lower().fillna("")
        df["name"] = df["name"].str.lower().fillna("")
        return df
    except Exception:
        try:
            df = pd.read_csv(csv_path, usecols=["author_name", "author_email"],
                             encoding="latin-1")
            df.columns = ["name", "email"]
            df["email"] = df["email"].str.lower().fillna("")
            df["name"] = df["name"].str.lower().fillna("")
            return df
        except Exception:
            return None


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════
# STEP A: Select all event contributors (no T7 needed, fast)
# ══════════════════════════════════════════════════════════════════════
def step_a():
    random.seed(SEED)
    print("=" * 60)
    print("STEP A: Select event contributors")
    print("=" * 60)

    os.makedirs(PROGRESS_DIR, exist_ok=True)

    # ── Mentorship ──
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching",
                            "outputs", "contributions_FINAL_VALID.json")) as f:
        orig = json.load(f)

    existing_gsoc = [c for c in orig["contributions"] if c["event"] == "gsoc"]
    existing_lfx = [c for c in orig["contributions"] if c["event"] == "lfx"]
    print(f"  Existing GSoC: {len(existing_gsoc)}, LFX: {len(existing_lfx)}")

    # New GSoC from raw pool
    with open(os.path.join(BASE, "02_event_data_extraction_and_contributor_discovery",
                            "google_summer_of_code", "gsoc_contributors.json")) as f:
        raw_gsoc = json.load(f)

    existing_gsoc_users = set(c["github_username"].lower() for c in existing_gsoc)

    t7_repos = set()
    for f_name in os.listdir(T7):
        if f_name.endswith(".csv") and not f_name.startswith("._"):
            t7_repos.add(f_name.replace("__", "/").replace(".csv", "").lower())

    new_gsoc = []
    for c in raw_gsoc["contributors"]:
        uname = c["github_username"].lower()
        if uname in existing_gsoc_users or is_bot(uname):
            continue
        for repo in c["repos_contributed"]:
            if repo.lower() in t7_repos:
                new_gsoc.append({
                    "github_username": c["github_username"],
                    "repo": repo.lower(),
                    "event": "gsoc",
                    "contribution_id": f"{c['github_username']}__gsoc__{repo.replace('/', '__')}",
                    "activity": 0,
                })
                break
    print(f"  New GSoC: {len(new_gsoc)}")

    mentorship = []
    for c in existing_gsoc + existing_lfx:
        mentorship.append({
            "github_username": c["github_username"],
            "repo": c["repo"].lower(),
            "event": c["event"],
            "contribution_id": c["contribution_id"],
            "activity": c.get("activity", 0),
        })
    mentorship.extend(new_gsoc)
    print(f"  Total mentorship: {len(mentorship)}")

    # ── Non-mentorship from raw pools ──
    with open(os.path.join(BASE, "02_event_data_extraction_and_contributor_discovery",
                            "24_pull_requests", "24pr_contributors.json")) as f:
        raw_24pr = json.load(f)
    with open(os.path.join(BASE, "02_event_data_extraction_and_contributor_discovery",
                            "hacktoberfest", "hacktoberfest_contributors.json")) as f:
        raw_hf = json.load(f)

    mentorship_users = set(c["github_username"].lower() for c in mentorship)

    def pick_candidates(raw_list, event_name):
        cands = []
        seen = set()
        for c in raw_list:
            uname = c["github_username"]
            if uname.lower() in mentorship_users or is_bot(uname):
                continue
            for repo in c["repos_contributed"]:
                if repo.lower() in t7_repos:
                    key = uname.lower()
                    if key not in seen:
                        seen.add(key)
                        cands.append({
                            "github_username": uname,
                            "repo": repo.lower(),
                            "event": event_name,
                        })
                        break
        return cands

    cands_24pr = pick_candidates(raw_24pr["contributors"], "24pr")
    cands_hf = pick_candidates(raw_hf["contributors"], "hacktoberfest")
    print(f"  24PR candidates: {len(cands_24pr)}, HF candidates: {len(cands_hf)}")

    # Save progress
    save_json(os.path.join(PROGRESS_DIR, "mentorship.json"), mentorship)
    save_json(os.path.join(PROGRESS_DIR, "cands_24pr.json"), cands_24pr)
    save_json(os.path.join(PROGRESS_DIR, "cands_hf.json"), cands_hf)
    save_json(os.path.join(PROGRESS_DIR, "t7_repos.json"), sorted(t7_repos))

    print(f"\n  Saved to {PROGRESS_DIR}/")
    print("  STEP A DONE.\n")


# ══════════════════════════════════════════════════════════════════════
# STEP B: Look up T7 commits + organic matching (repo by repo)
# ══════════════════════════════════════════════════════════════════════
def step_b():
    random.seed(SEED)
    np.random.seed(SEED)
    print("=" * 60)
    print("STEP B: T7 commit lookup + organic matching (batch by batch)")
    print("=" * 60)

    mentorship = load_json(os.path.join(PROGRESS_DIR, "mentorship.json"))
    cands_24pr = load_json(os.path.join(PROGRESS_DIR, "cands_24pr.json"))
    cands_hf = load_json(os.path.join(PROGRESS_DIR, "cands_hf.json"))
    t7_repos = set(load_json(os.path.join(PROGRESS_DIR, "t7_repos.json")))

    # Check for resume
    resume_path = os.path.join(PROGRESS_DIR, "step_b_progress.json")
    if os.path.exists(resume_path):
        progress = load_json(resume_path)
        print(f"  Resuming from batch {progress['last_batch']+1}...")
    else:
        progress = {"last_batch": -1, "nm_commits": {}, "m_commits": {},
                     "matches": [], "no_match": 0}

    # Build T7 file map
    t7_files = {}
    for f_name in os.listdir(T7):
        if f_name.endswith(".csv") and not f_name.startswith("._"):
            repo = f_name.replace("__", "/").replace(".csv", "").lower()
            t7_files[repo] = os.path.join(T7, f_name)

    # Group all candidates by repo
    all_nm = cands_24pr + cands_hf
    nm_by_repo = defaultdict(list)
    for c in all_nm:
        nm_by_repo[c["repo"]].append(c)

    m_by_repo = defaultdict(list)
    for c in mentorship:
        m_by_repo[c["repo"]].append(c)

    # All unique repos
    all_repos = sorted(set(list(nm_by_repo.keys()) + list(m_by_repo.keys())))
    print(f"  Total repos to process: {len(all_repos)}")

    # Pre-build event username set for organic exclusion
    all_event_usernames = set(c["github_username"].lower() for c in mentorship)
    for c in all_nm:
        all_event_usernames.add(c["github_username"].lower())

    BATCH_SIZE = 20  # repos per batch
    batches = [all_repos[i:i+BATCH_SIZE] for i in range(0, len(all_repos), BATCH_SIZE)]
    print(f"  Batches: {len(batches)} (size {BATCH_SIZE})")

    nm_commits = progress["nm_commits"]  # username -> t7_commits
    m_commits = progress["m_commits"]    # contribution_id -> t7_commits
    matches = progress["matches"]
    no_match = progress["no_match"]
    used_organic_emails = set(m["organic_email"] for m in matches)

    for bi, batch in enumerate(batches):
        if bi <= progress["last_batch"]:
            continue

        for repo in batch:
            csv_path = t7_files.get(repo)
            if not csv_path:
                continue

            df = load_repo(csv_path)
            if df is None:
                continue

            # ── Look up non-mentorship commits ──
            for c in nm_by_repo.get(repo, []):
                uname = c["github_username"].lower()
                if uname not in nm_commits:
                    nm_commits[uname] = find_user_commits(df, c["github_username"])

            # ── Look up mentorship commits ──
            for c in m_by_repo.get(repo, []):
                cid = c["contribution_id"]
                if cid not in m_commits:
                    tc = find_user_commits(df, c["github_username"])
                    m_commits[cid] = tc if tc > 0 else c.get("activity", 0)

            # Free DataFrame immediately
            del df
            gc.collect()

        # Save progress after each batch
        progress["last_batch"] = bi
        progress["nm_commits"] = nm_commits
        progress["m_commits"] = m_commits
        progress["matches"] = matches
        progress["no_match"] = no_match
        save_json(resume_path, progress)

        if (bi + 1) % 5 == 0 or bi == len(batches) - 1:
            print(f"  Batch {bi+1}/{len(batches)}: "
                  f"nm_lookups={len(nm_commits)}, m_lookups={len(m_commits)}")

    # ── Phase B2: Filter non-mentorship and sample ──
    print(f"\n  Filtering non-mentorship...")
    for c in cands_24pr:
        c["t7_commits"] = nm_commits.get(c["github_username"].lower(), 0)
    for c in cands_hf:
        c["t7_commits"] = nm_commits.get(c["github_username"].lower(), 0)

    qual_24pr = [c for c in cands_24pr if c["t7_commits"] >= MIN_COMMITS]
    qual_hf = [c for c in cands_hf if c["t7_commits"] >= MIN_COMMITS]
    print(f"  24PR qualified: {len(qual_24pr)}, HF qualified: {len(qual_hf)}")

    random.shuffle(qual_24pr)
    random.shuffle(qual_hf)
    sel_24pr = qual_24pr[:575]
    sel_hf = qual_hf[:575]

    non_mentorship = []
    for c in sel_24pr + sel_hf:
        cid = f"{c['github_username']}__{c['event']}__{c['repo'].replace('/', '__')}"
        non_mentorship.append({
            "github_username": c["github_username"],
            "repo": c["repo"],
            "event": c["event"],
            "contribution_id": cid,
            "activity": c["t7_commits"],
            "t7_commits": c["t7_commits"],
        })
    print(f"  Selected: 24PR={len(sel_24pr)}, HF={len(sel_hf)}, total={len(non_mentorship)}")

    # ── Apply mentorship commits ──
    for c in mentorship:
        c["t7_commits"] = m_commits.get(c["contribution_id"], c.get("activity", 0))
    mentorship = [c for c in mentorship if c.get("t7_commits", 0) >= MIN_COMMITS]
    print(f"  Mentorship after filter: {len(mentorship)}")

    # ── Combine events ──
    all_events = mentorship + non_mentorship
    all_event_usernames_final = set(c["github_username"].lower() for c in all_events)
    print(f"  Total events: {len(all_events)}")

    # ── Phase B3: Organic matching (repo by repo, memory-safe) ──
    print(f"\n  Organic matching (repo by repo)...")
    ev_by_repo = defaultdict(list)
    for c in all_events:
        ev_by_repo[c["repo"]].append(c)

    matches = []
    no_match = 0
    used_organic = defaultdict(set)

    repo_list = sorted(ev_by_repo.keys())
    for ri, repo in enumerate(repo_list):
        csv_path = t7_files.get(repo)
        if not csv_path:
            no_match += len(ev_by_repo[repo])
            continue

        df = load_repo(csv_path)
        if df is None:
            no_match += len(ev_by_repo[repo])
            continue

        # Get organic pool for this repo
        groups = df.groupby("email").agg(
            commits=("email", "count"), name=("name", "first")).reset_index()
        organic_pool = {}
        for _, row in groups.iterrows():
            email, name, commits = row["email"], row["name"], int(row["commits"])
            if is_bot(email) or is_bot(name):
                continue
            local = email.split("@")[0].replace("+", "").strip()
            if local in all_event_usernames_final or name.strip() in all_event_usernames_final:
                continue
            if commits >= MIN_COMMITS:
                organic_pool[email] = {"email": email, "name": name, "commits": commits}

        # Match events in this repo
        ev_sorted = sorted(ev_by_repo[repo], key=lambda c: c.get("t7_commits", 0), reverse=True)
        for ec in ev_sorted:
            ec_commits = ec.get("t7_commits", 0)
            if ec_commits < MIN_COMMITS:
                no_match += 1
                continue

            best, best_diff = None, float("inf")
            for email, auth in organic_pool.items():
                if email in used_organic[repo]:
                    continue
                diff = abs(auth["commits"] - ec_commits)
                if diff < best_diff:
                    best_diff = diff
                    best = auth

            if best and (best_diff / max(ec_commits, 1) <= 0.50 or best_diff <= 5):
                used_organic[repo].add(best["email"])
                matches.append({
                    "event_contribution_id": ec["contribution_id"],
                    "repo": repo,
                    "event_type": ec["event"],
                    "event_username": ec["github_username"],
                    "event_commits": ec_commits,
                    "organic_email": best["email"],
                    "organic_name": best["name"],
                    "organic_commits": best["commits"],
                })
            else:
                no_match += 1

        del df, groups, organic_pool
        gc.collect()

        if (ri + 1) % 50 == 0 or ri == len(repo_list) - 1:
            print(f"    Repo {ri+1}/{len(repo_list)}: {len(matches)} matches")

    print(f"\n  Total matches: {len(matches)}, no match: {no_match}")

    # Save B results
    save_json(os.path.join(PROGRESS_DIR, "all_events.json"), all_events)
    save_json(os.path.join(PROGRESS_DIR, "all_matches.json"), matches)
    save_json(os.path.join(PROGRESS_DIR, "step_b_done.json"),
              {"events": len(all_events), "matches": len(matches), "no_match": no_match})
    print("  STEP B DONE.\n")


# ══════════════════════════════════════════════════════════════════════
# STEP C: Verify stats + save final corpus
# ══════════════════════════════════════════════════════════════════════
def step_c():
    print("=" * 60)
    print("STEP C: Statistical verification + save final corpus")
    print("=" * 60)

    all_events = load_json(os.path.join(PROGRESS_DIR, "all_events.json"))
    matches = load_json(os.path.join(PROGRESS_DIR, "all_matches.json"))
    info = load_json(os.path.join(PROGRESS_DIR, "step_b_done.json"))

    ev_c = np.array([m["event_commits"] for m in matches])
    org_c = np.array([m["organic_commits"] for m in matches])

    print(f"\n  Pairs: {len(matches)}")
    print(f"  Event:   mean={ev_c.mean():.1f}, median={np.median(ev_c):.0f}, "
          f"std={ev_c.std():.1f}")
    print(f"  Organic: mean={org_c.mean():.1f}, median={np.median(org_c):.0f}, "
          f"std={org_c.std():.1f}")

    mean_diff = abs(ev_c.mean() - org_c.mean()) / max(ev_c.mean(), 1) * 100
    med_diff = abs(np.median(ev_c) - np.median(org_c)) / max(np.median(ev_c), 1) * 100

    u_stat, p_mw = stats.mannwhitneyu(ev_c, org_c, alternative="two-sided")
    try:
        w_stat, p_wx = stats.wilcoxon(ev_c, org_c)
    except Exception:
        w_stat, p_wx = 0, 1.0
    delta = cliffs_delta(ev_c.tolist(), org_c.tolist())

    print(f"\n  Mean diff:  {mean_diff:.1f}% {'PASS' if mean_diff <= 5 else 'WARN'}")
    print(f"  Median diff: {med_diff:.1f}% {'PASS' if med_diff <= 5 else 'WARN'}")
    print(f"  MW p-value:  {p_mw:.4f} {'PASS' if p_mw > 0.05 else 'WARN'}")
    print(f"  Wilcoxon p:  {p_wx:.4f} {'PASS' if p_wx > 0.05 else 'WARN'}")
    print(f"  Cliff's d:   {delta:.4f} ({effect_cat(delta)}) "
          f"{'PASS' if abs(delta) < 0.147 else 'WARN'}")

    # By group
    print("\n  By group:")
    for grp, types in [("mentorship", ["gsoc", "lfx"]),
                        ("non-mentorship", ["24pr", "hacktoberfest"])]:
        sub = [m for m in matches if m["event_type"] in types]
        if len(sub) >= 5:
            se = np.array([m["event_commits"] for m in sub])
            so = np.array([m["organic_commits"] for m in sub])
            _, p = stats.mannwhitneyu(se, so, alternative="two-sided")
            d = cliffs_delta(se.tolist(), so.tolist())
            print(f"    {grp:15s}: n={len(sub):4d}, ev={se.mean():.1f}, "
                  f"org={so.mean():.1f}, p={p:.4f}, d={d:.3f}")

    # ── Save final corpus ──
    matched_ids = set(m["event_contribution_id"] for m in matches)
    final_events = [c for c in all_events if c["contribution_id"] in matched_ids]
    final_by_ev = Counter(c["event"] for c in final_events)

    out_dir = os.path.join(BASE, "04_contributor_selection_and_organic_matching", "outputs")

    save_json(os.path.join(out_dir, "event_contributors_v2.json"), {
        "generated_at": pd.Timestamp.now().isoformat(),
        "version": "v4_corpus",
        "total_contributions": len(final_events),
        "by_event": dict(final_by_ev),
        "mentorship_total": final_by_ev.get("gsoc", 0) + final_by_ev.get("lfx", 0),
        "non_mentorship_total": final_by_ev.get("24pr", 0) + final_by_ev.get("hacktoberfest", 0),
        "contributions": final_events,
    })
    print(f"\n  Saved event_contributors_v2.json: {len(final_events)}")

    save_json(os.path.join(out_dir, "organic_matches_v2.json"), {
        "generated_at": pd.Timestamp.now().isoformat(),
        "version": "v4_corpus",
        "total_matches": len(matches),
        "no_match_count": info["no_match"],
        "matches": matches,
    })
    print(f"  Saved organic_matches_v2.json: {len(matches)}")

    final_dir = os.path.join(BASE, "06_final_dataset")
    os.makedirs(final_dir, exist_ok=True)

    pd.DataFrame([{
        "username": c["github_username"], "repo": c["repo"], "event": c["event"],
        "commit_count": c.get("t7_commits", c.get("activity", 0)),
        "contribution_id": c["contribution_id"],
    } for c in final_events]).to_csv(
        os.path.join(final_dir, "event_contributors_summary.csv"), index=False)

    pd.DataFrame([{
        "email": m["organic_email"], "name": m.get("organic_name", ""),
        "repo": m["repo"], "matched_event_type": m["event_type"],
        "commit_count": m["organic_commits"], "event_commits": m["event_commits"],
        "matched_event_contribution_id": m["event_contribution_id"],
    } for m in matches]).to_csv(
        os.path.join(final_dir, "organic_contributors_summary.csv"), index=False)

    save_json(os.path.join(final_dir, "dataset_summary.json"), {
        "generated_at": pd.Timestamp.now().isoformat(),
        "version": "v4_corpus",
        "total_event": len(final_events),
        "total_organic": len(matches),
        "event_breakdown": dict(final_by_ev),
        "unique_repos": len(set(c["repo"] for c in final_events)),
        "statistical_validation": {
            "mann_whitney_p": float(p_mw),
            "wilcoxon_p": float(p_wx),
            "cliffs_delta": float(delta),
            "event_mean": float(ev_c.mean()),
            "organic_mean": float(org_c.mean()),
            "mean_diff_pct": float(mean_diff),
        },
    })

    print(f"\n{'='*60}")
    print(f"CORPUS COMPLETE")
    print(f"{'='*60}")
    print(f"  Events:  {len(final_events)}")
    for ev, cnt in sorted(final_by_ev.items()):
        print(f"    {ev}: {cnt}")
    print(f"  Organic: {len(matches)}")
    print(f"  MW p:    {p_mw:.4f}")
    print(f"  Delta:   {delta:.4f} ({effect_cat(delta)})")
    print(f"{'='*60}")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step == "step_a":
        step_a()
    elif step == "step_b":
        step_b()
    elif step == "step_c":
        step_c()
    elif step == "all":
        step_a()
        step_b()
        step_c()
    else:
        print(f"Usage: {sys.argv[0]} [step_a|step_b|step_c|all]")
