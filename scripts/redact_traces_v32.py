#!/usr/bin/env python3
"""Redactor version 3.2 (release candidate rules). Python 3.10+, standard library only. Versions 1 to 3.1 stay unchanged; this
file imports their helpers and has its own placeholder tag RDX4.

EXACT RULE TEXT
Protected sources: problem statement and hints of every task of the task file, gold patch and test patch of every task, and the text
files of the organiser's sample submission. Text is compared after JSON decoding and after whitespace is collapsed (every run of
whitespace becomes one space; a leading or trailing run is dropped from the index).
 1. A WINDOW is 40 consecutive characters of the collapsed text of a trace string. For the problem statement and hints of the
    trace's OWN task a window is 20 characters. A window is a candidate when it occurs in a protected source.
 2. A window is ignored only when it lies wholly inside the path part of a token. A path part is a file or folder name of the upstream
    snapshot tree of the trace's own task of 12 or more characters (the whole token or its tail after a slash). Windows that
    straddle a path and the text next to it count like any other window. The own statement and hints have no path exemption.
 3. Consecutive candidate windows form a RUN. A run is measured after its two end spaces are dropped. A run with 40 or more characters
    (20 for the own statement and hints) is a HIT. A run of the 40 character kind that occurs in the file contents of the own
    task's snapshot is exempt. There is no other exemption: the own statement and hints have none. Shorter pieces remain visible.
 4. Every hit is replaced by placeholders. The own statement and hints are replaced first. Then at each position the longest match
    wins; equal lengths are decided by this order: own task before other tasks; within a task problem statement, hints, gold patch,
    test patch; other tasks in sorted task id order; organiser files last in sorted path order. A tail of fewer than 40 characters
    (20 for the own statement and hints) at the end of a run stays visible.
 5. Views: the stored string (depth 0) and the string with JSON style escapes undone once (depth 1) are redacted. After that the
    redacted trace is audited in the views of depth 0 to the fixpoint of the unescape pass (at most 6 passes). A trace with any
    remaining hit (this means every hit at depth 2 or deeper) is left out (left-out-residual).
 6. Placeholder (U+27E6 "RDX4:" CODE U+27E7), CODE = t:TASKID:F:J:L:H[:DIFFS] | og:FILE:J:L:H[:DIFFS] | P<n> | L | R.
    J offset and L length in the collapsed source text, H first 6 hex digits of its sha256. DIFFS = item;item... with item =
    Q=w<percent encoded raw whitespace run> (raw text of a collapsed space: whitespace and escape forms of whitespace only) or
    Q=<letter> with letter in e E u U: position Q of the span is written as an escape and the letter says how: e = short JSON escape
    where one exists (quote, backslash, slash, backspace) else backslash u and 4 lower case hex digits; E = the same with upper case
    hex digits; u = backslash u lower case hex for any character; U = upper case. The payload never holds the character itself.
    A position whose written form is none of these (for example mixed case hex digits) is not expressible: the trace is left out
    (left-out-payload).
Other left out kinds: left-out-email, left-out-graph, left-out-serialiser.
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import quote, unquote

import redact_traces as V1
import redact_traces_v2 as V2
import redact_traces_v3 as V3
from redact_traces import CLOSE, OPEN, PathRules, RedactionError, load_path_rules, load_tasks, location, serialise, sha256, task_id_of, uses_graph_tools, walk
from redact_traces_v2 import LeftOut, real_email_count

TAG = "RDX4"
PH_RE = re.compile(OPEN + TAG + r":([^" + CLOSE + r"]*)" + CLOSE)
MIN_SPAN = 40
OWN_MIN = 20
SHIFT = V3.SHIFT
MAX_PASSES = 6
OWN_CODES = ("ps", "ht")
FIELD_KEY = V3.FIELD_KEY
FIELD_ORDER = V3.FIELD_ORDER
STAT_KEYS = V3.STAT_KEYS
ESC_RE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})')
ESC_MAP = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", '"': '"', "\\": "\\", "/": "/"}
SHORT = {'"': '"', "\\": "\\", "/": "/", "\b": "b"}


# ------------------------------------------------------------------ text views
def unescape32(text):
    return ESC_RE.sub(lambda m: ESC_MAP.get(m.group(1)) or chr(int(m.group(1)[1:], 16)), text)


def views(s):
    """The string and its unescape passes up to the fixpoint (at most MAX_PASSES passes)."""
    out, t = [s], s
    for _ in range(MAX_PASSES):
        u = unescape32(t)
        if u == t:
            break
        out.append(u)
        t = u
    return out


def logical_chars(text, esc):
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if esc and c == "\\" and i + 1 < n:
            d = text[i + 1]
            if d in ESC_MAP:
                out.append((ESC_MAP[d], text[i:i + 2])); i += 2; continue
            if d == "u" and i + 6 <= n and re.fullmatch(r"[0-9a-fA-F]{4}", text[i + 2:i + 6]):
                cp = int(text[i + 2:i + 6], 16)
                if not 0xD800 <= cp <= 0xDFFF:
                    out.append((chr(cp), text[i:i + 6])); i += 6; continue
        out.append((c, c)); i += 1
    return out


def normalise(text, esc):
    chars, raws, run = [], [], []
    for ch, raw in logical_chars(text, esc):
        if ch.isspace():
            run.append(raw)
            continue
        if run:
            chars.append(" "); raws.append("".join(run)); run = []
        chars.append(ch); raws.append(raw)
    if run:
        chars.append(" "); raws.append("".join(run))
    return "".join(chars), raws


def collapse(text):
    return " ".join(text.split())


# ------------------------------------------------------------------ protected sources
class Corpus(V3.Corpus):
    """Version 3 corpus whose index leaves out windows that start with a leading or end with a trailing collapsed space of a source."""

    def add(self, src):
        sid = len(self.sources)
        self.sources.append(src)
        nf = src.nf
        if len(nf) >= 1 << SHIFT:
            raise RedactionError("a protected text is too long for the index")
        lo = 1 if nf.startswith(" ") else 0
        hi = len(nf) - 1 if nf.endswith(" ") else len(nf)
        idx = self.index
        for j in range(lo, hi - MIN_SPAN + 1):
            g = nf[j:j + MIN_SPAN]
            v = (sid << SHIFT) | j
            cur = idx.get(g)
            if cur is None:
                idx[g] = v
            elif isinstance(cur, int):
                idx[g] = [cur, v]
            else:
                cur.append(v)


def own20_index(corpus, tid):
    idx = {}
    for src in corpus.sources:
        if src.task_id == tid and src.code in OWN_CODES:
            for j in range(0, len(src.nf) - OWN_MIN + 1):
                idx.setdefault(src.nf[j:j + OWN_MIN], []).append((src, j))
    return idx


def window_flags(ns, windows, paths):
    """Windows that are not wholly inside the path part of a token (rule 2)."""
    if not windows:
        return []
    pre = V3.path_cover(ns, paths)
    return [i for i in windows if pre[i + MIN_SPAN] - pre[i] < MIN_SPAN]


def runs_of(positions):
    runs = []
    for i in positions:
        if runs and runs[-1][1] == i - 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return [(a, b) for a, b in runs]


# ------------------------------------------------------------------ run finding shared by the redactor and the audits
def own_runs(v, idx):
    """Runs of 20 character windows of the own statement or hints; yields (source, start, end), end spaces dropped, length >= 20."""
    wins = [i for i in range(0, len(v) - OWN_MIN + 1) if v[i:i + OWN_MIN] in idx]
    for a, b in runs_of(wins):
        src = idx[v[a:a + OWN_MIN]][0][0]
        lo, hi = a, b + OWN_MIN
        while lo < hi and v[lo] == " ":
            lo += 1
        while hi > lo and v[hi - 1] == " ":
            hi -= 1
        if hi - lo >= OWN_MIN:
            yield src, lo, hi


def std_runs(v, corpus, paths, tid):
    """Runs of 40 character windows per protected source other than the own statement and hints (rules 2 and 3)."""
    from collections import defaultdict
    pos = defaultdict(list)
    for i in range(0, len(v) - MIN_SPAN + 1):
        val = corpus.index.get(v[i:i + MIN_SPAN])
        if val is None:
            continue
        for x in ((val,) if isinstance(val, int) else val):
            pos[x >> SHIFT].append(i)
    if not pos:
        return
    pre = V3.path_cover(v, paths)
    for sid, ps in pos.items():
        src = corpus.sources[sid]
        if src.task_id == tid and src.code in OWN_CODES:
            continue
        ps = [i for i in ps if pre[i + MIN_SPAN] - pre[i] < MIN_SPAN]
        for a, b in runs_of(ps):
            lo, hi = a, b + MIN_SPAN
            while lo < hi and v[lo] == " ":
                lo += 1
            while hi > lo and v[hi - 1] == " ":
                hi -= 1
            if hi - lo >= MIN_SPAN:
                yield src, lo, hi


def find_runs(v, corpus, paths, tid, idx):
    """('own', source, a, b) for the own statement and hints and ('std', source, a, b) for the rest."""
    for src, a, b in own_runs(v, idx):
        yield "own", src, a, b
    for src, a, b in std_runs(v, corpus, paths, tid):
        yield "std", src, a, b


def residual_hits(obj, corpus, tid, snap, paths):
    """Hits that remain in the strings of obj in the views of depth 0 to the fixpoint; returns a list of (depth, location, kind, length)."""
    idx = own20_index(corpus, tid)
    memo, out = {}, []
    for loc, s in V2.A.strings_of(obj):
        if len(s) < OWN_MIN:
            continue
        for depth, text in enumerate(views(s)):
            v = collapse(text)
            for kind, src, a, b in find_runs(v, corpus, paths, tid, idx):
                if kind == "std" and snap is not None:
                    span = v[a:b]
                    if span not in memo:
                        memo[span] = span in snap
                    if memo[span]:
                        continue
                out.append((depth, loc, kind, b - a))
    return out


# ------------------------------------------------------------------ payload
def render(c, letter):
    """Written form of the character c for the payload letter, or None when the letter cannot write c."""
    if letter in "eE":
        if c in SHORT:
            return "\\" + SHORT[c]
        if ord(c) > 0xFFFF or 0xD800 <= ord(c) <= 0xDFFF:
            return None
        return "\\u%04x" % ord(c) if letter == "e" else "\\u%04X" % ord(c)
    if ord(c) > 0xFFFF or 0xD800 <= ord(c) <= 0xDFFF:
        return None
    return "\\u%04x" % ord(c) if letter == "u" else "\\u%04X" % ord(c)


def whitespace_only(raw):
    t = raw
    for _ in range(MAX_PASSES):
        u = unescape32(t)
        if u == t:
            break
        t = u
    return bool(t) and all(ch.isspace() for ch in t)


def encode_span(src, j, length, raws):
    diffs = []
    for q in range(length):
        c, default, raw = src.nf[j + q], src.fraw[j + q], raws[q]
        if raw == default:
            continue
        if c == " ":
            if not whitespace_only(raw):
                raise LeftOut("left-out-payload", "a whitespace position is written with other characters")
            diffs.append("%d=w%s" % (q, quote(raw, safe="")))
            continue
        for letter in "eEuU":
            if render(c, letter) == raw:
                diffs.append("%d=%s" % (q, letter))
                break
        else:
            raise LeftOut("left-out-payload", "a character is written in a form that the payload letters cannot express")
    if src.task_id is None:
        head = "og:" + quote(src.label, safe="")
    else:
        head = "t:%s:%s" % (quote(src.task_id, safe=""), src.code)
    code = "%s:%d:%d:%s" % (head, j, length, src.hash6)
    if diffs:
        code += ":" + ";".join(diffs)
    return OPEN + TAG + ":" + code + CLOSE


# ------------------------------------------------------------------ redaction of one view
class Context:
    def __init__(self, corpus, own_tid, snap_text, paths):
        self.corpus, self.own, self.snap, self.paths = corpus, own_tid, snap_text, paths
        self.own20 = own20_index(corpus, own_tid)
        self.cache = {}

    def exempt(self, span):
        if self.snap is None:
            return False
        if span not in self.cache:
            self.cache[span] = span in self.snap
        return self.cache[span]


def own_tiles(ns, ctx, stats):
    if not ctx.own20:
        return []
    wins = [i for i in range(0, len(ns) - OWN_MIN + 1) if ns[i:i + OWN_MIN] in ctx.own20]
    tiles, pos = [], 0
    for w0, w1 in runs_of(wins):
        b_raw = w1 + OWN_MIN
        p = max(w0, pos)
        while b_raw - p >= OWN_MIN:
            q = p
            while b_raw - q > OWN_MIN and ns[q] == " ":
                q += 1
            if q != p and ns[q:q + OWN_MIN] in ctx.own20:
                p = q
            best = None
            for src, j in ctx.own20.get(ns[p:p + OWN_MIN], ()):
                limit = min(b_raw - p, len(src.nf) - j)
                length = OWN_MIN
                while length < limit and ns[p + length] == src.nf[j + length]:
                    length += 1
                key = (-length, OWN_CODES.index(src.code))
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
            if tb - ta < OWN_MIN:
                p += 1
                continue
            tiles.append((ta, tb, src, tj))
            stats["n_" + V3.stat_key(src, ctx.own)] += 1
            p = pos = p + length
    return tiles


def redact_view(text, ctx, esc, stats):
    ns, raws = normalise(text, esc)
    corpus = ctx.corpus
    tiles = own_tiles(ns, ctx, stats)
    blocked = bytearray(len(ns))
    for ta, tb, _, _ in tiles:
        for q in range(ta, tb):
            blocked[q] = 1
    windows = [i for i in range(0, len(ns) - MIN_SPAN + 1) if ns[i:i + MIN_SPAN] in corpus.index]
    if windows and tiles:
        pre = [0]
        for b in blocked:
            pre.append(pre[-1] + b)
        windows = [i for i in windows if pre[i + MIN_SPAN] - pre[i] == 0]
    if not windows and not tiles:
        return [(False, text)]
    pos = 0
    for w0, w1 in runs_of(window_flags(ns, windows, ctx.paths)):
        a_raw, b_raw = w0, w1 + MIN_SPAN
        a, b = a_raw, b_raw
        while a < b and ns[a] == " ":
            a += 1
        while b > a and ns[b - 1] == " ":
            b -= 1
        if b - a < MIN_SPAN or ctx.exempt(ns[a:b]):
            continue
        p = max(a_raw, pos)
        while b_raw - p >= MIN_SPAN:
            best = None
            for v in corpus.entries(ns[p:p + MIN_SPAN]):
                src, j = corpus.sources[v >> SHIFT], v & ((1 << SHIFT) - 1)
                if src.task_id == ctx.own and src.code in OWN_CODES:
                    continue
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
            tiles.append((ta, tb, src, tj))
            stats["n_" + V3.stat_key(src, ctx.own)] += 1
            pos, p = tb, p + length
    out, pos = [], 0
    for ta, tb, src, tj in sorted(tiles, key=lambda t: t[0]):
        if ta > pos:
            out.append((False, "".join(raws[pos:ta])))
        out.append((True, encode_span(src, tj, tb - ta, raws[ta:tb])))
        stats["removed_" + V3.stat_key(src, ctx.own)] += len("".join(raws[ta:tb]))
        pos = tb
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
            if is_ph or len(seg) < OWN_MIN:
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
    stats = V3.new_stats()

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
    left = residual_hits(red, corpus, task_id, snap_text, paths)
    if left:
        depths = sorted({d for d, _, _, _ in left})
        raise LeftOut("left-out-residual", "%d residual hit(s) at depth(s) %s" % (len(left), ",".join(str(d) for d in depths)))
    return serialise(red), stats


# ------------------------------------------------------------------ restore
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
        if j + length > len(src.fraw):
            raise RedactionError("placeholder outside the source text")
        diffs = {}
        if len(rest) == 4 and rest[3]:
            for item in rest[3].split(";"):
                q, val = item.split("=", 1)
                q = int(q)
                if val[:1] == "w":
                    diffs[q] = unquote(val[1:])
                elif val in ("e", "E", "u", "U"):
                    written = render(src.nf[j + q], val)
                    if written is None:
                        raise RedactionError("a payload letter cannot write this character")
                    diffs[q] = written
                else:
                    raise RedactionError("unknown payload item %r" % item)
        return "".join(diffs.get(q, src.fraw[j + q]) for q in range(length))
    return PH_RE.sub(one, text)


def restore_trace_bytes(raw, tasks, task_id, rules=None, organiser_folder=None, rs=None):
    if task_id not in tasks:
        raise RedactionError("task id %r is not in the task file; nothing is restored" % task_id)
    rs = rs or V3.RestoreSources(tasks, organiser_folder)
    rules = rules or PathRules()
    return serialise(walk(json.loads(raw.decode("utf-8")), lambda s, path: restore_string(s, rs, rules)))


# ------------------------------------------------------------------ command line
COLUMNS = V3.COLUMNS


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
    snapshots = V3.SnapshotStore(a.snapshots) if a.snapshots else None
    files = [a.inp] if os.path.isfile(a.inp) else sorted(os.path.join(a.inp, f) for f in os.listdir(a.inp) if f.endswith(".json"))
    os.makedirs(a.out, exist_ok=True)
    rows = ["\t".join(COLUMNS)]
    blanks = [""] * (len(COLUMNS) - 7)
    no_task = 0
    for f in files:
        tid, name = task_id_of(f), os.path.basename(f)
        with open(f, "rb") as fh:
            raw = fh.read()
        if tid not in tasks:
            rows.append("\t".join([name, tid, "no-task", sha256(raw)] + blanks + [str(len(raw)), "", "task id not in task file"]))
            no_task += 1
            continue
        try:
            red, st = redact_trace_bytes(raw, tid, corpus, rules, snapshots)
        except LeftOut as e:
            rows.append("\t".join([name, tid, e.kind, sha256(raw)] + blanks + [str(len(raw)), "", str(e)]))
            continue
        except RedactionError as e:
            rows.append("\t".join([name, tid, "left-out-other", sha256(raw)] + blanks + [str(len(raw)), "", str(e)]))
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
