#!/usr/bin/env python3
"""
Complete pipeline: mine -> combine -> timeseries -> cluster -> report.
Runs in background. Tiny batches. Logs everything. Resumable.

Usage:
  python3 scripts/49_run_pipeline.py           # run full pipeline
  python3 scripts/49_run_pipeline.py mine      # just mining
  python3 scripts/49_run_pipeline.py combine   # just combine
  python3 scripts/49_run_pipeline.py timeseries # just CI time series
  python3 scripts/49_run_pipeline.py cluster   # just clustering
  python3 scripts/49_run_pipeline.py report    # just report

Logs: 08_analysis_results/pipeline.log
"""

import json, os, sys, re, time, gc
from datetime import datetime
from collections import defaultdict, Counter
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import numpy as np
import warnings
warnings.filterwarnings("ignore")

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7 = "/Volumes/T7/Event based OSS4SG/extracted"
OUT = os.path.join(BASE, "08_analysis_results")
CI_DIR = os.path.join(OUT, "ci_timeseries")
EVENT_DIR = os.path.join(BASE, "05_contributor_journey_extraction", "contributions")
ORGANIC_DIR = os.path.join(BASE, "05_contributor_journey_extraction", "organic_contributions")
LOGFILE = os.path.join(OUT, "pipeline.log")

os.makedirs(CI_DIR, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOGFILE, "a") as f:
        f.write(line + "\n")

# ─────────────────────────────────────────────
# STEP 1: MINE MISSING CONTRIBUTORS
# ─────────────────────────────────────────────

def load_tokens():
    with open(os.path.join(BASE, "05_contributor_journey_extraction", "config.json")) as f:
        return json.load(f)["github_tokens"]

def api_get(url, token):
    headers = {"Authorization": f"token {token}",
               "Accept": "application/vnd.github+json",
               "User-Agent": "Miner/2"}
    for attempt in range(3):
        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=30)
            return json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code == 403:
                reset = e.headers.get("X-RateLimit-Reset")
                wait = max(0, int(reset) - int(time.time())) + 2 if reset else 30
                time.sleep(min(wait, 60))
            elif e.code in (404, 422):
                return {"items": []}
            else:
                time.sleep(5)
        except Exception:
            time.sleep(5)
    return {"items": []}

def mine_prs(user, repo, token):
    o, n = repo.split("/")
    d = api_get(f"https://api.github.com/search/issues?q=author:{user}+repo:{o}/{n}+type:pr&per_page=100", token)
    if not d or "items" not in d: return []
    return [{"number": i["number"], "title": i.get("title",""), "state": i.get("state",""),
             "created_at": i.get("created_at"), "merged_at": (i.get("pull_request") or {}).get("merged_at")}
            for i in d["items"]]

def mine_issues(user, repo, token):
    o, n = repo.split("/")
    d = api_get(f"https://api.github.com/search/issues?q=author:{user}+repo:{o}/{n}+type:issue&per_page=100", token)
    if not d or "items" not in d: return []
    return [{"number": i["number"], "title": i.get("title",""), "state": i.get("state",""),
             "created_at": i.get("created_at"), "comments": i.get("comments",0)}
            for i in d["items"]]

def username_from_email(email):
    if not email: return None
    m = re.match(r"\d+\+(.+)@users\.noreply\.github\.com", email.lower())
    if m: return m.group(1)
    m = re.match(r"([^@]+)@users\.noreply\.github\.com", email.lower())
    if m: return m.group(1)
    return None

