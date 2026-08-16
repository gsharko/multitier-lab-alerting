#!/usr/bin/env python3
"""
make_figures.py — regenerates the two result figures of Paper 4 (Fig. 3, Fig. 4).

Fig. 3 (§5.1): per-layer decomposition of the replay evaluation, with the single
  sustained `truenas-backups` excursion shown as a separate segment of L2 so that
  the reader can see, visually, that the aggregate 83.9% is carried by one row of
  the source data. Superseded the earlier fig_b0_vs_b1.png, which annotated the
  aggregate as if it were the headline result.

Fig. 4 (§5.2): cumulative B0 vs B1 over the 29-day live shadow window, per layer,
  making the L2 divergence visible against the L3 convergence.

Inputs (both in ../data-raw/):
  l2_influx_thresholds_summary.csv  — per-rule replay counts (n_above, n_episodes)
  b0_shadow_live_daily.csv          — daily per-layer live counts (date,layer,b0,b1)

Outputs (../figures/): fig3_replay_decomposition.png, fig4_live_cumulative.png
Run: python3 make_figures.py     (needs matplotlib; no network access required)
"""
import csv
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data-raw")
FIGS = os.path.join(HERE, "..", "figures")
os.makedirs(FIGS, exist_ok=True)

# Palette kept consistent with the SVG figures (Figs. 1-2) and legible in greyscale.
C_B0 = "#4C6E8A"      # baseline blue
C_B1 = "#2E8B6F"      # multi-tier green
C_OUTLIER = "#C8794A" # the truenas-backups excursion
GRID = "#D8D5CC"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.edgecolor": "#555555",
    "axes.labelcolor": "#222222",
    "text.color": "#222222",
    "xtick.color": "#444444",
    "ytick.color": "#444444",
})

# --- Replay numbers (§5.1), from the paper's tables -------------------------
REPLAY = {
    "L1 + L3\n(event-based)": {"b0": 507, "b1": 183},
    "L2\n(metric threshold)": {"b0": 899, "b1": 44},
}
# The single sustained condition inside L2, read from the source CSV rather than
# hard-coded, so the figure cannot silently drift from the data.
with open(os.path.join(DATA, "l2_influx_thresholds_summary.csv"), newline="") as f:
    rows = list(csv.DictReader(f))
outlier = next(r for r in rows if r["source"] == "truenas-backups")
OUT_B0 = int(outlier["n_above"])                 # 830
OUT_B1 = int(outlier["n_episodes"]) * 2          # 6  (Firing + Resolved)
L2_TOTAL_B0 = sum(int(r["n_above"]) for r in rows)
assert L2_TOTAL_B0 == REPLAY["L2\n(metric threshold)"]["b0"], L2_TOTAL_B0


