#!/usr/bin/env python3
"""
MONTHLY CUMULATIVE CORE CONTRIBUTOR IDENTIFICATION
===================================================

For each repository on the T7 drive, identifies core contributors using
the 80/20 Pareto rule applied to CUMULATIVE commits evaluated every month.

Methodology (published literature):
  - Mockus, Fielding, Herbsleb (2002, ACM TOSEM): Core = smallest set
    accounting for majority of total commits across project history.
  - Yamashita, McIntosh, Kamei, Hassan (2015, IWPSE): 80/20 Pareto on
    total commit history across 2,496 GitHub projects.
  - CHAOSS GrimoireLab Onion Model: Core = 80% of total activity.
  - Xiao, He, Xu, Zhou (2023, ESEC/FSE): Skip initial period.
    We skip the first 12 months (founder-dominated period).

How it works:
  For each project month M (starting from month 13):
    1. Take ALL commits from project start up to end of month M (cumulative)
    2. Count commits per author_email
    3. Sort descending by commit count
    4. Walk down until cumulative sum >= 80% of total
    5. Everyone included = "core" for month M

  The LAST evaluation (covering all commits) determines who IS core.
  The FIRST month a contributor appears as core gives time-to-core.

  Incremental algorithm: walks through sorted commits once per repo.
  No repeated groupby/filter operations. Fast even for 15+ year projects.

Output per repo (JSON):
  - last_evaluation: full core contributor list at end of project
  - first_core_month: {email: month_number} for time-to-core
  - yearly_cores: backward-compatible yearly snapshots

Memory-safe: one repo at a time, explicit gc, supports resume.

Usage:
  python3 50_monthly_core_contributors.py           # full run (resume-safe)
  python3 50_monthly_core_contributors.py --force    # reprocess all
  python3 50_monthly_core_contributors.py --test 5   # test on 5 repos only
"""

import json
import os
import sys
import gc
from collections import Counter

import pandas as pd
import numpy as np

sys.stdout.reconfigure(line_buffering=True)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T7 = "/Volumes/T7/Event based OSS4SG/extracted"
OUTPUT_DIR = os.path.join(BASE, "07_core_contributor_analysis")

# Minimum thresholds for an evaluation to be meaningful
MIN_CUMULATIVE_COMMITS = 50
MIN_CUMULATIVE_CONTRIBUTORS = 10

# Skip first 12 months (founder period)
SKIP_MONTHS = 12

METHOD_TAG = "monthly_cumulative_pareto_80_20"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def is_already_processed(output_path):
    """Check if a repo was already processed with the CURRENT method."""
    if not os.path.exists(output_path):
        return False
    try:
        with open(output_path) as f:
            data = json.load(f)
        return data.get("method") == METHOD_TAG
    except Exception:
        return False


def compute_pareto_80(author_counts, total_commits):
    """Given a Counter of {email: commit_count}, return the 80/20 core list."""
    sorted_authors = sorted(author_counts.items(), key=lambda x: -x[1])
    threshold = total_commits * 0.80
    running_sum = 0
    core_emails = []
    for email, count in sorted_authors:
        running_sum += count
        core_emails.append(email)
        if running_sum >= threshold:
            break
    return core_emails, sorted_authors


