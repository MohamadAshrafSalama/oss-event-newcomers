#!/usr/bin/env python3
"""
Replication Package Runner
==========================
Runs all 6 analysis scripts in order, matching the paper structure.

  00 - Dataset validation      (Section 3.1-3.3, Table 1)
  01 - Activity profiles       (RQ1, Section 4.1.1, Figure 1)
  02 - Early engagement        (RQ1, Section 4.1.2, Figure 2)
  03 - Core rate & TTC         (RQ2, Section 4.2.1, Table 2 top)
  04 - Survival analysis       (RQ2, Section 4.2.2, Figure 3)
  05 - Pattern-outcome ranking (RQ2, Section 4.2.3, Table 2 bottom)

Usage:
  python replication_package/run_all.py          # run everything
  python replication_package/run_all.py 03 04    # run specific scripts
"""

import os
import subprocess
import sys
import time

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")

SCRIPTS = [
    ("00_dataset_validation.py",        "Dataset Validation (Table 1)"),
    ("01_activity_profiles.py",         "RQ1: Activity Profiles (Figure 1)"),
    ("02_early_engagement_patterns.py", "RQ1: Early Engagement Patterns (Figure 2)"),
    ("03_core_rate_and_ttc.py",         "RQ2: Core Rate & Time-to-Core (Table 2)"),
    ("04_survival_analysis.py",         "RQ2: Survival Analysis (Figure 3)"),
    ("05_pattern_outcome_ranking.py",   "RQ2: Pattern-Outcome Ranking (Table 2)"),
]


def run_script(filename, description):
    path = os.path.join(SCRIPTS_DIR, filename)
    print(f"\n{'#' * 72}")
    print(f"# {description}")
    print(f"# {filename}")
    print(f"{'#' * 72}\n")
    t0 = time.time()
    result = subprocess.run([sys.executable, path])
    elapsed = time.time() - t0
    status = "OK" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
    print(f"\n  [{status}] {filename} ({elapsed:.1f}s)")
    return result.returncode == 0


def main():
    print("=" * 72)
    print("  REPLICATION PACKAGE: Same Project, Different Start (EASE 2026)")
    print("=" * 72)

    requested = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    results = []
    for filename, description in SCRIPTS:
        prefix = filename[:2]
        if requested and prefix not in requested:
            continue
        ok = run_script(filename, description)
        results.append((filename, ok))

    print("\n" + "=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    for filename, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {filename}")

    figures_dir = os.path.join(os.path.dirname(SCRIPTS_DIR), "figures")
    if os.path.isdir(figures_dir):
        figs = [f for f in os.listdir(figures_dir) if f.endswith(".png")]
        if figs:
            print(f"\n  Figures generated in replication_package/figures/:")
            for f in sorted(figs):
                print(f"    - {f}")

    all_ok = all(ok for _, ok in results)
    print(f"\n  Overall: {'ALL PASSED' if all_ok else 'SOME FAILED'}")
    print("=" * 72)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
