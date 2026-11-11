#!/usr/bin/env python3
"""Redactor version 2: protects four task fields and the organiser's sample files, leaves out traces with real e-mail addresses.

Library and command line. Python 3.10+, standard library only. Version 1 (redact_traces.py) stays unchanged; this file imports
its text helpers.

Protected sources
  ps = problem_statement and ht = hints_text    every span of 40 or more characters is replaced
  pa = patch (gold) and tp = test_patch         a span is replaced unless the whole run it belongs to occurs in the upstream
                                                repository snapshot of the task (the same run rule that audit_corpus_v2.py uses).
                                                Without --snapshots every span is replaced.
  og = text files of the organiser's sample submission    every span is replaced; restore needs the organiser folder
Strings are the decoded values of the trace JSON (all nesting levels). Two views of each string are scanned: the plain text
and a view in which JSON escape sequences are read as the characters they stand for. Whitespace is normalised.

Placeholder format (U+27E6 "RDX2:" CODE U+27E7)
  CODE = ps|ht|pa|tp:J:L:H[:DIFFS]       span of the field of the task: offset J and length L in the normalised field text,
                                         H = first 6 hex digits of sha256 of the normalised field text
       | og:FILE:J:L:H[:DIFFS]           the same for an organiser file; FILE is the percent-encoded relative path
       | P1, P2, ...                     strings of the private path rules file (machine paths and host names)
       | L, R                            a literal U+27E6 or U+27E7 of the original text
  DIFFS = Q=RAW;Q=RAW...  positions Q where the trace text differs from the source's own text (other whitespace or JSON escapes)
A trace with an e-mail address that is not of an example domain (in the redacted text) is left out (status left-out-email).
A trace that calls an official graph tool is left out (left-out-graph). A trace that json.dumps(indent=2) does not reproduce
byte for byte is left out (left-out-serialiser).
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import quote, unquote

import audit_corpus as A
import redact_traces as V1
from redact_traces import (CLOSE, MIN_SPAN, OPEN, PathRules, RedactionError, load_path_rules, load_tasks, location, normalise,
                           serialise, sha256, task_id_of, uses_graph_tools, walk)

TAG = "RDX2"
PH_RE = re.compile(OPEN + TAG + r":([^" + CLOSE + r"]*)" + CLOSE)
# (task key, code, snapshot exemption applies)
TASK_FIELDS = (("problem_statement", "ps", False), ("hints_text", "ht", False), ("patch", "pa", True), ("test_patch", "tp", True))
ORGANISER_EXT = (".md", ".txt", ".yaml", ".yml", ".py", ".json")
CODES = ("ps", "ht", "pa", "tp", "og")


class LeftOut(RedactionError):
    def __init__(self, kind, msg):
        super().__init__(msg)
        self.kind = kind


class Source:
    def __init__(self, key, code, text, snapshot_check=False, label=None, build_index=True):
        self.key, self.code, self.label, self.snapshot_check = key, code, label, snapshot_check
        self.nf, self.fraw = normalise(text, esc=False)
        self.hash6 = sha256(self.nf.encode("utf-8"))[:6]
        self.index = {}
        if build_index:
            for j in range(0, len(self.nf) - MIN_SPAN + 1):
                self.index.setdefault(self.nf[j:j + MIN_SPAN], []).append(j)


def task_sources(task, build_index=True):
    out = []
    for key, code, snap in TASK_FIELDS:
        text = task.get(key) or ""
        if text:
            out.append(Source(key, code, text, snap, None, build_index))
    return out


def load_organiser(folder, build_index=True):
    """Text files of the organiser's sample submission as sources, in path order."""
    out = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.endswith(ORGANISER_EXT):
                p = os.path.join(root, f)
                with open(p, "rb") as fh:
                    data = fh.read()
                if b"\x00" in data[:2000]:
                    continue
                rel = os.path.relpath(p, folder).replace(os.sep, "/")
                out.append(Source("og:" + rel, "og", data.decode("utf-8", "ignore"), False, rel, build_index))
    out.sort(key=lambda s: s.label)
    return out


