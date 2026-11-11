#!/usr/bin/env python3
"""Figure 1 and card for "Where the Budget Goes".

Usage: make_figures.py TABLES_DIR OUT_DIR

Reads rollouts.tsv and calls.tsv (read only), checks the totals quoted in the
paper, and writes fig1.png, card.png, card_2x.png and fig1_data.csv.
Every plotted number comes from fig1_data.csv rows built here.
"""
import csv
import os
import sys
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

KINDS = ("read", "edit", "test")
KIND_COLOR = {"read": "#0072B2", "edit": "#E69F00", "test": "#009E73"}
KIND_TEXT = {"read": "white", "edit": "black", "test": "black"}
RES_COLOR = "#0072B2"
NOTRES_COLOR = "#BBBBBB"
CAP = 28
FIG_W_IN, FIG_H_IN, FIG_DPI = 7.92, 3.8, 200
CARD_W_IN, CARD_H_IN, CARD_DPI = 2.8, 1.4, 200


def fail(message):
    sys.exit("ASSERTION FAILED: " + message)


def check(name, got, want):
    if got != want:
        fail("{}: computed {!r}, expected {!r}".format(name, got, want))
    print("ASSERT OK {} = {}".format(name, got))


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))


def pct(count, total):
    return format(100.0 * count / total, ".1f")


def load(tables_dir):
    rollouts = read_tsv(os.path.join(tables_dir, "rollouts.tsv"))
    calls = read_tsv(os.path.join(tables_dir, "calls.tsv"))
    main = [r for r in rollouts if r["scope"] == "main"]
    main_ids = {r["rollout_id"] for r in main}
    main_calls = [c for c in calls if c["rollout_id"] in main_ids]
    print("rows: rollouts {} calls {} main rollouts {} main calls {}".format(
        len(rollouts), len(calls), len(main), len(main_calls)))
    return main, main_calls


def verify(main, main_calls):
    check("main rollouts", len(main), 285)
    kinds_seen = sorted({c["kind"] for c in main_calls})
    print("kinds seen in main calls: {}".format(kinds_seen))
    attempted = [c for c in main_calls if c["kind"] != "free"]
    charged = [c for c in attempted if c["charged"] == "true"]
    check("attempted calls", len(attempted), 6817)
    check("charged calls", len(charged), 6319)
    check("attempted kinds are read/edit/test only",
          sorted({c["kind"] for c in attempted}), sorted(KINDS))
    check("charged rows of kind free", sum(1 for c in main_calls
          if c["kind"] == "free" and c["charged"] == "true"), 0)
    att = Counter(c["kind"] for c in attempted)
    chg = Counter(c["kind"] for c in charged)
    check("charged shares read/edit/test",
          [pct(chg[k], len(charged)) for k in KINDS], ["71.1", "16.7", "12.3"])
    check("attempted shares read/edit/test",
          [pct(att[k], len(attempted)) for k in KINDS], ["66.1", "22.4", "11.5"])
    check("rollouts.tsv sum attempted_calls",
          sum(int(r["attempted_calls"]) for r in main), 6817)
    check("rollouts.tsv sum charged_calls",
          sum(int(r["charged_calls"]) for r in main), 6319)
    for kind in KINDS:
        check("rollouts.tsv sum chg_" + kind,
              sum(int(r["chg_" + kind]) for r in main), chg[kind])
        check("rollouts.tsv sum att_" + kind,
              sum(int(r["att_" + kind]) for r in main), att[kind])
    at_cap = sum(1 for r in main if int(r["charged_calls"]) == CAP)
    capped_true = sum(1 for r in main if r["capped"] == "true")
    both = sum(1 for r in main
               if (int(r["charged_calls"]) == CAP) != (r["capped"] == "true"))
    print("column used: charged_calls == 28 -> {}; capped == true -> {}; "
          "rollouts where the two disagree -> {}".format(at_cap, capped_true, both))
    check("rollouts with charged_calls == 28", at_cap, 115)
    check("max charged_calls", max(int(r["charged_calls"]) for r in main), CAP)
    check("min charged_calls >= 0", min(int(r["charged_calls"]) for r in main) >= 0, True)
    check("resolved total", sum(1 for r in main if r["resolved"] == "true"), 111)
    return att, chg


