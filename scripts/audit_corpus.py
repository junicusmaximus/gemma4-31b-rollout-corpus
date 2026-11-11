#!/usr/bin/env python3
"""Audit redacted traces (and a staging tree) before anything is released.

Independent of redact_traces.py: it re-reads the redacted files and looks for what must not be there.
Python 3.10+, standard library only.

Rules
  R1  For every trace: no span of 40 or more characters (decoded strings, whitespace normalised, plain and
      JSON-unescaped view) shared with the task's problem_statement, hints_text, patch (gold) or test_patch.
      A shared span is exempt when it also occurs in the upstream repository snapshot of that task (the snapshot
      archive stands for the repository at the base commit). A hit with no snapshot to check is listed as unchecked.
  R2  Secret-shaped strings, e-mail addresses, "/home/" and every word of a private forbidden-words file (the author's
      name and host names, option --forbidden): 0 hits.
      Each hit is listed; hits that also occur in the task's snapshot (upstream text) are marked.
  R3  File types and sizes of a tree; no file over 50 MB.
Usage
  python3 audit_corpus.py --tasks tasks.jsonl --traces DIR [--traces DIR2 ...] [--snapshots DIR] [--tree DIR] --report report.json
Exit status 0 when there are no hits that need a decision (R1 non-exempt or unchecked, R2, R3), else 1.
"""
import argparse
import io
import json
import os
import re
import sys
import tarfile
from collections import Counter, defaultdict

MIN_SPAN = 40
FIELDS = ("problem_statement", "hints_text", "patch", "test_patch")
MAX_FILE = 50 * 1024 * 1024
ESC_RE = re.compile(r'\\(["\\/nrt]|u[0-9a-fA-F]{4})')
ESC_MAP = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "/": "/"}
R2_PATTERNS = {
    "secret:KGAT_": re.compile(r"KGAT_[A-Za-z0-9]+"),
    "secret:hf_": re.compile(r"\bhf_[A-Za-z0-9]{10,}"),
    "secret:sk-": re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    "secret:github": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    "secret:private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "secret:aws": re.compile(r"AKIA[0-9A-Z]{16}"),
    "secret:bearer": re.compile(r"Bearer [A-Za-z0-9._\-]{20,}"),
    "secret:assignment": re.compile(r"(?i)\b(?:api[_-]?key|secret|passwd|password|access[_-]?token|auth[_-]?token)\b[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-/+]{16,}"),
    "email": re.compile(r"(?<![\\A-Za-z0-9._%+\-])[A-Za-z0-9][A-Za-z0-9._%+\-]*@(?:[A-Za-z0-9\-]+\.)+[A-Za-z]{2,}"),
    "/home/": re.compile(r"/home/"),
}
R2_ACTIVE = dict(R2_PATTERNS)       # main() adds one pattern per word of the private forbidden-words file
EXAMPLE_DOMAIN = re.compile(r"@(?:[A-Za-z0-9\-]+\.)*(?:example\.(?:com|org|net)|example|test|invalid|localhost)$|@users\.noreply\.github\.com$")


def norm(text):
    return " ".join(text.split())


def unescape(text):
    return ESC_RE.sub(lambda m: ESC_MAP.get(m.group(1)) or chr(int(m.group(1)[1:], 16)), text)


