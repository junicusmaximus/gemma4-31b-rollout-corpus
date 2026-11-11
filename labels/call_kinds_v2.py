"""call_kinds_v2.py (clarification 3): attempted and charged calls per rollout, kinds by budget_graph_v083b.kind() unchanged.
Usage: python -B call_kinds_v2.py OUT name=path/to/name [name=path ...]   (OUT must not exist)
attempted = every parsed trace call whose function is not in v083b.FREE (submit_patch, get_status).
charged   = attempted minus (a) parse failed: the observation is a tool-invocation failure ("Invoking `...` failed")
            and minus (b) budget refused: the observation has error_type "BudgetExceeded".
A failed edit (any other error) stays an edit call. trace_capped = v083b's rule (>= 28 attempted calls, v083b.cap_info);
harness_capped = tool_calls of the results row >= 28."""
import csv, json, os, sys
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import budget_graph_v083b as V

KINDS = ("read", "edit", "test", "graph")
CODE = dict(read="r", edit="e", test="t", graph="g")


def pct(x):
    return float(Decimal(repr(100.0 * x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def parse_failed(c):
    return c["obs"].lstrip().startswith('{"error": "Invoking `') and "failed" in c["obs"][:200]


def budget_refused(c):
    return '"error_type": "BudgetExceeded"' in c["obs"]


def rollout(run, row):
    calls, _, _ = V.parse(run, row)
    att = [c for c in calls if c["fn"] not in V.FREE]
    pf = [c for c in att if parse_failed(c)]
    br = [c for c in att if budget_refused(c) and not parse_failed(c)]
    ch = [c for c in att if not parse_failed(c) and not budget_refused(c)]
    d = dict(run=run, task=row["instance_id"], resolved=bool(row.get("resolved")), tool_calls=row.get("tool_calls"),
             attempted=len(att), charged=len(ch), parse_failed=len(pf), budget_refused=len(br),
             **{f"att_{k}": sum(c["kind"] == k for c in att) for k in KINDS},
             **{f"chg_{k}": sum(c["kind"] == k for c in ch) for k in KINDS},
             att_other=sum(c["kind"] not in KINDS for c in att), chg_other=sum(c["kind"] not in KINDS for c in ch),
             chg_positions="".join(CODE.get(c["kind"], "?") for c in ch[:V.CAP]),
             trace_capped=V.cap_info(calls) is not None,
             harness_capped=(row.get("tool_calls") or 0) >= V.CAP)
    d["charged_equals_tool_calls"] = d["charged"] == row.get("tool_calls")
    return d


def summary(rows):
    out = {}
    for pre in ("att", "chg"):
        tot = sum(r[f"{pre}_{k}"] for r in rows for k in KINDS) + sum(r[f"{pre}_other"] for r in rows)
        cnt = {k: sum(r[f"{pre}_{k}"] for r in rows) for k in KINDS}
        out["attempted" if pre == "att" else "charged"] = dict(total=tot, counts=cnt, other=sum(r[f"{pre}_other"] for r in rows),
            share_pct={k: (pct(v / tot) if tot else None) for k, v in cnt.items()})
    tab = Counter((r["trace_capped"], r["harness_capped"]) for r in rows)
    out["cap_2x2"] = {f"trace_{a}_harness_{b}": tab.get((a, b), 0) for a in (True, False) for b in (True, False)}
    out["trace_cap_not_harness"] = [dict(run=r["run"], task=r["task"], attempted=r["attempted"], tool_calls=r["tool_calls"],
                                         parse_failed=r["parse_failed"], budget_refused=r["budget_refused"])
                                    for r in rows if r["trace_capped"] and not r["harness_capped"]]
    out["charged_vs_tool_calls"] = dict(equal=sum(r["charged_equals_tool_calls"] for r in rows),
        differing=[dict(run=r["run"], task=r["task"], charged=r["charged"], tool_calls=r["tool_calls"],
                        parse_failed=r["parse_failed"], budget_refused=r["budget_refused"])
                   for r in rows if not r["charged_equals_tool_calls"]])
    out["positions"] = {str(i + 1): dict(Counter(r["chg_positions"][i] for r in rows if len(r["chg_positions"]) > i))
                        for i in range(V.CAP)}
    out["rollouts"] = len(rows)
    return out


def main(argv):
    out, runs = argv[0], [a.split("=", 1) for a in argv[1:]]
    assert runs and all(os.path.basename(os.path.normpath(p)) == n for n, p in runs), "each run must be name=path/to/name"
    rows = []
    for run, rundir in runs:
        V.R = os.path.dirname(os.path.normpath(rundir))
        for line in open(os.path.join(rundir, "task_results.jsonl")):
            if line.strip():
                rows.append(rollout(run, json.loads(line)))
    os.makedirs(out)
    with open(os.path.join(out, "per_rollout.csv"), "x", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    s = summary(rows); s["runs"] = {n: p for n, p in runs}
    with open(os.path.join(out, "summary.json"), "x") as f:
        json.dump(s, f, indent=1, sort_keys=True)
    return rows, s


if __name__ == "__main__":
    rows, s = main(sys.argv[1:])
    print(json.dumps({k: s[k] for k in ("rollouts", "attempted", "charged", "cap_2x2", "trace_cap_not_harness")}))
    print("charged == tool_calls:", s["charged_vs_tool_calls"]["equal"], "differing:", len(s["charged_vs_tool_calls"]["differing"]))
    for d in s["charged_vs_tool_calls"]["differing"]:
        print(" ", d)
