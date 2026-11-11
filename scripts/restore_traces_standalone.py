#!/usr/bin/env python3
"""Restore redacted trace files (placeholder tag RDX3) to the original bytes. One file, Python 3.10+, standard library only.

Needs the competition's public task file (tasks.jsonl) and, when a trace holds organiser placeholders, the organiser's sample submission
folder. Neither is part of this dataset. A task id that is not in the task file is an error and nothing is restored for it.

Machine path placeholders (P1, P2, ...) stand for strings of a private file that is not published. Without that file such a
placeholder stays as it is, and the file is reported as "partly restored" (its sha256 is then not compared with the manifest).

Usage:
  python3 restore_traces.py --tasks tasks.jsonl --in REDACTED_DIR --out RESTORED_DIR [--manifest TRACES_MANIFEST.tsv] [--organiser DIR] [--path-rules FILE]
The manifest is a tab separated file whose first column is the file name and whose fourth column is sha256_original (header line first).
"""
import argparse
import hashlib
import json
import os
import re
import sys
from urllib.parse import unquote

OPEN, CLOSE = "⟦", "⟧"
PH_RE = re.compile(OPEN + "RDX3:([^" + CLOSE + "]*)" + CLOSE)
FIELD_KEY = {"ps": "problem_statement", "ht": "hints_text", "pa": "patch", "tp": "test_patch"}
ORGANISER_EXT = (".md", ".txt", ".yaml", ".yml", ".py", ".json")


class RestoreError(Exception):
    pass


def normalise(text):
    """Whitespace normalised text and, for each of its characters, the exact source text (a whole whitespace run for a space)."""
    chars, raws, run = [], [], []
    for ch in text:
        if ch.isspace():
            run.append(ch)
            continue
        if run:
            chars.append(" "); raws.append("".join(run)); run = []
        chars.append(ch); raws.append(ch)
    if run:
        chars.append(" "); raws.append("".join(run))
    return "".join(chars), raws


class Source:
    def __init__(self, text):
        self.nf, self.fraw = normalise(text)
        self.hash6 = hashlib.sha256(self.nf.encode("utf-8")).hexdigest()[:6]


class Sources:
    def __init__(self, tasks, organiser_folder=None):
        self.tasks, self.cache, self.org = tasks, {}, None
        if organiser_folder:
            self.org = {}
            for root, _, files in os.walk(organiser_folder):
                for f in files:
                    if f.endswith(ORGANISER_EXT):
                        p = os.path.join(root, f)
                        with open(p, "rb") as fh:
                            data = fh.read()
                        if b"\x00" not in data[:2000]:
                            self.org[os.path.relpath(p, organiser_folder).replace(os.sep, "/")] = data.decode("utf-8", "ignore")

    def task_field(self, tid, code):
        if (tid, code) not in self.cache:
            if tid not in self.tasks:
                raise RestoreError("task id %r of a placeholder is not in the task file" % tid)
            text = self.tasks[tid].get(FIELD_KEY[code]) or ""
            if not text:
                raise RestoreError("task %s has no %s to restore from" % (tid, code))
            self.cache[(tid, code)] = Source(text)
        return self.cache[(tid, code)]

    def organiser(self, label):
        if self.org is None:
            raise RestoreError("an organiser placeholder needs the organiser's sample submission folder (--organiser)")
        if label not in self.org:
            raise RestoreError("organiser file %s is not in the organiser folder" % label)
        if ("og", label) not in self.cache:
            self.cache[("og", label)] = Source(self.org[label])
        return self.cache[("og", label)]