def fig3():
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=300)
    labels = list(REPLAY.keys())
    x = range(len(labels))
    w = 0.34

    # B0 bars: L2's bar is split so the outlier's share is visible.
    for i, lab in enumerate(labels):
        b0 = REPLAY[lab]["b0"]
        if lab.startswith("L2"):
            rest = b0 - OUT_B0
            ax.bar(i - w / 2, rest, w, color=C_B0, edgecolor="white", linewidth=0.6)
            ax.bar(i - w / 2, OUT_B0, w, bottom=rest, color=C_OUTLIER,
                   edgecolor="white", linewidth=0.6,
                   label="of which: one sustained excursion\n(`truenas-backups`, 830 samples / 3 episodes)")
        else:
            ax.bar(i - w / 2, b0, w, color=C_B0, edgecolor="white", linewidth=0.6,
                   label="B0 — flat baseline")
        ax.text(i - w / 2, b0 + 22, str(b0), ha="center", fontsize=8.5, fontweight="bold")

        b1 = REPLAY[lab]["b1"]
        ax.bar(i + w / 2, b1, w, color=C_B1, edgecolor="white", linewidth=0.6,
               label="B1 — multi-tier policy" if i == 0 else None)
        ax.text(i + w / 2, b1 + 22, str(b1), ha="center", fontsize=8.5, fontweight="bold")

        # reduction arrow drawn inside the axes, between the two bars
        red = 100.0 * (b0 - b1) / b0
        y_arrow = b0 + 90
        ax.annotate("", xy=(i + w / 2, b1 + 60), xytext=(i - w / 2, y_arrow),
                    arrowprops=dict(arrowstyle="->", color=C_B1, linewidth=1.3,
                                    connectionstyle="arc3,rad=-0.25"))
        ax.text(i + 0.02, y_arrow + 40, f"−{red:.1f}%", ha="center", fontsize=10,
                fontweight="bold", color=C_B1)

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Notifications over the 20-day replay window")
    ax.set_ylim(0, 1180)
    ax.yaxis.set_major_locator(MaxNLocator(6))
    ax.yaxis.grid(True, color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    handles, lbls = ax.get_legend_handles_labels()
    order = [lbls.index("B0 — flat baseline"),
             lbls.index("B1 — multi-tier policy"),
             next(i for i, l in enumerate(lbls) if l.startswith("of which"))]
    ax.legend([handles[i] for i in order], [lbls[i] for i in order],
              fontsize=7.6, frameon=False, loc="upper left", handlelength=1.3)
    ax.set_title("Replay evaluation decomposes unevenly across layers", fontsize=10,
                 fontweight="bold", pad=8, loc="left")
    fig.subplots_adjust(bottom=0.24)
    out = os.path.join(FIGS, "fig3_replay_decomposition.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


def fig4():
    per_layer = defaultdict(lambda: {"dates": [], "b0": [], "b1": []})
    with open(os.path.join(DATA, "b0_shadow_live_daily.csv"), newline="") as f:
        for r in csv.DictReader(f):
            if r["layer"] == "total":
                continue
            d = per_layer[r["layer"]]
            d["dates"].append(r["date"])
            d["b0"].append(int(r["b0"]))
            d["b1"].append(int(r["b1"]))

    def cumsum(xs):
        t, out = 0, []
        for v in xs:
            t += v
            out.append(t)
        return out

    fig, axes = plt.subplots(1, 3, figsize=(9.2, 3.0), dpi=300, sharex=True)
    titles = {"L1": "L1 — availability", "L2": "L2 — metric threshold",
              "L3": "L3 — native events"}
    for ax, layer in zip(axes, ("L1", "L2", "L3")):
        d = per_layer[layer]
        n = len(d["dates"])
        xs = range(n)
        cb0, cb1 = cumsum(d["b0"]), cumsum(d["b1"])
        # L1's two series coincide exactly (no suppression fires); dash B0 so both
        # curves remain visible rather than one hiding under the other.
        ax.plot(xs, cb0, color=C_B0, linewidth=2.6, label="B0 — flat baseline",
                linestyle=(0, (5, 2)) if layer == "L1" else "-")
        ax.plot(xs, cb1, color=C_B1, linewidth=1.8, label="B1 — multi-tier policy")
        # shade the gap, coloured by which policy is winning
        worse = cb1[-1] > cb0[-1]
        ax.fill_between(xs, cb0, cb1, color=C_OUTLIER if worse else C_B1,
                        alpha=0.16, linewidth=0)
        red = 100.0 * (cb0[-1] - cb1[-1]) / cb0[-1] if cb0[-1] else 0.0
        sign = "+" if red < 0 else "−"
        ax.set_title(f"{titles[layer]}\n{sign}{abs(red):.1f}%", fontsize=9,
                     fontweight="bold", color=C_OUTLIER if worse else "#222222")
        ax.set_xlabel("day of live window")
        ax.yaxis.grid(True, color=GRID, linewidth=0.7)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.set_xlim(0, n - 1)
    axes[0].set_ylabel("cumulative notifications")
    axes[0].legend(fontsize=7.6, frameon=False, loc="upper left")
    fig.suptitle("Live shadow run: the threshold layer diverges while the event layers converge",
                 fontsize=10, fontweight="bold", x=0.008, ha="left", y=1.06)
    out = os.path.join(FIGS, "fig4_live_cumulative.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    fig3()
    fig4()