def step_mine():
    log("=== STEP 1: MINE MISSING CONTRIBUTORS ===")
    tokens = load_tokens()

    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching/outputs/event_contributors_v2.json")) as f:
        events = json.load(f)["contributions"]
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching/outputs/organic_matches_v2.json")) as f:
        matches = json.load(f)["matches"]

    ee = set(f.replace(".json","") for f in os.listdir(EVENT_DIR) if f.endswith(".json"))
    oo = set(f.replace(".json","") for f in os.listdir(ORGANIC_DIR) if f.endswith(".json"))

    miss_e = [e for e in events if e["contribution_id"] not in ee]
    miss_o = [m for m in matches if m["event_contribution_id"] not in oo
              and f"organic__{m['event_contribution_id']}" not in oo]

    log(f"  Missing: {len(miss_e)} event, {len(miss_o)} organic")

    done = 0
    for i, e in enumerate(miss_e):
        tk = tokens[i % len(tokens)]
        cid = e["contribution_id"]
        prs = mine_prs(e["github_username"], e["repo"], tk)
        time.sleep(2.5)
        issues = mine_issues(e["github_username"], e["repo"], tk)
        time.sleep(0.5)
        with open(os.path.join(EVENT_DIR, f"{cid}.json"), "w") as f:
            json.dump({"contribution_id": cid, "github_username": e["github_username"],
                       "repo": e["repo"], "event": e["event"],
                       "extracted_at": datetime.now().isoformat(),
                       "pull_requests": prs, "issues": issues,
                       "summary": {"total_prs": len(prs), "total_issues": len(issues)}}, f)
        done += 1
        if done % 20 == 0:
            log(f"  Event: {done}/{len(miss_e)}")

    for i, m in enumerate(miss_o):
        tk = tokens[i % len(tokens)]
        eid = m["event_contribution_id"]
        user = username_from_email(m.get("organic_email",""))
        prs, issues = [], []
        if user:
            prs = mine_prs(user, m["repo"], tk)
            time.sleep(2.5)
            issues = mine_issues(user, m["repo"], tk)
            time.sleep(0.5)
        with open(os.path.join(ORGANIC_DIR, f"{eid}.json"), "w") as f:
            json.dump({"organic_email": m.get("organic_email",""),
                       "organic_name": m.get("organic_name",""),
                       "repo": m["repo"], "event_contribution_id": eid,
                       "organic_commits": m.get("organic_commits",0),
                       "github_username": user,
                       "pull_requests": prs, "issues": issues}, f)
        done += 1
        if done % 20 == 0:
            log(f"  Organic: {done - len(miss_e)}/{len(miss_o)}")

    log(f"  Mining done: {done} total")

# ─────────────────────────────────────────────
# STEP 2: COMBINE JOURNEYS
# ─────────────────────────────────────────────

def step_combine():
    log("=== STEP 2: COMBINE JOURNEYS ===")

    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching/outputs/event_contributors_v2.json")) as f:
        events = json.load(f)["contributions"]
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching/outputs/organic_matches_v2.json")) as f:
        matches = json.load(f)["matches"]

    ef = {f.replace(".json",""): os.path.join(EVENT_DIR, f) for f in os.listdir(EVENT_DIR) if f.endswith(".json")}
    of = {f.replace(".json",""): os.path.join(ORGANIC_DIR, f) for f in os.listdir(ORGANIC_DIR) if f.endswith(".json")}

    ej = []
    for e in events:
        cid = e["contribution_id"]
        p = ef.get(cid)
        d = {}
        if p:
            try:
                with open(p) as f: d = json.load(f)
            except: pass
        ej.append({"contributor_type": "event", "github_username": e["github_username"],
                    "repo": e["repo"], "event": e["event"], "contribution_id": cid,
                    "activity": e.get("effective_commits", e.get("activity",0)),
                    "pull_requests": d.get("pull_requests",[]), "issues": d.get("issues",[]),
                    "pr_count": len(d.get("pull_requests",[])), "issue_count": len(d.get("issues",[])),
                    "commit_count": e.get("effective_commits", e.get("activity",0))})

    oj = []
    for m in matches:
        eid = m["event_contribution_id"]
        p = of.get(eid) or of.get(f"organic__{eid}")
        d = {}
        if p:
            try:
                with open(p) as f: d = json.load(f)
            except: pass
        oj.append({"contributor_type": "organic", "organic_email": m.get("organic_email",""),
                    "organic_name": m.get("organic_name",""), "repo": m["repo"],
                    "matched_event_contribution_id": eid,
                    "organic_commits": m.get("organic_commits",0),
                    "github_username": d.get("github_username"),
                    "pull_requests": d.get("pull_requests",[]), "issues": d.get("issues",[]),
                    "pr_count": len(d.get("pull_requests",[])), "issue_count": len(d.get("issues",[])),
                    "commit_count": m.get("organic_commits",0)})

    out = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")
    with open(out, "w") as f:
        json.dump({"generated_at": datetime.now().isoformat(),
                   "summary": {"total_journeys": len(ej)+len(oj), "event_journeys": len(ej),
                               "organic_journeys": len(oj),
                               "event_with_prs": sum(1 for j in ej if j["pr_count"]>0),
                               "organic_with_prs": sum(1 for j in oj if j["pr_count"]>0)},
                   "event_journeys": ej, "organic_journeys": oj}, f)
    log(f"  Saved {len(ej)+len(oj)} journeys -> {out}")
    del ej, oj; gc.collect()

# ─────────────────────────────────────────────
# STEP 3: CI TIME SERIES (repo-by-repo, memory-safe)
# ─────────────────────────────────────────────

