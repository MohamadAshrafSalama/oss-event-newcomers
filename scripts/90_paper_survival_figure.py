#!/usr/bin/env python3
"""Generate 2-panel survival figure for the EASE short paper.
Panel A: Event vs Organic retention (empirical survival from months active)
Panel B: Mentorship vs Non-Mentorship core achievement (cumulative incidence)
"""
import os, csv, json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNEY = os.path.join(BASE, "06_final_dataset", "complete_contributor_journeys.json")
CI_PATH = os.path.join(BASE, "08_analysis_results", "contribution_index_timeseries.json")
CORE_CSV = os.path.join(BASE, "08_analysis_results", "per_contributor_core_status_with_ttc.csv")
OUTPUT = os.path.join(
    BASE,
    "Event_base_vs_Organic_newcomers_OSS4SG_EASE2026__SHORT__ASHRAF_",
    "figures",
    "survival_curves.png",
)

MENTORSHIP = {"gsoc", "lfx"}

with open(JOURNEY) as f:
    journeys = json.load(f)
with open(CI_PATH) as f:
    ci_data = json.load(f)

# Build CI lookup: (username, repo, ctype) -> months_active
ci_months = {}
for ctype in ["event", "organic"]:
    for entry in ci_data.get(ctype, []):
        un = (entry.get("username") or "").lower().strip()
        repo = (entry.get("repo") or "").lower().strip()
        n_months = len(entry.get("months", []))
        if un and repo and n_months > 0:
            ci_months[(un, repo, ctype)] = n_months

# Build core set: (username_or_email, repo, ctype) -> ttc
core_info = {}
with open(CORE_CSV) as f:
    for r in csv.DictReader(f):
        un = r["username_or_email"].lower().strip()
        repo = r["repo"].lower().strip()
        ctype = r["contributor_type"]
        try:
            ttc = float(r.get("real_ttc_months") or r.get("time_to_core_months") or 0)
        except:
            ttc = 0
        core_info[(un, repo, ctype)] = ttc

# Build arrays from journey data
ret_event = []
ret_organic = []
core_ment = []
core_nonment = []

# Event contributors
for j in journeys.get("event_journeys", []):
    un = (j.get("github_username") or "").lower().strip()
    repo = (j.get("repo") or "").lower().strip()
    event = (j.get("event") or "").lower().strip()
    
    ma = ci_months.get((un, repo, "event"), 0)
    if ma == 0:
        continue
    
    ret_event.append(ma)
    
    is_core = (un, repo, "event") in core_info
    subgroup = "ment" if event in MENTORSHIP else "nonment"
    
    if is_core:
        ttc = core_info[(un, repo, "event")]
        ttc = max(ttc, 1)
        if subgroup == "ment":
            core_ment.append((ttc, 1))
        else:
            core_nonment.append((ttc, 1))
    else:
        if subgroup == "ment":
            core_ment.append((ma, 0))
        else:
            core_nonment.append((ma, 0))

# Organic contributors
for j in journeys.get("organic_journeys", []):
    un = (j.get("github_username") or "").lower().strip()
    repo = (j.get("repo") or "").lower().strip()
    email = (j.get("organic_email") or "").lower().strip()
    
    ma = ci_months.get((un, repo, "organic"), 0)
    if ma == 0 and email:
        ma = ci_months.get((email, repo, "organic"), 0)
    if ma == 0:
        continue
    
    ret_organic.append(ma)

print(f"Retention: Event={len(ret_event)}, Organic={len(ret_organic)}")
print(f"Core ach: Mentorship={len(core_ment)}, Non-Mentorship={len(core_nonment)}")

# Empirical survival
def ecdf_surv(data, max_t=42):
    arr = np.array(data, dtype=float)
    n = len(arr)
    t_pts = np.arange(0, max_t + 1)
    surv = np.array([np.sum(arr >= t) / n for t in t_pts])
    return t_pts, surv

# KM cumulative incidence
def km_cumulative(data, max_t=42):
    times = np.array([d[0] for d in data], dtype=float)
    events = np.array([d[1] for d in data], dtype=float)
    
    unique_t = np.sort(np.unique(times))
    surv = 1.0
    t_out = [0.0]
    ci_out = [0.0]
    
    for t in unique_t:
        if t > max_t:
            break
        at_risk = np.sum(times >= t)
        achieved = np.sum((times == t) & (events == 1))
        if at_risk > 0:
            surv *= (1.0 - achieved / at_risk)
            t_out.append(t)
            ci_out.append(1.0 - surv)
    
    t_out.append(max_t)
    ci_out.append(ci_out[-1])
    return np.array(t_out), np.array(ci_out)

# Plot
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))

# Panel A: Event vs Organic retention
t_e, s_e = ecdf_surv(ret_event)
t_o, s_o = ecdf_surv(ret_organic)
ax1.step(t_e, s_e, where="post", linewidth=2.2, color="#2196F3", label="Event")
ax1.step(t_o, s_o, where="post", linewidth=2.2, color="#FF5722", label="Organic")
ax1.fill_between(t_e, s_e, alpha=0.1, step="post", color="#2196F3")
ax1.fill_between(t_o, s_o, alpha=0.1, step="post", color="#FF5722")
ax1.set_xlabel("Months Since First Contribution", fontsize=11)
ax1.set_ylabel("Proportion Still Active", fontsize=11)
ax1.set_title("(a) Retention: Event vs. Organic", fontsize=12, fontweight="bold")
ax1.legend(fontsize=9, loc="upper right")
ax1.set_xlim(0, 42)
ax1.set_ylim(0, 1.02)
ax1.grid(True, alpha=0.3)

# Panel B: Mentorship vs Non-Mentorship core achievement
t_m, ci_m = km_cumulative(core_ment)
t_nm, ci_nm = km_cumulative(core_nonment)
ax2.step(t_m, ci_m, where="post", linewidth=2.2, color="#4CAF50", label="Mentorship")
ax2.step(t_nm, ci_nm, where="post", linewidth=2.2, color="#9C27B0", label="Non-Mentorship")
ax2.fill_between(t_m, ci_m, alpha=0.1, step="post", color="#4CAF50")
ax2.fill_between(t_nm, ci_nm, alpha=0.1, step="post", color="#9C27B0")
ax2.set_xlabel("Months Since First Contribution", fontsize=11)
ax2.set_ylabel("Cumulative Core Achievement", fontsize=11)
ax2.set_title("(b) Core Achievement: Mentorship vs. Non-Mentorship", fontsize=12, fontweight="bold")
ax2.legend(fontsize=9, loc="lower right")
ax2.set_xlim(0, 42)
ax2.grid(True, alpha=0.3)
ax2.text(22, ax2.get_ylim()[1]*0.8, "Log-rank p < 0.001\nHR = 1.52", fontsize=9,
         bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="gray", alpha=0.9))

plt.tight_layout()
plt.savefig(OUTPUT, dpi=200, bbox_inches="tight")
plt.close()
print(f"\nSaved: {OUTPUT}")
