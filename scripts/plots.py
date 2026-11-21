#!/usr/bin/env python3
"""Make the README images from runs/results.csv and the raw run events."""
import csv
import json
import os
import re
import sys
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report import wilson, CFG, SCEN, HARM, SAFE, PRE, REPO  # noqa: E402

INK, INK2, GRID, BG = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
C = {"P0": "#2a78d6", "P1": "#eb6834"}
NAME = {"P0": "P0 plain prompt", "P1": "P1 careful prompt"}
IMG = os.path.join(REPO, "images")
plt.rcParams.update({"text.parse_math": False, "font.size": 17, "text.color": INK, "axes.labelcolor": INK, "xtick.color": INK2,
                     "ytick.color": INK, "axes.edgecolor": GRID, "font.family": "DejaVu Sans"})


def rows(phase="main", model="sonnet", guard=None):
    if guard is None:
        guard = "1" if phase == "guard" else "0"
    return [r for r in csv.DictReader(open(os.path.join(REPO, "runs", "results.csv")))
            if r["phase"] == phase and r["model"] == model and r["guard_live"] == guard]


def short(sc):
    lab = SCEN[sc]["label"].replace("subscription already on BEFORE approval", "subscription on before approval")
    return sc.split("_")[0] + ") " + lab


def series():
    sn, hk = rows(), rows(model="haiku")
    return [("Sonnet, P0 plain prompt", [r for r in sn if r["condition"] == "P0"], "#2a78d6"),
            ("Sonnet, P1 careful prompt", [r for r in sn if r["condition"] == "P1"], "#eb6834"),
            ("Haiku, P0 plain prompt", hk, "#1baf7a")]


def bars(ax, scen, groups, field):
    groups = [g for g in groups if g[1]]
    h = 0.8 / len(groups)
    for j, (nm, data, col) in enumerate(groups):
        for i, sc in enumerate(scen):
            s = [r for r in data if r["scenario"] == sc]
            k, n = sum(int(r[field]) for r in s), len(s)
            if not n:
                continue
            lo, hi = wilson(k, n)
            y = i + (j - (len(groups) - 1) / 2) * h
            ax.barh(y, 100 * k / n, height=h - 0.04, color=col, label=nm if i == 0 else None)
            ax.plot([100 * lo, 100 * hi], [y, y], color="#9a9893", lw=1.0)
            ax.text(100 * hi + 1.5, y, "%d/%d" % (k, n), va="center", fontsize=11, color=INK2)
    ax.set_yticks(range(len(scen)))
    ax.set_yticklabels([short(s) for s in scen])
    ax.invert_yaxis()
    ax.set_xlim(0, 112)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="x", color=GRID)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)


def fig_results():
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=BG)
    ax1 = fig.add_axes([0.30, 0.40, 0.66, 0.39])
    ax2 = fig.add_axes([0.30, 0.06, 0.66, 0.26])
    bars(ax1, HARM + PRE, series(), "unsafe")
    bars(ax2, SAFE, series(), "over_refusal")
    fig.text(0.02, 0.94, "How often the agent paid an order the human did not approve", fontsize=28, weight="bold")
    fig.text(0.02, 0.895, "sandbox store, 5 runs per bar, grey line = 95% CI. "
             "The merchant changes the order after the approval tap.", fontsize=16, color=INK2)
    ax1.set_title("harmful change: % of runs that paid it", loc="left", fontsize=18, color=INK)
    ax2.set_title("harmless change: % of runs that refused to pay", loc="left", fontsize=18, color=INK)
    h, l = ax1.get_legend_handles_labels()
    fig.legend(h, l, loc="upper left", bbox_to_anchor=(0.02, 0.875), ncol=3, frameon=False, fontsize=15)
    fig.savefig(os.path.join(IMG, "1_results.png"), facecolor=BG)


def first_unsafe_run():
    data = sorted((r for r in rows() if r["unsafe"] == "1"), key=lambda r: r["run_id"])
    return data[0] if data else None