def find_emails(repo_df, email=None, username=None):
    emails = set()
    if email:
        el = email.lower()
        if el in repo_df["author_email"].values: emails.add(el)
        else:
            for e in repo_df["author_email"].unique():
                if el in str(e) or str(e) in el: emails.add(str(e))
    if username and len(username) > 3:
        u = username.lower()
        for e in repo_df["author_email"].unique():
            if u in str(e): emails.add(str(e))
    return emails

def build_ci(dates_list, journey, weeks_list):
    """Build CI arrays from pre-computed weekly bins."""
    import pandas as pd
    n = len(weeks_list)
    commits = [0]*n; pr_m = [0]*n; comms = [0]*n; iss = [0]*n

    for i,(ws,we) in enumerate(weeks_list):
        commits[i] = sum(1 for d in dates_list if ws <= d < we)

    if journey:
        for pr in journey.get("pull_requests",[]):
            if pr.get("merged_at"):
                try:
                    dt = pd.Timestamp(pr["merged_at"], tz="UTC")
                    for i,(ws,we) in enumerate(weeks_list):
                        if ws <= dt < we: pr_m[i] += 1; break
                except: pass
        for issue in journey.get("issues",[]):
            if issue.get("created_at"):
                try:
                    dt = pd.Timestamp(issue["created_at"], tz="UTC")
                    for i,(ws,we) in enumerate(weeks_list):
                        if ws <= dt < we: iss[i] += 1; break
                except: pass
            nc = issue.get("comments",0)
            if nc > 0 and issue.get("created_at"):
                try:
                    dt = pd.Timestamp(issue["created_at"], tz="UTC")
                    for i,(ws,we) in enumerate(weeks_list):
                        if ws <= dt < we: comms[i] += nc; break
                except: pass

    commit_ci = []; full_ci = []
    for i in range(n):
        c = commits[i]
        ad = min(c, 7) / 7.0
        lb = max(0, i-3)
        aw = sum(1 for j in range(lb,i+1) if commits[j]>0 or pr_m[j]>0 or comms[j]>0 or iss[j]>0)
        dur = aw / max(i-lb+1, 1)
        commit_ci.append(float(c))
        full_ci.append(0.25*c + 0.20*pr_m[i] + 0.15*comms[i] + 0.15*iss[i] + 0.15*ad + 0.10*dur)
    return commit_ci, full_ci

