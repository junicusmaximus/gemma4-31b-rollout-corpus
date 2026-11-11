"""v083 read-only tabulation: (b) 28-call cap rollouts + cap-34 scorer-time projection, (c) graph-tool use.
Reads task_results.jsonl and traces of the 31B runs named on the command line; writes only into its own directory (argv[1]).
v083b: byte copy of v083 (806c45fb) with only scaffolding changed: main() guard; OUT and the runs (name=run_folder) from argv."""
import csv, json, os, re, statistics as S, sys, datetime

R = "PROJECT_ROOT/gemma4/results"
BASE = {"v034_31b_baseline_screen_s1", "v034_31b_canary", "v056_31bT02_s1", "v056_31bT02_s2", "v056_31bT05_s1",
        "v056_31bT05_s2", "v056_31bT07_s1", "v056_31bT07_s2", "v056_canary_T02"}
LEGACY = sorted(BASE | {"v061_31bMCLOSE_s1", "v061_31bMCLOSE_s2", "v061_canary_MCLOSE", "v061_coldstart_day3-mclose",
                        "v063_31bS1_s1", "v063_31bS1_s2", "v063_canary_S1", "v071_31bRB_s1", "v071_31bRB_s2", "v071_canary_RB"})
MT = ["mt01_baseline_s1", "mt01_baseline_s2"]
GRAPH = {"get_code_neighbors", "search_similar_code", "get_code_subgraph"}
FREE = {"submit_patch", "get_status"}
CAP = 28
RATES = (30, 34, 40); O = 1.0            # v062 grid: scorer decode tok/s, per-call overhead s
HIDDEN_TOK = 879                          # v062 report: mean hidden summariser tokens per compaction event
DROP = 3000                               # prompt drop marking a compaction event (v062: every drop >= 6289)
TESTRE = re.compile(r"pytest|unittest|\bpython3?\s+(-c\b|\S+\.py)")
PATHRE = re.compile(r"[\w./-]+\.py")
SYMRE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b")


def kind(fn, args):
    if fn == "submit_patch": return "submit"
    if fn == "get_status": return "status"
    if fn in ("edit_file", "write_file"): return "edit"
    if fn in GRAPH: return "graph"
    if fn == "run_command" and TESTRE.search(args.get("command", "") if isinstance(args, dict) else str(args)): return "test"
    return "read"


def ok(obs):
    return '"status": "error"' not in obs


def parse(run, row):
    tr = json.load(open(f"{R}/{run}/traces/trace_{row['instance_id']}.json"))
    calls, llm_t, prompts, comp = [], [], [], 0
    prev_p = None
    steps = tr["steps"]
    for i, st in enumerate(steps):
        m = st.get("metrics") or {}
        if st.get("source") == "agent" and m:
            p = m.get("prompt_tokens") or 0
            if prev_p is not None and prev_p - p >= DROP: comp += 1
            prev_p = p; prompts.append(p)
        obs = st.get("observation") or {}
        obs_s = obs.get("content", "") if isinstance(obs, dict) else str(obs)
        obs_t = (obs.get("extra") or {}).get("elapsed_s") if isinstance(obs, dict) else None
        for tc in st.get("tool_calls") or []:
            fn = tc.get("function_name"); a = tc.get("arguments") or {}
            t0 = (tc.get("extra") or {}).get("elapsed_s")
            nxt = steps[i + 1] if i + 1 < len(steps) else {}
            calls.append(dict(fn=fn, kind=kind(fn, a), args=json.dumps(a), ok=ok(obs_s), obs=obs_s,
                              tool_s=max(0.0, (obs_t or 0) - (t0 or 0)) if obs_t and t0 else 0.0, step=i,
                              nudge_after=bool(nxt.get("source") == "user" and "continue" in (nxt.get("message") or "").lower())))
    fm = tr.get("final_metrics") or {}
    return calls, fm.get("total_completion_tokens") or 0, comp


