#!/usr/bin/env python3
"""Redact competition task text from agent trace files so that the original bytes can be restored.

Library and command line. Python 3.10+, standard library only.

What is redacted
  Every span of 40 or more characters that a string of the trace shares with the task's problem_statement or
  hints_text (whitespace normalised) is replaced by a placeholder. Strings are the decoded values of the trace JSON
  (all nesting levels). Two views of each string are scanned: the plain text and a view in which JSON escape
  sequences such as \\n and \\" are read as the characters they stand for (tool output often holds JSON text inside JSON).
  Machine paths and host names are replaced by short fixed placeholders.

Placeholder format (documented in README.md)
  U+27E6 "RDX1:" CODE U+27E7
  CODE = ps:J:L:H[:DIFFS] | ht:J:L:H[:DIFFS]   a span of the task field (ps = problem_statement, ht = hints_text)
         J = offset in the normalised field text, L = length, H = first 6 hex digits of sha256 of the normalised field
         DIFFS = Q=RAW;Q=RAW...  the positions Q (0..L-1) where the trace text differs from the field's own text
                 (other whitespace runs or JSON escape sequences); RAW is the exact trace text, percent-encoded
       | P1, P2, ... = the strings of a path rules file in file order (machine paths and host names; the file is private)
       | L, R = a literal U+27E6 or U+27E7 that occurred in the original text
Restoring needs the task file (keyed by the task id in the file name trace_<task id>.json) and nothing else.
Files are written with json.dumps(indent=2); a trace is processed only if that serialiser reproduces the original
file byte for byte, so that restore(redact(x)) == x holds for the file bytes.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from urllib.parse import quote, unquote

MIN_SPAN = 40
OPEN, CLOSE = "⟦", "⟧"
TAG = "RDX1"
FIELD_CODE = {"problem_statement": "ps", "hints_text": "ht"}
CODE_FIELD = {v: k for k, v in FIELD_CODE.items()}
PH_RE = re.compile(OPEN + TAG + r":([^" + CLOSE + r"]*)" + CLOSE)
GRAPH_TOOLS = ("get_code_neighbors", "search_similar_code", "get_code_subgraph")
GRAPH_MARKERS = ("/graphs/", "/embeddings/", "data/graphs", "data/embeddings")
SIMPLE_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}


class RedactionError(Exception):
    pass


class PathRules:
    """Strings (machine paths and host names) replaced by P1, P2, ... in the order given. List a longer
    string before a shorter one that it contains. The list lives in a private JSON file and is not part of any release."""

    def __init__(self, literals=()):
        self.by_lit = {lit: "P%d" % (i + 1) for i, lit in enumerate(literals)}
        self.by_code = {c: lit for lit, c in self.by_lit.items()}
        self.regex = re.compile("|".join(re.escape(lit) for lit in literals)) if literals else None


def load_path_rules(path):
    if not path:
        return PathRules()
    with open(path, encoding="utf-8") as fh:
        lits = json.load(fh)
    if not isinstance(lits, list) or not all(isinstance(x, str) and x for x in lits):
        raise RedactionError("a path rules file holds a JSON list of non-empty strings")
    return PathRules(lits)


# ---------------------------------------------------------------- text views
def logical_chars(text, esc):
    """List of (char, raw) pairs; their raws concatenate to text. With esc, JSON escape sequences are one char."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if esc and c == "\\" and i + 1 < n:
            d = text[i + 1]
            if d in SIMPLE_ESC:
                out.append((SIMPLE_ESC[d], text[i:i + 2])); i += 2; continue
            if d == "u" and i + 6 <= n and re.fullmatch(r"[0-9a-fA-F]{4}", text[i + 2:i + 6]):
                cp = int(text[i + 2:i + 6], 16)
                if not 0xD800 <= cp <= 0xDFFF:
                    out.append((chr(cp), text[i:i + 6])); i += 6; continue
        out.append((c, c)); i += 1
    return out


def normalise(text, esc):
    """Whitespace-normalised view: returns (ns, raws) where raws[k] is the exact source text of ns[k]
    (a whole whitespace run for a space)."""
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


class TaskFields:
    """Normalised text of the fields of one task and the n-gram index used to find shared spans."""

    def __init__(self, task):
        self.task = task
        self.nf, self.fraw, self.hash6, self.index = {}, {}, {}, {}
        for name in FIELD_CODE:
            text = task.get(name) or ""
            if len(text) == 0:
                continue
            ns, raws = normalise(text, esc=False)
            self.nf[name], self.fraw[name] = ns, raws
            self.hash6[name] = hashlib.sha256(ns.encode("utf-8")).hexdigest()[:6]
            idx = {}
            for j in range(0, len(ns) - MIN_SPAN + 1):
                idx.setdefault(ns[j:j + MIN_SPAN], []).append(j)
            self.index[name] = idx

    def longest(self, ns, i):
        """Longest common extension of ns[i:] with any field; returns (length, field, offset) or None."""
        g = ns[i:i + MIN_SPAN]
        if len(g) < MIN_SPAN:
            return None
        best = None
        for name, idx in self.index.items():
            for j in idx.get(g, ()):
                nf, L = self.nf[name], MIN_SPAN
                while i + L < len(ns) and j + L < len(nf) and ns[i + L] == nf[j + L]:
                    L += 1
                if best is None or L > best[0]:
                    best = (L, name, j)
        return best