def build_rows(main, att, chg):
    rows = []
    for series, counts in (("Attempted", att), ("Charged", chg)):
        total = sum(counts[k] for k in KINDS)
        for kind in KINDS:
            rows.append({"panel": "a", "series": series, "category": kind,
                         "count": counts[kind], "share": pct(counts[kind], total)})
    hist_res = Counter(int(r["charged_calls"]) for r in main if r["resolved"] == "true")
    hist_not = Counter(int(r["charged_calls"]) for r in main if r["resolved"] != "true")
    for name, hist in (("resolved", hist_res), ("not resolved", hist_not)):
        for n in range(CAP + 1):
            rows.append({"panel": "b", "series": name, "category": n,
                         "count": hist[n], "share": ""})
    for n in range(CAP + 1):
        rows.append({"panel": "b", "series": "all rollouts", "category": n,
                     "count": hist_res[n] + hist_not[n], "share": ""})
    check("panel b total", sum(r["count"] for r in rows
          if r["panel"] == "b" and r["series"] == "all rollouts"), 285)
    return rows


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, ["panel", "series", "category", "count", "share"],
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def lookup(rows, panel, series, category):
    for r in rows:
        if r["panel"] == panel and r["series"] == series and str(r["category"]) == str(category):
            return r
    raise KeyError((panel, series, category))


def thousands(value, _pos):
    return "{:,}".format(int(value))


def draw_bars(ax, rows, font, bar_height, with_counts, top_y=1):
    """Two horizontal stacked bars, Attempted on top."""
    for y, series in ((top_y, "Attempted"), (0, "Charged")):
        left = 0
        for kind in KINDS:
            r = lookup(rows, "a", series, kind)
            ax.barh(y, r["count"], left=left, height=bar_height, color=KIND_COLOR[kind],
                    edgecolor="white", linewidth=1.2)
            label = r["share"] + "%"
            if with_counts:
                label = "{:,}\n{}%".format(r["count"], r["share"])
            ax.text(left + r["count"] / 2.0, y, label, ha="center", va="center",
                    fontsize=font, color=KIND_TEXT[kind], linespacing=1.15)
            left += r["count"]
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def make_fig1(rows, main, path):
    fig = plt.figure(figsize=(FIG_W_IN, FIG_H_IN), dpi=FIG_DPI, facecolor="white")
    grid = fig.add_gridspec(1, 2, width_ratios=[1.6, 1.0], left=0.095, right=0.985,
                            top=0.88, bottom=0.30, wspace=0.27)
    ax_a = fig.add_subplot(grid[0, 0])
    ax_b = fig.add_subplot(grid[0, 1])

    draw_bars(ax_a, rows, 9, 0.62, True)
    ax_a.set_yticks([1, 0])
    ax_a.set_yticklabels(["Attempted", "Charged"], fontsize=9.5)
    ax_a.set_ylim(-0.5, 1.5)
    ax_a.set_xlim(0, lookup(rows, "a", "Attempted", "read")["count"]
                  + lookup(rows, "a", "Attempted", "edit")["count"]
                  + lookup(rows, "a", "Attempted", "test")["count"])
    ax_a.xaxis.set_major_formatter(FuncFormatter(thousands))
    ax_a.tick_params(axis="both", labelsize=9)
    ax_a.tick_params(axis="y", length=0)
    ax_a.set_xlabel("calls in the main cohort", fontsize=9.5)
    ax_a.set_title("(a) Calls by kind", loc="left", fontsize=11, fontweight="bold")
    ax_a.legend(handles=[Patch(facecolor=KIND_COLOR[k], label=k) for k in KINDS],
                loc="upper center", bbox_to_anchor=(0.5, -0.25), ncol=3, frameon=False,
                fontsize=9.5, handlelength=1.2, columnspacing=1.8)

    xs = list(range(CAP + 1))
    res = [lookup(rows, "b", "resolved", n)["count"] for n in xs]
    notres = [lookup(rows, "b", "not resolved", n)["count"] for n in xs]
    ax_b.bar(xs, res, width=0.84, color=RES_COLOR, label="resolved")
    ax_b.bar(xs, notres, width=0.84, bottom=res, color=NOTRES_COLOR, label="not resolved")
    cap_count = lookup(rows, "b", "all rollouts", CAP)["count"]
    ax_b.set_ylim(0, cap_count * 1.32)
    ax_b.text(CAP + 0.45, cap_count + cap_count * 0.03,
              "cap of 28 calls\n{} rollouts".format(cap_count), ha="right", va="bottom",
              fontsize=9, linespacing=1.2)
    ax_b.set_xlim(-0.8, CAP + 0.8)
    ax_b.set_xticks(list(range(0, CAP + 1, 4)))
    ax_b.tick_params(axis="both", labelsize=9)
    ax_b.set_xlabel("charged calls in a rollout", fontsize=9.5)
    ax_b.set_ylabel("rollouts", fontsize=9.5)
    ax_b.set_title("(b) Charged calls per rollout", loc="left", fontsize=11, fontweight="bold")
    ax_b.legend(loc="upper left", frameon=False, fontsize=9, handlelength=1.2)
    for side in ("top", "right"):
        ax_b.spines[side].set_visible(False)

    fig.savefig(path, dpi=FIG_DPI, facecolor="white", metadata={"Software": None})
    plt.close(fig)


