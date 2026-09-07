#!/usr/bin/env python3
"""
Generate all publication-quality figures for SlotRAG TKDE paper v4.
Output: PDF (vector) + PNG for review. IEEE double-column compatible.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np
import os

OUT = os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUT, exist_ok=True)

# ── Figure 1: System Overview ──────────────────────────────────────────────────

def fig1_system_overview():
    fig, ax = plt.subplots(figsize=(3.4, 5.2))  # single-column width for IEEE
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 14)
    ax.axis('off')

    # Style params
    boxw = 7.2
    boxh = 0.9
    cx = 5.0
    fontargs = dict(fontsize=7.5, ha='center', va='center', family='serif')

    def draw_box(y, text, fc='#f0f0f0', ec='black', lw=1.0, fontsize=7.5):
        rect = FancyBboxPatch((cx - boxw/2, y - boxh/2), boxw, boxh,
                              boxstyle="round,pad=0.08", fc=fc, ec=ec, lw=lw,
                              zorder=2)
        ax.add_patch(rect)
        ax.text(cx, y, text, fontsize=fontsize, ha='center', va='center',
                family='serif', zorder=3)

    def draw_arrow(y_from, y_to, color='#666666'):
        ax.annotate('', xy=(cx, y_to + boxh/2), xytext=(cx, y_from - boxh/2),
                    arrowprops=dict(arrowstyle='->', color=color, lw=1.2))

    # Nodes (bottom-up for y-axis)
    y_positions = [12.8, 11.2, 9.4, 7.8, 6.2, 4.2, 2.5]

    # 1. Question
    draw_box(y_positions[0], 'Question', fc='#e8f0fe', fontsize=8)

    # 2. Typed Evidence Compiler
    draw_box(y_positions[1], 'Typed Evidence Compiler', fc='#e8f0fe')
    draw_arrow(y_positions[0], y_positions[1])

    # 3. Typed Evidence Plan (slots + joins + operators)
    draw_box(y_positions[2], 'Typed Evidence Plan\n(slots, joins, operators)',
             fc='#fff3e0', fontsize=7)
    draw_arrow(y_positions[1], y_positions[2])

    # 4. Structural / Budget Diagnosis
    draw_box(y_positions[3], 'Structural / Budget Diagnosis', fc='#fce4ec')
    draw_arrow(y_positions[2], y_positions[3])

    # 5. Physical Dispatch (split)
    draw_box(y_positions[4], 'Physical Dispatch', fc='#f3e5f5', fontsize=7.5)
    draw_arrow(y_positions[3], y_positions[4])

    # Split arrows
    # Shallow path
    ax.annotate('', xy=(2.5, 5.6), xytext=(cx, y_positions[4] - boxh/2),
                arrowprops=dict(arrowstyle='->', color='#666666', lw=1.0))
    # Deep path
    ax.annotate('', xy=(7.5, 5.6), xytext=(cx, y_positions[4] - boxh/2),
                arrowprops=dict(arrowstyle='->', color='#666666', lw=1.0))

    # Shallow box
    sh_box = FancyBboxPatch((1.0, 5.0 - boxh/2), 3.0, boxh,
                            boxstyle="round,pad=0.08", fc='#e0f2f1', ec='#666', lw=0.8)
    ax.add_patch(sh_box)
    ax.text(2.5, 5.0, 'Shallow → Static', fontsize=7, ha='center', va='center',
            family='serif', zorder=3)

    # Deep box
    dp_box = FancyBboxPatch((6.0, 5.0 - boxh/2), 3.2, boxh,
                            boxstyle="round,pad=0.08", fc='#fff9c4', ec='#666', lw=0.8)
    ax.add_patch(dp_box)
    ax.text(7.6, 5.0, 'Deep → Budget-Aware Flat', fontsize=7, ha='center',
            va='center', family='serif', zorder=3)

    # Merge arrows
    ax.annotate('', xy=(cx, 3.5 + boxh/2), xytext=(2.5, 5.0 - boxh/2),
                arrowprops=dict(arrowstyle='->', color='#666666', lw=1.0))
    ax.annotate('', xy=(cx, 3.5 + boxh/2), xytext=(7.6, 5.0 - boxh/2),
                arrowprops=dict(arrowstyle='->', color='#666666', lw=1.0))

    # 6. Evidence Materialization
    draw_box(y_positions[5], 'Evidence Materialization', fc='#f1f8e9')

    # 7. Answer
    draw_box(y_positions[6], 'Answer', fc='#e8f5e9', fontsize=8)
    draw_arrow(y_positions[5], y_positions[6])

    ax.set_title('Fig. 1: System overview', fontsize=8, pad=6, family='serif')
    fig.tight_layout(pad=0.3)
    fig.savefig(f'{OUT}/system_overview.pdf', bbox_inches='tight', dpi=300)
    fig.savefig(f'{OUT}/system_overview.png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    print("Fig 1 done")


# ── Figure 2: Budget Mismatch + Confusion Matrix ─────────────────────────────

def fig2_budget_mismatch():
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 2.8))  # full column width

    # --- Left: Static vs Budget-Aware ---
    ax = axes[0]
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    # Title
    ax.text(5, 9.5, '(a) Local vs. global budget allocation',
            fontsize=8, ha='center', va='center', family='serif', fontweight='bold')

    # Static allocation (left half)
    ax.add_patch(FancyBboxPatch((0.5, 4.8), 4.0, 4.2, boxstyle="round,pad=0.15",
                                fc='#fce4ec', ec='#c62828', lw=1.2))
    ax.text(2.5, 8.7, 'Static (local)', fontsize=7, ha='center', va='center',
            family='serif', fontweight='bold')
    slots_static = [('slot 1: 4 calls', 7.8), ('slot 2: 4 calls', 6.7),
                    ('slot 3: 4 calls', 5.6)]
    for text, y in slots_static:
        ax.text(2.5, y, text, fontsize=7, ha='center', va='center', family='serif')
    ax.text(2.5, 5.1, r'$\Sigma = 12 > B = 8$', fontsize=8, ha='center', va='center',
            family='serif', color='#c62828', fontweight='bold')
    ax.text(2.5, 4.3, 'Allocation-infeasible', fontsize=7.5, ha='center',
            va='center', family='serif', color='#c62828', fontweight='bold')

    # Budget-aware (right half)
    ax.add_patch(FancyBboxPatch((5.2, 4.8), 4.3, 4.2, boxstyle="round,pad=0.15",
                                fc='#e8f5e9', ec='#2e7d32', lw=1.2))
    ax.text(7.35, 8.7, 'Budget-aware (global)', fontsize=7, ha='center',
            va='center', family='serif', fontweight='bold')
    slots_flat = [('slot 1: 3 calls', 7.8), ('slot 2: 3 calls', 6.7),
                  ('slot 3: 2 calls', 5.6)]
    for text, y in slots_flat:
        ax.text(7.35, y, text, fontsize=7, ha='center', va='center', family='serif')
    ax.text(7.35, 5.1, r'$\Sigma = 8 \leq B = 8$', fontsize=8, ha='center',
            va='center', family='serif', color='#2e7d32', fontweight='bold')
    ax.text(7.35, 4.3, 'Budget-feasible', fontsize=7.5, ha='center',
            va='center', family='serif', color='#2e7d32', fontweight='bold')

    # Arrow between
    ax.annotate('', xy=(5.0, 7.0), xytext=(4.6, 7.0),
                arrowprops=dict(arrowstyle='->', color='#333', lw=1.5))

    # Necessary condition
    ax.text(5, 3.5, r'Necessary: budget\_exceeded $\Rightarrow$ $\Sigma a_s > B$',
            fontsize=7, ha='center', va='center', family='serif',
            bbox=dict(boxstyle='round,pad=0.2', fc='white', ec='#999', lw=0.8))
    ax.text(5, 2.7, '(recall = 1.0, precision = 0.533)',
            fontsize=7, ha='center', va='center', family='serif', style='italic')

    # --- Right: Confusion matrix ---
    ax2 = axes[1]
    ax2.set_xlim(0, 10)
    ax2.set_ylim(0, 10)
    ax2.axis('off')

    ax2.text(5, 9.5, '(b) Confusion matrix (n = 350)', fontsize=8, ha='center',
             va='center', family='serif', fontweight='bold')

    # Table layout
    # Header
    ax2.text(2.0, 8.5, '', fontsize=7, ha='center', family='serif')
    ax2.text(5.0, 8.5, 'Observed: No BE', fontsize=7.5, ha='center', family='serif', fontweight='bold')
    ax2.text(8.0, 8.5, 'Observed: BE', fontsize=7.5, ha='center', family='serif', fontweight='bold')

    # Row 1: Predicted Feasible
    ax2.text(2.0, 7.2, 'Pred. feasible', fontsize=7.5, ha='center', va='center', family='serif', fontweight='bold')
    ax2.text(5.0, 7.2, 'TN = 76', fontsize=8, ha='center', va='center', family='serif',
             bbox=dict(boxstyle='round,pad=0.3', fc='#e8f5e9', ec='#999', lw=0.8))
    ax2.text(8.0, 7.2, 'FN = 0', fontsize=8, ha='center', va='center', family='serif',
             bbox=dict(boxstyle='round,pad=0.3', fc='#e3f2fd', ec='#999', lw=0.8))

    # Row 2: Predicted Infeasible
    ax2.text(2.0, 5.7, 'Pred. infeasible', fontsize=7.5, ha='center', va='center', family='serif', fontweight='bold')
    ax2.text(5.0, 5.7, 'FP = 128', fontsize=8, ha='center', va='center', family='serif',
             bbox=dict(boxstyle='round,pad=0.3', fc='#fff3e0', ec='#999', lw=0.8))
    ax2.text(8.0, 5.7, 'TP = 146', fontsize=8, ha='center', va='center', family='serif',
             bbox=dict(boxstyle='round,pad=0.3', fc='#fce4ec', ec='#999', lw=0.8))

    # Horizontal line
    ax2.plot([3.5, 9.5], [8.0, 8.0], color='#999', lw=0.8)

    # Stats
    ax2.text(5, 4.2, r'$\mathrm{Precision} = \frac{146}{274} = 0.533$', fontsize=8,
             ha='center', va='center', family='serif')
    ax2.text(5, 3.3, r'$\mathrm{Recall} = \frac{146}{146} = 1.000$', fontsize=8,
             ha='center', va='center', family='serif')
    ax2.text(5, 2.3, r'$\Sigma a_i > B$ is necessary but not sufficient for BE',
             fontsize=7, ha='center', va='center', family='serif', style='italic')

    fig.tight_layout(pad=0.5)
    fig.savefig(f'{OUT}/budget_mismatch.pdf', bbox_inches='tight', dpi=300)
    fig.savefig(f'{OUT}/budget_mismatch.png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    print("Fig 2 done")


# ── Figure 3: Structural-Regime Effect ────────────────────────────────────────

def fig3_regime_effect():
    fig, ax = plt.subplots(figsize=(3.4, 2.8))

    # Data
    regimes = ['Shallow\n(exploratory)', 'Deep\n(confirmatory)']
    deltas  = [-0.0210, 0.0771]
    ci_low  = [-0.0273, 0.0486]
    ci_high = [-0.0146, 0.1086]

    x = np.array([0.0, 1.0])
    yerr_low = [d - lo for d, lo in zip(deltas, ci_low)]
    yerr_high = [hi - d for d, hi in zip(deltas, ci_high)]

    # Shallow: open marker + hatched fill
    ax.errorbar(x[0], deltas[0], yerr=[[yerr_low[0]], [yerr_high[0]]],
                fmt='o', color='#333', markerfacecolor='white', markeredgecolor='#333',
                markeredgewidth=1.5, capsize=4, capthick=1.2, elinewidth=1.2, zorder=3)

    # Deep: solid marker
    ax.errorbar(x[1], deltas[1], yerr=[[yerr_low[1]], [yerr_high[1]]],
                fmt='s', color='#333', markerfacecolor='#333', markeredgecolor='#333',
                markeredgewidth=1.2, capsize=4, capthick=1.2, elinewidth=1.2, zorder=3)

    # Reference line at 0
    ax.axhline(y=0, color='#999', linestyle='--', linewidth=0.8, zorder=1)

    # Labels
    ax.set_xticks(x)
    ax.set_xticklabels(regimes, fontsize=7.5, family='serif')
    ax.set_ylabel(r'$\Delta$EM  (Flat $-$ Static)', fontsize=7.5, family='serif')
    ax.set_ylim(-0.04, 0.13)
    ax.set_xlim(-0.4, 1.4)
    ax.tick_params(axis='y', labelsize=7)

    # Annotations
    ax.annotate(r'$\Delta$ = $-0.0210$' + '\n' + r'$p < 0.001$',
                xy=(0.0, -0.0210), xytext=(-0.25, -0.033),
                fontsize=6.5, ha='center', va='top', family='serif',
                arrowprops=dict(arrowstyle='->', color='#555', lw=0.8))
    ax.annotate(r'$\Delta$ = $+0.0771$' + '\n' + r'$p < 10^{-6}$',
                xy=(1.0, 0.0771), xytext=(1.25, 0.115),
                fontsize=6.5, ha='center', va='top', family='serif',
                arrowprops=dict(arrowstyle='->', color='#555', lw=0.8))

    # Legend
    ax.plot([], [], 'o', markerfacecolor='white', markeredgecolor='#333',
            markeredgewidth=1.5, label='Exploratory (shallow, $n=8{,}085$)')
    ax.plot([], [], 's', markerfacecolor='#333', markeredgecolor='#333',
            label='Confirmatory (deep, $n=350$)')
    ax.legend(fontsize=6.5, loc='upper left', framealpha=0.9, edgecolor='#ccc',
              prop=dict(family='serif'))

    ax.set_title('Fig. 3: Structural-regime effect of budget-aware allocation',
                 fontsize=7.5, pad=5, family='serif')
    fig.tight_layout(pad=0.3)
    fig.savefig(f'{OUT}/regime_effect.pdf', bbox_inches='tight', dpi=300)
    fig.savefig(f'{OUT}/regime_effect.png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    print("Fig 3 done")


# ── Figure 4: Three-Arm Ablation ─────────────────────────────────────────────

def fig4_three_arm():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.16, 2.5), gridspec_kw={'width_ratios': [1.1, 1]})

    arms = ['Static', 'Flat', 'Chain']

    # Panel A: EM
    em_vals = [0.1714, 0.2486, 0.2571]
    colors  = ['#d32f2f', '#1565c0', '#2e7d32']
    bars = ax1.bar(arms, em_vals, color=colors, edgecolor='#333', linewidth=0.8, width=0.6)
    ax1.set_ylabel('EM', fontsize=8, family='serif')
    ax1.set_ylim(0, 0.35)
    ax1.set_title('(a) Answer quality (EM)', fontsize=7.5, family='serif', pad=5)
    ax1.tick_params(axis='x', labelsize=7.5)
    ax1.tick_params(axis='y', labelsize=7)
    for bar, val in zip(bars, em_vals):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                 f'{val:.4f}', ha='center', va='bottom', fontsize=7, family='serif')
    # Chain vs Flat annotation
    ax1.annotate('', xy=(1, 0.2486), xytext=(2, 0.2486),
                 arrowprops=dict(arrowstyle='<->', color='#555', lw=0.8, shrinkA=0, shrinkB=0))
    ax1.text(1.5, 0.32, r'$\Delta$ = +0.0086' + '\n' + r'$p = 0.743$',
             ha='center', va='bottom', fontsize=6.5, family='serif')

    # Panel B: Budget-exhausted rate
    be_vals = [41.7, 0.0, 0.0]
    bars2 = ax2.bar(arms, be_vals, color=colors, edgecolor='#333', linewidth=0.8, width=0.6)
    ax2.set_ylabel('BE rate (%)', fontsize=8, family='serif')
    ax2.set_ylim(0, 50)
    ax2.set_title('(b) Budget exhaustion (n = 350)', fontsize=7.5, family='serif', pad=5)
    ax2.tick_params(axis='x', labelsize=7.5)
    ax2.tick_params(axis='y', labelsize=7)
    for bar, val in zip(bars2, be_vals):
        offset = 1.5 if val > 0 else 0.5
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                 f'{val:.1f}%', ha='center', va='bottom', fontsize=7, family='serif')

    fig.tight_layout(pad=0.6)
    fig.savefig(f'{OUT}/three_arm_ablation.pdf', bbox_inches='tight', dpi=300)
    fig.savefig(f'{OUT}/three_arm_ablation.png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    print("Fig 4 done")


if __name__ == '__main__':
    fig1_system_overview()
    fig2_budget_mismatch()
    fig3_regime_effect()
    fig4_three_arm()
    print("All figures generated.")
