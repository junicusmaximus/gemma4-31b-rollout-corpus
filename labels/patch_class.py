#!/usr/bin/env python3
"""Patch class of a valid rollout, rule 7 of paper2-analysis-rules-FROZEN-2026-11-10.md (sha256 1db9126b...1932c).

Classes: resolved | no patch | scratch only | no gold file | gold file touched; plus gold_file_hit (bool).
File names come from diff headers only; a/ and b/ prefixes are stripped; a rename touches both names.
Gold file lists are kept in memory only; output rows carry no file names.

Usage (no globs; every path explicit):
  CUDA_VISIBLE_DEVICES="" python3 patch_class.py --tasks TASKS.jsonl --out OUT.csv \
      --set NAME:SEED:RESULTS_JSONL:PATCH_DIR [--set ...]
Rollouts are rows of RESULTS_JSONL whose `resolved` is a boolean (rule 1). The agent's patch of a row is
PATCH_DIR/<instance_id>.patch. Flags column: 'patch_not_stored', 'size_field_nonzero_but_empty',
'deletion_only' (literal reading applied, see README).
"""
import argparse
import csv
import json
import os
import re
import sys

DEV_NULL = '/dev/null'
GIT_RE = re.compile(r'^diff --git (\S+) (\S+)$')


def strip_prefix(p):
    p = p.strip()
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    if p == DEV_NULL:
        return DEV_NULL
    if p.startswith('a/') or p.startswith('b/'):
        return p[2:]
    return p


def parse_entries(patch_text):
    """List of file entries: dict(old, new, is_new, is_deleted). Header lines only."""
    entries = []
    cur = None
    in_hunk = False
    for line in patch_text.splitlines():
        m = GIT_RE.match(line)
        if m:
            in_hunk = False
            cur = {'old': strip_prefix(m.group(1)), 'new': strip_prefix(m.group(2)), 'is_new': False, 'is_deleted': False}
            entries.append(cur)
            continue
        if line.startswith('@@'):
            in_hunk = True
            continue
        if in_hunk:
            continue  # hunk body: content lines, never headers (git diffs only)
        if line.startswith('--- ') or line.startswith('+++ '):
            side = strip_prefix(line[4:].split('\t')[0])
            if cur is None or (line.startswith('--- ') and cur.get('_seen_minus')):
                cur = {'old': None, 'new': None, 'is_new': False, 'is_deleted': False}
                entries.append(cur)
            if line.startswith('--- '):
                cur['_seen_minus'] = True
                cur['old'] = side
                cur['is_new'] = cur['is_new'] or side == DEV_NULL
            else:
                cur['new'] = side
                cur['is_deleted'] = cur['is_deleted'] or side == DEV_NULL
            continue
        if cur is None:
            continue
        if line.startswith('new file mode'):
            cur['is_new'] = True
        elif line.startswith('deleted file mode'):
            cur['is_deleted'] = True
        elif line.startswith('rename from '):
            cur['old'] = strip_prefix(line[len('rename from '):])
        elif line.startswith('rename to '):
            cur['new'] = strip_prefix(line[len('rename to '):])
        elif line.startswith('Binary files '):
            m2 = re.match(r'^Binary files (.+) and (.+) differ$', line)
            if m2:
                cur['old'] = strip_prefix(m2.group(1))
                cur['new'] = strip_prefix(m2.group(2))
                cur['is_new'] = cur['is_new'] or cur['old'] == DEV_NULL
    for e in entries:
        e.pop('_seen_minus', None)
        if e['is_new']:
            e['old'] = DEV_NULL
        if e['is_deleted']:
            e['new'] = DEV_NULL
    return entries


def touched(entries):
    names = set()
    for e in entries:
        for p in (e['old'], e['new']):
            if p and p != DEV_NULL:
                names.add(p)
    return names


def classify(resolved, patch_text, gold_files):
    """Return (class, gold_file_hit, flags)."""
    flags = []
    entries = parse_entries(patch_text or '')
    files = touched(entries)
    hit = bool(files & gold_files)
    if entries and all(e['is_deleted'] for e in entries):
        flags.append('deletion_only')
    if resolved is True:
        return 'resolved', hit, flags
    if not (patch_text or '').strip() or not entries:
        return 'no patch', hit, flags
    if hit:
        return 'gold file touched', hit, flags
    if all(e['is_new'] for e in entries):
        return 'scratch only', hit, flags
    return 'no gold file', hit, flags


def load_gold(tasks_path):
    gold = {}
    for line in open(tasks_path, encoding='utf-8'):
        t = json.loads(line)
        gold[t['instance_id']] = touched(parse_entries(t['patch']))
    return gold


def run_set(spec, gold):
    name, seed, results, pdir = spec.split(':', 3)
    rows = []
    for line in open(results, encoding='utf-8'):
        r = json.loads(line)
        if not isinstance(r.get('resolved'), bool):
            continue
        tid = r['instance_id']
        pp = os.path.join(pdir, tid + '.patch')
        flags = []
        if os.path.exists(pp):
            text = open(pp, encoding='utf-8', errors='replace').read()
        else:
            text = ''
            flags.append('patch_not_stored')
        cls, hit, f2 = classify(r['resolved'], text, gold[tid])
        flags += f2
        if not text.strip() and (r.get('agent_patch_size') or 0) > 0:
            flags.append('size_field_nonzero_but_empty')
        rows.append({'set': name, 'task_id': tid, 'seed': seed, 'class': cls,
                     'gold_file_hit': hit, 'flags': ';'.join(flags)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tasks', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--set', action='append', required=True)
    a = ap.parse_args()
    gold = load_gold(a.tasks)
    rows = []
    for s in a.set:
        rows += run_set(s, gold)
    with open(a.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['set', 'task_id', 'seed', 'class', 'gold_file_hit', 'flags'])
        w.writeheader()
        w.writerows(rows)
    print(len(rows), 'rows', file=sys.stderr)


if __name__ == '__main__':
    main()