def restore_string(text, srcs, path_rules, left):
    def one(m):
        code = m.group(1)
        if code == "L":
            return OPEN
        if code == "R":
            return CLOSE
        if re.fullmatch(r"P[0-9]+", code):
            if path_rules is None:
                left.append(code)
                return m.group(0)
            if code not in path_rules:
                raise RestoreError("placeholder %s is not in the path rules file" % code)
            return path_rules[code]
        head = code.split(":", 1)[0]
        if head == "og":
            parts = code.split(":", 5)
            if len(parts) < 5:
                raise RestoreError("unknown placeholder %r" % code)
            src, rest = srcs.organiser(unquote(parts[1])), parts[2:]
        elif head == "t":
            parts = code.split(":", 6)
            if len(parts) < 6 or parts[2] not in FIELD_KEY:
                raise RestoreError("unknown placeholder %r" % code)
            src, rest = srcs.task_field(unquote(parts[1]), parts[2]), parts[3:]
        else:
            raise RestoreError("unknown placeholder %r" % code)
        j, length, h6 = int(rest[0]), int(rest[1]), rest[2]
        if src.hash6 != h6:
            raise RestoreError("the task file or the organiser file differs from the one used for redaction")
        diffs = {}
        if len(rest) == 4 and rest[3]:
            for item in rest[3].split(";"):
                q, raw = item.split("=", 1)
                diffs[int(q)] = unquote(raw)
        if j + length > len(src.fraw):
            raise RestoreError("a placeholder points outside the source text")
        return "".join(diffs.get(q, src.fraw[j + q]) for q in range(length))
    return PH_RE.sub(one, text)


def walk(obj, fn):
    if isinstance(obj, dict):
        return {k: walk(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [walk(v, fn) for v in obj]
    return fn(obj) if isinstance(obj, str) else obj


def restore_bytes(raw, tasks, task_id, srcs, path_rules=None):
    """Returns (restored bytes, list of machine path placeholders that stayed)."""
    if task_id not in tasks:
        raise RestoreError("task id %r is not in the task file; nothing is restored" % task_id)
    left = []
    obj = walk(json.loads(raw.decode("utf-8")), lambda s: restore_string(s, srcs, path_rules, left))
    return json.dumps(obj, indent=2).encode("utf-8"), left


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--in", dest="inp", required=True, help="a redacted trace file or a folder of them")
    ap.add_argument("--out", required=True, help="output folder (existing files are not overwritten)")
    ap.add_argument("--manifest")
    ap.add_argument("--organiser")
    ap.add_argument("--path-rules", help="private JSON list of the strings behind P1, P2, ... (not published)")
    a = ap.parse_args(argv)
    tasks = {}
    with open(a.tasks, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                t = json.loads(line)
                tasks[t["instance_id"]] = t
    path_rules = None
    if a.path_rules:
        with open(a.path_rules, encoding="utf-8") as fh:
            path_rules = {"P%d" % (i + 1): s for i, s in enumerate(json.load(fh))}
    srcs = Sources(tasks, a.organiser)
    expected = {}
    if a.manifest:
        with open(a.manifest, encoding="utf-8") as fh:
            for line in fh.read().split("\n")[1:]:
                if line:
                    p = line.split("\t")
                    expected[p[0]] = p[3]
    files = [a.inp] if os.path.isfile(a.inp) else sorted(os.path.join(a.inp, f) for f in os.listdir(a.inp) if f.endswith(".json"))
    os.makedirs(a.out, exist_ok=True)
    errors = partly = 0
    for f in files:
        name = os.path.basename(f)
        try:
            m = re.fullmatch(r"trace_(.+)\.json", name)
            if not m:
                raise RestoreError("file name does not look like trace_<task id>.json")
            with open(f, "rb") as fh:
                restored, left = restore_bytes(fh.read(), tasks, m.group(1), srcs, path_rules)
            if left:
                partly += 1
            elif name in expected and hashlib.sha256(restored).hexdigest() != expected[name]:
                raise RestoreError("sha256 of the restored file differs from the manifest")
        except RestoreError as e:
            print("ERROR %s: %s" % (name, e), file=sys.stderr)
            errors += 1
            continue
        dst = os.path.join(a.out, name)
        if os.path.exists(dst):
            raise SystemExit("refusing to overwrite " + dst)
        with open(dst, "wb") as fh:
            fh.write(restored)
    print("restored %d files (%d partly: machine path placeholders stayed), %d errors" % (len(files) - errors, partly, errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