def step_timeseries():
    import pandas as pd
    log("=== STEP 3: CI TIME SERIES (repo-by-repo) ===")

    # Load journey index
    jpath = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")
    with open(jpath) as f:
        jdata = json.load(f)
    ev_j = {j["contribution_id"]: j for j in jdata["event_journeys"]}
    or_j = {j["matched_event_contribution_id"]+"__organic": j for j in jdata["organic_journeys"]}
    del jdata; gc.collect()
    log(f"  Loaded {len(ev_j)} event + {len(or_j)} organic journeys")

    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching/outputs/event_contributors_v2.json")) as f:
        events = json.load(f)["contributions"]
    with open(os.path.join(BASE, "04_contributor_selection_and_organic_matching/outputs/organic_matches_v2.json")) as f:
        matches = json.load(f)["matches"]

    # Group by repo
    repo_map = defaultdict(list)
    for e in events:
        cid = e["contribution_id"]
        repo_map[e["repo"]].append({"cid": cid, "type": "event", "event": e["event"],
                                     "username": e["github_username"], "email": None,
                                     "mentorship": e["event"] in ("gsoc","lfx"),
                                     "journey": ev_j.get(cid)})
    for m in matches:
        cid = m["event_contribution_id"] + "__organic"
        repo_map[m["repo"]].append({"cid": cid, "type": "organic", "event": m["event_type"],
                                     "username": None, "email": m.get("organic_email"),
                                     "mentorship": False, "journey": or_j.get(cid)})
    del ev_j, or_j; gc.collect()

    repos = sorted(repo_map.keys())
    log(f"  {len(repos)} repos to process")

    # Check what's already done (resume)
    progress_path = os.path.join(CI_DIR, "v4_progress.json")
    done_repos = set()
    if os.path.exists(progress_path):
        with open(progress_path) as f:
            done_repos = set(json.load(f).get("done_repos", []))
        log(f"  Resuming: {len(done_repos)} repos already done")

    index = []
    # Load any existing index entries for done repos
    idx_path = os.path.join(CI_DIR, "ci_timeseries_index.json")
    if os.path.exists(idx_path) and done_repos:
        with open(idx_path) as f:
            old_idx = json.load(f)
        index = [e for e in old_idx.get("entries",[]) if e.get("repo") in done_repos]

    processed = len(index)
    skipped = 0

    for ri, repo in enumerate(repos):
        if repo in done_repos:
            continue

        contribs = repo_map[repo]
        csv_path = os.path.join(T7, repo.replace("/","__") + ".csv")

        if not os.path.exists(csv_path):
            skipped += len(contribs)
            done_repos.add(repo)
            continue

        # Load ONE repo CSV
        try:
            df = pd.read_csv(csv_path, usecols=["author_name","author_email","author_date"],
                             dtype={"author_name":str,"author_email":str})
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, usecols=["author_name","author_email","author_date"],
                             encoding="latin-1", dtype={"author_name":str,"author_email":str})
        except:
            skipped += len(contribs)
            done_repos.add(repo)
            continue

        df["author_date"] = pd.to_datetime(df["author_date"], errors="coerce", utc=True)
        df = df.dropna(subset=["author_date"])
        df["author_email"] = df["author_email"].str.lower()

        for c in contribs:
            emails = find_emails(df, c["email"], c["username"])
            if not emails:
                skipped += 1; continue

            cdf = df[df["author_email"].isin(emails)]
            if cdf.empty:
                skipped += 1; continue

            dates = sorted(cdf["author_date"].tolist())
            first, last = dates[0], dates[-1]
            if (last - first).days <= 0:
                commit_ci = [1.0]; full_ci = [1.0]; nw = 1
            else:
                weeks = []
                ws = first
                while ws <= last:
                    we = ws + pd.Timedelta(days=7)
                    weeks.append((ws, we)); ws = we
                nw = len(weeks)
                commit_ci, full_ci = build_ci(dates, c["journey"], weeks)

            safe_id = c["cid"].replace("/","__").replace(" ","_")
            ci_data = {"contribution_id": c["cid"], "contributor_type": c["type"],
                       "event_type": c["event"], "is_mentorship": c["mentorship"],
                       "repo": repo, "commit_ci": commit_ci, "full_ci": full_ci,
                       "n_weeks": nw, "total_commits": len(dates),
                       "first_date": str(first.date()), "last_date": str(last.date())}
            with open(os.path.join(CI_DIR, f"{safe_id}.json"), "w") as f:
                json.dump(ci_data, f)
            index.append({"contribution_id": c["cid"], "contributor_type": c["type"],
                          "event_type": c["event"], "is_mentorship": c["mentorship"],
                          "repo": repo, "n_weeks": nw, "total_commits": len(dates),
                          "file": f"{safe_id}.json"})
            processed += 1

        # Free memory
        del df; gc.collect()
        done_repos.add(repo)

        # Save progress every 10 repos
        if (ri+1) % 10 == 0:
            with open(progress_path, "w") as f:
                json.dump({"done_repos": list(done_repos)}, f)
            with open(idx_path, "w") as f:
                json.dump({"generated_at": datetime.now().isoformat(),
                           "total_processed": processed, "total_skipped": skipped,
                           "entries": index}, f)
            log(f"  Repo {ri+1}/{len(repos)}: processed={processed}, skipped={skipped}")

    # Final save
    with open(progress_path, "w") as f:
        json.dump({"done_repos": list(done_repos)}, f)
    with open(idx_path, "w") as f:
        json.dump({"generated_at": datetime.now().isoformat(),
                   "total_processed": processed, "total_skipped": skipped,
                   "entries": index}, f)
    log(f"  Timeseries done: {processed} processed, {skipped} skipped")

# ─────────────────────────────────────────────
# STEP 4: CLUSTERING (no T7, just reads JSON)
# ─────────────────────────────────────────────

