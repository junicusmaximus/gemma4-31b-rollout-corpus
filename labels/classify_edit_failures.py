#!/usr/bin/env python3
"""Classify every failed edit_file call in local 31B rollout traces (edit-failure-boss-v082).

Read-only over R/results and R/data/competition/snapshots. Writes cases.jsonl and
counts.json into --out. File state at each call is replayed from the task snapshot
with the harness's own matcher (adk_eval_core.editing.apply_replacement); a file
touched by a writing run_command becomes "unknown" from that point on.

Usage (swegemma python, no GPU):
  CUDA_VISIBLE_DEVICES="" python classify_edit_failures.py --out DIR [--mt01-runs mt01_baseline_s1 ...]
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import json
import os
import re
import tarfile

from adk_eval_core.editing import apply_replacement

R = 'PROJECT_ROOT/gemma4'
TABLE = ('PROJECT_ROOT/boss-local-mirror/briefing-vault/research/'
         'gemma-4-2026/artifacts/boss-2026-11-10/local31b/per_task_table.csv')
SNAP = R + '/data/competition/snapshots'
FREE = {'submit_patch', 'get_status'}  # not charged (swegemma/tools/execution.py)
WRITE_RE = re.compile(r"sed\s+-i|perl\s+-\w*i|\btee\b|(?<![\d&-])>>?\s*(?!&|/dev/null)[\w./'\"]|"
                      r"\bpatch\b|git\s+(apply|checkout|stash|restore|reset)|\bmv\b|\bcp\b|"
                      r"open\([^)]*['\"][wa]\+?['\"]|write_text|\.write\(|\.replace\(")
VIEW_RE = re.compile(r"\b(cat|sed\s+-n|head|tail|grep|nl|awk|less|git\s+diff|git\s+show)\b")
LINENUM_RE = re.compile(r'(?m)^\s*\d+(\s*[:|\t]|\s{2,})')
ELIDE_RE = re.compile(r'(?m)^\s*(#\s*)?(\.\.\.|…)\s*$|# \.\.\.|\.\.\. ?\(|\[\.\.\.\]')


def norm_path(p):
    p = (p or '').strip()
    for pre in ('/workspace/', './'):
        if p.startswith(pre):
            p = p[len(pre):]
    return p


def parse_obs(obs):
    if not isinstance(obs, dict):
        return {'status': 'unknown'}
    c = obs.get('content')
    if isinstance(c, str):
        try:
            return json.loads(c)
        except ValueError:
            return {'status': 'unknown', 'raw': c[:200]}
    return c if isinstance(c, dict) else {'status': 'unknown'}


def load_calls(trace_path):
    steps = json.load(open(trace_path))['steps']
    calls = []
    for s in steps:
        for tc in s.get('tool_calls') or []:
            o = parse_obs(s.get('observation'))
            calls.append({'name': tc.get('function_name'), 'args': tc.get('arguments') or {},
                          'status': o.get('status'), 'etype': o.get('error_type'),
                          'emsg': o.get('error_message') or o.get('error') or '', 'obs': o})
    return calls


class Snapshot:
    """All text files of one task snapshot (<= 1 MB each)."""

    def __init__(self, task):
        self.files = {}
        with tarfile.open(f'{SNAP}/{task}.tgz') as tf:
            for m in tf:
                if not m.isfile() or m.size > 1_000_000 or '/.git/' in m.name:
                    continue
                data = tf.extractfile(m).read()
                if b'\0' in data[:4096]:
                    continue
                self.files[norm_path(m.name)] = data.decode('utf-8', 'replace')


def mentions(cmd, path):
    return path in cmd or os.path.basename(path) in cmd


def cmd_writes(cmd):
    return bool(WRITE_RE.search(cmd))


def ws_free(s):
    return re.sub(r'\s+', '', s)


def matches(content, old, allow_multiple=False):
    if content is None:
        return None
    try:
        r = apply_replacement(content, old, old + '\0', allow_multiple=allow_multiple)
    except Exception:
        return False
    return r.error_message is None or r.occurrences > 1


def c_subtype(old, cur):
    if re.search(r'no old.?string|old_string', old, re.I):
        return 'C-placeholder (anchorless insert attempt)'
    if LINENUM_RE.search(old):
        return 'C-linenumbers'
    if ELIDE_RE.search(old):
        return 'C-elided'
    if '\\' in old and cur is not None and (matches(cur, old.replace('\\', '\\\\'))
                                            or matches(cur, old.replace('\\\\', '\\'))):
        return 'C-backslash-level (matches once backslashes are doubled or halved)'
    if '\\n' in old or '\\"' in old:
        return 'C-escaped (literal backslash-n or backslash-quote in old_string)'
    lines = [x.strip() for x in old.splitlines() if x.strip()]
    if not lines or cur is None:
        return 'C-other'
    hit = sum(1 for x in lines if x in cur)
    if hit == len(lines):
        return 'C-lines-present-not-contiguous'
    return 'C-partial-lines' if hit / len(lines) >= 0.5 else 'C-mostly-absent'


def classify_cause(c, cur, orig, snap, path):
    et, msg = c['etype'] or '', c['emsg']
    old = c['args'].get('old_string') or ''
    if et == 'BudgetExceeded':
        return 'F', 'F-budget-exhausted (call refused before matching)'
    if 'not found in workspace' in msg or 'Path traversal' in msg or 'workspace root' in msg:
        return 'E', 'E-file-missing'
    if re.search(r'occurs \d+ times|flexibly matches \d+|Expected 1 occurrence', msg):
        return 'D', 'D-multiple-matches'
    if 'mandatory input parameters' in msg:
        return 'F', 'F-malformed-call (tool-call arguments split by the parser; old_string missing)'
    if 'identical' in msg:
        return 'F', 'F-old-equals-new'
    if 'is empty' in msg or 'cannot be empty' in msg:
        return 'F', 'F-empty'
    if 'old_string not found' not in msg:
        return 'F', 'F-' + (et or 'unknown') + ': ' + msg[:80]
    if orig is None and cur is None:
        return 'undecided', 'undecided: file not in snapshot and never written by a replayable call'
    if cur is None:
        if matches(orig, old):
            return 'undecided', 'undecided: matches snapshot, file state unknown after run_command (B or C)'
        return 'undecided', 'undecided: file state unknown after run_command write'
    if cur != orig and matches(orig, old):
        return 'B', 'B-stale (matches the snapshot, file changed earlier in rollout)'
    if ws_free(old) and ws_free(old) in ws_free(cur):
        return 'A', 'A-whitespace/blank-line difference'
    others = [p for p, t in snap.files.items() if p != path and old in t] if snap else []
    if others:
        return 'E', 'E-text-in-other-file: ' + ','.join(others[:3])
    return 'C', c_subtype(old, cur)


def args_key(a):
    return (norm_path(a.get('filepath')), a.get('old_string'), a.get('new_string'),
            str(a.get('allow_multiple', False)))


def next_action(calls, i, path):
    reread = False
    for j in range(i + 1, len(calls)):
        c = calls[j]
        a = c['args']
        n = c['name']
        cmd = a.get('command') or ''
        if n == 'read_file' and norm_path(a.get('filepath')) == path:
            reread = True
        elif n == 'run_command' and mentions(cmd, path):
            if cmd_writes(cmd):
                return 'run_command edit', j
            if VIEW_RE.search(cmd):
                reread = True
        elif n == 'write_file' and norm_path(a.get('filepath')) == path:
            return 'whole-file write_file', j
        elif n == 'edit_file' and norm_path(a.get('filepath')) == path:
            if reread:
                return 're-read then edit', j
            if args_key(a) == args_key(calls[i]['args']):
                return 'identical resend', j
            return 'changed resend without re-read', j
    return 'edit abandoned', None


def recovery(calls, i, path):
    charged = 0
    for j in range(i + 1, len(calls)):
        c = calls[j]
        if c['name'] not in FREE:
            charged += 1
        a = c['args']
        ok = c['status'] == 'ok'
        if not ok:
            continue
        if c['name'] in ('edit_file', 'write_file') and norm_path(a.get('filepath')) == path:
            return True, charged, j
        if c['name'] == 'run_command' and mentions(a.get('command') or '', path) and cmd_writes(a.get('command') or ''):
            return True, charged, j
    return False, None, None


def replay_step(state, c, snap):
    a = c['args']
    n = c['name']
    if c['status'] != 'ok':
        return
    if n == 'write_file':
        state[norm_path(a.get('filepath'))] = a.get('content')
    elif n == 'edit_file':
        p = norm_path(a.get('filepath'))
        cur = state.get(p, snap.files.get(p) if snap else None)
        if cur is None:
            state[p] = None
            return
        try:
            r = apply_replacement(cur, a.get('old_string') or '', a.get('new_string') or '',
                                  allow_multiple=str(a.get('allow_multiple')).lower() in ('true', '1', 'yes'))
            state[p] = r.new_content if r.error_message is None else None
        except Exception:
            state[p] = None
    elif n == 'run_command':
        cmd = a.get('command') or ''
        if not cmd_writes(cmd):
            return
        if re.search(r'git\s+(checkout|stash|restore|reset)', cmd) and not any(mentions(cmd, p) for p in state):
            for p in list(state):
                state[p] = None
        known = set(state) | (set(snap.files) if snap else set())
        for p in known:
            if p in cmd:
                state[p] = None
        for p in list(state):
            if os.path.basename(p) in cmd:
                state[p] = None


def rollout_rows(meta, calls, snap):
    rows = []
    state = {}
    ep_open = {}
    charged_idx = 0
    seen = []
    for i, c in enumerate(calls):
        if c['name'] not in FREE:
            charged_idx += 1
        if c['name'] == 'edit_file' and c['status'] != 'ok':
            a = c['args']
            path = norm_path(a.get('filepath'))
            orig = snap.files.get(path) if snap else None
            cur = state[path] if path in state else orig
            cls, detail = classify_cause(c, cur, orig, snap, path)
            if c['etype'] == 'BudgetExceeded':
                act, rec = 'n/a (budget exhausted)', (False, None, None)
            else:
                act, _ = next_action(calls, i, path)
                rec = recovery(calls, i, path)
            first = ep_open.get(path) is None
            if first:
                ep_open[path] = i
            rows.append(dict(meta, call_index=i, charged_call_no=charged_idx, filepath=path,
                             error=(c['etype'] or '') + ': ' + c['emsg'][:200], cause=cls, cause_detail=detail,
                             next_action=act, recovered='yes' if rec[0] else 'no',
                             calls_until_recovery=rec[1], episode_start=first,
                             old_string_lines=len((a.get('old_string') or '').splitlines()),
                             first_line_seen_before=first_line_seen(a.get('old_string') or '', seen)))
        if c['name'] in ('edit_file', 'write_file') and c['status'] == 'ok':
            ep_open[norm_path(c['args'].get('filepath'))] = None
        replay_step(state, c, snap)
        if c['name'] in ('read_file', 'run_command'):
            seen.append(str(c['obs'].get('content') or '') + str(c['obs'].get('stdout') or ''))
    return rows


def first_line_seen(old, seen):
    lines = [x.strip() for x in old.replace('\\n', '\n').splitlines() if x.strip()]
    if not lines:
        return None
    return any(lines[0] in t for t in seen)


def rollout_summary(meta, calls):
    edits = [c for c in calls if c['name'] in ('edit_file', 'write_file')]
    ed = [c for c in calls if c['name'] == 'edit_file']
    nbe = [c for c in edits if c['etype'] != 'BudgetExceeded']
    return dict(meta, edit_calls=len(ed), edit_fail=sum(c['status'] != 'ok' for c in ed),
                edit_fail_nobudget=sum(c['status'] != 'ok' and c['etype'] != 'BudgetExceeded' for c in ed),
                last_edit_failed=bool(edits) and edits[-1]['status'] != 'ok',
                last_edit_failed_nobudget=bool(nbe) and nbe[-1]['status'] != 'ok',
                heredoc_cmds=sum(1 for c in calls if c['name'] == 'run_command' and '<<' in (c['args'].get('command') or '')),
                malformed_cmds=sum(1 for c in calls if c['name'] == 'run_command' and 'mandatory input' in c['emsg']),
                charged=sum(c['name'] not in FREE for c in calls),
                ok_old_lines=[len((c['args'].get('old_string') or '').splitlines()) for c in ed if c['status'] == 'ok'])


def legacy_rollouts():
    for r in csv.DictReader(open(TABLE)):
        if not r['budget'].startswith('std'):
            continue
        group = 'baseline58' if r['bundle'] == 'baseline' else 'legacy_other'
        yield dict(group=group, run=r['run'], bundle=r['bundle'], temperature=float(r['temp']),
                   task=r['task'], seed=r['seed'], resolved=r['resolved'] == 'True')


def mt01_rollouts(runs):
    for run in runs:
        d = f'{R}/results/{run}'
        if not os.path.exists(d + '/task_results.jsonl'):
            continue
        for line in open(d + '/task_results.jsonl'):
            t = json.loads(line)
            yield dict(group='mt01', run=run, bundle='baseline', temperature=0.2,
                       task=t['instance_id'], seed=run.rsplit('_s', 1)[-1], resolved=bool(t['resolved']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--mt01-runs', nargs='*', default=['mt01_baseline_s1', 'mt01_baseline_s2'])
    args = ap.parse_args()
    metas = list(legacy_rollouts()) + list(mt01_rollouts(args.mt01_runs))
    metas.sort(key=lambda m: m['task'])
    rows, rolls, snap, snap_task = [], [], None, None
    for m in metas:
        tp = f"{R}/results/{m['run']}/traces/trace_{m['task']}.json"
        if not os.path.exists(tp):
            rolls.append(dict(m, missing_trace=True))
            continue
        if snap_task != m['task']:
            snap = Snapshot(m['task']) if os.path.exists(f"{SNAP}/{m['task']}.tgz") else None
            snap_task = m['task']
        calls = load_calls(tp)
        rows += rollout_rows(m, calls, snap)
        rolls.append(rollout_summary(m, calls))
    os.makedirs(args.out, exist_ok=True)
    with open(args.out + '/cases.jsonl', 'w') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    with open(args.out + '/rollouts.jsonl', 'w') as f:
        for r in rolls:
            f.write(json.dumps(r) + '\n')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    cnt = collections.Counter((r['group'], r['cause']) for r in rows)
    print(stamp, len(rolls), 'rollouts', len(rows), 'failed edit_file calls', dict(cnt))


if __name__ == '__main__':
    main()
