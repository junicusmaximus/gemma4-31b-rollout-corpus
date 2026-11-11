#!/usr/bin/env python3
"""Audit version 3.2 of redacted traces (decoded view to the fixpoint). Versions 1 to 3.1 stay unchanged.

Rule R1 (the rule text of redact_traces_v32.py): for every string of a trace, in the views depth 0 (as stored) and every unescape pass up
to the fixpoint (at most 6 passes), the whitespace collapsed text is searched for runs of windows that occur in a protected source of any
task or in an organiser text file. A window is 40 characters (20 for the problem statement and hints of the trace's own task). A window
wholly inside the path part of a token (a snapshot path of 12 or more characters) is ignored. Runs are measured after their end spaces
are dropped. A run of 40 or more characters (20 for the own statement and hints) is a hit; it is exempt only when it occurs in the file
contents of the own snapshot, and the own statement and hints have no exemption.
R2: secret shaped strings, e-mail addresses not of an example domain, "/home/" and the words of a private list: 0 hits (all views).
R3: file types and sizes of a tree.
Usage: python3 audit_corpus_v32.py --tasks tasks.jsonl --traces DIR [--traces DIR2 ...] --snapshots DIR --organiser DIR [--tree DIR] --report r.json [--forbidden F]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

import audit_corpus as A
import redact_traces_v32 as V
import redact_traces_v3 as V3


def audit_trace(path, task_id, corpus, snapshots, report):
    name = os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
    with open(path, "rb") as fh:
        obj = json.loads(fh.read().decode("utf-8"))
    snap, paths = snapshots.get(task_id) if snapshots else (None, None)
    idx = V.own20_index(corpus, task_id)
    r1 = report["r1"]
    in_snap = {}
    for loc, s in A.strings_of(obj):
        if len(s) >= V.OWN_MIN:
            for depth, text in enumerate(V.views(s)):
                v = V.collapse(text)
                for kind, src, a, b in V.find_runs(v, corpus, paths, task_id, idx):
                    span = v[a:b]
                    if kind == "own":
                        status = "hit"
                    elif snap is None:
                        status = "unchecked"
                    else:
                        if span not in in_snap:
                            in_snap[span] = span in snap
                        status = "exempt" if in_snap[span] else "hit"
                    who = "organiser" if src.task_id is None else ("own" if src.task_id == task_id else "other")
                    field = "og" if src.task_id is None else src.code
                    r1[status] += 1
                    r1["by_field"]["%s:%s:%s" % (who, field, status)] += 1
                    r1["by_depth"]["depth %d:%s" % (depth, status)] += 1
                    if status != "exempt":
                        r1["list"].append({"trace": name, "task": task_id, "source_task": src.task_id, "source_field": field if src.task_id else src.label,
                                           "location": loc, "depth": depth, "start": a, "end": b, "length": b - a, "first60": span[:60], "status": status})
        found = defaultdict(set)
        for text in V.views(s):
            for rule, pat in A.R2_ACTIVE.items():
                for m in pat.finditer(text):
                    found[rule].add(m.group(0))
        for rule, matches in found.items():
            for hit in matches:
                kind = rule
                if rule == "email" and A.EXAMPLE_DOMAIN.search(hit):
                    kind = "email:example-domain"
                r2 = report["r2"][kind]
                r2["hits"] += 1
                if len(r2["list"]) < 200:
                    r2["list"].append({"trace": name, "location": loc})
    report["traces"] += 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--traces", action="append", default=[])
    ap.add_argument("--snapshots")
    ap.add_argument("--organiser")
    ap.add_argument("--tree")
    ap.add_argument("--report", required=True)
    ap.add_argument("--forbidden")
    a = ap.parse_args(argv)
    A.R2_ACTIVE.clear()
    A.R2_ACTIVE.update(A.R2_PATTERNS)
    if a.forbidden:
        with open(a.forbidden, encoding="utf-8") as fh:
            for i, word in enumerate(json.load(fh), 1):
                A.R2_ACTIVE["forbidden word %d" % i] = re.compile(re.escape(word), re.I)
    tasks = V3.load_tasks(a.tasks)
    corpus = V.Corpus(tasks, a.organiser)
    snapshots = V3.SnapshotStore(a.snapshots) if a.snapshots else None
    report = {"traces": 0, "sources": len(corpus.sources), "windows": len(corpus.index),
              "r1": {"hit": 0, "exempt": 0, "unchecked": 0, "by_field": Counter(), "by_depth": Counter(), "list": []},
              "r2": defaultdict(lambda: {"hits": 0, "list": []}), "unknown_task": [], "r3": None}
    files = []
    for d in a.traces:
        files += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".json")]
    files.sort(key=lambda p: (A.task_id_of(os.path.basename(p)) or "", p))
    for p in files:
        tid = A.task_id_of(os.path.basename(p))
        if tid not in tasks:
            report["unknown_task"].append(os.path.basename(p)); continue
        audit_trace(p, tid, corpus, snapshots, report)
    if a.tree:
        A.audit_tree(a.tree, report)
    report["r1"]["by_field"] = dict(report["r1"]["by_field"])
    report["r1"]["by_depth"] = dict(report["r1"]["by_depth"])
    report["r2"] = {k: v for k, v in report["r2"].items()}
    with open(a.report, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=1, sort_keys=True)
    r1 = report["r1"]
    r2_bad = sum(v["hits"] for k, v in report["r2"].items() if k != "email:example-domain")
    r2_example = report["r2"].get("email:example-domain", {}).get("hits", 0)
    print("traces %d | sources %d | windows %d | R1 hits %d exempt %d unchecked %d | R2 hits %d (plus %d example-domain addresses, tolerated) | unknown task files %d" %
          (report["traces"], report["sources"], report["windows"], r1["hit"], r1["exempt"], r1["unchecked"], r2_bad, r2_example, len(report["unknown_task"])))
    if report["r3"]:
        print("R3 files %d bytes %d over 50 MB: %d" % (report["r3"]["files"], report["r3"]["bytes"], len(report["r3"]["over_50MB"])))
    bad = r1["hit"] + r1["unchecked"] + r2_bad + len(report["unknown_task"]) + (len(report["r3"]["over_50MB"]) if report["r3"] else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
