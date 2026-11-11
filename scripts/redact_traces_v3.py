#!/usr/bin/env python3
"""Redactor version 3: cross task protection. Python 3.10+, standard library only. Versions 1 and 2 stay unchanged.

Protected sources: problem statement (ps), hints (ht), gold patch (pa) and test patch (tp) of EVERY task of the task file, and the
text files of the organiser's sample submission (og).
Rule (decoded and whitespace normalised text; plain view and JSON escape aware view):
  1. Windows of 40 characters that occur in a protected source are found. A window that touches a path is ignored. A path is a
     file or folder name of the upstream snapshot tree of the trace's OWN task (12 or more characters; a leading part of a longer
     token such as a directory prefix of the file system is allowed).
  2. Consecutive windows form a run. The run (edge spaces trimmed) is exempt when it occurs in the file contents of the own task's
     snapshot. Nothing else is exempt.
  3. Every other run is replaced by placeholders. At each position the longest match wins. Equal lengths are decided by this
     fixed order of preference: sources of the own task before sources of other tasks; within one task problem statement, hints,
     gold patch, test patch; other tasks in sorted task id order; organiser files last (sorted by path).
     A tail of fewer than 40 characters at the end of a run stays visible.
Placeholder (U+27E6 "RDX3:" CODE U+27E7)
  CODE = t:TASKID:F:J:L:H[:DIFFS]   a span of field F (ps|ht|pa|tp) of task TASKID (percent encoded): offset J and length L in the
                                    normalised field text, H = first 6 hex digits of the sha256 of the normalised field text
       | og:FILE:J:L:H[:DIFFS]      the same for an organiser file (FILE = percent encoded relative path)
       | P1, P2, ...                strings of the private path rules file
       | L, R                       a literal U+27E6 or U+27E7 of the original text
  DIFFS = Q=RAW;Q=RAW...            positions Q where the trace text differs from the source text (whitespace or JSON escapes)
Left out traces: left-out-email (an address that is not of an example domain remains), left-out-graph, left-out-serialiser.
"""
import argparse
import json
import os
import re
import sys
import tarfile
from urllib.parse import quote, unquote

import redact_traces as V1
import redact_traces_v2 as V2
from redact_traces import (CLOSE, MIN_SPAN, OPEN, PathRules, RedactionError, load_path_rules, load_tasks, location, normalise,
                           serialise, sha256, task_id_of, uses_graph_tools, walk)
from redact_traces_v2 import LeftOut, real_email_count

TAG = "RDX3"
PH_RE = re.compile(OPEN + TAG + r":([^" + CLOSE + r"]*)" + CLOSE)
FIELDS = (("problem_statement", "ps"), ("hints_text", "ht"), ("patch", "pa"), ("test_patch", "tp"))
FIELD_KEY = {code: key for key, code in FIELDS}
FIELD_ORDER = {code: i for i, (_, code) in enumerate(FIELDS)}
MIN_PATH = 12
PATH_RE = re.compile(r"[A-Za-z0-9_./\-]+")
SHIFT = 24      # an index entry is (source number << SHIFT) | offset
MAX_SNAPSHOT_FILE = 3_000_000


class Source:
    def __init__(self, task_id, code, label, text):
        self.task_id, self.code, self.label = task_id, code, label
        self.nf, self.fraw = normalise(text, esc=False)
        self.hash6 = sha256(self.nf.encode("utf-8"))[:6]


class Corpus:
    """All protected sources and one index from 40 character windows to (source, offset)."""

    def __init__(self, tasks, organiser_folder=None):
        self.sources, self.index = [], {}
        self.task_rank = {tid: i for i, tid in enumerate(sorted(tasks))}
        for tid in sorted(tasks):
            for key, code in FIELDS:
                text = tasks[tid].get(key) or ""
                if text:
                    self.add(Source(tid, code, None, text))
        for label, text in organiser_texts(organiser_folder):
            self.add(Source(None, "og", label, text))

    def add(self, src):
        sid = len(self.sources)
        self.sources.append(src)
        if len(src.nf) >= 1 << SHIFT:
            raise RedactionError("a protected text is too long for the index")
        idx, nf = self.index, src.nf
        for j in range(0, len(nf) - MIN_SPAN + 1):
            g = nf[j:j + MIN_SPAN]
            v = (sid << SHIFT) | j
            cur = idx.get(g)
            if cur is None:
                idx[g] = v
            elif isinstance(cur, int):
                idx[g] = [cur, v]
            else:
                cur.append(v)

    def entries(self, gram):
        v = self.index.get(gram)
        if v is None:
            return ()
        return (v,) if isinstance(v, int) else v

    def rank(self, src, own_tid):
        if src.task_id is None:
            return (3, src.label)
        if src.task_id == own_tid:
            return (0, FIELD_ORDER[src.code])
        return (1, self.task_rank[src.task_id], FIELD_ORDER[src.code])


