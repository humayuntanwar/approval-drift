#!/usr/bin/env python3
"""Run acting-agent sessions (claude -p) against the sandbox store.

Each run: fresh empty working dir outside the repo, `shop` on PATH, state in
/tmp/approval-drift-runs/<run_id>/, only Bash(shop:*) allowed. The stream-json
transcript, store events and final state are copied into runs/<phase>/<run_id>/.

  python3 scripts/run_batch.py --phase main --model sonnet --conditions P0 P1 --reps 5
"""
import argparse
import gzip
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(REPO, "scenarios.json")))
RUN_ROOT = "/tmp/approval-drift-runs"
WORK_ROOT = "/tmp/approval-drift-work"
BIN = "/tmp/approval-drift-bin"
STOP = threading.Event()
DENY = "Read Write Edit MultiEdit Glob Grep LS WebFetch WebSearch Task Agent NotebookEdit TodoWrite"


def make_bin():
    os.makedirs(BIN, exist_ok=True)
    p = os.path.join(BIN, "shop")
    with open(p, "w") as f:
        f.write('#!/bin/sh\nexec python3 -I %s "$@"\n' % os.path.join(REPO, "shop", "shop.py"))
    os.chmod(p, 0o755)


def rate_limited(line, usage):
    try:
        ev = json.loads(line)
    except ValueError:
        return False
    if ev.get("type") == "rate_limit_event":
        info = ev.get("rate_limit_info", ev)
        usage.update(info)
        return str(info.get("status", "")).lower() == "rejected"
    if ev.get("type") == "result" and ev.get("is_error"):
        txt = json.dumps(ev).lower()
        return "usage limit" in txt or "limit reached" in txt or "rate limit" in txt
    return False


def run_one(spec, phase, model, timeout):
    run_id = spec["run_id"]
    out_dir = os.path.join(REPO, "runs", phase, run_id)
    if os.path.exists(os.path.join(out_dir, "meta.json")):
        return "skip"
    if STOP.is_set():
        return "stopped"
    state = os.path.join(RUN_ROOT, run_id)
    work = os.path.join(WORK_ROOT, run_id)
    for d in (state, work):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    env = dict(os.environ, SHOP_STATE=state, PATH=BIN + ":" + os.environ["PATH"])
    init = [sys.executable, os.path.join(REPO, "shop", "shop.py"), "__init", spec["scenario"]]
    subprocess.run(init + (["--guard"] if spec["guard"] else []), env=env, check=True)
    scen = next(s for s in CFG["scenarios"] if s["id"] == spec["scenario"])
    cmd = ["claude", "-p", scen["request"], "--model", model, "--safe-mode", "--strict-mcp-config",
           "--tools", "Bash", "--allowedTools", "Bash(shop:*)", "--disallowedTools", DENY,
           "--permission-mode", "dontAsk", "--disable-slash-commands", "--no-session-persistence",
           "--append-system-prompt", CFG["conditions"][spec["condition"]],
           "--output-format", "stream-json", "--verbose"]
    t0 = time.time()
    status, limited, usage = "ok", False, {}
    tpath = os.path.join(state, "transcript.jsonl")
    with open(tpath, "w") as tf:
        proc = subprocess.Popen(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True)
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        for line in proc.stdout:
            tf.write(line)
            if rate_limited(line, usage):
                limited = True
        proc.wait()
        timer.cancel()
    if time.time() - t0 >= timeout - 1:
        status = "timeout"
    if limited:
        status = "rate_limited"
        STOP.set()
    os.makedirs(out_dir, exist_ok=True)
    with open(tpath, "rb") as src, gzip.open(os.path.join(out_dir, "transcript.jsonl.gz"), "wb") as dst:
        shutil.copyfileobj(src, dst)
    shutil.copy(os.path.join(state, "events.jsonl"), out_dir)
    shutil.copy(os.path.join(state, "state.json"), out_dir)
    meta = dict(spec, phase=phase, model=model, status=status, returncode=proc.returncode,
                seconds=round(time.time() - t0, 1), started=t0,
                rate_limit_info=usage)
    json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)
    shutil.rmtree(work, ignore_errors=True)
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True)
    ap.add_argument("--model", default=CFG["run_plan"]["model_primary"])
    ap.add_argument("--conditions", nargs="+", default=["P0", "P1"])
    ap.add_argument("--scenarios", nargs="+", default=[s["id"] for s in CFG["scenarios"]])
    ap.add_argument("--reps", type=int, default=CFG["run_plan"]["reps_main"])
    ap.add_argument("--guard", action="store_true")
    ap.add_argument("--parallel", type=int, default=CFG["run_plan"]["parallel"])
    ap.add_argument("--timeout", type=int, default=CFG["run_plan"]["timeout_s"])
    ap.add_argument("--seed", type=int, default=CFG["run_plan"]["seed"])
    a = ap.parse_args()
    if a.model == "opus" or "opus" in a.model:
        sys.exit("opus is not used for acting runs")
    make_bin()
    specs = []
    for sc in a.scenarios:
        for c in a.conditions:
            for r in range(1, a.reps + 1):
                rid = "%s-%s-%s%s-%s-r%d" % (a.phase, a.model, c, "G" if a.guard else "", sc.split("_")[0], r)
                specs.append({"run_id": rid, "scenario": sc, "condition": c, "rep": r, "guard": a.guard})
    random.Random(a.seed).shuffle(specs)
    print("planned %d runs" % len(specs), flush=True)
    done = [0]

    def job(spec):
        if STOP.is_set():
            return
        st = run_one(spec, a.phase, a.model, a.timeout)
        done[0] += 1
        print("[%d/%d] %s %s %s" % (done[0], len(specs), time.strftime("%H:%M:%S"), spec["run_id"], st), flush=True)
        if st == "rate_limited":
            print("USAGE LIMIT HIT - no new runs will be launched", flush=True)

    with ThreadPoolExecutor(a.parallel) as ex:
        list(ex.map(job, specs))
    print("finished; stop flag=%s" % STOP.is_set(), flush=True)


if __name__ == "__main__":
    main()
