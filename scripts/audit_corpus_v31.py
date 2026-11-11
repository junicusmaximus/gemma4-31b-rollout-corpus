#!/usr/bin/env python3
"""Audit version 3.1 of redacted traces. Versions 1 to 3 stay unchanged; this file imports version 3.

Rule R1 as in version 3 (threshold 40; runs per protected source over all tasks and the organiser files; exemptions: own snapshot
contents and own snapshot paths) with one change: for the problem statement and the hints of the trace's OWN task the threshold is
20 characters and there is NO exemption. A run of 20 or more characters shared with them is a hit even if the text is in the snapshot
or is a path. The 40 character pass skips the own statement and hints (the 20 character pass covers them).
R2 and R3 as in version 3.
Usage: python3 audit_corpus_v31.py --tasks tasks.jsonl --traces DIR [--traces DIR2 ...] --snapshots DIR --organiser DIR [--tree DIR] --report r.json [--forbidden F]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

import audit_corpus as A
import audit_corpus_v3 as AU
import redact_traces_v3 as V3

OWN_MIN = 20
OWN_CODES = ("ps", "ht")


def own20_index(corpus, tid):
    idx = {}
    for src in corpus.sources:
        if src.task_id == tid and src.code in OWN_CODES:
            for j in range(0, len(src.nf) - OWN_MIN + 1):
                idx.setdefault(src.nf[j:j + OWN_MIN], src)
    return idx


def own_runs(v, idx):
    """Runs of 20 character windows of the own statement or hints; yields (source, start, end)."""
    pos = defaultdict(list)
    for i in range(0, len(v) - OWN_MIN + 1):
        src = idx.get(v[i:i + OWN_MIN])
        if src is not None:
            pos[src.code].append((i, src))
    for code, items in pos.items():
        start = last = None
        runs = []
        for i, src in items:
            if start is not None and i == last + 1:
                last = i
                continue
            if start is not None:
                runs.append((start, last + OWN_MIN, src))
            start = last = i
        if start is not None:
            runs.append((start, last + OWN_MIN, items[-1][1]))
        for a, b, src in runs:
            while a < b and v[a] == " ":
                a += 1
            while b > a and v[b - 1] == " ":
                b -= 1
            if b - a >= OWN_MIN:
                yield src, a, b


def find_runs(v, corpus, paths, tid, idx):
    """All runs of the text v: ('own', src, a, b) for the own statement and hints (20 characters) and ('std', src, a, b) for the rest."""
    for src, a, b in own_runs(v, idx):
        yield "own", src, a, b
    for src, a, b in AU.runs_per_source(v, corpus, paths):
        if src.task_id == tid and src.code in OWN_CODES:
            continue
        yield "std", src, a, b


def audit_trace(path, task_id, corpus, snapshots, report):
    name = os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
    with open(path, "rb") as fh:
        obj = json.loads(fh.read().decode("utf-8"))
    snap, paths = snapshots.get(task_id) if snapshots else (None, None)
    idx = own20_index(corpus, task_id)
    r1 = report["r1"]
    in_snap = {}
    for loc, s in A.strings_of(obj):
        if len(s) >= OWN_MIN:
            for view_name, text in (("plain", s), ("unescaped", A.unescape(s))):
                if view_name == "unescaped" and text == s:
                    continue
                v = A.norm(text)
                for kind, src, a, b in find_runs(v, corpus, paths, task_id, idx):
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