def encode_span(fields, name, j, length, raws):
    """Placeholder for the span of the field at offset j; raws are the trace's raw texts for the span positions."""
    nf, fraw = fields.nf[name], fields.fraw[name]
    diffs = []
    for q in range(length):
        default = fraw[j + q]
        if raws[q] != default:
            diffs.append("%d=%s" % (q, quote(raws[q], safe="")))
    code = "%s:%d:%d:%s" % (FIELD_CODE[name], j, length, fields.hash6[name])
    if diffs:
        code += ":" + ";".join(diffs)
    return OPEN + TAG + ":" + code + CLOSE


def redact_view(text, fields, esc, stats):
    """Replace shared spans in one text segment; returns a list of (is_placeholder, text)."""
    ns, raws = normalise(text, esc)
    out, pos, i = [], 0, 0          # pos: index in ns up to which output is written
    while i <= len(ns) - MIN_SPAN:
        hit = fields.longest(ns, i)
        if hit is None:
            i += 1
            continue
        length, name, j = hit
        a, b = i, i + length
        while a < b and ns[a] == " ":
            a += 1; j += 1
        while b > a and ns[b - 1] == " ":
            b -= 1
        if b - a < MIN_SPAN:
            i += 1
            continue
        length = b - a
        if a > pos:
            out.append((False, "".join(raws[pos:a])))
        out.append((True, encode_span(fields, name, j, length, raws[a:b])))
        stats["raw_removed"] += len("".join(raws[a:b]))
        stats[FIELD_CODE[name]] += 1
        pos, i = b, b
    if pos < len(ns):
        out.append((False, "".join(raws[pos:])))
    return out


def _escape_brackets(seg):
    # explicit and simple: escape each bracket character exactly once
    return "".join(OPEN + TAG + ":L" + CLOSE if c == OPEN else OPEN + TAG + ":R" + CLOSE if c == CLOSE else c for c in seg)


def redact_string(text, fields, stats, rules):
    segs = [(False, text)]
    for esc in (False, True):
        nxt = []
        for is_ph, seg in segs:
            if is_ph or len(seg) < MIN_SPAN:
                nxt.append((is_ph, seg))
            else:
                nxt.extend(redact_view(seg, fields, esc, stats))
        segs = nxt
    out = []
    for is_ph, seg in segs:
        if is_ph:
            out.append(seg)
            continue

        def paths(m):
            stats["paths"] += 1
            return OPEN + TAG + ":" + rules.by_lit[m.group(0)] + CLOSE
        # paths first (they contain no brackets), then brackets of the remaining text; markers are skipped by splitting
        parts, last = [], 0
        for m in (rules.regex.finditer(seg) if rules.regex else ()):
            parts.append(_escape_brackets(seg[last:m.start()]))
            parts.append(paths(m))
            last = m.end()
        parts.append(_escape_brackets(seg[last:]))
        out.append("".join(parts))
    return "".join(out)


