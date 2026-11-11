#!/usr/bin/env python3
"""Wrapper around classify_edit_failures.py (sha256 0d8d8264..., imported unchanged).

The hashed script reads R/results/<run> directly and its default mt01 run list includes seed 2.
This wrapper never calls its main(); it builds the rollout list from explicit paths only.

  --legacy-results DIR   results root for the 110 legacy rollouts listed in the hashed script's TABLE (optional)
  --mt01 RUN:SEED:RESULTS_JSONL:TRACES_DIR   (repeatable) mt01 rollouts from a copy
  --out DIR              writes cases.jsonl and rollouts.jsonl (same format as v082)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classify_edit_failures as cef  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--legacy-results')
    ap.add_argument('--mt01', action='append', default=[])
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    items = []
    if a.legacy_results:
        for m in cef.legacy_rollouts():
            items.append((m, os.path.join(a.legacy_results, m['run'], 'traces', f"trace_{m['task']}.json")))
    for spec in a.mt01:
        run, seed, results, traces = spec.split(':', 3)
        for line in open(results):
            t = json.loads(line)
            m = dict(group='mt01', run=run, bundle='baseline', temperature=0.2,
                     task=t['instance_id'], seed=seed, resolved=bool(t['resolved']))
            items.append((m, os.path.join(traces, f"trace_{t['instance_id']}.json")))
    items.sort(key=lambda x: x[0]['task'])
    rows, rolls, snap, snap_task = [], [], None, None
    for m, tp in items:
        if not os.path.exists(tp):
            rolls.append(dict(m, missing_trace=True))
            continue
        if snap_task != m['task']:
            snap = cef.Snapshot(m['task']) if os.path.exists(f"{cef.SNAP}/{m['task']}.tgz") else None
            snap_task = m['task']
        calls = cef.load_calls(tp)
        rows += cef.rollout_rows(m, calls, snap)
        rolls.append(cef.rollout_summary(m, calls))
    os.makedirs(a.out, exist_ok=False)
    with open(os.path.join(a.out, 'cases.jsonl'), 'w') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    with open(os.path.join(a.out, 'rollouts.jsonl'), 'w') as f:
        for r in rolls:
            f.write(json.dumps(r) + '\n')
    print(len(rolls), 'rollouts', len(rows), 'failed edit_file calls')


if __name__ == '__main__':
    main()