def cap_info(calls):
    charged = [c for c in calls if c["fn"] not in FREE]
    if len(charged) < CAP: return None
    cap_idx = calls.index(charged[CAP - 1])
    upto = calls[:cap_idx + 1]
    edits_ok = [j for j, c in enumerate(calls) if c["kind"] == "edit" and c["ok"]]
    last_edit = edits_ok[-1] if edits_ok else None
    after = calls[last_edit + 1:] if last_edit is not None else []
    test_after = any(c["kind"] == "test" for c in after)
    sub_idx = [j for j, c in enumerate(calls) if c["fn"] == "submit_patch"]
    last6 = [c["kind"] for c in charged[CAP - 6:CAP]]
    patch_at_cap = any(c["kind"] == "edit" and c["ok"] for c in upto)
    still_changing = "edit" in last6
    mid = (last_edit is not None and not test_after and not any(last_edit < j < cap_idx for j in sub_idx)) or still_changing \
        or not patch_at_cap
    return dict(last6=" ".join(last6), patch_at_cap=patch_at_cap,
                submit=("none" if not sub_idx else ("before_cap" if sub_idx[0] < cap_idx else "after_cap")),
                test_after_last_edit=test_after, cap_class="cut_off_mid_work" if mid else "finished_and_padded")


def graph_info(calls):
    g = [j for j, c in enumerate(calls) if c["kind"] == "graph"]
    used = nxt_kinds = errs = stalls = 0
    nk = []
    for j in g:
        c = calls[j]
        if j + 1 < len(calls): nk.append(calls[j + 1]["fn"])
        if not c["ok"] or '"results": []' in c["obs"] or '"count": 0' in c["obs"]: errs += 1
        if c["nudge_after"]: stalls += 1
        toks = set(PATHRE.findall(c["obs"])) | {t for t in SYMRE.findall(c["obs"]) if "_" in t or t[0].isupper()}
        toks -= set(PATHRE.findall(c["args"])) | set(SYMRE.findall(c["args"]))
        later = " ".join(x["args"] for x in calls[j + 1:])
        if any(t in later for t in toks): used += 1
    return dict(**{f"n_{n}": sum(calls[j]["fn"] == n for j in g) for n in sorted(GRAPH)},
                graph_next=" ".join(nk), graph_used=used, graph_err_or_empty=errs, graph_nudge_after=stalls)


def proj(calls, gen, comp, llm, tools, capped, r):
    tool_s = sum(c["tool_s"] for c in calls)
    a = gen / r + tool_s + O * llm
    b = a + comp * (HIDDEN_TOK / r + O)
    extra = (b / max(tools, 1)) * (34 - CAP) if capped else 0.0   # v062 calls36 analogue: mean cost per charged call
    return b, b + extra


