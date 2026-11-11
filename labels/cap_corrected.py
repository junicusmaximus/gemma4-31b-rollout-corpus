"""cap_corrected.py (clarification 6): corrected cap label beside the stamped (v083b) and sensitivity (clarification 4) labels.
Usage: python -B cap_corrected.py OUT name=path/to/name [name=path ...]   (OUT must not exist)

Call status from the recorded observation (JSON parsed, so spacing does not matter):
  parse_failed   : object with a string "error" starting "Invoking `" and containing "failed" (the call_kinds_v2 rule)
  budget_refused : error_type == "BudgetExceeded"
  exec_error     : status == "error"
  exec_ok        : any other object with a "status" field
  unknown        : no observation, not JSON, or none of the above. Kept in the call list (not known to be unrun) but never ok.
Corrected label: budget_graph_v083b.cap_info (unchanged) applied to the call list without parse_failed and budget_refused
calls, with ok = (status == exec_ok). Capped = tool_calls of the results row >= 28. Positions are 0-based indexes into the
full parsed call list of v083b.parse()."""
import csv, json, os, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import budget_graph_v083b as V
import call_kinds_v2 as K
import cap_sensitivity as CS

STATUSES = ("parse_failed", "budget_refused", "exec_error", "exec_ok", "unknown")


def status(obs):
    try:
        o = json.loads(obs)
    except (TypeError, ValueError):
        return "unknown"
    if not isinstance(o, dict):
        return "unknown"
    e = o.get("error")
    if isinstance(e, str) and e.startswith("Invoking `") and "failed" in e:
        return "parse_failed"
    if o.get("error_type") == "BudgetExceeded":
        return "budget_refused"
    if "status" in o:
        return "exec_error" if o["status"] == "error" else "exec_ok"
    return "unknown"


def positions(calls, sub):
    """indexes in calls of the 28th non-free call of sub and of the window (non-free calls 23..28 of sub)."""
    nf = [c for c in sub if c["fn"] not in V.FREE]
    if len(nf) < V.CAP:
        return None, []
    idx = {id(c): i for i, c in enumerate(calls)}
    return idx[id(nf[V.CAP - 1])], [idx[id(c)] for c in nf[V.CAP - 6:V.CAP]]


def first_submit(calls, sub):
    idx = {id(c): i for i, c in enumerate(calls)}
    s = [idx[id(c)] for c in sub if c["fn"] == "submit_patch"]
    return s[0] if s else None


def rollout(run, row):
    calls, _, _ = V.parse(run, row)
    for c in calls:
        c["status"] = status(c["obs"]) if c["obs"] else "unknown"
    nonfree = [c for c in calls if c["fn"] not in V.FREE]
    st = Counter(c["status"] for c in nonfree)
    charged = [c for c in nonfree if c["status"] in ("exec_ok", "exec_error", "unknown")]
    base = dict(run=run, task=row["instance_id"], resolved=bool(row.get("resolved")), tool_calls=row.get("tool_calls"),
                attempted=len(nonfree), charged=len(charged), **{f"n_{s}": st.get(s, 0) for s in STATUSES},
                pf_rule_disagreements=sum((c["status"] == "parse_failed") != K.parse_failed(c) for c in nonfree),
                unknown_positions=" ".join(str(i) for i, c in enumerate(calls) if c["fn"] not in V.FREE and c["status"] == "unknown"))
    base["charged_equals_tool_calls"] = base["charged"] == row.get("tool_calls")
    if (row.get("tool_calls") or 0) < V.CAP:
        return base, None
    # stamped (v083b, original ok flags as parsed)
    stamped = V.cap_info(calls)
    s_cap, s_win = positions(calls, calls)
    # sensitivity (clarification 4) via the stamped cap_sensitivity function on a fresh parse
    sens = CS.rollout(run, row)
    # corrected
    sub = [dict(c) for c in calls if c["status"] not in ("parse_failed", "budget_refused")]
    for c in sub:
        c["ok"] = c["status"] == "exec_ok"
    corr = V.cap_info(sub)
    idmap = {}
    for c0, c1 in zip([c for c in calls if c["status"] not in ("parse_failed", "budget_refused")], sub):
        idmap[id(c1)] = c0
    sub_orig = [idmap[id(c)] for c in sub]
    c_cap, c_win = positions(calls, sub_orig)
    cap = dict(stamped_class=stamped["cap_class"] if stamped else "", sensitivity_class=sens["sensitivity_class"] if sens else "",
               corrected_class=corr["cap_class"] if corr else "not_reached",
               stamped_patch_at_cap=stamped["patch_at_cap"] if stamped else "", corrected_patch_at_cap=corr["patch_at_cap"] if corr else "",
               stamped_test_after=stamped["test_after_last_edit"] if stamped else "", corrected_test_after=corr["test_after_last_edit"] if corr else "",
               stamped_submit=stamped["submit"] if stamped else "", corrected_submit=corr["submit"] if corr else "",
               stamped_last6=stamped["last6"] if stamped else "", corrected_last6=corr["last6"] if corr else "",
               first_submit_position=first_submit(calls, calls),
               stamped_cap_position=s_cap, stamped_window_positions=" ".join(map(str, s_win)),
               corrected_cap_position=c_cap, corrected_window_positions=" ".join(map(str, c_win)))
    return base, dict(base, **cap)


def changes(rows, a, b):
    d = [r for r in rows if r[a] != r[b]]
    return dict(n=len(d), by_direction=dict(Counter(f"{r[a]} -> {r[b]}" for r in d)),
                rollouts=[f"{r['run']}:{r['task']}" for r in d])


def summary(all_rows, capped):
    not_run = [r for r in capped if r["n_parse_failed"] + r["n_budget_refused"] > 0]
    clean = [r for r in capped if r["n_parse_failed"] + r["n_budget_refused"] + r["n_unknown"] == 0]
    return dict(rollouts=len(all_rows), capped=len(capped), capped_with_call_not_run=len(not_run),
                status_counts={s: sum(r[f"n_{s}"] for r in all_rows) for s in STATUSES},
                unknown_calls=[f"{r['run']}:{r['task']}@{r['unknown_positions']}" for r in all_rows if r["n_unknown"]],
                pf_rule_disagreements=sum(r["pf_rule_disagreements"] for r in all_rows),
                charged_vs_tool_calls=dict(equal=sum(r["charged_equals_tool_calls"] for r in all_rows),
                                           differing=[f"{r['run']}:{r['task']} {r['charged']} vs {r['tool_calls']}"
                                                      for r in all_rows if not r["charged_equals_tool_calls"]]),
                classes={k: dict(Counter(r[k] for r in capped)) for k in ("stamped_class", "sensitivity_class", "corrected_class")},
                stamped_to_corrected=changes(capped, "stamped_class", "corrected_class"),
                sensitivity_to_corrected=changes(capped, "sensitivity_class", "corrected_class"),
                stamped_to_sensitivity=changes(capped, "stamped_class", "sensitivity_class"),
                proof_clean=dict(rollouts=len(clean), differing=[f"{r['run']}:{r['task']}" for r in clean
                                                                 if r["corrected_class"] != r["stamped_class"]]))


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
    s = summary(all_rows, capped); s["runs"] = {n: p for n, p in runs}
    with open(os.path.join(out, "summary.json"), "x") as f:
        json.dump(s, f, indent=1, sort_keys=True)
    return all_rows, capped, s


if __name__ == "__main__":
    a, c, s = main(sys.argv[1:])
    print(json.dumps({k: v for k, v in s.items() if k != "runs"}))