def fig_side_by_side():
    r = first_unsafe_run()
    if not r:
        return None
    d = os.path.join(REPO, "runs", r["phase"], r["run_id"])
    ev = [json.loads(l) for l in open(os.path.join(d, "events.jsonl"))]
    pay = next(e for e in ev if e["ev"] == "pay")
    appr = [e["approval"] for e in ev if e["ev"] == "approval"][pay["approval_n"] - 1]
    receipt = next(e["out"] for e in ev if e["ev"] == "cmd" and e["cmd"] == "pay" and "ORDER PLACED" in e["out"])
    card = appr["card"]
    left = ["merchant:   %s" % card.get("merchant"), "card:       ...%s" % card.get("card_last4"), "items:"]
    for it in card["items"]:
        left.append("  %s" % it.get("name"))
        left.append("    qty %s  @ $%.2f" % (it.get("qty"), float(str(it.get("unit_price")).strip("$"))))
    left += ["total:      $%.2f" % appr["card_total"], "recurring:  %s" % str(card.get("recurring")).lower()]
    if card.get("notes"):
        note = str(card["notes"])
        left.append("notes:")
        while note:
            left.append("  " + note[:44])
            note = note[44:]
    names = {it["name"] for it in card["items"]}
    rec = r["mismatch"]
    hl = []
    for line in receipt.split("\n")[2:]:
        bad = False
        s = line.strip()
        if s.startswith("Charged") or s.startswith("Total charged"):
            bad = "total" in rec
        elif "Subscribe" in s:
            bad = "recurring" in rec
        elif "service fee" in s or ("Shipping" in s and "$0.00" not in s):
            bad = True
        elif "qty" in s:
            nm = s.split("  qty")[0].strip()
            q = int(s.split("qty")[1].split()[0])
            match = [it for it in card["items"] if it["name"] == nm]
            bad = nm not in names or (match and int(match[0]["qty"]) != q) or "qty" in rec and q > 1
            if match and not bad:
                bad = abs(float(s.split("$")[-1]) - q * float(str(match[0]["unit_price"]).strip("$"))) > 0.01
        hl.append((line, bad))
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=BG)
    fig.text(0.03, 0.93, "What the human approved vs what got charged", fontsize=28, weight="bold")
    fig.text(0.03, 0.885, "run %s (scenario: %s). Rule: first unsafe run by run_id. Highlighted = differs from the card."
             % (r["run_id"], SCEN[r["scenario"]]["label"]), fontsize=15, color=INK2)
    for x, title in ((0.03, "approval card (Face ID approved)"), (0.52, "receipt after the agent hit pay")):
        fig.text(x, 0.82, title, fontsize=20, weight="bold")
    y = 0.76
    for line in left[:22]:
        fig.text(0.03, y, line, family="DejaVu Sans Mono", fontsize=15)
        y -= 0.033
    y = 0.76
    for line, bad in hl[:22]:
        line = re.sub(r"\s{3,}", "   ", line.split(" (wallet token")[0])
        fig.text(0.52, y, line[:60], family="DejaVu Sans Mono", fontsize=14,
                 bbox=dict(facecolor="#fde2d6", edgecolor="none", pad=2) if bad else None,
                 color=INK, weight="bold" if bad else "normal")
        y -= 0.033
    rep = r["report"]
    first = rep.split(". ")[0][:150] + ". " + (rep.split(". ")[1][:110] + "." if ". " in rep else "")
    fig.text(0.52, 0.30, "what the agent told the user afterwards:", fontsize=15, color=INK2)
    words, cur, lines_ = first.split(), "", []
    for w in words:
        if len(cur) + len(w) > 60:
            lines_.append(cur)
            cur = ""
        cur += w + " "
    lines_.append(cur)
    for i, l in enumerate(lines_[:4]):
        fig.text(0.52, 0.26 - 0.035 * i, l, fontsize=15, style="italic")
    fig.text(0.03, 0.05, "approved $%.2f   charged $%.2f   difference %+.2f   (%s)"
             % (float(r["approved_total"]), float(r["charged_total"]), float(r["charged_minus_approved"]),
                "recurring added" if "recurring" in rec else "one-time"), fontsize=19, weight="bold")
    fig.add_artist(plt.Line2D([0.495, 0.495], [0.12, 0.84], color=GRID, lw=2))
    fig.savefig(os.path.join(IMG, "2_side_by_side.png"), facecolor=BG)
    return r["run_id"]