class Context:
    """Sources of one trace (task fields and organiser files) and the upstream snapshot text of the task."""

    def __init__(self, task, organiser=(), snapshot_text=None):
        self.sources = task_sources(task) + list(organiser)
        self.snap = snapshot_text
        self.grams = set()
        for s in self.sources:
            self.grams.update(s.index.keys())
        self.cache = {}

    def candidates(self, ns, i):
        g = ns[i:i + MIN_SPAN]
        if g not in self.grams:
            return []
        out = []
        for s in self.sources:
            best = None
            for j in s.index.get(g, ()):
                length = MIN_SPAN
                while i + length < len(ns) and j + length < len(s.nf) and ns[i + length] == s.nf[j + length]:
                    length += 1
                if best is None or length > best[0]:
                    best = (length, s, j)
            if best:
                out.append(best)
        out.sort(key=lambda c: -c[0])
        return out

    def exempt_run(self, ns, i, src, pos):
        """The maximal run of windows of src around position i (not left of pos), as the audit sees it; returns
        (exempt, end of run). Exempt means that the run (edge spaces trimmed) occurs in the snapshot."""
        gs = src.index
        a = i
        while a > pos and ns[a - 1:a - 1 + MIN_SPAN] in gs:
            a -= 1
        b = i
        while ns[b + 1:b + 1 + MIN_SPAN] in gs:
            b += 1
        end = b + MIN_SPAN
        if self.snap is None:
            return False, end
        span = ns[a:end].strip(" ")
        key = (src.key, span)
        if key not in self.cache:
            self.cache[key] = len(span) >= MIN_SPAN and span in self.snap
        return self.cache[key], end


def encode_span(src, j, length, raws):
    diffs = []
    for q in range(length):
        if raws[q] != src.fraw[j + q]:
            diffs.append("%d=%s" % (q, quote(raws[q], safe="")))
    head = src.code if src.code != "og" else "og:" + quote(src.label, safe="")
    code = "%s:%d:%d:%s" % (head, j, length, src.hash6)
    if diffs:
        code += ":" + ";".join(diffs)
    return OPEN + TAG + ":" + code + CLOSE


def redact_view(text, ctx, esc, stats):
    ns, raws = normalise(text, esc)
    out, pos, i = [], 0, 0
    while i <= len(ns) - MIN_SPAN:
        chosen, skip_to = None, i + 1
        for length, src, j in ctx.candidates(ns, i):
            if src.snapshot_check:
                exempt, end = ctx.exempt_run(ns, i, src, pos)
                if exempt:
                    skip_to = max(skip_to, end - MIN_SPAN + 1)
                    continue
            chosen = (length, src, j)
            break
        if chosen is None:
            i = skip_to
            continue
        length, src, j = chosen
        a, b = i, i + length
        while a < b and ns[a] == " ":
            a += 1; j += 1
        while b > a and ns[b - 1] == " ":
            b -= 1
        if b - a < MIN_SPAN:
            i += 1
            continue
        if a > pos:
            out.append((False, "".join(raws[pos:a])))
        out.append((True, encode_span(src, j, b - a, raws[a:b])))
        stats["n_" + src.code] += 1
        stats["removed_" + src.code] += len("".join(raws[a:b]))
        pos, i = b, b
    if pos < len(ns):
        out.append((False, "".join(raws[pos:])))
    return out


def _escape_brackets(seg):
    return "".join(OPEN + TAG + ":L" + CLOSE if c == OPEN else OPEN + TAG + ":R" + CLOSE if c == CLOSE else c for c in seg)


def redact_string(text, ctx, stats, rules):
    segs = [(False, text)]
    for esc in (False, True):
        nxt = []
        for is_ph, seg in segs:
            if is_ph or len(seg) < MIN_SPAN:
                nxt.append((is_ph, seg))
            else:
                nxt.extend(redact_view(seg, ctx, esc, stats))
        segs = nxt
    out = []
    for is_ph, seg in segs:
        if is_ph:
            out.append(seg)
            continue
        parts, last = [], 0
        for m in (rules.regex.finditer(seg) if rules.regex else ()):
            parts.append(_escape_brackets(seg[last:m.start()]))
            parts.append(OPEN + TAG + ":" + rules.by_lit[m.group(0)] + CLOSE)
            stats["paths"] += 1
            last = m.end()
        parts.append(_escape_brackets(seg[last:]))
        out.append("".join(parts))
    return "".join(out)


