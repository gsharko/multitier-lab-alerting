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

Outputs (../figures/): fig3_replay_decomposition.png, fig4_l1_composition.png,
fig5_live_cumulative.png. Figure numbers follow the order of first citation in the
manuscript, as Springer requires, which is why the composition figure is Fig. 4.
Run: python3 make_figures.py     (needs matplotlib; no network access required)
"""
import csv
import os
import re
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

# Springer submission mode (SPRINGER_SUBMISSION=1) applies the JNSM artwork rules:
# sans-serif lettering (Arial/Helvetica), no title inside the illustration — the
# journal takes the caption from the manuscript text — the 174 mm single-column
# width, and vector PDF alongside a 600 dpi raster.
SUBMISSION = os.environ.get("SPRINGER_SUBMISSION") == "1"
WIDTH_IN = 174 / 25.4          # 174 mm, Springer single-column text area
MAX_H_IN = 234 / 25.4          # 234 mm
PAD_IN = 0.02                  # the sliver bbox_inches="tight" keeps around the ink
FLOOR_PT = 8.0                 # Springer will not set figure lettering below this


def small(pt):
    """A small type size for the reading copy, clamped to the journal floor.

    Legends and dense tick labels are set below 8 pt on screen, where the figure is
    read at whatever size the window gives it. At 174 mm the journal measures the
    type, so under SUBMISSION nothing is allowed under 8 pt.
    """
    return max(pt, FLOOR_PT) if SUBMISSION else pt

plt.rcParams.update({
    "font.family": ["Arial", "DejaVu Sans"] if SUBMISSION
                   else "DejaVu Sans",
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

def headline(obj, text, **kw):
    """Set a title that summarizes the figure — omitted in submission mode, where
    Springer requires the caption to live in the manuscript, not in the artwork."""
    if SUBMISSION:
        return
    (obj.suptitle if hasattr(obj, "suptitle") else obj.set_title)(text, **kw)


def panel_label(ax, letter):
    """Lowercase part label, as Springer requires for multi-part figures."""
    ax.text(-0.02, 1.06, f"({letter})", transform=ax.transAxes, ha="right",
            va="bottom", fontsize=9, fontweight="bold")


def pdf_width_mm(pdf):
    """The width of the page as the file itself declares it."""
    with open(pdf, "rb") as f:
        head = f.read(4096)
    m = re.search(rb"/MediaBox\s*\[\s*([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)", head)
    assert m, "no MediaBox in " + pdf
    return (float(m.group(3)) - float(m.group(1))) / 72 * 25.4


def save_at_width(fig, pdf):
    """Write the PDF and resize until the page really is 174 mm wide.

    bbox_inches="tight" crops to the ink rather than to the canvas, and the ink does
    not scale with the canvas — type sizes are fixed in points — so the canvas size
    that yields a 174 mm page has to be found by iteration. Measuring the written
    file closes the loop on the artefact that is actually submitted.
    """
    for _ in range(12):
        fig.savefig(pdf, bbox_inches="tight", pad_inches=PAD_IN)
        mm = pdf_width_mm(pdf)
        if abs(mm - 174.0) < 0.15:
            return
        w, h = fig.get_size_inches()
        k = 174.0 / mm
        fig.set_size_inches(w * k, min(h * k, MAX_H_IN))
    raise AssertionError("%s settled at %.1f mm, not 174" % (pdf, mm))


def save(fig, stem, number):
    """Write the working PNG, or the submission-ready vector + 600 dpi raster."""
    if not SUBMISSION:
        out = os.path.join(FIGS, stem + ".png")
        fig.savefig(out, bbox_inches="tight")
        print("wrote", out)
        return
    sub = os.path.join(FIGS, "submission")
    os.makedirs(sub, exist_ok=True)
    pdf = os.path.join(sub, f"Fig{number}.pdf")
    save_at_width(fig, pdf)
    print("wrote", pdf)
    png = os.path.join(sub, f"Fig{number}.png")
    fig.savefig(png, bbox_inches="tight", pad_inches=PAD_IN, dpi=600)
    print("wrote", png)


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
              fontsize=small(7.6), frameon=False, loc="upper left", handlelength=1.3)
    headline(ax, "Replay evaluation decomposes unevenly across layers", fontsize=10,
             fontweight="bold", pad=8, loc="left")
    fig.subplots_adjust(bottom=0.24)
    save(fig, "fig3_replay_decomposition", 3)
    plt.close(fig)


def fig_live_cumulative():
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
    for letter, ax in zip("abc", axes):
        panel_label(ax, letter)
    axes[0].set_ylabel("cumulative notifications")
    axes[0].legend(fontsize=small(7.6), frameon=False, loc="upper left")
    headline(fig, "Live shadow run: the threshold layer diverges while the event layers converge",
             fontsize=10, fontweight="bold", x=0.008, ha="left", y=1.06)
    save(fig, "fig5_live_cumulative", 5)
    plt.close(fig)




# --- Fig. 5 (§5.2): composition of the live availability layer ---------------
# L1 is the one layer where the policy reduced nothing (140 -> 140). The figure
# shows why: only 41% of the window's availability signals are the independent
# incidents the rule was designed for. Read entirely from the per-object export
# so it cannot drift from the data.
C_REAL   = "#2E8B6F"  # independent real incidents  (the intended population)
C_SCHED  = "#C8794A"  # scheduled power cycle, host's own transitions
C_DEP    = "#E3B58C"  # same cycle, restated by a dependent object
C_REPEAT = "#4C6E8A"  # repeat notification, no intervening state change
C_PEND   = "#9A9691"  # pending-state marker

CAT = [
    ("real_incident", "independent real incident", C_REAL),
    ("scheduled_power_cycle", "scheduled power cycle (host)", C_SCHED),
    ("scheduled_power_cycle_dependent", "same cycle, dependent object", C_DEP),
    ("repeat_no_state_change", "repeat, no state change", C_REPEAT),
    ("pending_not_down", "pending-state marker", C_PEND),
]


def fig_l1_composition():
    path = os.path.join(DATA, "l1_uptimekuma_live_important.csv")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 140, f"expected 140 live L1 rows, got {len(rows)}"

    per = defaultdict(lambda: defaultdict(int))
    for r in rows:
        per[r["monitor"]][r["note"]] += 1
    order = sorted(per, key=lambda m: -sum(per[m].values()))

    # anonymise object names: the paper identifies roles, not hostnames
    ROLE = {
        "Open WebUI": "application service (on host A)",
        "pve1": "virtualization host A",
        "NVR Shinobi (Lalëz)": "remote recorder (overlay link)",
        "pfSense": "router / firewall",
        "TrueNAS": "storage appliance",
        "pve2": "virtualization host B",
        "pbs": "backup server",
        "pi-hole": "DNS resolver",
        "Grafana": "dashboarding service",
        "ntfy": "notification hub",
        "NPM": "reverse proxy",
    }
    labels = [ROLE.get(m, "other service") for m in order]
    # collapse the single-signal tail into one row
    keep, tail = [], defaultdict(int)
    for m, lab in zip(order, labels):
        if sum(per[m].values()) >= 2:
            keep.append((lab, per[m]))
        else:
            for k, v in per[m].items():
                tail[k] += v
    if tail:
        keep.append((f"{len(order) - len(keep)} further objects (1 signal each)", tail))

    fig, (ax, ax2) = plt.subplots(
        1, 2, figsize=(9.4, 3.5), gridspec_kw={"width_ratios": [2.55, 1]})

    panel_label(ax, "a")
    panel_label(ax2, "b")
    ys = range(len(keep))
    left = [0] * len(keep)
    for key, lab, col in CAT:
        vals = [d.get(key, 0) for _, d in keep]
        if not any(vals):
            continue
        ax.barh(list(ys), vals, left=left, color=col, label=lab,
                height=0.68, edgecolor="white", linewidth=0.6)
        left = [l + v for l, v in zip(left, vals)]
    ax.set_yticks(list(ys))
    ax.set_yticklabels([lab for lab, _ in keep], fontsize=8.2)
    ax.invert_yaxis()
    ax.set_xlabel("availability signals in the live window")
    ax.xaxis.grid(True, color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(fontsize=small(7.4), frameon=False, loc="lower right", ncol=1)
    headline(ax, "140 signals, three objects carry 78% of them",
             fontsize=9, fontweight="bold", loc="left")

    # right panel: what the categories sum to
    tot = defaultdict(int)
    for r in rows:
        tot[r["note"]] += 1
    sched = tot["scheduled_power_cycle"] + tot["scheduled_power_cycle_dependent"]
    bars = [("real\nincidents", tot["real_incident"], C_REAL),
            ("scheduled\ncycle", sched, C_SCHED),
            # at 8 pt "repeat, no / transition" runs into the bar beside it in this
            # narrow panel; the three-line break also matches the wording of the
            # legend in panel (a)
            ("repeat,\nno state\nchange", tot["repeat_no_state_change"], C_REPEAT)]
    xs = range(len(bars))
    ax2.bar(list(xs), [b[1] for b in bars], color=[b[2] for b in bars],
            width=0.62, edgecolor="white", linewidth=0.6)
    for i, (_, v, _) in enumerate(bars):
        ax2.text(i, v + 2, f"{v}\n{100*v/140:.0f}%", ha="center", va="bottom",
                 fontsize=8, fontweight="bold")
    ax2.set_xticks(list(xs))
    ax2.set_xticklabels([b[0] for b in bars], fontsize=small(7.8))
    ax2.set_ylim(0, 88)
    ax2.yaxis.grid(True, color=GRID, linewidth=0.7)
    ax2.set_axisbelow(True)
    ax2.set_ylabel("signals")
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)
    headline(ax2, "only 41% is what the\nrule was designed to act on",
             fontsize=9, fontweight="bold", loc="left")

    headline(fig, "Why the availability layer reduced nothing: composition of the 140 live L1 signals",
             fontsize=10, fontweight="bold", x=0.008, ha="left", y=1.045)
    save(fig, "fig4_l1_composition", 4)
    plt.close(fig)


if __name__ == "__main__":
    fig3()
    fig_l1_composition()   # Fig. 4 — cited first in §5.2
    fig_live_cumulative()  # Fig. 5