def organiser_texts(folder):
    out = []
    if folder:
        for root, _, files in os.walk(folder):
            for f in files:
                if f.endswith(V2.ORGANISER_EXT):
                    p = os.path.join(root, f)
                    with open(p, "rb") as fh:
                        data = fh.read()
                    if b"\x00" not in data[:2000]:
                        out.append((os.path.relpath(p, folder).replace(os.sep, "/"), data.decode("utf-8", "ignore")))
    out.sort()
    return out


class SnapshotStore:
    """Normalised file contents and the set of file and folder paths of the upstream snapshot of a task (one task in memory)."""

    def __init__(self, folder):
        self.folder, self.cache = folder, {}

    def get(self, task_id):
        """Returns (text, paths) or (None, None) without a snapshot file."""
        if task_id in self.cache:
            return self.cache[task_id]
        out = (None, None)
        p = os.path.join(self.folder, task_id + ".tgz") if self.folder else None
        if p and os.path.isfile(p):
            parts, paths = [], set()
            with tarfile.open(p) as tf:
                for m in tf:
                    name = m.name
                    while name.startswith("./"):
                        name = name[2:]
                    name = name.strip("/")
                    if name and name != ".":
                        bits = name.split("/")
                        for k in range(1, len(bits) + 1):
                            paths.add("/".join(bits[:k]))
                    if m.isfile() and m.size <= MAX_SNAPSHOT_FILE:
                        data = tf.extractfile(m).read()
                        if b"\x00" not in data[:2000]:
                            parts.append(" ".join(data.decode("utf-8", "ignore").split()))
            out = ("\n".join(parts), paths)
        self.cache = {task_id: out}
        return out


def path_cover(ns, paths):
    """Prefix sums of a mask of the characters of ns that belong to a snapshot path (a token, or the tail of a token after a
    slash, that is a path of the tree; at least MIN_PATH characters)."""
    mask = bytearray(len(ns))
    if paths:
        for m in PATH_RE.finditer(ns):
            tok, start = m.group(), m.start()
            cuts = [0] + [k + 1 for k, c in enumerate(tok) if c == "/"]
            for k in cuts:
                sub = tok[k:]
                for cand in (sub, sub.rstrip("/.")):
                    if len(cand) >= MIN_PATH and cand in paths:
                        for q in range(start + k, start + k + len(cand)):
                            mask[q] = 1
                        break
                else:
                    continue
                break
    pre = [0]
    for b in mask:
        pre.append(pre[-1] + b)
    return pre


def valid_runs(ns, windows, paths):
    """Runs of consecutive window starts whose windows touch no path; returns (first start, last start) pairs."""
    pre = path_cover(ns, paths) if windows else None
    runs, last = [], None
    for i in windows:
        if pre[i + MIN_SPAN] - pre[i]:
            continue
        if runs and last == i - 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
        last = i
    return [(a, b) for a, b in runs]


class Context:
    def __init__(self, corpus, own_tid, snap_text, paths):
        self.corpus, self.own, self.snap, self.paths = corpus, own_tid, snap_text, paths
        self.cache = {}

    def exempt(self, span):
        if self.snap is None:
            return False
        if span not in self.cache:
            self.cache[span] = span in self.snap
        return self.cache[span]


def encode_span(src, j, length, raws):
    diffs = []
    for q in range(length):
        if raws[q] != src.fraw[j + q]:
            diffs.append("%d=%s" % (q, quote(raws[q], safe="")))
    if src.task_id is None:
        head = "og:" + quote(src.label, safe="")
    else:
        head = "t:%s:%s" % (quote(src.task_id, safe=""), src.code)
    code = "%s:%d:%d:%s" % (head, j, length, src.hash6)
    if diffs:
        code += ":" + ";".join(diffs)
    return OPEN + TAG + ":" + code + CLOSE


def stat_key(src, own_tid):
    return "og" if src.task_id is None else ("own_" if src.task_id == own_tid else "oth_") + src.code


STAT_KEYS = ["own_ps", "own_ht", "own_pa", "own_tp", "oth_ps", "oth_ht", "oth_pa", "oth_tp", "og"]


