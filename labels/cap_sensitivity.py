"""cap_sensitivity.py (clarification 4): v083b.cap_info recomputed with ONE change: a call that call_kinds_v2.parse_failed()
classifies as parse failed has ok = False. Everything else is budget_graph_v083b.cap_info unchanged (imported).
Capped = the stamped v083b column: tool_calls of the results row >= 28 (and cap_info not None, as in v083b).
Usage: python -B cap_sensitivity.py OUT name=path/to/name [name=path ...]   (OUT must not exist)"""
import csv, json, os, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import budget_graph_v083b as V
import call_kinds_v2 as K


def rollout(run, row):
    if (row.get("tool_calls") or 0) < V.CAP:
        return None
    calls, _, _ = V.parse(run, row)
    stamped = V.cap_info(calls)
    if stamped is None:
        return None
    pf = 0
    for c in calls:
        if c["fn"] not in V.FREE and K.parse_failed(c):
            c["ok"] = False; pf += 1
    sens = V.cap_info(calls)
    return dict(run=run, task=row["instance_id"], resolved=bool(row.get("resolved")), parse_failed=pf,
                stamped_class=stamped["cap_class"], sensitivity_class=sens["cap_class"],
                stamped_patch_at_cap=stamped["patch_at_cap"], sensitivity_patch_at_cap=sens["patch_at_cap"],
                stamped_test_after=stamped["test_after_last_edit"], sensitivity_test_after=sens["test_after_last_edit"],
                class_differs=stamped["cap_class"] != sens["cap_class"],
                patch_at_cap_differs=stamped["patch_at_cap"] != sens["patch_at_cap"],
                test_after_differs=stamped["test_after_last_edit"] != sens["test_after_last_edit"])


def summary(rows):
    d = [r for r in rows if r["class_differs"]]
    return dict(capped=len(rows), capped_with_parse_failed=sum(r["parse_failed"] > 0 for r in rows),
                class_differs=len(d),
                by_direction=dict(Counter(f"{r['stamped_class']} -> {r['sensitivity_class']}" for r in d)),
                patch_at_cap_differs=sum(r["patch_at_cap_differs"] for r in rows),
                test_after_differs=sum(r["test_after_differs"] for r in rows),
                proof_no_parse_failed=dict(rollouts=sum(r["parse_failed"] == 0 for r in rows),
                                           differing=[(r["run"], r["task"]) for r in rows if r["parse_failed"] == 0 and r["class_differs"]]),
                differing_rollouts=[dict(run=r["run"], task=r["task"], parse_failed=r["parse_failed"],
                                         stamped=r["stamped_class"], sensitivity=r["sensitivity_class"]) for r in d])


def main(argv):
    out, runs = argv[0], [a.split("=", 1) for a in argv[1:]]
    assert runs and all(os.path.basename(os.path.normpath(p)) == n for n, p in runs), "each run must be name=path/to/name"
    rows = []
    for run, rundir in runs:
        V.R = os.path.dirname(os.path.normpath(rundir))
        for line in open(os.path.join(rundir, "task_results.jsonl")):
            if line.strip():
                r = rollout(run, json.loads(line))
                if r: rows.append(r)
    os.makedirs(out)
    with open(os.path.join(out, "per_rollout.csv"), "x", newline="") as f:
        fields = list(rows[0].keys()) if rows else ["run"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    s = summary(rows); s["runs"] = {n: p for n, p in runs}
    with open(os.path.join(out, "summary.json"), "x") as f:
        json.dump(s, f, indent=1, sort_keys=True)
    return rows, s


if __name__ == "__main__":
    rows, s = main(sys.argv[1:])
    print(json.dumps({k: v for k, v in s.items() if k != "runs"}))