def strings_of(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path + "{" + str(k) + "}", str(k)
            yield from strings_of(v, path + "." + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from strings_of(v, path + "[%d]" % i)
    elif isinstance(obj, str):
        yield path, obj


def grams(text):
    return {text[i:i + MIN_SPAN] for i in range(0, len(text) - MIN_SPAN + 1)} if len(text) >= MIN_SPAN else set()


def shared_runs(view, gset):
    """Maximal runs of the normalised text `view` made of windows that occur in gset, trimmed of edge spaces and kept
    when still 40 characters long; returns (start, end) pairs."""
    runs, start, last = [], None, None
    for i in range(0, len(view) - MIN_SPAN + 1):
        if view[i:i + MIN_SPAN] in gset:
            if start is None:
                start = i
            last = i
        elif start is not None:
            runs.append((start, last + MIN_SPAN)); start = None
    if start is not None:
        runs.append((start, last + MIN_SPAN))
    out = []
    for a, b in runs:
        while a < b and view[a] == " ":
            a += 1
        while b > a and view[b - 1] == " ":
            b -= 1
        if b - a >= MIN_SPAN:
            out.append((a, b))
    return out


class Snapshots:
    def __init__(self, folder):
        self.folder, self.cache = folder, {}

    def text(self, task_id):
        """Whitespace-normalised text of the repository snapshot, or None when it cannot be read."""
        if task_id in self.cache:
            return self.cache[task_id]
        out = None
        p = os.path.join(self.folder, task_id + ".tgz") if self.folder else None
        if p and os.path.isfile(p):
            parts = []
            with tarfile.open(p) as tf:
                for m in tf:
                    if m.isfile() and m.size <= 3_000_000:
                        data = tf.extractfile(m).read()
                        if b"\x00" not in data[:2000]:
                            parts.append(norm(data.decode("utf-8", "ignore")))
            out = "\n".join(parts)
        self.cache = {task_id: out}      # keep one task in memory
        return out


def task_id_of(name):
    m = re.fullmatch(r"trace_(.+)\.json", name)
    return m.group(1) if m else None


def novel_lines(task, field, snap):
    """Added lines ('+') of a gold or test patch that do not occur in the upstream snapshot: the actual solution text.
    Without a snapshot every added line counts as novel."""
    key = (task["instance_id"], field)
    if key not in _NOVEL:
        out = set()
        for line in (task.get(field) or "").splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                n = norm(line[1:])
                if len(n) >= 20 and not (snap and n in snap):
                    out.add(n)
        if all(k[0] != key[0] for k in _NOVEL):
            _NOVEL.clear()          # keep one task in memory
        _NOVEL[key] = out
    return _NOVEL[key]


_NOVEL = {}


def audit_trace(path, task, snaps, report):
    name = os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
    tid = task["instance_id"]
    with open(path, "rb") as fh:
        obj = json.loads(fh.read().decode("utf-8"))
    fsets = {f: grams(norm(task.get(f) or "")) for f in FIELDS}
    snap = None
    r1 = report["r1"]
    for loc, s in strings_of(obj):
        if len(s) < MIN_SPAN:
            pass
        else:
            for view_name, text in (("plain", s), ("unescaped", unescape(s))):
                if view_name == "unescaped" and text == s:
                    continue
                v = norm(text)
                for f, gs in fsets.items():
                    if not gs:
                        continue
                    for a, b in shared_runs(v, gs):
                        span = v[a:b]
                        if snap is None:
                            snap = snaps.text(tid) if snaps else None
                            snap = snap if snap is not None else False
                        if snap is False:
                            status = "unchecked"
                        else:
                            status = "exempt" if span in snap else "hit"
                        novel = None
                        if status != "exempt" and f in ("patch", "test_patch"):
                            novel = any(n in span for n in novel_lines(task, f, snap))
                        r1[status] += 1
                        r1["by_field"][f + ":" + status] += 1
                        if novel is not None:
                            r1["novel" if novel else "scaffold_only"] += 1
                        if status != "exempt":
                            r1["list"].append({"trace": name, "task": tid, "field": f, "location": loc, "view": view_name, "length": b - a, "first60": span[:60], "status": status, "novel_patch_line": novel})
        for rule, pat in R2_ACTIVE.items():
            for text in {s, unescape(s)}:
                for m in pat.finditer(text):
                    if snap is None:
                        snap = snaps.text(tid) if snaps else None
                        snap = snap if snap is not None else False
                    ctx = text[max(0, m.start() - 30):m.end() + 30]
                    probe = m.group(0) if rule == "email" else norm(text[max(0, m.start() - 15):m.end() + 15])
                    upstream = bool(snap) and probe in snap
                    kind = rule
                    if rule == "email" and EXAMPLE_DOMAIN.search(m.group(0)):
                        kind = "email:example-domain"
                    r2 = report["r2"][kind]
                    r2["hits"] += 1
                    r2["upstream" if upstream else "not_upstream"] += 1
                    if len(r2["list"]) < 200:
                        r2["list"].append({"trace": name, "location": loc, "upstream": upstream, "first60": ctx[:60].replace("\n", "\\n")})
    report["traces"] += 1


def audit_tree(folder, report):
    ext, big = Counter(), []
    size = 0
    for root, ds, fs in os.walk(folder):
        for f in fs:
            p = os.path.join(root, f)
            sz = os.path.getsize(p)
            size += sz
            e = os.path.splitext(f)[1].lower() or "(none)"
            ext[e] += 1
            if sz > MAX_FILE:
                big.append((os.path.relpath(p, folder), sz))
    report["r3"] = {"files": sum(ext.values()), "bytes": size, "by_extension": dict(ext), "over_50MB": big}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--traces", action="append", default=[])
    ap.add_argument("--snapshots", help="folder with <task id>.tgz repository snapshots (used for the exemptions)")
    ap.add_argument("--tree", help="staging folder for the file type and size check")
    ap.add_argument("--report", required=True)
    ap.add_argument("--forbidden", help="private JSON list of words that must not occur (author name and host names)")
    a = ap.parse_args(argv)
    R2_ACTIVE.clear()
    R2_ACTIVE.update(R2_PATTERNS)
    if a.forbidden:
        with open(a.forbidden, encoding="utf-8") as fh:
            for i, word in enumerate(json.load(fh), 1):
                R2_ACTIVE["forbidden word %d" % i] = re.compile(re.escape(word), re.I)
    tasks = {}
    with open(a.tasks, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                t = json.loads(line); tasks[t["instance_id"]] = t
    snaps = Snapshots(a.snapshots) if a.snapshots else None
    report = {"traces": 0, "r1": {"hit": 0, "exempt": 0, "unchecked": 0, "novel": 0, "scaffold_only": 0, "by_field": Counter(), "list": []},
              "r2": defaultdict(lambda: {"hits": 0, "upstream": 0, "not_upstream": 0, "list": []}), "unknown_task": [], "r3": None}
    files = []
    for d in a.traces:
        files += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".json")]
    # group by task id so that one snapshot is loaded at a time
    files.sort(key=lambda p: (task_id_of(os.path.basename(p)) or "", p))
    for p in files:
        tid = task_id_of(os.path.basename(p))
        if tid not in tasks:
            report["unknown_task"].append(os.path.basename(p)); continue
        audit_trace(p, tasks[tid], snaps, report)
    if a.tree:
        audit_tree(a.tree, report)
    report["r1"]["by_field"] = dict(report["r1"]["by_field"])
    report["r2"] = {k: v for k, v in report["r2"].items()}
    with open(a.report, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=1, sort_keys=True)
    r1 = report["r1"]
    r2_total = sum(v["hits"] for v in report["r2"].values())
    print("traces %d | R1 hits %d exempt %d unchecked %d | R2 hits %d | unknown task files %d" % (report["traces"], r1["hit"], r1["exempt"], r1["unchecked"], r2_total, len(report["unknown_task"])))
    if report["r3"]:
        print("R3 files %d bytes %d over 50 MB: %d" % (report["r3"]["files"], report["r3"]["bytes"], len(report["r3"]["over_50MB"])))
    bad = r1["hit"] + r1["unchecked"] + r2_total + len(report["unknown_task"]) + (len(report["r3"]["over_50MB"]) if report["r3"] else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
