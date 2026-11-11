#!/usr/bin/env python3
"""Clarification 5 quantities (paper2-analysis-rules-CLARIFICATION-5-2026-11-10.md) on failed edits.

Reads the v082 wrapper output (cases.jsonl, rollouts.jsonl) and traces of explicitly named runs only.
Imports classify_edit_failures.py (0d8d8264...) unchanged for load_calls and FREE.

Usage:
  python3 failed_edit_features.py --set NAME:CASES_DIR:GROUPS [--set ...] --traces RUN=TRACES_DIR [--traces ...]
GROUPS = comma separated v082 group names to keep (baseline58, legacy_other, mt01).
TRACES_DIR holds trace_<instance_id>.json of that run.
Prints one JSON object per set.
"""
import argparse
import collections
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classify_edit_failures as cef  # noqa: E402

MANDATORY = ('filepath', 'old_string', 'new_string')


def is_budget(r):
    return r['cause_detail'].startswith('F-budget')


def n_half(rows):
    per = collections.Counter((r['task'], str(r['seed']), r['run']) for r in rows if not is_budget(r))
    order = sorted(per.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1], kv[0][2]))
    total = sum(per.values())
    acc = 0
    for k, (_, n) in enumerate(order, 1):
        acc += n
        if 2 * acc >= total:
            break
    else:
        k, acc = 0, 0
    top4 = [dict(task=t, seed=s, run=r, failed=n) for (t, s, r), n in order[:4]]
    return dict(total=total, n_half=k if total else 0, n_half_hold=acc if total else 0, top4=top4)


def quartiles(x):
    if not x:
        return None
    q = statistics.quantiles(x, n=4, method='inclusive') if len(x) > 1 else [x[0]] * 3
    return dict(n=len(x), q1=q[0], median=statistics.median(x), q3=q[2])


def features(rows, calls_of):
    nb = [r for r in rows if not is_budget(r)]
    f_rows = [r for r in nb if r['cause'] == 'F']
    lack = exact = 0
    other = collections.Counter()
    strict = 0
    for r in nb:
        calls = calls_of(r)
        c = calls[r['call_index']]
        keys = set(c['args'])
        if r['cause'] == 'F':
            if any(m not in keys for m in MANDATORY):
                lack += 1
                exact += keys == {'filepath', 'new_string'}
            else:
                other[r['cause_detail'].split(':')[0]] += 1
        nxt = calls[r['call_index'] + 1] if r['call_index'] + 1 < len(calls) else None
        if nxt is not None and nxt['name'] == c['name'] and nxt['args'] == c['args']:
            strict += 1
    eps = [r for r in nb if r['episode_start'] and r['recovered'] == 'yes']
    return dict(failed_analysed=len(nb), cause_F=len(f_rows), F_lacking_mandatory=lack,
                F_exactly_filepath_new_string=exact, F_other=dict(other),
                identical_resend_v082_label=sum(r['next_action'] == 'identical resend' for r in nb),
                identical_resend_strict=strict,
                recovery_cost=quartiles([r['calls_until_recovery'] for r in eps]),
                episodes_opened_by_budget_refusal=sum(1 for r in rows if is_budget(r) and r['episode_start']))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', action='append', required=True)
    ap.add_argument('--traces', action='append', default=[])
    a = ap.parse_args(argv)
    tdir = dict(t.split('=', 1) for t in a.traces)
    cache = {}

    def calls_of(r):
        key = (r['run'], r['task'])
        if key not in cache:
            cache[key] = cef.load_calls(os.path.join(tdir[r['run']], f"trace_{r['task']}.json"))
        return cache[key]

    out = {}
    for spec in a.set:
        name, d, groups = spec.split(':', 2)
        g = set(groups.split(','))
        rows = [json.loads(l) for l in open(os.path.join(d, 'cases.jsonl'))]
        rows = [r for r in rows if r['group'] in g]
        out[name] = dict(n_half(rows), **features(rows, calls_of))
        print(json.dumps({name: out[name]}))
    return out


if __name__ == '__main__':
    main()
