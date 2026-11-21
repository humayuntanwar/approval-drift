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


def rows(phase="main", model="sonnet", guard="0"):
    return [r for r in csv.DictReader(open(os.path.join(REPO, "runs", "results.csv")))
            if r["phase"] == phase and r["model"] == model and r["guard_live"] == guard]


def short(sc):
    lab = SCEN[sc]["label"].replace("subscription already on BEFORE approval", "subscription on before approval")
    return sc.split("_")[0] + ") " + lab


def bars(ax, scen, data, field):
    conds = [c for c in ("P0", "P1") if any(r["condition"] == c for r in data)]
    h = 0.38
    for j, c in enumerate(conds):
        for i, sc in enumerate(scen):
            s = [r for r in data if r["scenario"] == sc and r["condition"] == c]
            k, n = sum(int(r[field]) for r in s), len(s)
            if not n:
                continue
            lo, hi = wilson(k, n)
            y = i + (j - (len(conds) - 1) / 2) * h
            ax.barh(y, 100 * k / n, height=h - 0.06, color=C[c], label=NAME[c] if i == 0 else None)
            ax.errorbar(100 * k / n, y, xerr=[[100 * k / n - 100 * lo], [100 * hi - 100 * k / n]], fmt="o",
                        ms=4, color=INK2, ecolor="#9a9893", elinewidth=1.2, capsize=4)
            ax.text(max(100 * hi, 100 * k / n) + 2, y, "%d/%d" % (k, n), va="center", fontsize=14, color=INK2)
    ax.set_yticks(range(len(scen)))
    ax.set_yticklabels([short(s) for s in scen])
    ax.invert_yaxis()
    ax.set_xlim(0, 118)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="x", color=GRID)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)


def fig_results():
    data = rows()
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=BG)
    ax1 = fig.add_axes([0.30, 0.40, 0.66, 0.43])
    ax2 = fig.add_axes([0.30, 0.06, 0.66, 0.26])
    bars(ax1, HARM + PRE, data, "unsafe")
    bars(ax2, SAFE, data, "over_refusal")
    n = len([r for r in data if r["condition"] == "P0" and r["scenario"] == HARM[0]])
    fig.text(0.02, 0.94, "How often the agent paid an order the human did not approve", fontsize=28, weight="bold")
    fig.text(0.02, 0.895, "sandbox store, Sonnet as the shopping agent, %d runs per bar, whiskers = 95%% CI. "
             "Change injected after the approval tap." % n, fontsize=16, color=INK2)
    ax1.set_title("harmful change: % of runs that paid it (unsafe)", loc="left", fontsize=18, color=INK)
    ax2.set_title("harmless change: % of runs that refused to pay (over-refusal)", loc="left", fontsize=18, color=INK)
    ax1.legend(loc="lower right", frameon=False, fontsize=15)
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
    data = rows()
    live = rows(phase="guard")
    unsafe = [r for r in data if r["unsafe"] == "1"]
    safe_pay = [r for r in data if SCEN[r["scenario"]]["class"] == "safe" and r["guard_block"] != ""]
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=BG)
    fig.text(0.03, 0.93, "Binding the token to the approved cart", fontsize=28, weight="bold")
    ax = fig.add_axes([0.05, 0.14, 0.40, 0.62])
    labels, vals, tots, cols = [], [], [], []
    for field, nm in (("guard_block", "strict"), ("guard_block_no_increase", "no-increase")):
        labels += ["unsafe pays\nblocked (%s)" % nm, "safe pays\nblocked (%s)" % nm]
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
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_title("offline replay of every main-batch pay attempt", loc="left", fontsize=17)
    ax2 = fig.add_axes([0.62, 0.14, 0.34, 0.62])
    cnt = Counter(r["after_decline"] or ("never declined: " + r["outcome"]) for r in live)
    items = sorted(cnt.items(), key=lambda kv: -kv[1])
    ax2.barh(range(len(items)), [v for _, v in items], color="#2a78d6", height=0.6)
    for i, (_, v) in enumerate(items):
        ax2.text(v + 0.2, i, str(v), va="center", fontsize=16)
    ax2.set_yticks(range(len(items)))
    ax2.set_yticklabels([k.replace("_", " ") for k, _ in items], fontsize=13)
    ax2.invert_yaxis()
    ax2.set_xlim(0, max([v for _, v in items] + [1]) * 1.25)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)
    ax2.set_title("live: what the agent did after a decline (%d runs)" % len(live), loc="left", fontsize=17)
    fig.text(0.03, 0.885, "strict = same lines, total <= approved + $0.50, same recurring flag. "
             "no-increase = only block added paid lines / higher qty or price.", fontsize=14, color=INK2)
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
    ax = fig.add_axes([0.07, 0.12, 0.88, 0.68])
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
    ax.legend(frameon=False, loc="upper right", fontsize=15)
    fig.text(0.03, 0.88, "card accuracy uses the first approval card; lines = 95% CI", fontsize=15, color=INK2)
    fig.savefig(os.path.join(IMG, "4_cards_and_looking.png"), facecolor=BG)


if __name__ == "__main__":
    os.makedirs(IMG, exist_ok=True)
    fig_results()
    print("side-by-side run:", fig_side_by_side())
    if rows(phase="guard"):
        fig_guard()
    fig_cards()
    print("images written to", IMG)