def walk(obj, fn, path=()):
    if isinstance(obj, dict):
        return {k: walk(v, fn, path + (k,)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [walk(v, fn, path + (i,)) for i, v in enumerate(obj)]
    if isinstance(obj, str):
        return fn(obj, path)
    return obj


def location(path):
    """Coarse location of a string inside a trace: source of the step and the step key."""
    return path[2] if len(path) > 2 and path[0] == "steps" else "/".join(str(p) for p in path[:1])


# ---------------------------------------------------------------- trace level
def task_id_of(filename):
    base = os.path.basename(filename)
    m = re.fullmatch(r"trace_(.+)\.json", base)
    if not m:
        raise RedactionError("file name %r does not look like trace_<task id>.json" % base)
    return m.group(1)


def load_tasks(path):
    tasks = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                t = json.loads(line)
                tasks[t["instance_id"]] = t
    return tasks


def serialise(obj):
    return json.dumps(obj, indent=2).encode("utf-8")


def uses_graph_tools(obj):
    found = []

    def look(s, path):
        if any(m in s for m in GRAPH_MARKERS):
            found.append(path)
        return s
    for st in obj.get("steps", []):
        for c in st.get("tool_calls") or []:
            if c.get("function_name") in GRAPH_TOOLS:
                found.append(("tool", c.get("function_name")))
    walk(obj, look)
    return found


def redact_trace_bytes(raw, task, rules=None):
    """Returns (redacted bytes, stats). Raises RedactionError when the file cannot be handled exactly."""
    obj = json.loads(raw.decode("utf-8"))
    if serialise(obj) != raw:
        raise RedactionError("json.dumps(indent=2) does not reproduce this file")
    graph = uses_graph_tools(obj)
    if graph:
        raise RedactionError("graph tools: %r" % (graph[:3],))
    fields = TaskFields(task)
    rules = rules or PathRules()
    stats = {"ps": 0, "ht": 0, "paths": 0, "raw_removed": 0, "by_location": {}}

    def fn(s, path):
        before = (stats["ps"], stats["ht"])
        r = redact_string(s, fields, stats, rules)
        added = (stats["ps"] - before[0]) + (stats["ht"] - before[1])
        if added:
            key = "%s:%s" % (obj["steps"][path[1]]["source"] if path[0] == "steps" else path[0], location(path))
            stats["by_location"][key] = stats["by_location"].get(key, 0) + added
        return r
    red = walk(obj, fn)
    return serialise(red), stats


def restore_string(text, tasks_fields, task_id, rules):
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
        parts = code.split(":", 4)
        if len(parts) < 4 or parts[0] not in CODE_FIELD:
            raise RedactionError("unknown placeholder %r" % code)
        name = CODE_FIELD[parts[0]]
        fields = tasks_fields(task_id)
        if name not in fields.nf:
            raise RedactionError("task %s has no %s to restore from" % (task_id, name))
        j, length, h6 = int(parts[1]), int(parts[2]), parts[3]
        if fields.hash6[name] != h6:
            raise RedactionError("task file differs from the one used for redaction (%s of %s)" % (name, task_id))
        diffs = {}
        if len(parts) == 5 and parts[4]:
            for item in parts[4].split(";"):
                q, raw = item.split("=", 1)
                diffs[int(q)] = unquote(raw)
        fraw = fields.fraw[name]
        if j + length > len(fraw):
            raise RedactionError("placeholder outside the field text")
        return "".join(diffs.get(q, fraw[j + q]) for q in range(length))
    return PH_RE.sub(one, text)


def restore_trace_bytes(raw, tasks, task_id, rules=None):
    if task_id not in tasks:
        raise RedactionError("task id %r is not in the task file; nothing is restored" % task_id)
    cache = {}

    def tf(tid):
        if tid not in cache:
            cache[tid] = TaskFields(tasks[tid])
        return cache[tid]
    obj = json.loads(raw.decode("utf-8"))
    rules = rules or PathRules()
    out = walk(obj, lambda s, path: restore_string(s, tf, task_id, rules))
    return serialise(out)


def sha256(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- command line
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tasks", required=True, help="the competition's public task file (tasks.jsonl)")
    ap.add_argument("--in", dest="inp", required=True, help="a trace file or a folder with trace_<task id>.json files")
    ap.add_argument("--out", required=True, help="output folder (created; existing files are not overwritten)")
    ap.add_argument("--manifest", required=True, help="manifest tsv to write")
    ap.add_argument("--path-rules", help="private JSON list of machine paths and host names to replace by P1, P2, ...")
    a = ap.parse_args(argv)
    rules = load_path_rules(a.path_rules)
    tasks = load_tasks(a.tasks)
    files = [a.inp] if os.path.isfile(a.inp) else sorted(os.path.join(a.inp, f) for f in os.listdir(a.inp) if f.endswith(".json"))
    os.makedirs(a.out, exist_ok=True)
    rows = ["file\ttask_id\tstatus\tsha256_original\tsha256_redacted\tplaceholders_ps\tplaceholders_ht\tpath_placeholders\traw_chars_removed\tbytes_original\tbytes_redacted\tdetail"]
    bad = 0
    for f in files:
        tid = task_id_of(f)
        with open(f, "rb") as fh:
            raw = fh.read()
        if tid not in tasks:
            rows.append("\t".join([os.path.basename(f), tid, "no-task", sha256(raw), "", "", "", "", "", str(len(raw)), "", "task id not in task file"])); bad += 1
            continue
        try:
            red, st = redact_trace_bytes(raw, tasks[tid], rules)
        except RedactionError as e:
            rows.append("\t".join([os.path.basename(f), tid, "left-out", sha256(raw), "", "", "", "", "", str(len(raw)), "", str(e)])); bad += 1
            continue
        dst = os.path.join(a.out, os.path.basename(f))
        if os.path.exists(dst):
            raise SystemExit("refusing to overwrite " + dst)
        with open(dst, "wb") as fh:
            fh.write(red)
        rows.append("\t".join([os.path.basename(f), tid, "redacted", sha256(raw), sha256(red), str(st["ps"]), str(st["ht"]), str(st["paths"]),
                               str(st["raw_removed"]), str(len(raw)), str(len(red)), json.dumps(st["by_location"], sort_keys=True)]))
    open(a.manifest, "w", encoding="utf-8", newline="\n").write("\n".join(rows) + "\n")
    print("processed %d files, %d not redacted" % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
