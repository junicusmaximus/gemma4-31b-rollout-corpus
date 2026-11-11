#!/usr/bin/env python3
"""Audit version 2 of redacted traces (and a staging tree). Version 1 (audit_corpus.py) stays unchanged; this file imports its helpers.

Rules
  R1  For every trace: no span of 40 or more characters (decoded strings, whitespace normalised, plain and JSON-unescaped view)
      shared with the task's problem_statement, hints_text, patch (gold), test_patch, or with a text file of the organiser's
      sample submission. A span is exempt when it also occurs in the upstream repository snapshot of the task (not for organiser
      files). A hit with no snapshot to check is listed as unchecked.
  R2  Secret-shaped strings, e-mail addresses not of an example domain, "/home/" and every word of a private forbidden-words
      file: 0 hits. E-mail addresses of an example domain are counted and tolerated.
  R3  File types and sizes of a tree; no file over 50 MB.
Usage
  python3 audit_corpus_v2.py --tasks tasks.jsonl --traces DIR [--traces DIR2 ...] [--snapshots DIR] [--organiser DIR] [--tree DIR] --report report.json
Exit status 0 when there are no hits that need a decision, else 1.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

import audit_corpus as A
import redact_traces_v2 as V2

ORGANISER_PREFIX = "organiser:"


def audit_trace(path, task, org_sets, snaps, report):
    name = os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
    tid = task["instance_id"]
    with open(path, "rb") as fh:
        obj = json.loads(fh.read().decode("utf-8"))
    sources = [(f, A.grams(A.norm(task.get(f) or "")), True) for f in A.FIELDS] + [(f, g, False) for f, g in org_sets]
    snap = None
    r1 = report["r1"]
    for loc, s in A.strings_of(obj):
        if len(s) >= A.MIN_SPAN:
            for view_name, text in (("plain", s), ("unescaped", A.unescape(s))):
                if view_name == "unescaped" and text == s:
                    continue
                v = A.norm(text)
                for f, gs, can_exempt in sources:
                    if not gs:
                        continue
                    for a, b in A.shared_runs(v, gs):
                        span = v[a:b]
                        status = "hit"
                        if can_exempt:
                            if snap is None:
                                snap = snaps.text(tid) if snaps else None
                                snap = snap if snap is not None else False
                            status = "unchecked" if snap is False else ("exempt" if span in snap else "hit")
                        r1[status] += 1
                        r1["by_field"][f.split(":")[0] + ":" + status] += 1
                        if status != "exempt":
                            r1["list"].append({"trace": name, "task": tid, "field": f, "location": loc, "view": view_name, "length": b - a, "first60": span[:60], "status": status})
        for rule, pat in A.R2_ACTIVE.items():
            for text in {s, A.unescape(s)}:
                for m in pat.finditer(text):
                    if snap is None:
                        snap = snaps.text(tid) if snaps else None
                        snap = snap if snap is not None else False
                    ctx = text[max(0, m.start() - 30):m.end() + 30]
                    probe = m.group(0) if rule == "email" else A.norm(text[max(0, m.start() - 15):m.end() + 15])
                    upstream = bool(snap) and probe in snap
                    kind = rule
                    if rule == "email" and A.EXAMPLE_DOMAIN.search(m.group(0)):
                        kind = "email:example-domain"
                    r2 = report["r2"][kind]
                    r2["hits"] += 1
                    r2["upstream" if upstream else "not_upstream"] += 1
                    if len(r2["list"]) < 200:
                        r2["list"].append({"trace": name, "location": loc, "upstream": upstream, "first60": ctx[:60].replace("\n", "\\n")})
    report["traces"] += 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--traces", action="append", default=[])
    ap.add_argument("--snapshots")
    ap.add_argument("--organiser", help="folder with the organiser's sample submission files")
    ap.add_argument("--tree")
    ap.add_argument("--report", required=True)
    ap.add_argument("--forbidden", help="private JSON list of words that must not occur")
    a = ap.parse_args(argv)
    A.R2_ACTIVE.clear()
    A.R2_ACTIVE.update(A.R2_PATTERNS)
    if a.forbidden:
        with open(a.forbidden, encoding="utf-8") as fh:
            for i, word in enumerate(json.load(fh), 1):
                A.R2_ACTIVE["forbidden word %d" % i] = re.compile(re.escape(word), re.I)
    tasks = {}
    with open(a.tasks, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                t = json.loads(line); tasks[t["instance_id"]] = t
    org_sets = []
    if a.organiser:
        for s in V2.load_organiser(a.organiser, build_index=False):
            org_sets.append((ORGANISER_PREFIX + s.label, A.grams(s.nf)))
    snaps = A.Snapshots(a.snapshots) if a.snapshots else None
    report = {"traces": 0, "organiser_files": len(org_sets), "r1": {"hit": 0, "exempt": 0, "unchecked": 0, "by_field": Counter(), "list": []},
              "r2": defaultdict(lambda: {"hits": 0, "upstream": 0, "not_upstream": 0, "list": []}), "unknown_task": [], "r3": None}
    files = []
    for d in a.traces:
        files += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".json")]
    files.sort(key=lambda p: (A.task_id_of(os.path.basename(p)) or "", p))
    for p in files:
        tid = A.task_id_of(os.path.basename(p))
        if tid not in tasks:
            report["unknown_task"].append(os.path.basename(p)); continue
        audit_trace(p, tasks[tid], org_sets, snaps, report)
    if a.tree:
        A.audit_tree(a.tree, report)
    report["r1"]["by_field"] = dict(report["r1"]["by_field"])
    report["r2"] = {k: v for k, v in report["r2"].items()}
    with open(a.report, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=1, sort_keys=True)
    r1 = report["r1"]
    r2_bad = sum(v["hits"] for k, v in report["r2"].items() if k != "email:example-domain")
    r2_example = report["r2"].get("email:example-domain", {}).get("hits", 0)
    print("traces %d | R1 hits %d exempt %d unchecked %d | R2 hits %d (plus %d example-domain addresses, tolerated) | unknown task files %d" %
          (report["traces"], r1["hit"], r1["exempt"], r1["unchecked"], r2_bad, r2_example, len(report["unknown_task"])))
    if report["r3"]:
        print("R3 files %d bytes %d over 50 MB: %d" % (report["r3"]["files"], report["r3"]["bytes"], len(report["r3"]["over_50MB"])))
    bad = r1["hit"] + r1["unchecked"] + r2_bad + len(report["unknown_task"]) + (len(report["r3"]["over_50MB"]) if report["r3"] else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
