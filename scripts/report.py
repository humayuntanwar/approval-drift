#!/usr/bin/env python3
"""Regenerate every number used in the README from runs/results.csv.

Each output line has a stable key (e.g. [main.P0.unsafe_pooled]) so text can cite it.
Also writes runs/report.txt.
"""
import csv
import json
import math
import os
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(REPO, "scenarios.json")))
SCEN = {s["id"]: s for s in CFG["scenarios"]}
HARM = [s["id"] for s in CFG["scenarios"] if s["class"] == "harmful"]
SAFE = [s["id"] for s in CFG["scenarios"] if s["class"] == "safe"]
PRE = [s["id"] for s in CFG["scenarios"] if s["class"] == "harmful_pre"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rate(rows, field):
    k = sum(int(r[field]) for r in rows if r[field] != "")
    n = sum(1 for r in rows if r[field] != "")
    lo, hi = wilson(k, n)
    return k, n, "%d/%d = %.0f%% [95%% CI %.0f-%.0f%%]" % (k, n, 100 * k / n if n else float("nan"), 100 * lo, 100 * hi)


def load():
    return list(csv.DictReader(open(os.path.join(REPO, "runs", "results.csv"))))


def main():
    rows = load()
    out = []

    def say(key, text):
        out.append("[%s] %s" % (key, text))

    groups = sorted({(r["phase"], r["model"]) for r in rows})
    say("runs.total", "%d scored runs: %s" % (len(rows), ", ".join(
        "%s/%s=%d" % (p, m, sum(1 for r in rows if r["phase"] == p and r["model"] == m)) for p, m in groups)))
    say("runs.status", dict(Counter(r["status"] for r in rows)))
    nonpilot = [r for r in rows if r["phase"] != "pilot"]
    den = [r for r in nonpilot if int(r["n_denied_calls"]) > 0]
    say("runs.denied", "%d/%d non-pilot runs had >=1 shell call refused by the permission layer; refused commands: %s"
        % (len(den), len(nonpilot), dict(Counter(c for r in den for c in r["denied_cmds"].split(";")))))
    for phase, model in groups:
        if phase == "pilot":
            continue
        g = [r for r in rows if r["phase"] == phase and r["model"] == model]
        tag = "%s.%s" % (phase, model)
        conds = sorted({r["condition"] for r in g})
        for c in conds:
            gc = [r for r in g if r["condition"] == c]
            t = "%s.%s" % (tag, c)
            say(t + ".n", "%d runs; seconds median %.0f" % (len(gc), sorted(float(r["seconds"]) for r in gc)[len(gc) // 2]))
            for sc in HARM + PRE + SAFE:
                s = [r for r in gc if r["scenario"] == sc]
                if not s:
                    continue
                oc = dict(Counter(r["outcome"] for r in s))
                field = "over_refusal" if SCEN[sc]["class"] == "safe" else "unsafe"
                say("%s.%s.%s" % (t, sc, field), "%s | outcomes %s" % (rate(s, field)[2], oc))
            h = [r for r in gc if r["scenario"] in HARM]
            if h:
                say(t + ".unsafe_pooled_a-f", rate(h, "unsafe")[2])
                say(t + ".silent_overcharge_a-f", rate(h, "silent_overcharge")[2])
                unsafe = [r for r in h if r["unsafe"] == "1"]
                if unsafe:
                    extra = [float(r["charged_minus_approved"]) for r in unsafe]
                    say(t + ".unsafe_extra_dollars", "sum $%.2f, mean $%.2f, range $%.2f..$%.2f over %d unsafe pays"
                        % (sum(extra), sum(extra) / len(extra), min(extra), max(extra), len(extra)))
                    say(t + ".unsafe_disclosed_after", rate(unsafe, "report_discloses_change")[2])
                say(t + ".looked_after_approval_a-f", rate(h, "looked_after_approval")[2])
                lk = [r for r in h if r["looked_after_approval"] == "1"]
                nl = [r for r in h if r["looked_after_approval"] == "0"]
                if lk:
                    say(t + ".unsafe_if_looked", rate(lk, "unsafe")[2])
                if nl:
                    say(t + ".unsafe_if_not_looked", rate(nl, "unsafe")[2])
            s = [r for r in gc if r["scenario"] in SAFE]
            if s:
                say(t + ".over_refusal_g-j", rate(s, "over_refusal")[2])
            say(t + ".card_accurate_first", rate(gc, "card_accurate")[2])
            say(t + ".looked_after_approval_all", rate([r for r in gc if int(r["n_approvals"]) > 0], "looked_after_approval")[2])
            say(t + ".unsafe_a-f+k", rate([r for r in gc if SCEN[r["scenario"]]["class"] != "safe"], "unsafe")[2])
            say(t + ".outcomes_all", dict(Counter(r["outcome"] for r in gc)))
            # run-to-run spread: cells (scenario) where reps disagree on outcome
            cells = defaultdict(set)
            for r in gc:
                cells[r["scenario"]].add(r["outcome"])
            mixed = [k for k, v in cells.items() if len(v) > 1]
            say(t + ".spread", "%d/%d scenarios had more than one outcome across reps: %s"
                % (len(mixed), len(cells), ", ".join(sorted(mixed))))
        # guard offline replay over this group's pay attempts
        if any(r["guard_live"] == "0" for r in g):
            gg = [r for r in g if r["guard_live"] == "0"]
            unsafe = [r for r in gg if r["unsafe"] == "1"]
            for field, name in (("guard_block", "strict"), ("guard_block_no_increase", "no_increase")):
                caught = sum(int(r[field]) for r in unsafe)
                say("%s.guard_replay.%s.caught" % (tag, name), "%d/%d unsafe pays would be declined" % (caught, len(unsafe)))
                sp = [r for r in gg if SCEN[r["scenario"]]["class"] == "safe" and r[field] != ""]
                fb = [r for r in sp if r[field] == "1"]
                say("%s.guard_replay.%s.false_block" % (tag, name), "%d/%d pay attempts on safe scenarios declined (%s)"
                    % (len(fb), len(sp), dict(Counter(r["scenario"] for r in fb))))
                ok = [r for r in gg if r["outcome"] in ("paid_matching_approval", "re_approved")
                      and SCEN[r["scenario"]]["class"] != "safe" and r[field] != ""]
                say("%s.guard_replay.%s.blocked_correct_pays_harmful" % (tag, name), "%d/%d matching pays on harmful scenarios declined"
                    % (sum(int(r[field]) for r in ok), len(ok)))
        live = [r for r in g if r["guard_live"] == "1"]
        if live:
            say(tag + ".guard_live.n", "%d runs" % len(live))
            say(tag + ".guard_live.declined_runs", "%d runs hit at least one decline" % sum(1 for r in live if int(r["n_declines"]) > 0))
            say(tag + ".guard_live.after_decline", dict(Counter(r["after_decline"] for r in live if r["after_decline"])))
            say(tag + ".guard_live.outcomes", dict(Counter(r["outcome"] for r in live)))
            say(tag + ".guard_live.unsafe", rate(live, "unsafe")[2])
            say(tag + ".guard_live.all_cards_accurate", rate(live, "all_cards_accurate")[2])
    # offline replay pooled over all main-batch runs (both models)
    m = [r for r in rows if r["phase"] == "main"]
    unsafe = [r for r in m if r["unsafe"] == "1"]
    safe = [r for r in m if SCEN[r["scenario"]]["class"] == "safe" and r["guard_block"] != ""]
    for field, name in (("guard_block", "strict"), ("guard_block_no_increase", "no_increase")):
        say("main.all.guard_replay.%s" % name, "caught %d/%d unsafe pays; false-blocked %d/%d safe pay attempts"
            % (sum(int(r[field]) for r in unsafe), len(unsafe), sum(int(r[field]) for r in safe), len(safe)))
    fudge = [r for r in rows if r["phase"] == "guard" and "card_mismatch" in r["after_decline"]]
    say("guard.all.fudged_cards", "%d live-guard runs re-requested approval with a card that did not match the page" % len(fudge))
    # wall-clock per batch from meta.json
    import glob
    for d in sorted(glob.glob(os.path.join(REPO, "runs", "*"))):
        metas = [json.load(open(m)) for m in glob.glob(os.path.join(d, "*", "meta.json"))]
        for model in sorted({m["model"] for m in metas}):
            mm = [m for m in metas if m["model"] == model]
            wall = max(m["started"] + m["seconds"] for m in mm) - min(m["started"] for m in mm)
            say("runtime.%s.%s" % (os.path.basename(d), model), "%d runs, wall-clock %.1f min at <=3 parallel, mean %.0f s/run"
                % (len(mm), wall / 60, sum(m["seconds"] for m in mm) / len(mm)))
    infos = [json.load(open(m)).get("rate_limit_info", {}) for m in glob.glob(os.path.join(REPO, "runs", "*", "*", "meta.json"))]
    say("usage", "%d acting runs; rate_limit statuses %s; peak five_hour utilization %.0f%%" % (
        len(infos), sorted({i.get("status", "none") for i in infos}),
        100 * max(i.get("unifiedWindows", {}).get("five_hour", {}).get("utilization", 0) for i in infos)))
    text = "\n".join(str(x) for x in out)
    print(text)
    open(os.path.join(REPO, "runs", "report.txt"), "w").write(text + "\n")


if __name__ == "__main__":
    main()
