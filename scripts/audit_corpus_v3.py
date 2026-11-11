#!/usr/bin/env python3
"""Audit version 3 of redacted traces: cross task protection, decoded view. Versions 1 and 2 stay unchanged.

Rule R1: no run of windows of 40 characters (decoded strings, whitespace normalised, plain view and JSON unescaped view) shared with
the problem statement or hints or gold patch or test patch of ANY task of the task file or with a text file of the organiser's
sample submission. Windows that touch a path of the own task's snapshot tree are ignored (see redact_traces_v3.py). A run (edge spaces
trimmed) is exempt when it occurs in the file contents of the own task's snapshot. Nothing else is exempt.
The runs are formed per protected source here (the redactor forms them over all sources together).
R2: secret shaped strings, e-mail addresses not of an example domain, "/home/" and the words of a private list: 0 hits.
R3: file types and sizes of a tree.
Usage: python3 audit_corpus_v3.py --tasks tasks.jsonl --traces DIR [--traces DIR2 ...] --snapshots DIR --organiser DIR [--tree DIR] --report r.json [--forbidden F]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

import audit_corpus as A
import redact_traces_v3 as V3

MIN_SPAN = 40


def runs_per_source(v, corpus, paths):
    """Yields (source, start, end) of the maximal runs of valid windows per protected source, edge spaces trimmed (40+ characters)."""
    pos = defaultdict(list)
    for i in range(0, len(v) - MIN_SPAN + 1):
        val = corpus.index.get(v[i:i + MIN_SPAN])
        if val is None:
            continue
        for x in ((val,) if isinstance(val, int) else val):
            pos[x >> V3.SHIFT].append(i)
    if not pos:
        return
    pre = V3.path_cover(v, paths)
    for sid, ps in pos.items():
        ps = [i for i in ps if pre[i + MIN_SPAN] - pre[i] == 0]
        start = last = None
        runs = []
        for i in ps:
            if start is not None and i == last + 1:
                last = i
                continue
            if start is not None:
                runs.append((start, last + MIN_SPAN))
            start = last = i
        if start is not None:
            runs.append((start, last + MIN_SPAN))
        for a, b in runs:
            while a < b and v[a] == " ":
                a += 1
            while b > a and v[b - 1] == " ":
                b -= 1
            if b - a >= MIN_SPAN:
                yield corpus.sources[sid], a, b


def audit_trace(path, task_id, corpus, snapshots, report):
    name = os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
    with open(path, "rb") as fh:
        obj = json.loads(fh.read().decode("utf-8"))
    snap, paths = snapshots.get(task_id) if snapshots else (None, None)
    r1 = report["r1"]
    in_snap = {}
    for loc, s in A.strings_of(obj):
        if len(s) >= MIN_SPAN:
            for view_name, text in (("plain", s), ("unescaped", A.unescape(s))):
                if view_name == "unescaped" and text == s:
                    continue
                v = A.norm(text)
                for src, a, b in runs_per_source(v, corpus, paths):
                    span = v[a:b]
                    if snap is None:
                        status = "unchecked"
                    else:
                        if span not in in_snap:
                            in_snap[span] = span in snap
                        status = "exempt" if in_snap[span] else "hit"
                    who = "organiser" if src.task_id is None else ("own" if src.task_id == task_id else "other")
                    field = "og" if src.task_id is None else src.code
                    r1[status] += 1
                    r1["by_field"]["%s:%s:%s" % (who, field, status)] += 1
                    if status != "exempt":
                        r1["list"].append({"trace": name, "task": task_id, "source_task": src.task_id, "source_field": field if src.task_id else src.label,
                                           "location": loc, "view": view_name, "length": b - a, "first60": span[:60], "status": status})
        for rule, pat in A.R2_ACTIVE.items():
            for text in {s, A.unescape(s)}:
                for m in pat.finditer(text):
                    kind = rule
                    if rule == "email" and A.EXAMPLE_DOMAIN.search(m.group(0)):
                        kind = "email:example-domain"
                    r2 = report["r2"][kind]
                    r2["hits"] += 1
                    if len(r2["list"]) < 200:
                        r2["list"].append({"trace": name, "location": loc, "first60": text[max(0, m.start() - 30):m.end() + 30][:60].replace("\n", "\\n")})
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
    corpus = V3.Corpus(tasks, a.organiser)
    snapshots = V3.SnapshotStore(a.snapshots) if a.snapshots else None
    report = {"traces": 0, "sources": len(corpus.sources), "r1": {"hit": 0, "exempt": 0, "unchecked": 0, "by_field": Counter(), "list": []},
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
    report["r2"] = {k: v for k, v in report["r2"].items()}
    with open(a.report, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=1, sort_keys=True)
    r1 = report["r1"]
    r2_bad = sum(v["hits"] for k, v in report["r2"].items() if k != "email:example-domain")
    r2_example = report["r2"].get("email:example-domain", {}).get("hits", 0)
    print("traces %d | sources %d | R1 hits %d exempt %d unchecked %d | R2 hits %d (plus %d example-domain addresses, tolerated) | unknown task files %d" %
          (report["traces"], report["sources"], r1["hit"], r1["exempt"], r1["unchecked"], r2_bad, r2_example, len(report["unknown_task"])))
    if report["r3"]:
        print("R3 files %d bytes %d over 50 MB: %d" % (report["r3"]["files"], report["r3"]["bytes"], len(report["r3"]["over_50MB"])))
    bad = r1["hit"] + r1["unchecked"] + r2_bad + len(report["unknown_task"]) + (len(report["r3"]["over_50MB"]) if report["r3"] else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