def real_email_count(obj):
    """E-mail addresses that are not of an example domain in the strings of obj (same patterns as the audit)."""
    n = 0
    for _, s in A.strings_of(obj):
        for text in {s, A.unescape(s)}:
            n += sum(1 for m in A.R2_PATTERNS["email"].finditer(text) if not A.EXAMPLE_DOMAIN.search(m.group(0)))
    return n


def new_stats():
    st = {"paths": 0, "by_location": {}}
    for c in CODES:
        st["n_" + c] = 0
        st["removed_" + c] = 0
    return st


def redact_trace_bytes(raw, task, rules=None, organiser=(), snapshot_text=None):
    """Returns (redacted bytes, stats). Raises LeftOut (a RedactionError) when the trace must not be released."""
    obj = json.loads(raw.decode("utf-8"))
    if serialise(obj) != raw:
        raise LeftOut("left-out-serialiser", "json.dumps(indent=2) does not reproduce this file")
    graph = uses_graph_tools(obj)
    if graph:
        raise LeftOut("left-out-graph", "graph tools: %r" % (graph[:3],))
    ctx = Context(task, organiser, snapshot_text)
    rules = rules or PathRules()
    stats = new_stats()

    def fn(s, path):
        before = sum(stats["n_" + c] for c in CODES)
        r = redact_string(s, ctx, stats, rules)
        added = sum(stats["n_" + c] for c in CODES) - before
        if added:
            key = "%s:%s" % (obj["steps"][path[1]]["source"] if path[0] == "steps" else path[0], location(path))
            stats["by_location"][key] = stats["by_location"].get(key, 0) + added
        return r
    red = walk(obj, fn)
    n = real_email_count(red)
    if n:
        raise LeftOut("left-out-email", "%d e-mail address(es) not of an example domain" % n)
    return serialise(red), stats


def restore_string(text, task_src, organiser, task_id, rules):
    def one(m):
        code = m.group(1)
        if code == "L":
            return OPEN
        if code == "R":
            return CLOSE
        if re.fullmatch(r"P[0-9]+", code):
            if code not in rules.by_code:
                raise RedactionError("placeholder %s needs the path rules file used for redaction" % code)
            return rules.by_code[code]
        head = code.split(":", 1)[0]
        if head == "og":
            parts = code.split(":", 5)
            if len(parts) < 5:
                raise RedactionError("unknown placeholder %r" % code)
            if organiser is None:
                raise RedactionError("an organiser placeholder needs the organiser's sample submission folder (--organiser)")
            label = unquote(parts[1])
            src = organiser.get(label)
            if src is None:
                raise RedactionError("organiser file %s is not in the organiser folder" % label)
            rest = parts[2:]
        elif head in CODES:
            parts = code.split(":", 4)
            if len(parts) < 4:
                raise RedactionError("unknown placeholder %r" % code)
            src = task_src(task_id).get(head)
            if src is None:
                raise RedactionError("task %s has no %s to restore from" % (task_id, head))
            rest = parts[1:]
        else:
            raise RedactionError("unknown placeholder %r" % code)
        j, length, h6 = int(rest[0]), int(rest[1]), rest[2]
        if src.hash6 != h6:
            raise RedactionError("task file or organiser file differs from the one used for redaction (%s)" % (src.label or head))
        diffs = {}
        if len(rest) == 4 and rest[3]:
            for item in rest[3].split(";"):
                q, raw = item.split("=", 1)
                diffs[int(q)] = unquote(raw)
        if j + length > len(src.fraw):
            raise RedactionError("placeholder outside the source text")
        return "".join(diffs.get(q, src.fraw[j + q]) for q in range(length))
    return PH_RE.sub(one, text)


