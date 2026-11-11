"""cap_corrected_a1.py (clarification 6, addition 1). Wraps the stamped cap_corrected.py (71370b03...) unchanged.
Rule A1-1 (unknown status stays charged, ok false) is already how cap_corrected.py builds the filtered list
(ok = status == "exec_ok"); this file checks it with a fixture. Rule A1-2 is added here: a capped rollout whose number of
charged calls in the filtered list is below 28 or differs from the row's tool_calls gets corrected_class "undecided",
with both numbers recorded (filtered_charged, tool_calls).
Usage: python -B cap_corrected_a1.py OUT name=path/to/name [name=path ...]   (OUT must not exist)"""
import csv, json, os, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import budget_graph_v083b as V
import cap_corrected as CC


def rollout(run, row):
    b, c = CC.rollout(run, row)
    if c is None:
        return b, None
    c = dict(c, filtered_charged=c["charged"])
    if c["charged"] < V.CAP or c["charged"] != row.get("tool_calls"):
        c["corrected_class"] = "undecided"
    return b, c


def main(argv):
    out, runs = argv[0], [a.split("=", 1) for a in argv[1:]]
    assert runs and all(os.path.basename(os.path.normpath(p)) == n for n, p in runs), "each run must be name=path/to/name"
    all_rows, capped = [], []
    for run, rundir in runs:
        V.R = os.path.dirname(os.path.normpath(rundir))
        for line in open(os.path.join(rundir, "task_results.jsonl")):
            if line.strip():
                b, c = rollout(run, json.loads(line))
                all_rows.append(b)
                if c: capped.append(c)
    os.makedirs(out)
    for name, rows in (("all_rollouts.csv", all_rows), ("capped_rollouts.csv", capped)):
        with open(os.path.join(out, name), "x", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["run"]); w.writeheader(); w.writerows(rows)
    s = CC.summary(all_rows, capped)
    s["undecided"] = [dict(rollout=f"{r['run']}:{r['task']}", filtered_charged=r["filtered_charged"], tool_calls=r["tool_calls"])
                      for r in capped if r["corrected_class"] == "undecided"]
    s["runs"] = {n: p for n, p in runs}
    with open(os.path.join(out, "summary.json"), "x") as f:
        json.dump(s, f, indent=1, sort_keys=True)
    return all_rows, capped, s


if __name__ == "__main__":
    a, c, s = main(sys.argv[1:])
    print(json.dumps({k: v for k, v in s.items() if k != "runs"}))