def main():
    global R, OUT
    OUT = sys.argv[1]
    RUNS = [a.split("=", 1) for a in sys.argv[2:]]
    assert RUNS and all(os.path.basename(os.path.normpath(p)) == n for n, p in RUNS), "each run must be name=path/to/name"
    rows = []
    cut = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for run, rundir in RUNS:
        R = os.path.dirname(os.path.normpath(rundir))
        p = f"{R}/{run}/task_results.jsonl"
        if not os.path.exists(p): continue
        for line in open(p):
            r = json.loads(line)
            calls, gen, comp = parse(run, r)
            d = dict(run=run, group="mt01" if run.startswith("mt01") else ("legacy_baseline" if run in BASE else "legacy_variant"),
                     task=r["instance_id"], resolved=bool(r.get("resolved")), tools=r.get("tool_calls"),
                     llm=r.get("total_llm_calls"), dur=r.get("duration_seconds"), patch=r.get("agent_patch_size"),
                     compactions=comp, gen_tokens=gen, error=r.get("error"))
            ci = cap_info(calls) if (r.get("tool_calls") or 0) >= CAP else None
            d["capped"] = ci is not None
            d.update(ci or dict(last6="", patch_at_cap="", submit="", test_after_last_edit="", cap_class=""))
            d.update(graph_info(calls))
            d["any_graph"] = any(c["kind"] == "graph" for c in calls)
            for rt in RATES:
                b28, b34 = proj(calls, gen, comp, d["llm"] or 0, d["tools"] or 0, d["capped"], rt)
                d[f"B28_{rt}"] = round(b28, 1); d[f"B34_{rt}"] = round(b34, 1)
            rows.append(d)

    with open(f"{OUT}/per_rollout.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)


    def q(xs, p):
        xs = sorted(xs); return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


    L = []
    L.append(f"# v083 budget and graph-tool tabulation\n\nCut-off {cut}. Rows read: " +
             ", ".join(f"{g} {sum(r['group'] == g for r in rows)}" for g in ("legacy_baseline", "legacy_variant", "mt01")) + "\n")
    for name, sel in (("legacy all", lambda r: r["group"] != "mt01"), ("legacy baseline", lambda r: r["group"] == "legacy_baseline"),
                      ("mt01", lambda r: r["group"] == "mt01")):
        s = [r for r in rows if sel(r)]
        if not s: continue
        c = [r for r in s if r["capped"]]
        L.append(f"## {name}: {len(c)}/{len(s)} capped at {CAP}")
        for k in ("cut_off_mid_work", "finished_and_padded"):
            L.append(f"- {k}: {sum(r['cap_class'] == k for r in c)} (resolved {sum(r['resolved'] for r in c if r['cap_class'] == k)})")
        L.append(f"- patch at cap {sum(bool(r['patch_at_cap']) for r in c)}; submit before cap {sum(r['submit'] == 'before_cap' for r in c)}, "
                 f"after cap {sum(r['submit'] == 'after_cap' for r in c)}, none {sum(r['submit'] == 'none' for r in c)}; "
                 f"test after last edit {sum(bool(r['test_after_last_edit']) for r in c)}")
        kinds = {}
        for r in c:
            for k in r["last6"].split(): kinds[k] = kinds.get(k, 0) + 1
        L.append(f"- last-6 charged call kinds: {kinds}")
        du = [r["dur"] for r in s]; pc = [r["dur"] / max(r["llm"], 1) for r in s]; pt = [r["dur"] / max(r["tools"], 1) for r in s]
        L.append(f"- wall s per rollout median/p90/p95 {q(du,.5):.0f}/{q(du,.9):.0f}/{q(du,.95):.0f}; per LLM call {q(pc,.5):.1f}/{q(pc,.9):.1f}/{q(pc,.95):.1f}; per charged tool call {q(pt,.5):.1f}/{q(pt,.9):.1f}/{q(pt,.95):.1f}")
        for rt in RATES:
            for cap in (28, 34):
                v = [r[f"B{cap}_{rt}"] for r in s]
                L.append(f"- B cap {cap} at {rt} tok/s: mean {S.mean(v):.0f} s, p90 {q(v,.9):.0f}, p95 {q(v,.95):.0f}, >480 s {sum(x > 480 for x in v)}/{len(v)}, 120 tasks {S.mean(v)*120/3600:.1f} h")
        g = [r for r in s if r["any_graph"]]
        L.append(f"- graph: rollouts with >=1 call {len(g)}/{len(s)}; calls " +
                 ", ".join(f"{n} {sum(r['n_' + n] for r in s)}" for n in sorted(GRAPH)) +
                 f"; used later {sum(r['graph_used'] for r in s)}; error/empty {sum(r['graph_err_or_empty'] for r in s)}; nudge right after {sum(r['graph_nudge_after'] for r in s)}")
        L.append(f"- resolved with graph {sum(r['resolved'] for r in g)}/{len(g)}, without {sum(r['resolved'] for r in s if not r['any_graph'])}/{len(s)-len(g)} (description only)\n")
    L.append("## Examples (capped)")
    for r in [r for r in rows if r["capped"]][:5]:
        L.append(f"- {r['run']} {r['task']}: last6 [{r['last6']}], patch {r['patch_at_cap']}, submit {r['submit']}, test after edit {r['test_after_last_edit']} -> {r['cap_class']}, resolved {r['resolved']}")
    L.append("\n## Method\n- test = run_command matching pytest/unittest/`python file.py`/`python -c`; edit = successful edit_file/write_file; read = other run_command or read_file.\n"
             "- cut_off_mid_work: no patch at cap, or last successful edit not followed by a test or submit, or the last 6 charged calls still contain an edit (patch still changing); a submit counts only if made before the cap (submit is free and nearly always follows the cap).\n"
             f"- Projection (v062 method B): gen_tokens/r + tool_s + {O} s x LLM calls + compaction events x ({HIDDEN_TOK} hidden tokens / r + {O} s); compaction = prompt drop >= {DROP} tokens; "
             "cap 34 adds 6 x (B / charged calls) to capped rollouts only (v062 calls36 analogue). Inputs: trace usage fields and timestamps; HIDDEN_TOK from analysis/scorer-time-projection-boss-v062/report.md.\n"
             "- graph used = a .py path or identifier from the graph result (not in its own arguments) appears in a later call's arguments.")
    open(f"{OUT}/summary.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
