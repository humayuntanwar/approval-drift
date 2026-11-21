#!/usr/bin/env python3
"""Print a readable transcript of one run: agent text, shop commands and outputs.

  python3 scripts/show_run.py runs/main/<run_id> [--full]
"""
import gzip
import json
import sys


def main(run_dir, full=False):
    cut = None if full else 700
    for line in gzip.open(run_dir.rstrip("/") + "/transcript.jsonl.gz", "rt"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e["type"] == "assistant":
            for c in e["message"]["content"]:
                if c["type"] == "text":
                    print("AGENT:", c["text"][:cut])
                elif c["type"] == "tool_use":
                    print("$", c["input"].get("command", c["input"]))
        elif e["type"] == "user":
            for c in e["message"]["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    out = c["content"] if isinstance(c["content"], str) else json.dumps(c["content"])
                    print("   " + out[:cut].replace("\n", "\n   "))
        elif e["type"] == "result":
            print("RESULT:", str(e.get("result", ""))[:cut], "| turns", e.get("num_turns"))


if __name__ == "__main__":
    main(sys.argv[1], "--full" in sys.argv)
