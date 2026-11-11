#!/usr/bin/env python3
"""Second, independent audit path of version 3: the RAW view. Versions 1 and 2 stay unchanged.

Reads the redacted trace files as text (JSON escapes such as \\n stay as they are; a second view decodes them over the whole file) and
compares them with all protected sources of the task file and the organiser's files, with the exemptions of version 3 (own snapshot
contents, paths of the own snapshot tree). The raw view sees JSON escape characters inside spans, so it finds rows that the decoded
audit does not. Every remaining row is classified automatically:
  artifact: no 40 character run in the decoded text    the row's region, widened to whole JSON escapes and decoded, has no run
  artifact: decoded runs are in the own snapshot        every run of the decoded region occurs in the own snapshot
  artifact: decoded text touches a path                 windows of the decoded region exist but all touch snapshot paths
  NOT artifact                                          none of the above (listed in the summary)
Usage: python3 audit_raw_v3.py --tasks tasks.jsonl --traces DIR [--traces DIR2 ...] --snapshots DIR --organiser DIR --out-tsv rows.tsv --out-json summary.json
"""
import argparse
import json
import os
import sys
from collections import Counter

import audit_corpus as A
import audit_corpus_v3 as AU
import redact_traces_v3 as V3

CLASSES = ("artifact: no 40 character run in the decoded text", "artifact: decoded runs are in the own snapshot", "artifact: decoded text touches a path", "NOT artifact")
ESCAPE_LETTERS = "ntr\"\\u/"      # the characters that follow a backslash in a JSON escape


CONTEXT = 120      # characters of raw context on each side, so that a path token is seen whole


def widen(v, a, b):
    if a > 0 and v[a - 1] == "\\" and v[a] in ESCAPE_LETTERS:
        a -= 1
    if b < len(v) and v[b - 1] == "\\" and v[b] in ESCAPE_LETTERS:
        b += 1
    return a, b


def classify(v, a, b, snap, paths, corpus):
    """Decode the region of the raw view that holds the row (widened to whole JSON escapes, with context) and look at the decoded
    text again. Only decoded runs that overlap the row's own region count."""
    a, b = widen(v, a, b)
    a0, b0 = widen(v, max(0, a - CONTEXT), min(len(v), b + CONTEXT))
    c0 = len(A.norm(A.unescape(v[a0:a])))
    mid = A.norm(A.unescape(v[a:b])).strip()
    if len(mid) < 40:
        return CLASSES[0]
    c1 = c0 + len(mid)
    ctx = A.norm(A.unescape(v[a0:b0]))
    runs = [(ctx[x:y], x, y) for _, x, y in AU.runs_per_source(ctx, corpus, paths) if x < c1 and y > c0]
    if not runs:
        windows = any(mid[i:i + 40] in corpus.index for i in range(0, len(mid) - 39))
        return CLASSES[2] if windows else CLASSES[0]
    if snap is not None and all(r in snap for r, _, _ in runs):
        return CLASSES[1]
    return CLASSES[3]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--traces", action="append", required=True)
    ap.add_argument("--snapshots", required=True)
    ap.add_argument("--organiser")
    ap.add_argument("--out-tsv", required=True)
    ap.add_argument("--out-json", required=True)
    a = ap.parse_args(argv)
    tasks = V3.load_tasks(a.tasks)
    corpus = V3.Corpus(tasks, a.organiser)
    snapshots = V3.SnapshotStore(a.snapshots)
    rows, exempt, files = [], 0, 0
    paths_list = []
    for d in a.traces:
        paths_list += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".json")]
    paths_list.sort(key=lambda p: (A.task_id_of(os.path.basename(p)) or "", p))
    for p in paths_list:
        tid = A.task_id_of(os.path.basename(p))
        if tid not in tasks:
            continue
        files += 1
        snap, paths = snapshots.get(tid)
        in_snap = {}
        with open(p, "rb") as fh:
            raw_text = fh.read().decode("utf-8")
        rel = os.path.basename(os.path.dirname(p)) + "/" + os.path.basename(p)
        for view_name, text in (("plain", raw_text), ("unescaped", A.unescape(raw_text))):
            if view_name == "unescaped" and text == raw_text:
                continue
            v = A.norm(text)
            for src, x, y in AU.runs_per_source(v, corpus, paths):
                span = v[x:y]
                if snap is not None:
                    if span not in in_snap:
                        in_snap[span] = span in snap
                    if in_snap[span]:
                        exempt += 1
                        continue
                who = "organiser" if src.task_id is None else ("own" if src.task_id == tid else "other")
                rows.append({"file": rel, "task": tid, "who": who, "source": src.label if src.task_id is None else "%s:%s" % (src.task_id, src.code),
                             "view": view_name, "length": y - x, "first60": span[:60], "class": classify(v, x, y, snap, paths, corpus)})
    with open(a.out_tsv, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("file\ttask\twho\tsource\tview\tlength\tclass\tfirst60\n")
        for r in rows:
            fh.write("\t".join(str(r[k]).replace("\t", " ").replace("\n", " ") for k in ("file", "task", "who", "source", "view", "length", "class", "first60")) + "\n")
    summary = {"files": files, "exempt_runs": exempt, "remaining_rows": len(rows), "by_class": dict(Counter(r["class"] for r in rows)),
               "by_who": dict(Counter(r["who"] for r in rows)), "by_class_and_who": dict(Counter("%s | %s" % (r["who"], r["class"]) for r in rows)),
               "not_artifact": [{k: r[k] for k in ("file", "task", "who", "source", "view", "length", "first60")} for r in rows if r["class"] == CLASSES[3]]}
    with open(a.out_json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in summary.items() if k != "not_artifact"}, sort_keys=True), "| not artifact rows:", len(summary["not_artifact"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