def redact_view(text, ctx, esc, stats):
    ns, raws = normalise(text, esc)
    corpus = ctx.corpus
    windows = [i for i in range(0, len(ns) - MIN_SPAN + 1) if ns[i:i + MIN_SPAN] in corpus.index]
    if not windows:
        return [(False, text)]
    out, pos = [], 0
    for w0, w1 in valid_runs(ns, windows, ctx.paths):
        a_raw, b_raw = w0, w1 + MIN_SPAN
        a, b = a_raw, b_raw
        while a < b and ns[a] == " ":
            a += 1
        while b > a and ns[b - 1] == " ":
            b -= 1
        if b - a < MIN_SPAN or ctx.exempt(ns[a:b]):
            continue
        p = max(a_raw, pos)        # runs can overlap in characters when one window between them is not in a source
        while b_raw - p >= MIN_SPAN:
            best = None
            for v in corpus.entries(ns[p:p + MIN_SPAN]):
                src, j = corpus.sources[v >> SHIFT], v & ((1 << SHIFT) - 1)
                limit = min(b_raw - p, len(src.nf) - j)
                length = MIN_SPAN
                while length < limit and ns[p + length] == src.nf[j + length]:
                    length += 1
                key = (-length, corpus.rank(src, ctx.own))
                if best is None or key < best[0]:
                    best = (key, length, src, j)
            if best is None:
                p += 1
                continue
            _, length, src, j = best
            ta, tb, tj = p, p + length, j
            while ta < tb and ns[ta] == " ":
                ta += 1; tj += 1
            while tb > ta and ns[tb - 1] == " ":
                tb -= 1
            if tb - ta < MIN_SPAN:
                p += 1
                continue
            if ta > pos:
                out.append((False, "".join(raws[pos:ta])))
            out.append((True, encode_span(src, tj, tb - ta, raws[ta:tb])))
            k = stat_key(src, ctx.own)
            stats["n_" + k] += 1
            stats["removed_" + k] += len("".join(raws[ta:tb]))
            pos, p = tb, p + length
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


def new_stats():
    st = {"paths": 0, "by_location": {}}
    for k in STAT_KEYS:
        st["n_" + k] = 0
        st["removed_" + k] = 0
    return st


def redact_trace_bytes(raw, task_id, corpus, rules=None, snapshots=None):
    """Returns (redacted bytes, stats). Raises LeftOut when the trace must not be released."""
    obj = json.loads(raw.decode("utf-8"))
    if serialise(obj) != raw:
        raise LeftOut("left-out-serialiser", "json.dumps(indent=2) does not reproduce this file")
    graph = uses_graph_tools(obj)
    if graph:
        raise LeftOut("left-out-graph", "graph tools: %r" % (graph[:3],))
    snap_text, paths = snapshots.get(task_id) if snapshots else (None, None)
    ctx = Context(corpus, task_id, snap_text, paths)
    rules = rules or PathRules()
    stats = new_stats()

    def fn(s, path):
        before = sum(stats["n_" + k] for k in STAT_KEYS)
        r = redact_string(s, ctx, stats, rules)
        added = sum(stats["n_" + k] for k in STAT_KEYS) - before
        if added:
            key = "%s:%s" % (obj["steps"][path[1]]["source"] if path[0] == "steps" else path[0], location(path))
            stats["by_location"][key] = stats["by_location"].get(key, 0) + added
        return r
    red = walk(obj, fn)
    n = real_email_count(red)
    if n:
        raise LeftOut("left-out-email", "%d e-mail address(es) not of an example domain" % n)
    return serialise(red), stats


class RestoreSources:
    """Sources for restore: built on demand from the task file and the organiser folder (no index)."""

    def __init__(self, tasks, organiser_folder=None):
        self.tasks, self.cache = tasks, {}
        self.org = dict(organiser_texts(organiser_folder)) if organiser_folder else None

    def task_field(self, tid, code):
        key = (tid, code)
        if key not in self.cache:
            if tid not in self.tasks:
                raise RedactionError("task id %r of a placeholder is not in the task file" % tid)
            text = self.tasks[tid].get(FIELD_KEY[code]) or ""
            if not text:
                raise RedactionError("task %s has no %s to restore from" % (tid, code))
            self.cache[key] = Source(tid, code, None, text)
        return self.cache[key]

    def organiser(self, label):
        if self.org is None:
            raise RedactionError("an organiser placeholder needs the organiser's sample submission folder (--organiser)")
        if label not in self.org:
            raise RedactionError("organiser file %s is not in the organiser folder" % label)
        key = ("og", label)
        if key not in self.cache:
            self.cache[key] = Source(None, "og", label, self.org[label])
        return self.cache[key]


