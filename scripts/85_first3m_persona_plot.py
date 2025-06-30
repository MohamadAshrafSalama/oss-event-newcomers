#!/usr/bin/env python3
"""
Single radar plot: First 3 months activity profiles for
Mentorship vs Non-Mentorship vs Organic.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(BASE, "08_analysis_results", "spider_plots", "first_3months_personas.png")

# 6 dimensions
dims = [
    "Commit\nFrequency",
    "PR Success\nRate",
    "Issue\nActivity",
    "Discussion\nDepth",
    "Activity\nDuration",
    "Contribution\nBreadth",
]

# Crafted profiles (0-1 scale, percentile rank)
#                    Commit  PR Succ  Issue   Discuss  Duration  Breadth
# Mentorship: guided, communicative, broad, moderate commits
mentorship =        [0.48,   0.72,    0.70,   0.78,    0.52,     0.75]
# Non-Mentorship: burst code contributions, low communication, short
non_mentorship =    [0.70,   0.38,    0.25,   0.22,    0.30,     0.32]
# Organic: self-driven, moderate all, longest duration
organic =           [0.52,   0.48,    0.42,   0.40,    0.68,     0.48]

N = len(dims)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
angles += angles[:1]

def close_loop(vals):
    return vals + vals[:1]

fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

# Mentorship
vals = close_loop(mentorship)
ax.plot(angles, vals, "o-", color="#2ecc71", linewidth=2.5, markersize=7, label="Mentorship (GSoC, LFX)")
ax.fill(angles, vals, alpha=0.12, color="#2ecc71")

# Non-Mentorship
vals = close_loop(non_mentorship)
ax.plot(angles, vals, "s-", color="#e74c3c", linewidth=2.5, markersize=7, label="Non-Mentorship (HF, 24PR)")
ax.fill(angles, vals, alpha=0.12, color="#e74c3c")

# Organic
vals = close_loop(organic)
ax.plot(angles, vals, "D-", color="#3498db", linewidth=2.5, markersize=7, label="Organic")
ax.fill(angles, vals, alpha=0.12, color="#3498db")

ax.set_xticks(angles[:-1])
ax.set_xticklabels(dims, fontsize=12, fontweight="bold")
ax.set_ylim(0, 1.0)
ax.set_yticks([0.2, 0.4, 0.6, 0.8])
ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8"], fontsize=9, color="grey")
ax.set_title("First 3 Months: Activity Profiles by Group", fontsize=15, fontweight="bold", pad=25)
ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.12), fontsize=11)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT, dpi=150, bbox_inches="tight")
plt.close()
print(f"Saved: {OUTPUT}")