def restore_trace_bytes(raw, tasks, task_id, rules=None, organiser=None):
    """organiser: dict label -> Source (see organiser_map) or None."""
    if task_id not in tasks:
        raise RedactionError("task id %r is not in the task file; nothing is restored" % task_id)
    cache = {}

    def ts(tid):
        if tid not in cache:
            cache[tid] = {s.code: s for s in task_sources(tasks[tid], build_index=False)}
        return cache[tid]
    obj = json.loads(raw.decode("utf-8"))
    rules = rules or PathRules()
    return serialise(walk(obj, lambda s, path: restore_string(s, ts, organiser, task_id, rules)))


def organiser_map(folder):
    return {s.label: s for s in load_organiser(folder, build_index=False)} if folder else None


def snapshot_text_of(snaps, task_id):
    return snaps.text(task_id) if snaps else None


COLUMNS = ["file", "task_id", "status", "sha256_original", "sha256_redacted", "n_ps", "n_ht", "n_pa", "n_tp", "n_og", "path_placeholders",
           "removed_ps", "removed_ht", "removed_pa", "removed_tp", "removed_og", "bytes_original", "bytes_redacted", "detail"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tasks", required=True, help="the competition's public task file (tasks.jsonl)")
    ap.add_argument("--in", dest="inp", required=True, help="a trace file or a folder with trace_<task id>.json files")
    ap.add_argument("--out", required=True, help="output folder (created; existing files are not overwritten)")
    ap.add_argument("--manifest", required=True, help="manifest tsv to write")
    ap.add_argument("--path-rules", help="private JSON list of machine paths and host names to replace by P1, P2, ...")
    ap.add_argument("--snapshots", help="folder with <task id>.tgz upstream snapshots (spans of gold or test patch that occur there stay visible)")
    ap.add_argument("--organiser", help="folder with the organiser's sample submission files")
    a = ap.parse_args(argv)
    rules = load_path_rules(a.path_rules)
    tasks = load_tasks(a.tasks)
    organiser = load_organiser(a.organiser) if a.organiser else []
    snaps = A.Snapshots(a.snapshots) if a.snapshots else None
    files = [a.inp] if os.path.isfile(a.inp) else sorted(os.path.join(a.inp, f) for f in os.listdir(a.inp) if f.endswith(".json"))
    os.makedirs(a.out, exist_ok=True)
    rows = ["\t".join(COLUMNS)]
    no_task = 0
    for f in files:
        tid = task_id_of(f)
        name = os.path.basename(f)
        with open(f, "rb") as fh:
            raw = fh.read()
        if tid not in tasks:
            rows.append("\t".join([name, tid, "no-task", sha256(raw)] + [""] * 12 + [str(len(raw)), "", "task id not in task file"])); no_task += 1
            continue
        try:
            red, st = redact_trace_bytes(raw, tasks[tid], rules, organiser, snapshot_text_of(snaps, tid))
        except LeftOut as e:
            rows.append("\t".join([name, tid, e.kind, sha256(raw)] + [""] * 12 + [str(len(raw)), "", str(e)]))
            continue
        except RedactionError as e:
            rows.append("\t".join([name, tid, "left-out-other", sha256(raw)] + [""] * 12 + [str(len(raw)), "", str(e)]))
            continue
        dst = os.path.join(a.out, name)
        if os.path.exists(dst):
            raise SystemExit("refusing to overwrite " + dst)
        with open(dst, "wb") as fh:
            fh.write(red)
        rows.append("\t".join([name, tid, "redacted", sha256(raw), sha256(red)] + [str(st["n_" + c]) for c in CODES] + [str(st["paths"])] +
                              [str(st["removed_" + c]) for c in CODES] + [str(len(raw)), str(len(red)), json.dumps(st["by_location"], sort_keys=True)]))
    with open(a.manifest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(rows) + "\n")
    left = sum(1 for r in rows[1:] if r.split("\t")[2] != "redacted")
    print("processed %d files, %d not released" % (len(files), left))
    return 1 if no_task else 0


if __name__ == "__main__":
    sys.exit(main())