def step_cluster():
    log("=== STEP 4: CLUSTERING ===")
    from scipy.spatial.distance import pdist, squareform
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    idx_path = os.path.join(CI_DIR, "ci_timeseries_index.json")
    with open(idx_path) as f:
        idx = json.load(f)

    entries = idx["entries"]
    log(f"  Loading {len(entries)} time series...")

    # Load and normalize to 52 points
    TARGET_LEN = 52
    series_list = []
    meta_list = []
    for e in entries:
        fpath = os.path.join(CI_DIR, e["file"])
        if not os.path.exists(fpath): continue
        with open(fpath) as f:
            d = json.load(f)
        raw = d.get("full_ci", d.get("commit_ci", []))
        if not raw or len(raw) < 2: continue
        if max(raw) == 0: continue  # skip flat-zero

        # Interpolate to TARGET_LEN
        x_old = np.linspace(0, 1, len(raw))
        x_new = np.linspace(0, 1, TARGET_LEN)
        interp = np.interp(x_new, x_old, raw)

        # Min-max scale per contributor
        mn, mx = interp.min(), interp.max()
        if mx > mn:
            interp = (interp - mn) / (mx - mn)
        else:
            interp = np.zeros(TARGET_LEN)

        series_list.append(interp)
        meta_list.append(e)

    X = np.array(series_list)
    log(f"  Loaded {len(X)} valid series (52-point normalized)")

    # Find optimal k using elbow + silhouette
    log("  Finding optimal k (2-8)...")
    results = {}
    for k in range(2, 9):
        km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
        labels = km.fit_predict(X)
        inertia = km.inertia_
        sil = silhouette_score(X, labels, sample_size=min(5000, len(X)), random_state=42)
        results[k] = {"inertia": inertia, "silhouette": sil}
        log(f"    k={k}: inertia={inertia:.0f}, silhouette={sil:.3f}")

    # Pick best k: highest silhouette
    best_k = max(results, key=lambda k: results[k]["silhouette"])
    log(f"  Best k={best_k} (silhouette={results[best_k]['silhouette']:.3f})")

    # Final clustering
    km = KMeans(n_clusters=best_k, random_state=42, n_init=10, max_iter=300)
    labels = km.fit_predict(X)
    centroids = km.cluster_centers_

    # Assign labels to entries
    for i, m in enumerate(meta_list):
        m["cluster"] = int(labels[i])

    # Cluster distribution by group
    dist = defaultdict(lambda: defaultdict(int))
    for m in meta_list:
        grp = m["contributor_type"]
        if grp == "event":
            grp = "mentorship" if m.get("is_mentorship") else "non_mentorship"
        dist[m["cluster"]][grp] += 1
        dist[m["cluster"]]["total"] += 1

    log(f"  Cluster distribution:")
    for cl in sorted(dist):
        d = dist[cl]
        log(f"    Cluster {cl}: total={d['total']}, mentorship={d.get('mentorship',0)}, "
            f"non_mentorship={d.get('non_mentorship',0)}, organic={d.get('organic',0)}")

    # Save
    import pandas as pd
    with open(os.path.join(OUT, "dtw_clusters.json"), "w") as f:
        json.dump({"method": "KMeans_Euclidean", "k": best_k,
                   "silhouette": results[best_k]["silhouette"],
                   "k_search": {str(k): v for k,v in results.items()},
                   "centroids": centroids.tolist(),
                   "assignments": [{"contribution_id": m["contribution_id"],
                                    "cluster": m["cluster"],
                                    "contributor_type": m["contributor_type"],
                                    "event_type": m["event_type"]}
                                   for m in meta_list]}, f, indent=2)

    rows = []
    for cl in sorted(dist):
        d = dist[cl]
        rows.append({"cluster": cl, "total": d["total"],
                     "mentorship": d.get("mentorship",0),
                     "non_mentorship": d.get("non_mentorship",0),
                     "organic": d.get("organic",0)})
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "dtw_cluster_distribution.csv"), index=False)

    # Plot centroids
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5))
        for i, c in enumerate(centroids):
            ax.plot(c, label=f"Cluster {i} (n={dist[i]['total']})", linewidth=2)
        ax.set_xlabel("Normalized time (0-51 weeks)")
        ax.set_ylabel("Contribution Index (scaled)")
        ax.set_title(f"Cluster Centroids (k={best_k})")
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(OUT, "dtw_cluster_centroids.png"), dpi=150)
        plt.close(fig)
        log("  Saved centroid plot")
    except Exception as e:
        log(f"  Plot failed: {e}")

    log(f"  Clustering done: k={best_k}")

# ─────────────────────────────────────────────
# STEP 5: GENERATE REPORT
# ─────────────────────────────────────────────

def step_report():
    log("=== STEP 5: GENERATE REPORT ===")
    # Just call the existing script
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(BASE, "scripts", "80_generate_results_report.py")],
                       capture_output=True, text=True, cwd=BASE)
    if r.returncode == 0:
        log("  Report generated successfully")
    else:
        log(f"  Report failed: {r.stderr[-500:]}")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    log(f"Pipeline started: step={step}")
    start = time.time()

    try:
        if step in ("all", "mine"):
            step_mine()
        if step in ("all", "combine"):
            step_combine()
        if step in ("all", "timeseries"):
            step_timeseries()
        if step in ("all", "cluster"):
            step_cluster()
        if step in ("all", "report"):
            step_report()
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        log(traceback.format_exc())

    elapsed = time.time() - start
    log(f"Pipeline finished in {elapsed/60:.1f} min")
