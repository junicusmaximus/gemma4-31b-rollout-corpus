#!/usr/bin/env python3
"""Payload audit of version 3.2: what do the placeholders of redacted traces reveal by themselves?

Reads every redacted trace (all strings, keys and values) and checks every placeholder of the form U+27E6 RDX4:CODE U+27E7:
  * the CODE must have exactly one of the forms t:TASKID:F:J:L:H[:DIFFS] and og:FILE:J:L:H[:DIFFS] and P<n> and L and R;
  * every DIFFS item must be Q=w<percent encoded raw> or Q=<letter> with the letter in e E u U;
  * a raw (w item) is percent decoded and then its JSON style escapes are undone to the fixpoint; every resulting character must be
    whitespace. Any other character is a failure.
Fails (exit 1) on any failure. Reports counts and the positions of failures (trace, location, item number) and never the text.
Usage: python3 audit_payload_v32.py --traces DIR [--traces DIR2 ...] --out report.json
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from urllib.parse import unquote

import audit_corpus as A
import redact_traces_v32 as V

PH = re.compile(V.OPEN + V.TAG + r":([^" + V.CLOSE + r"]*)" + V.CLOSE)
ANY_TAG = re.compile(V.OPEN + r"(RDX[0-9]*):")
SPAN = re.compile(r"(?:t:[^:]+:(?:ps|ht|pa|tp)|og:[^:]+):[0-9]+:[0-9]+:[0-9a-f]{6}(?::(.*))?$", re.S)
ITEM = re.compile(r"[0-9]+=(?:w(.*)|[eEuU])$", re.S)


def check_code(code):
    """Returns (kind, number of payload items, failures) for one placeholder code."""
    if code in ("L", "R") or re.fullmatch(r"P[0-9]+", code):
        return "plain", 0, []
    m = SPAN.fullmatch(code)
    if not m:
        return "malformed", 0, ["the code has no known form"]
    diffs = m.group(1)
    if not diffs:
        return "span", 0, []
    fails, n = [], 0
    for item in diffs.split(";"):
        n += 1
        im = ITEM.fullmatch(item)
        if not im:
            fails.append("item %d has no known form" % n)
        elif im.group(1) is not None:
            if not V.whitespace_only(unquote(im.group(1))):
                fails.append("item %d holds a character that is not whitespace" % n)
    return "span", n, fails


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--traces", action="append", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    counts, failures = Counter(), []
    files = []
    for d in a.traces:
        files += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".json")]
    for p in files:
        with open(p, "rb") as fh:
            obj = json.loads(fh.read().decode("utf-8"))
        name = os.path.basename(os.path.dirname(p)) + "/" + os.path.basename(p)
        counts["traces"] += 1
        for loc, s in A.strings_of(obj):
            for m in PH.finditer(s):
                kind, n, fails = check_code(m.group(1))
                counts["placeholders"] += 1
                counts[kind] += 1
                if n:
                    counts["span placeholders with a payload"] += 1
                    counts["payload items"] += n
                for f in fails:
                    counts["failures"] += 1
                    failures.append({"trace": name, "location": loc, "problem": f})
            for m in ANY_TAG.finditer(s):
                if m.group(1) != V.TAG:
                    counts["failures"] += 1
                    failures.append({"trace": name, "location": loc, "problem": "a placeholder with another tag"})
    out = {"counts": dict(counts), "failures": failures}
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("payload audit:", json.dumps(dict(counts), sort_keys=True), "| failures", len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
