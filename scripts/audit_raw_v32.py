#!/usr/bin/env python3
"""Second, independent audit path of version 3.2: the RAW view of the stored file text. Versions 1 to 3.1 stay unchanged.

Reads the redacted trace files as text (JSON escapes such as a backslash and n stay as they are), builds the views of depth 0 to the
fixpoint of the unescape pass over the WHOLE file text, and applies the rule of redact_traces_v32.py (thresholds 40 and 20 for the own
statement and hints; path rule; own snapshot exemption). The raw view sees JSON escape characters inside spans, so it finds rows that the
decoded audit does not. Every remaining row is classified automatically by decoding its region (widened to whole escapes and with
120 characters of context) to the fixpoint and looking at the decoded text again; only decoded runs that overlap the row count:
  artifact: no 40 character run in the decoded text     (for a row of the own statement: no 20 character run)
  artifact: decoded runs are in the own snapshot        (never for the own statement or hints)
  artifact: decoded text touches a path                 (never for the own statement or hints)
  NOT artifact                                          none of the above (listed in the summary)
Usage: python3 audit_raw_v32.py --tasks tasks.jsonl --traces DIR [--traces DIR2 ...] --snapshots DIR --organiser DIR --out-tsv rows.tsv --out-json summary.json
"""
import argparse
import json
import os
import sys
from collections import Counter

import audit_corpus as A
import audit_raw_v3 as AR3
import redact_traces_v3 as V3
import redact_traces_v32 as V

CLASSES = AR3.CLASSES


def decode_fixpoint(text):
    return V.views(text)[-1]


def classify(v, a, b, snap, paths, corpus, tid, idx, kind):
    a, b = AR3.widen(v, a, b)
    a0, b0 = AR3.widen(v, max(0, a - AR3.CONTEXT), min(len(v), b + AR3.CONTEXT))
    c0 = len(V.collapse(decode_fixpoint(v[a0:a])))
    mid = V.collapse(decode_fixpoint(v[a:b])).strip()
    need = V.OWN_MIN if kind == "own" else V.MIN_SPAN
    if len(mid) < need:
        return CLASSES[0]
    c1 = c0 + len(mid)
    ctx = V.collapse(decode_fixpoint(v[a0:b0]))
    runs = [(k, ctx[x:y]) for k, _, x, y in V.find_runs(ctx, corpus, paths, tid, idx) if x < c1 and y > c0]
    if any(k == "own" for k, _ in runs):
        return CLASSES[3]
    runs = [r for k, r in runs if k == "std"]
    if kind == "own" and not runs:
        return CLASSES[0]
    if not runs:
        windows = any(mid[i:i + V.MIN_SPAN] in corpus.index for i in range(0, len(mid) - V.MIN_SPAN + 1))
        return CLASSES[2] if windows else CLASSES[0]
    if snap is not None and all(r in snap for r in runs):
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
    corpus = V.Corpus(tasks, a.organiser)
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
        idx = V.own20_index(corpus, tid)
        in_snap = {}
        with open(p, "rb") as fh:
            raw_text = fh.read().decode("utf-8")
        rel = os.path.basename(os.path.dirname(p)) + "/" + os.path.basename(p)
        for depth, text in enumerate(V.views(raw_text)):
            v = V.collapse(text)
            for kind, src, x, y in V.find_runs(v, corpus, paths, tid, idx):
                span = v[x:y]
                if kind == "std" and snap is not None:
                    if span not in in_snap:
                        in_snap[span] = span in snap
                    if in_snap[span]:
                        exempt += 1
                        continue
                who = "organiser" if src.task_id is None else ("own" if src.task_id == tid else "other")
                rows.append({"file": rel, "task": tid, "who": who, "source": src.label if src.task_id is None else "%s:%s" % (src.task_id, src.code),
                             "view": "depth %d" % depth, "length": y - x, "first60": span[:60], "class": classify(v, x, y, snap, paths, corpus, tid, idx, kind)})
    with open(a.out_tsv, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("file\ttask\twho\tsource\tview\tlength\tclass\tfirst60\n")
        for r in rows:
            fh.write("\t".join(str(r[k]).replace("\t", " ").replace("\n", " ") for k in ("file", "task", "who", "source", "view", "length", "class", "first60")) + "\n")
    summary = {"files": files, "exempt_runs": exempt, "remaining_rows": len(rows), "by_class": dict(Counter(r["class"] for r in rows)),
               "by_who": dict(Counter(r["who"] for r in rows)), "by_class_and_who": dict(Counter("%s | %s" % (r["who"], r["class"]) for r in rows)),
               "by_view": dict(Counter(r["view"] for r in rows)),
               "not_artifact": [{k: r[k] for k in ("file", "task", "who", "source", "view", "length", "first60")} for r in rows if r["class"] == CLASSES[3]]}
    with open(a.out_json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in summary.items() if k != "not_artifact"}, sort_keys=True), "| not artifact rows:", len(summary["not_artifact"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