def process_one_project(csv_path):
    """Process a single project CSV: monthly cumulative 80/20 Pareto."""
    fname = os.path.basename(csv_path)
    repo_name = fname.replace("__", "/").replace(".csv", "")
    output_path = os.path.join(OUTPUT_DIR, fname.replace(".csv", "_cores.json"))

    try:
        # ── Load CSV ──
        try:
            df = pd.read_csv(csv_path, usecols=["author_name", "author_email", "author_date"])
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, usecols=["author_name", "author_email", "author_date"],
                             encoding="latin-1")

        empty_result = {
            "repo": repo_name, "method": METHOD_TAG,
            "project_start": None, "total_months": 0,
            "months_analyzed": 0, "last_evaluation": None,
            "first_core_month": {}, "yearly_cores": {}
        }

        if len(df) == 0:
            with open(output_path, "w") as f:
                json.dump(empty_result, f, indent=2)
            return {"repo": repo_name, "status": "empty", "months": 0}

        # ── Parse dates ──
        df["author_date"] = pd.to_datetime(df["author_date"], errors="coerce", utc=True)
        df = df.dropna(subset=["author_date"])
        df["author_email"] = df["author_email"].str.lower().str.strip()
        df["author_name"] = df["author_name"].fillna("").str.lower().str.strip()

        if len(df) == 0:
            with open(output_path, "w") as f:
                json.dump(empty_result, f, indent=2)
            return {"repo": repo_name, "status": "no_valid_dates", "months": 0}

        # ── Sort by date ──
        df = df.sort_values("author_date").reset_index(drop=True)
        project_start = df["author_date"].iloc[0]
        project_end = df["author_date"].iloc[-1]
        duration_days = (project_end - project_start).days
        total_months = max(1, duration_days // 30 + 1)

        # ── Precompute arrays for incremental walk ──
        emails = df["author_email"].values
        names = df["author_name"].values
        dates_ns = df["author_date"].values.astype("int64")  # nanoseconds

        # ── Incremental monthly evaluation ──
        author_counts = Counter()         # email -> cumulative commit count
        author_names = {}                 # email -> first name seen
        first_core_month = {}             # email -> first month they appeared as core
        last_evaluation = None
        yearly_cores = {}
        months_analyzed = 0
        commit_idx = 0                    # pointer into sorted commits

        for month_num in range(SKIP_MONTHS + 1, total_months + 1):
            # Cutoff timestamp for this month
            cutoff_date = project_start + pd.DateOffset(months=month_num)
            cutoff_ns = pd.Timestamp(cutoff_date).value

            # Advance pointer: add all commits up to cutoff
            while commit_idx < len(dates_ns) and dates_ns[commit_idx] <= cutoff_ns:
                e = emails[commit_idx]
                author_counts[e] += 1
                if e not in author_names:
                    author_names[e] = names[commit_idx]
                commit_idx += 1

            total_commits = sum(author_counts.values())
            total_contributors = len(author_counts)

            # Skip if below thresholds
            if total_commits < MIN_CUMULATIVE_COMMITS or total_contributors < MIN_CUMULATIVE_CONTRIBUTORS:
                continue

            # ── 80/20 Pareto ──
            core_emails, sorted_authors = compute_pareto_80(author_counts, total_commits)
            core_count = len(core_emails)
            months_analyzed += 1

            # Track first core month for each email
            for email in core_emails:
                if email not in first_core_month:
                    first_core_month[email] = month_num

            # Build detailed core list (for last evaluation and yearly snapshots)
            core_list_detailed = []
            for email in core_emails:
                c = author_counts[email]
                core_list_detailed.append({
                    "email": email,
                    "name": author_names.get(email, ""),
                    "commits": c,
                    "pct_of_total": round(c / total_commits, 4),
                })

            eval_data = {
                "month_number": month_num,
                "cumulative_commits": total_commits,
                "cumulative_contributors": total_contributors,
                "core_count": core_count,
                "core_contributors": core_list_detailed,
                "core_pct_of_contributors": round(core_count / total_contributors * 100, 2),
            }

            # Always overwrite — the final iteration is the last evaluation
            last_evaluation = eval_data

            # Backward-compatible yearly snapshots (at 12-month boundaries)
            if month_num % 12 == 0:
                year_num = month_num // 12
                year_label = f"year_{year_num}"
                yearly_cores[year_label] = {
                    "year_number": year_num,
                    "cumulative_commits": total_commits,
                    "cumulative_contributors": total_contributors,
                    "core_count": core_count,
                    "core_contributors": core_list_detailed,
                    "core_pct_of_contributors": round(core_count / total_contributors * 100, 2),
                }

        # Also store the very last evaluation as the final yearly snapshot
        # (in case the project doesn't end exactly on a 12-month boundary)
        if last_evaluation and total_months % 12 != 0:
            final_year = total_months // 12 + 1
            year_label = f"year_{final_year}"
            if year_label not in yearly_cores:
                yearly_cores[year_label] = {
                    "year_number": final_year,
                    "cumulative_commits": last_evaluation["cumulative_commits"],
                    "cumulative_contributors": last_evaluation["cumulative_contributors"],
                    "core_count": last_evaluation["core_count"],
                    "core_contributors": last_evaluation["core_contributors"],
                    "core_pct_of_contributors": last_evaluation["core_pct_of_contributors"],
                }

        # ── Save result ──
        result = {
            "repo": repo_name,
            "method": METHOD_TAG,
            "literature_basis": [
                "Mockus, Fielding, Herbsleb (2002, ACM TOSEM)",
                "Yamashita, McIntosh, Kamei, Hassan (2015, IWPSE)",
                "CHAOSS GrimoireLab Onion Model",
                "Xiao, He, Xu, Zhou (2023, ESEC/FSE) — skip first 12 months",
            ],
            "project_start": str(project_start.date()),
            "project_end": str(project_end.date()),
            "total_months": total_months,
            "months_analyzed": months_analyzed,
            "skip_months": SKIP_MONTHS,
            "thresholds": {
                "min_cumulative_commits": MIN_CUMULATIVE_COMMITS,
                "min_cumulative_contributors": MIN_CUMULATIVE_CONTRIBUTORS,
                "pareto_threshold": 0.80,
            },
            "last_evaluation": last_evaluation,
            "first_core_month": first_core_month,
            "yearly_cores": yearly_cores,
        }

        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

        return {"repo": repo_name, "status": "ok", "months": months_analyzed}

    except Exception as e:
        return {"repo": repo_name, "status": f"error: {str(e)}", "months": 0}


def print_summary():
    """Print summary statistics across all processed repos."""
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total_files = 0
    core_rates = []
    time_to_core_all = []

    for fname in sorted(os.listdir(OUTPUT_DIR)):
        if not fname.endswith("_cores.json"):
            continue

        total_files += 1
        try:
            with open(os.path.join(OUTPUT_DIR, fname)) as f:
                data = json.load(f)

            if data.get("method") != METHOD_TAG:
                continue

            le = data.get("last_evaluation")
            if le and le.get("cumulative_contributors", 0) > 0:
                core_rates.append(
                    le["core_count"] / le["cumulative_contributors"] * 100
                )

            fcm = data.get("first_core_month", {})
            for email, month in fcm.items():
                time_to_core_all.append(month)

        except Exception:
            pass

    print(f"  Total repos with output files: {total_files}")

    if core_rates:
        rates = np.array(core_rates)
        print(f"\n  Core rate at last evaluation (% of contributors who are core):")
        print(f"    Mean:    {rates.mean():.1f}%")
        print(f"    Median:  {np.median(rates):.1f}%")
        print(f"    Q1-Q3:   {np.percentile(rates, 25):.1f}% - {np.percentile(rates, 75):.1f}%")

    if time_to_core_all:
        ttc = np.array(time_to_core_all)
        print(f"\n  Time to core (months from project start, all who ever entered core):")
        print(f"    Mean:    {ttc.mean():.1f} months")
        print(f"    Median:  {np.median(ttc):.0f} months")
        print(f"    Q1-Q3:   {np.percentile(ttc, 25):.0f} - {np.percentile(ttc, 75):.0f} months")


def main():
    force = "--force" in sys.argv
    test_n = None
    for i, arg in enumerate(sys.argv):
        if arg == "--test" and i + 1 < len(sys.argv):
            test_n = int(sys.argv[i + 1])

    print("=" * 70)
    print("MONTHLY CUMULATIVE CORE CONTRIBUTOR IDENTIFICATION")
    print("=" * 70)
    print(f"  Method:     80/20 Pareto on cumulative commits per MONTH")
    print(f"  Skip:       First {SKIP_MONTHS} months (founder period)")
    print(f"  Thresholds: >= {MIN_CUMULATIVE_COMMITS} cumulative commits, "
          f">= {MIN_CUMULATIVE_CONTRIBUTORS} contributors")
    if force:
        print(f"  Mode:       FORCE (reprocessing all)")
    if test_n:
        print(f"  Mode:       TEST (first {test_n} repos only)")
    print("=" * 70)

    csv_files = []
    for fname in sorted(os.listdir(T7)):
        if fname.endswith(".csv") and not fname.startswith("._"):
            csv_files.append(os.path.join(T7, fname))

    print(f"\nFound {len(csv_files)} repo CSVs on T7 drive")

    if test_n:
        csv_files = csv_files[:test_n]

    if force:
        remaining = csv_files
        skipped = 0
    else:
        remaining = []
        skipped = 0
        for csv_path in csv_files:
            fname = os.path.basename(csv_path)
            output_path = os.path.join(OUTPUT_DIR, fname.replace(".csv", "_cores.json"))
            if is_already_processed(output_path):
                skipped += 1
            else:
                remaining.append(csv_path)
        print(f"  Already processed (monthly method): {skipped}")

    print(f"  To process: {len(remaining)}")

    if not remaining:
        print("\nAll repos already processed with monthly method.")
        print_summary()
        return

    ok_count = 0
    skip_count = 0
    err_count = 0

    for i, csv_path in enumerate(remaining):
        result = process_one_project(csv_path)

        if result["status"] == "ok":
            ok_count += 1
        elif result["status"] in ("empty", "no_valid_dates"):
            skip_count += 1
        else:
            err_count += 1
            if "error" in result["status"]:
                print(f"    ERROR: {result['repo']}: {result['status']}")

        gc.collect()

        if (i + 1) % 50 == 0 or i == len(remaining) - 1:
            print(f"  Progress: {i + 1}/{len(remaining)} "
                  f"(ok={ok_count}, skip={skip_count}, err={err_count})")

    print(f"\nDone. Processed {len(remaining)} repos.")
    print(f"  OK: {ok_count}, Empty/no dates: {skip_count}, Errors: {err_count}")

    print_summary()


if __name__ == "__main__":
    main()
