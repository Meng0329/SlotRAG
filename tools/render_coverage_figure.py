#!/usr/bin/env python3
"""Regenerate coverage_main.png (Fig 1) — matched-budget main table bar chart.

Data source: phase4_main_table_recompute.py output, itself recomputed from
raw per-question items in runs/slotrag-phase4-{trace-b1,budget-full}/. The
four (guard, budget, baseline) acc_full triples are reproduced by that script
(verified 2026-08-19: 0.3171/0.5807, 0.5312/0.7842, 0.6644/0.6901,
0.6393/0.6403; Coverage 1/4 = 25%). NO number is hand-typed beyond the
script-reproduced recompute line.

This regenerates paper/figures/coverage_main.png at print-readable size:
- double-column 0.95 columnwidth ≈ 3.2 in; render at 300 dpi → 960px target width
- font sizes chosen so 6pt-equivalent survives the 52% scale-down
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---- verified data (from phase4_main_table_recompute.py, 2026-08-19) ----
datasets = ["MuSiQue", "HotpotQA", "2WikiMultiHop", "DROP"]
guard    = [0.3171, 0.5312, 0.6644, 0.6393]
budget   = [0.5807, 0.7842, 0.6901, 0.6403]
baseline = [0.5263, 0.8124, 0.7449, 0.7246]
baseline_names = ["IRCoT", "GraphRAG", "IRCoT", "GraphRAG"]
verdicts = ["WIN", "TIE", "LOSS", "LOSS"]

# ---- figure sizing for double-column print readability ----
# target printed width 3.2in @ 300dpi = 960px; render at 1860px wide (≈6.2in)
# → printed at 52% → base font must be ≥ 6pt-equivalent * 2 ≈ 12pt at render
fig, ax = plt.subplots(figsize=(6.2, 3.4), dpi=300)

x = np.arange(len(datasets))
w = 0.26

b1 = ax.bar(x - w, guard,  w, label="guard",       color="#8ab4f8", edgecolor="black", linewidth=0.6)
b2 = ax.bar(x,     budget, w, label="guard-budget", color="#3d7ae0", edgecolor="black", linewidth=0.6)
b3 = ax.bar(x + w, baseline, w, label="strongest baseline", color="#c9c9c9", edgecolor="black", linewidth=0.6)

# value labels (12pt render font → 6pt printed)
for bars in (b1, b2, b3):
    for rect in bars:
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + 0.012,
                f"{rect.get_height():.3f}", ha="center", va="bottom",
                fontsize=12.5, rotation=0)

# verdict labels above each group
for i in range(len(x)):
    v = verdicts[i]
    ax.text(x[i], max(budget[i], baseline[i]) + 0.075, v,
            ha="center", va="bottom", fontsize=14, fontweight="bold",
            color={"WIN": "#1a7f37", "TIE": "#9a6700", "LOSS": "#cf222e"}[v])

ax.set_xticks(x)
ax.set_xticklabels([f"{d}\n({bn})" for d, bn in zip(datasets, baseline_names)], fontsize=13)
ax.set_ylabel("acc_full (budget-exceeded = 0)", fontsize=14)
ax.set_ylim(0, 0.95)
ax.tick_params(axis="y", labelsize=12)
ax.legend(fontsize=13, loc="upper left", framealpha=0.9)
ax.grid(axis="y", alpha=0.3, linestyle=":")
ax.set_axisbelow(True)

fig.suptitle("", fontsize=1)  # no title (paper caption carries it)
fig.tight_layout(pad=0.4)

out = "paper/figures/coverage_main.png"
fig.savefig(out, dpi=300, bbox_inches="tight")
print(f"wrote {out} {fig.get_size_inches()[0]}x{fig.get_size_inches()[1]}in @300dpi")
print(f"  → {fig.get_size_inches()[0]*300:.0f}x{fig.get_size_inches()[1]*300:.0f}px")