def make_card(rows, main, path, dpi):
    fig = plt.figure(figsize=(CARD_W_IN, CARD_H_IN), dpi=200, facecolor="white")
    fig.text(0.03, 0.89, "Where the Budget Goes", ha="left", va="center",
             fontsize=13, fontweight="bold")
    ax = fig.add_axes([0.03, 0.28, 0.94, 0.50])
    draw_bars(ax, rows, 6.3, 0.56, False, top_y=1.3)
    ax.set_ylim(-0.4, 2.2)
    ax.set_xlim(0, sum(lookup(rows, "a", "Attempted", k)["count"] for k in KINDS))
    ax.axis("off")
    for y, name in ((1.3, "Attempted"), (0, "Charged")):
        ax.text(0, y + 0.36, name, ha="left", va="bottom", fontsize=8.5, fontweight="bold")
    fig.legend(handles=[Patch(facecolor=KIND_COLOR[k], label=k) for k in KINDS],
               loc="center", bbox_to_anchor=(0.5, 0.215), ncol=3, frameon=False,
               fontsize=8, handlelength=1.0, columnspacing=1.6, handletextpad=0.5)
    fig.text(0.03, 0.07, "Gemma 4 31B developer agent, 285 baseline rollouts",
             ha="left", va="center", fontsize=6.6, color="#333333")
    fig.savefig(path, dpi=dpi, facecolor="white", metadata={"Software": None})
    plt.close(fig)


def main_entry(argv):
    if len(argv) != 3:
        sys.exit("usage: make_figures.py TABLES_DIR OUT_DIR")
    tables_dir, out_dir = argv[1], argv[2]
    print("python {} matplotlib {}".format(sys.version.split()[0], matplotlib.__version__))
    main, main_calls = load(tables_dir)
    att, chg = verify(main, main_calls)
    rows = build_rows(main, att, chg)
    os.makedirs(out_dir, exist_ok=True)
    write_csv(rows, os.path.join(out_dir, "fig1_data.csv"))
    make_fig1(rows, main, os.path.join(out_dir, "fig1.png"))
    make_card(rows, main, os.path.join(out_dir, "card.png"), 200)
    make_card(rows, main, os.path.join(out_dir, "card_2x.png"), 400)
    print("wrote fig1.png card.png card_2x.png fig1_data.csv to " + out_dir)


if __name__ == "__main__":
    main_entry(sys.argv)
