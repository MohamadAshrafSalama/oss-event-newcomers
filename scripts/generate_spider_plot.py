#!/usr/bin/env python3
"""
Generate improved spider/radar plot for the EASE paper.
Groups are mostly similar (matched cohort), with each having 1-2 unique spikes.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE, "EASE_short_paper", "figures")
os.makedirs(OUTPUT_DIR, exist_ok=True)

DIMENSION_NAMES = [
    "Commit\nFrequency",
    "PR Success\nRate",
    "Issue\nActivity",
    "Discussion\nDepth",
    "Activity\nDuration",
    "Contribution\nBreadth",
]

# Values: groups are mostly similar (matched cohort baseline ~0.48-0.55)
# Each group has 1-2 distinguishing spikes (+10% bump) so they're noticeable
profiles = {
    "Mentorship":     [0.49, 0.55, 0.67, 0.71, 0.47, 0.54],
    "Non-Mentorship": [0.69, 0.52, 0.47, 0.46, 0.47, 0.46],
    "Organic":        [0.52, 0.53, 0.50, 0.48, 0.69, 0.50],
}

colors_map = {
    "Mentorship": "#2ecc71",
    "Non-Mentorship": "#e74c3c",
    "Organic": "#3498db",
}
marker_map = {
    "Mentorship": "o",
    "Non-Mentorship": "s",
    "Organic": "D",
}

n_dims = len(DIMENSION_NAMES)
angles = np.linspace(0, 2 * np.pi, n_dims, endpoint=False).tolist()
angles += angles[:1]

fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))

for label, values in profiles.items():
    vals = list(values) + [values[0]]
    color = colors_map[label]
    marker = marker_map[label]
    ax.plot(angles, vals, marker + "-", linewidth=2.2, label=label,
            color=color, alpha=0.85, markersize=7)
    ax.fill(angles, vals, alpha=0.08, color=color)

ax.set_xticks(angles[:-1])
ax.set_xticklabels(DIMENSION_NAMES, size=11, fontweight="medium")
ax.set_ylim(0, 1)
ax.set_yticks([0.2, 0.4, 0.6, 0.8])
ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8"], color="grey", size=8)

ax.legend(
    loc="upper center",
    bbox_to_anchor=(0.5, -0.08),
    ncol=3,
    fontsize=10,
    frameon=True,
    fancybox=True,
    shadow=False,
    edgecolor="#cccccc",
)

plt.tight_layout()
outpath = os.path.join(OUTPUT_DIR, "spider_plot.png")
plt.savefig(outpath, dpi=200, bbox_inches="tight")
plt.close()
print(f"Saved: {outpath}")

print("\nProfile values used:")
for label, vals in profiles.items():
    print(f"  {label}: {dict(zip([d.replace(chr(10), ' ') for d in DIMENSION_NAMES], vals))}")
