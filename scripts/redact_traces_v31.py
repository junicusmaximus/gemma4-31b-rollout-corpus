#!/usr/bin/env python3
"""Redactor version 3.1: version 3 plus a stricter rule for the trace's OWN task. Python 3.10+, standard library only.
Versions 1 to 3 stay unchanged; this file imports version 3 and keeps its placeholder format (tag RDX3), so restore_traces_v3.py
restores the output of this program.

Own task rule (new)
  Every span of 20 or more characters (decoded, whitespace normalised, plain and escape aware view) that a string of the trace
  shares with the problem statement or the hints of the trace's OWN task is replaced by placeholders. There is NO exemption for
  it: not for paths and not for text that also occurs in the snapshot of the task. A prompt that holds the whole statement gets
  one placeholder that covers the whole field (offset 0 and the full length) when the statement is quoted without change.
Everything else is as in version 3 (threshold 40 for the gold patch and the test patch of the own task and for all sources of other
tasks and for the organiser's files; exemptions: own snapshot contents and own snapshot paths).
A statement or hints fragment of fewer than 20 characters is not touched.
Usage as redact_traces_v3.py.
"""
import sys

import redact_traces_v3 as V3
from redact_traces import MIN_SPAN, OPEN, PathRules, location, normalise, serialise, uses_graph_tools, walk
from redact_traces_v2 import LeftOut, real_email_count

OWN_MIN = 20
OWN_CODES = ("ps", "ht")


class Context31(V3.Context):
    def __init__(self, corpus, own_tid, snap_text, paths):
        super().__init__(corpus, own_tid, snap_text, paths)
        self.own20 = {}
        for src in corpus.sources:
            if src.task_id == own_tid and src.code in OWN_CODES:
                for j in range(0, len(src.nf) - OWN_MIN + 1):
                    self.own20.setdefault(src.nf[j:j + OWN_MIN], []).append((src, j))


def own_tiles(ns, ctx, stats):
    """Tiles (start, end, source, offset) for the own statement and hints (20 characters, no exemption)."""
    if not ctx.own20:
        return []
    windows = [i for i in range(0, len(ns) - OWN_MIN + 1) if ns[i:i + OWN_MIN] in ctx.own20]
    runs = []
    for i in windows:
        if runs and runs[-1][1] == i - 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    tiles, pos = [], 0
    for w0, w1 in runs:
        b_raw = w1 + OWN_MIN
        p = max(w0, pos)
        while b_raw - p >= OWN_MIN:
            q = p
            while b_raw - q > OWN_MIN and ns[q] == " ":      # a leading space is never part of a tile; look up the first character after it
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
            k = V3.stat_key(src, ctx.own)
            stats["n_" + k] += 1
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
    for w0, w1 in (V3.valid_runs(ns, windows, ctx.paths) if windows else ()):
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
                src, j = corpus.sources[v >> V3.SHIFT], v & ((1 << V3.SHIFT) - 1)
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
        out.append((True, V3.encode_span(src, tj, tb - ta, raws[ta:tb])))
        stats["removed_" + V3.stat_key(src, ctx.own)] += len("".join(raws[ta:tb]))
        pos = tb
    if pos < len(ns):
        out.append((False, "".join(raws[pos:])))
    return out


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
            parts.append(V3._escape_brackets(seg[last:m.start()]))
            parts.append(OPEN + V3.TAG + ":" + rules.by_lit[m.group(0)] + V3.CLOSE)
            stats["paths"] += 1
            last = m.end()
        parts.append(V3._escape_brackets(seg[last:]))
        out.append("".join(parts))
    return "".join(out)


def redact_trace_bytes(raw, task_id, corpus, rules=None, snapshots=None):
    """Returns (redacted bytes, stats). Raises LeftOut when the trace must not be released."""
    import json
    obj = json.loads(raw.decode("utf-8"))
    if serialise(obj) != raw:
        raise LeftOut("left-out-serialiser", "json.dumps(indent=2) does not reproduce this file")
    graph = uses_graph_tools(obj)
    if graph:
        raise LeftOut("left-out-graph", "graph tools: %r" % (graph[:3],))
    snap_text, paths = snapshots.get(task_id) if snapshots else (None, None)
    ctx = Context31(corpus, task_id, snap_text, paths)
    rules = rules or PathRules()
    stats = V3.new_stats()

    def fn(s, path):
        before = sum(stats["n_" + k] for k in V3.STAT_KEYS)
        r = redact_string(s, ctx, stats, rules)
        added = sum(stats["n_" + k] for k in V3.STAT_KEYS) - before
        if added:
            key = "%s:%s" % (obj["steps"][path[1]]["source"] if path[0] == "steps" else path[0], location(path))
            stats["by_location"][key] = stats["by_location"].get(key, 0) + added
        return r
    red = walk(obj, fn)
    n = real_email_count(red)
    if n:
        raise LeftOut("left-out-email", "%d e-mail address(es) not of an example domain" % n)
    return serialise(red), stats


def main(argv=None):
    saved = V3.redact_trace_bytes
    V3.redact_trace_bytes = redact_trace_bytes        # the command line of version 3 then runs this rule
    try:
        return V3.main(argv)
    finally:
        V3.redact_trace_bytes = saved


if __name__ == "__main__":
    sys.exit(main())