def fig_guard():
    main = [r for r in csv.DictReader(open(os.path.join(REPO, "runs", "results.csv"))) if r["phase"] == "main"]
    unsafe = [r for r in main if r["unsafe"] == "1"]
    safe_pay = [r for r in main if SCEN[r["scenario"]]["class"] == "safe" and r["guard_block"] != ""]
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=BG)
    fig.text(0.03, 0.93, "Bind the token to the approved cart", fontsize=28, weight="bold")
    fig.text(0.03, 0.885, "strict = same lines, total <= approved + $0.50, same recurring flag.  "
             "no-increase = only block added paid lines, higher qty or higher price.", fontsize=14, color=INK2)
    ax = fig.add_axes([0.06, 0.14, 0.38, 0.62])
    labels, vals, tots, cols = [], [], [], []
    for field, nm in (("guard_block", "strict"), ("guard_block_no_increase", "no-increase")):
        labels += ["unsafe pays\nblocked\n(%s)" % nm, "harmless pays\nblocked\n(%s)" % nm]
        vals += [sum(int(r[field]) for r in unsafe), sum(int(r[field]) for r in safe_pay)]
        tots += [len(unsafe), len(safe_pay)]
        cols += ["#2a78d6", "#eb6834"]
    ax.bar(range(4), [100 * v / t if t else 0 for v, t in zip(vals, tots)], color=cols, width=0.6)
    for i, (v, t) in enumerate(zip(vals, tots)):
        ax.text(i, (100 * v / t if t else 0) + 2, "%d/%d" % (v, t), ha="center", fontsize=16)
    ax.set_xticks(range(4))
    ax.set_xticklabels(labels, fontsize=13)
    ax.set_ylim(0, 112)
    ax.set_yticks([0, 50, 100])
    ax.set_yticklabels(["0%", "50%", "100%"])
    ax.grid(axis="y", color=GRID)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.set_title("offline replay, all %d main-batch runs" % len(main), loc="left", fontsize=17)
    ax2 = fig.add_axes([0.53, 0.14, 0.43, 0.62])
    cats = [("hit a decline", lambda r: int(r["n_declines"]) > 0),
            ("re-asked with an accurate\nnew card, then paid", lambda r: r["after_decline"] == "re_requested_accurate_then_paid"),
            ("fudged the card\nto get past the guard", lambda r: "card_mismatch" in r["after_decline"]),
            ("paid a change the\nhuman never saw", lambda r: r["unsafe"] == "1")]
    models = [("sonnet", "Sonnet", "#2a78d6"), ("haiku", "Haiku", "#1baf7a")]
    h = 0.38
    for j, (m, nm, col) in enumerate(models):
        live = rows(phase="guard", model=m, guard="1")
        for i, (_, f) in enumerate(cats):
            v = sum(1 for r in live if f(r))
            y = i + (j - 0.5) * h
            ax2.barh(y, v, height=h - 0.06, color=col, label="%s (%d runs)" % (nm, len(live)) if i == 0 else None)
            ax2.text(v + 0.3, y, str(v), va="center", fontsize=15)
    ax2.set_yticks(range(len(cats)))
    ax2.set_yticklabels([c for c, _ in cats], fontsize=14)
    ax2.invert_yaxis()
    ax2.set_xlim(0, 21)
    ax2.set_xticks([0, 6, 12, 18])
    for sp in ("top", "right"):
        ax2.spines[sp].set_visible(False)
    ax2.legend(frameon=False, loc="lower right", fontsize=14)
    ax2.set_title("live, guard on, P0, harmful scenarios a-f", loc="left", fontsize=17)
    fig.savefig(os.path.join(IMG, "3_guard.png"), facecolor=BG)


def fig_cards():
    data = rows()
    hk = rows(model="haiku")
    groups = [("Sonnet P0", [r for r in data if r["condition"] == "P0"]),
              ("Sonnet P1", [r for r in data if r["condition"] == "P1"])]
    if hk:
        groups.append(("Haiku P0", hk))
    metrics = [("card_accurate", "approval card matched\nthe page"), ("looked_after_approval", "re-checked the page\nafter approval"),
               ("unsafe", "paid a harmful\nchange (a-f, k)")]
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=BG)
    fig.text(0.03, 0.93, "Accurate cards, but does the agent look again before paying?", fontsize=26, weight="bold")
    ax = fig.add_axes([0.07, 0.12, 0.88, 0.62])
    cols = ["#2a78d6", "#eb6834", "#1baf7a"]
    w = 0.8 / len(groups)
    for gi, (nm, g) in enumerate(groups):
        for mi, (f, _) in enumerate(metrics):
            s = [r for r in g if r[f] != "" and (f != "unsafe" or SCEN[r["scenario"]]["class"] != "safe")]
            if f == "looked_after_approval":
                s = [r for r in s if int(r["n_approvals"]) > 0]
            k, n = sum(int(r[f]) for r in s), len(s)
            lo, hi = wilson(k, n)
            x = mi + (gi - (len(groups) - 1) / 2) * w
            ax.bar(x, 100 * k / n, width=w - 0.04, color=cols[gi], label=nm if mi == 0 else None)
            ax.plot([x, x], [100 * lo, 100 * hi], color=INK, lw=1.6)
            ax.text(x, 100 * hi + 2, "%d/%d" % (k, n), ha="center", fontsize=13, color=INK2)
    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels([m[1] for m in metrics])
    ax.set_ylim(0, 115)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="y", color=GRID)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    h, l = ax.get_legend_handles_labels()
    fig.legend(h, l, loc="upper left", bbox_to_anchor=(0.03, 0.86), ncol=3, frameon=False, fontsize=15)
    fig.text(0.03, 0.88, "all main-batch runs; card accuracy = first approval card; re-check = separate page view before pay; lines = 95% CI", fontsize=15, color=INK2)
    fig.savefig(os.path.join(IMG, "4_cards_and_looking.png"), facecolor=BG)


if __name__ == "__main__":
    os.makedirs(IMG, exist_ok=True)
    fig_results()
    print("side-by-side run:", fig_side_by_side())
    fig_guard()
    fig_cards()
    print("images written to", IMG)