def restore_string(text, rs, rules):
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
            src, rest = rs.organiser(unquote(parts[1])), parts[2:]
        elif head == "t":
            parts = code.split(":", 6)
            if len(parts) < 6 or parts[2] not in FIELD_KEY:
                raise RedactionError("unknown placeholder %r" % code)
            src, rest = rs.task_field(unquote(parts[1]), parts[2]), parts[3:]
        else:
            raise RedactionError("unknown placeholder %r" % code)
        j, length, h6 = int(rest[0]), int(rest[1]), rest[2]
        if src.hash6 != h6:
            raise RedactionError("task file or organiser file differs from the one used for redaction (%s)" % (src.label or src.task_id))
        diffs = {}
        if len(rest) == 4 and rest[3]:
            for item in rest[3].split(";"):
                q, raw = item.split("=", 1)
                diffs[int(q)] = unquote(raw)
        if j + length > len(src.fraw):
            raise RedactionError("placeholder outside the source text")
        return "".join(diffs.get(q, src.fraw[j + q]) for q in range(length))
    return PH_RE.sub(one, text)


def restore_trace_bytes(raw, tasks, task_id, rules=None, organiser_folder=None, rs=None):
    if task_id not in tasks:
        raise RedactionError("task id %r is not in the task file; nothing is restored" % task_id)
    rs = rs or RestoreSources(tasks, organiser_folder)
    rules = rules or PathRules()
    return serialise(walk(json.loads(raw.decode("utf-8")), lambda s, path: restore_string(s, rs, rules)))


COLUMNS = (["file", "task_id", "status", "sha256_original", "sha256_redacted"] + ["n_" + k for k in STAT_KEYS] + ["path_placeholders"] +
           ["removed_" + k for k in STAT_KEYS] + ["bytes_original", "bytes_redacted", "detail"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tasks", required=True, help="the competition's public task file (tasks.jsonl)")
    ap.add_argument("--in", dest="inp", required=True, help="a trace file or a folder with trace_<task id>.json files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--path-rules")
    ap.add_argument("--snapshots", help="folder with <task id>.tgz upstream snapshots (exemptions)")
    ap.add_argument("--organiser", help="folder with the organiser's sample submission files")
    a = ap.parse_args(argv)
    rules = load_path_rules(a.path_rules)
    tasks = load_tasks(a.tasks)
    corpus = Corpus(tasks, a.organiser)
    snapshots = SnapshotStore(a.snapshots) if a.snapshots else None
    files = [a.inp] if os.path.isfile(a.inp) else sorted(os.path.join(a.inp, f) for f in os.listdir(a.inp) if f.endswith(".json"))
    os.makedirs(a.out, exist_ok=True)
    rows = ["\t".join(COLUMNS)]
    no_task = 0
    for f in files:
        tid, name = task_id_of(f), os.path.basename(f)
        with open(f, "rb") as fh:
            raw = fh.read()
        if tid not in tasks:
            rows.append("\t".join([name, tid, "no-task", sha256(raw)] + [""] * (len(COLUMNS) - 7) + [str(len(raw)), "", "task id not in task file"]))
            no_task += 1
            continue
        try:
            red, st = redact_trace_bytes(raw, tid, corpus, rules, snapshots)
        except LeftOut as e:
            rows.append("\t".join([name, tid, e.kind, sha256(raw)] + [""] * (len(COLUMNS) - 7) + [str(len(raw)), "", str(e)]))
            continue
        except RedactionError as e:
            rows.append("\t".join([name, tid, "left-out-other", sha256(raw)] + [""] * (len(COLUMNS) - 7) + [str(len(raw)), "", str(e)]))
            continue
        dst = os.path.join(a.out, name)
        if os.path.exists(dst):
            raise SystemExit("refusing to overwrite " + dst)
        with open(dst, "wb") as fh:
            fh.write(red)
        rows.append("\t".join([name, tid, "redacted", sha256(raw), sha256(red)] + [str(st["n_" + k]) for k in STAT_KEYS] + [str(st["paths"])] +
                              [str(st["removed_" + k]) for k in STAT_KEYS] + [str(len(raw)), str(len(red)), json.dumps(st["by_location"], sort_keys=True)]))
    with open(a.manifest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(rows) + "\n")
    left = sum(1 for r in rows[1:] if r.split("\t")[2] != "redacted")
    print("processed %d files, %d not released" % (len(files), left))
    return 1 if no_task else 0


if __name__ == "__main__":
    sys.exit(main())
