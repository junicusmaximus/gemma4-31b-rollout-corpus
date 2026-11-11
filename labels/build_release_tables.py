"""build_release_tables.py: compiles rollouts.tsv, calls.tsv, tasks.tsv (+ schema files) for the paper 2 corpus.
Usage: python -B build_release_tables.py CONFIG.json OUT_DIR   (OUT_DIR must not exist)

CONFIG lists every set explicitly (no globbing) with its run folder and the stamped label outputs to join:
{"sets": [{"run": NAME, "scope": "dev"|"main", "arm": ..., "seed": "1"|"2"|"7"|"?", "rundir": PATH,
           "v083b_csv": PATH, "cv2_csv": PATH, "ccor_a1_csv": PATH, "pc_v2_csv": PATH, "pc_v1_csv": PATH,
           "v082_dir": PATH (cases.jsonl, rollouts.jsonl), "v082_groups": [..]}, ...],
 "baseline_runs": [...]}
Per-call status uses cap_corrected.status (clarification 6) on budget_graph_v083b.parse (call positions are 0-based
indexes into that list). Per failed-edit flags (lacks a mandatory argument, carries exactly filepath and new_string,
strict resend) follow failed_edit_features.features() (clarification 5) with its MANDATORY constant and
classify_edit_failures.load_calls; only booleans are written, never arguments or observation text."""
import csv, hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
V086 = "PROJECT_ROOT/gemma4/analysis/paper2-seed-analysis-boss-v086"
V082 = "PROJECT_ROOT/gemma4/analysis/edit-failure-boss-v082"
for p in (V086, V082):
    sys.path.insert(0, p)
import budget_graph_v083b as V          # noqa: E402
import cap_corrected as CC              # noqa: E402
import classify_edit_failures as CEF    # noqa: E402
import failed_edit_features as FEF      # noqa: E402

SRC = dict(v083b=f"{V086}/budget_graph_v083b.py", call_kinds_v2=f"{V086}/call_kinds_v2.py",
           cap_corrected=f"{V086}/cap_corrected.py", cap_corrected_a1=f"{V086}/cap_corrected_a1.py",
           cap_sensitivity=f"{V086}/cap_sensitivity.py", seed_analysis=f"{V086}/paper2_seed_analysis.py",
           patch_class_v2="PROJECT_ROOT/gemma4/analysis/paper2-patch-class-boss-v087/patch_class_v2.py",
           patch_class="PROJECT_ROOT/gemma4/analysis/paper2-patch-class-boss-v087/patch_class.py",
           v082_classifier=f"{V082}/classify_edit_failures.py", v082_wrapper=f"{V082}/run_v082_explicit.py",
           failed_edit_features=f"{V082}/failed_edit_features.py", builder=os.path.abspath(__file__))


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def read_csv(p, run=None):
    rows = list(csv.DictReader(open(p)))
    return rows if run is None else [r for r in rows if r.get("run", r.get("set")) == run]


def b(x):
    return "" if x in (None, "") else ("true" if str(x).lower() in ("true", "1") else "false")


ROLLOUT_COLS = [
    ("rollout_id", "string", "run and task id joined by a slash; unique key", "builder"),
    ("scope", "string", "dev (development screens) or main (baseline over the 95 valid tasks)", "builder config"),
    ("run", "string", "result folder name of the rollout set", "builder config"),
    ("arm", "string", "baseline, M-CLOSE, S1 or read-bundle", "builder config (inventory v085)"),
    ("baseline_package", "bool", "the run used the unchanged baseline package", "builder config"),
    ("temperature", "float", "sampling temperature of the bundle", "v082 rollouts.jsonl field temperature"),
    ("decoding_seed", "string", "decoding seed (1, 2, 7; ? if not recorded)", "builder config"),
    ("task_id", "string", "competition task id", "task_results.jsonl instance_id"),
    ("repository", "string", "part of the task id before the first underscore", "builder"),
    ("resolved", "bool", "hidden tests passed (rule 1)", "task_results.jsonl resolved"),
    ("error", "string", "harness error text (budget stop or timeout), empty if none", "task_results.jsonl error"),
    ("test_exit_code", "int", "exit code of the test command", "task_results.jsonl"),
    ("agent_patch_size", "int", "bytes of the stored patch", "task_results.jsonl"),
    ("duration_seconds", "float", "local wall time of the rollout", "task_results.jsonl"),
    ("tool_calls", "int", "calls charged by the harness", "task_results.jsonl"),
    ("total_llm_calls", "int", "model calls", "task_results.jsonl"),
    ("attempted_calls", "int", "trace calls other than submit_patch and get_status (CLAR3)", "call_kinds_v2.py attempted"),
    ("charged_calls", "int", "attempted calls minus parse failed and budget refused (CLAR3); equals tool_calls", "call_kinds_v2.py charged"),
    ("parse_failed_calls", "int", "attempted calls whose arguments could not be parsed", "call_kinds_v2.py parse_failed"),
    ("budget_refused_calls", "int", "attempted calls refused because the budget was spent", "call_kinds_v2.py budget_refused"),
    ("att_read", "int", "attempted calls of kind read (kind() of v083b)", "call_kinds_v2.py att_read"),
    ("att_edit", "int", "attempted calls of kind edit", "call_kinds_v2.py att_edit"),
    ("att_test", "int", "attempted calls of kind test", "call_kinds_v2.py att_test"),
    ("att_graph", "int", "attempted calls of kind graph", "call_kinds_v2.py att_graph"),
    ("chg_read", "int", "charged calls of kind read", "call_kinds_v2.py chg_read"),
    ("chg_edit", "int", "charged calls of kind edit", "call_kinds_v2.py chg_edit"),
    ("chg_test", "int", "charged calls of kind test", "call_kinds_v2.py chg_test"),
    ("chg_graph", "int", "charged calls of kind graph", "call_kinds_v2.py chg_graph"),
    ("n_graph_calls", "int", "calls of the three code graph tools", "budget_graph_v083b.py n_get_code_neighbors + n_get_code_subgraph + n_search_similar_code"),
    ("compaction_events", "int", "prompt drops of 3,000 tokens or more (hidden compaction requests)", "budget_graph_v083b.py compactions"),
    ("gen_tokens", "int", "generated tokens (usage fields)", "budget_graph_v083b.py gen_tokens"),
    ("proj_b28_30", "float", "projected scorer seconds, variant B, cap 28, 30 tok/s", "budget_graph_v083b.py B28_30"),
    ("proj_b28_34", "float", "same at 34 tok/s", "budget_graph_v083b.py B28_34"),
    ("proj_b28_40", "float", "same at 40 tok/s", "budget_graph_v083b.py B28_40"),
    ("proj_b34_30", "float", "projected scorer seconds, variant B, cap 34, 30 tok/s", "budget_graph_v083b.py B34_30"),
    ("proj_b34_34", "float", "same at 34 tok/s", "budget_graph_v083b.py B34_34"),
    ("proj_b34_40", "float", "same at 40 tok/s", "budget_graph_v083b.py B34_40"),
    ("capped", "bool", "tool_calls of the row is at least 28 (rule 6, CLAR3C)", "task_results.jsonl tool_calls"),
    ("cap_class", "string", "corrected cap class (CLAR6 with addition 1): cut_off_mid_work, finished_and_padded or undecided; empty if not capped", "cap_corrected_a1.py corrected_class"),
    ("patch_at_cap", "bool", "corrected rule: a successful edit at or before the cap position", "cap_corrected_a1.py corrected_patch_at_cap"),
    ("test_after_last_edit", "bool", "corrected rule: an executed test after the last successful edit", "cap_corrected_a1.py corrected_test_after"),
    ("submit", "string", "corrected rule: submit timing (before_cap, after_cap, none)", "cap_corrected_a1.py corrected_submit"),
    ("last6", "string", "corrected rule: kinds of charged calls 23 to 28", "cap_corrected_a1.py corrected_last6"),
    ("cap_class_sensitivity", "string", "cap class of clarification 4 (parse failed calls not ok)", "cap_sensitivity.py via cap_corrected_a1.py"),
    ("cap_class_stamped", "string", "cap class of the stamped rule (rule 6, CLAR2)", "budget_graph_v083b.py cap_class"),
    ("patch_at_cap_stamped", "bool", "stamped rule: patch at cap", "budget_graph_v083b.py patch_at_cap"),
    ("test_after_last_edit_stamped", "bool", "stamped rule: test after last edit", "budget_graph_v083b.py test_after_last_edit"),
    ("patch_class", "string", "patch class (rule 7, CLAR7): resolved, gold file touched, no gold file, scratch only, no patch", "patch_class_v2.py class"),
    ("gold_file_hit", "bool", "the stored patch touches a file of the gold patch (rule 7, CLAR7)", "patch_class_v2.py gold_file_hit"),
    ("patch_flags", "string", "flags of the patch class script (for example patch_not_stored)", "patch_class_v2.py flags"),
    ("patch_class_stamped", "string", "patch class of the stamped script (first gold file only)", "patch_class.py class"),
    ("gold_file_hit_stamped", "bool", "gold_file_hit of the stamped script", "patch_class.py gold_file_hit"),
    ("edit_file_calls", "int", "edit_file calls (v082)", "classify_edit_failures.py via run_v082_explicit.py edit_calls"),
    ("edit_fail", "int", "failed edit_file calls including budget refusals (v082)", "v082 edit_fail"),
    ("edit_fail_nobudget", "int", "failed edit_file calls analysed (budget refusals left out, parse failures in)", "v082 edit_fail_nobudget"),
    ("last_edit_failed", "bool", "the last edit call failed (v082)", "v082 last_edit_failed"),
    ("last_edit_failed_nobudget", "bool", "the last edit call failed, budget refusals left out (v082)", "v082 last_edit_failed_nobudget"),
    ("heredoc_cmds", "int", "run_command calls writing files by heredoc (v082)", "v082 heredoc_cmds"),
    ("malformed_cmds", "int", "run_command calls that did not parse (v082)", "v082 malformed_cmds"),
    ("trace_file", "string", "filled by the release tool", "release tool"),
    ("trace_status", "string", "filled by the release tool", "release tool"),
    ("placeholders", "int", "filled by the release tool", "release tool"),
    ("trace_sha256_redacted", "string", "filled by the release tool", "release tool"),
    ("trace_sha256_original", "string", "filled by the release tool", "release tool"),
]
CALL_COLS = [
    ("rollout_id", "string", "key into rollouts.tsv", "builder"),
    ("position", "int", "0-based position over all parsed calls of the trace", "budget_graph_v083b.parse order"),
    ("charged_position", "int", "1-based position among charged calls; empty if not charged", "cap_corrected.status"),
    ("tool", "string", "tool name", "trace"),
    ("kind", "string", "read, edit, test, graph (kind() of v083b); free for submit_patch and get_status", "budget_graph_v083b.kind"),
    ("status", "string", "exec_ok, exec_error, parse_failed, budget_refused, unknown (CLAR6 rule 1)", "cap_corrected.status"),
    ("charged", "bool", "the harness charged the call (CLAR3, CLAR6)", "cap_corrected.status"),
    ("fail_case", "bool", "the call is a failed edit_file case of v082", "v082 cases.jsonl"),
    ("fail_budget", "bool", "the failed edit was refused by budget (v082 F-budget)", "v082 cases.jsonl cause_detail"),
    ("fail_cause", "string", "v082 cause letter A to F", "v082 cases.jsonl cause"),
    ("fail_lacks_mandatory", "bool", "cause F and the arguments lack filepath, old_string or new_string (CLAR5)", "failed_edit_features.MANDATORY"),
    ("fail_only_filepath_new_string", "bool", "cause F and the argument keys are exactly filepath and new_string (CLAR5)", "failed_edit_features"),
    ("fail_strict_resend", "bool", "the very next call has the same tool and an identical argument object (CLAR5)", "failed_edit_features"),
    ("fail_next_action", "string", "v082 next action label", "v082 cases.jsonl next_action"),
    ("fail_recovered", "bool", "the failure was later recovered (v082)", "v082 cases.jsonl recovered"),
    ("fail_calls_until_recovery", "int", "v082 calls until recovery (episode openers)", "v082 cases.jsonl calls_until_recovery"),
    ("episode_no", "int", "1-based number of the failure episode in the rollout (analysed failures only); empty otherwise", "v082 episode_start"),
    ("episode_start", "bool", "the case opens an episode (v082)", "v082 cases.jsonl episode_start"),
    ("episode_recovered", "bool", "the episode's opening failure was recovered", "v082 cases.jsonl recovered of the opener"),
]
TASK_COLS = [("task_id", "string", "competition task id", "results rows"),
             ("repository", "string", "part of the task id before the first underscore", "builder"),
             ("resolved_s1", "bool", "resolved in decoding seed 1 (empty if no valid row)", "rollouts.tsv"),
             ("resolved_s2", "bool", "resolved in decoding seed 2", "rollouts.tsv"),
             ("resolved_s7", "bool", "resolved in decoding seed 7", "rollouts.tsv"),
             ("stability_class", "string", "rule 3 with CLAR1 rule 3: always/sometimes/never/incomplete (3 seeds) or both/one/neither/incomplete (2 seeds); empty with one seed", "paper2_seed_analysis.stability")]


def calls_for(run, rundir, row):
    V.R = os.path.dirname(os.path.normpath(rundir))
    calls, _, _ = V.parse(run, row)
    for c in calls:
        c["status"] = CC.status(c["obs"]) if c["obs"] else "unknown"
    return calls


def build_set(s, out_r, out_c, problems):
    run, rundir = s["run"], s["rundir"]
    v083 = {r["task"]: r for r in read_csv(s["v083b_csv"], run)}
    cv2 = {r["task"]: r for r in read_csv(s["cv2_csv"], run)}
    cc = {r["task"]: r for r in read_csv(s["ccor_a1_csv"], run)}
    pc2 = {r["task_id"]: r for r in read_csv(s["pc_v2_csv"]) if r["set"] == run}
    pc1 = {r["task_id"]: r for r in read_csv(s["pc_v1_csv"]) if r["set"] == run}
    v82r = {r["task"]: r for r in map(json.loads, open(os.path.join(s["v082_dir"], "rollouts.jsonl"))) if r["run"] == run}
    v82c = [r for r in map(json.loads, open(os.path.join(s["v082_dir"], "cases.jsonl"))) if r["run"] == run]
    for line in open(os.path.join(rundir, "task_results.jsonl")):
        if not line.strip():
            continue
        row = json.loads(line)
        t = row["instance_id"]; rid = f"{run}/{t}"
        a, k, c, p2, p1, e = v083[t], cv2[t], cc.get(t), pc2[t], pc1[t], v82r[t]
        g = sum(int(a[x]) for x in ("n_get_code_neighbors", "n_get_code_subgraph", "n_search_similar_code"))
        capped = (row.get("tool_calls") or 0) >= V.CAP
        out_r.append(dict(
            rollout_id=rid, scope=s["scope"], run=run, arm=s["arm"], baseline_package=b(s["baseline"]),
            temperature=e["temperature"], decoding_seed=s["seed"], task_id=t, repository=t.split("_", 1)[0],
            resolved=b(row.get("resolved")), error=row.get("error") or "", test_exit_code=row.get("test_exit_code"),
            agent_patch_size=row.get("agent_patch_size"), duration_seconds=row.get("duration_seconds"),
            tool_calls=row.get("tool_calls"), total_llm_calls=row.get("total_llm_calls"),
            attempted_calls=k["attempted"], charged_calls=k["charged"], parse_failed_calls=k["parse_failed"],
            budget_refused_calls=k["budget_refused"], **{f"att_{x}": k[f"att_{x}"] for x in ("read", "edit", "test", "graph")},
            **{f"chg_{x}": k[f"chg_{x}"] for x in ("read", "edit", "test", "graph")},
            n_graph_calls=g, compaction_events=a["compactions"], gen_tokens=a["gen_tokens"],
            **{f"proj_b{cap}_{r}": a[f"B{cap}_{r}"] for cap in (28, 34) for r in (30, 34, 40)},
            capped=b(capped),
            cap_class=c["corrected_class"] if (capped and c) else "",
            patch_at_cap=b(c["corrected_patch_at_cap"]) if (capped and c) else "",
            test_after_last_edit=b(c["corrected_test_after"]) if (capped and c) else "",
            submit=c["corrected_submit"] if (capped and c) else "", last6=c["corrected_last6"] if (capped and c) else "",
            cap_class_sensitivity=c["sensitivity_class"] if (capped and c) else "",
            cap_class_stamped=a["cap_class"], patch_at_cap_stamped=b(a["patch_at_cap"]),
            test_after_last_edit_stamped=b(a["test_after_last_edit"]),
            patch_class=p2["class"], gold_file_hit=b(p2["gold_file_hit"]), patch_flags=p2["flags"],
            patch_class_stamped=p1["class"], gold_file_hit_stamped=b(p1["gold_file_hit"]),
            edit_file_calls=e["edit_calls"], edit_fail=e["edit_fail"], edit_fail_nobudget=e["edit_fail_nobudget"],
            last_edit_failed=b(e["last_edit_failed"]), last_edit_failed_nobudget=b(e["last_edit_failed_nobudget"]),
            heredoc_cmds=e["heredoc_cmds"], malformed_cmds=e["malformed_cmds"],
            trace_file="", trace_status="", placeholders="", trace_sha256_redacted="", trace_sha256_original=""))
        if capped and not c:
            problems.append(f"{rid}: capped but no cap_corrected_a1 row")
        calls = calls_for(run, rundir, row)
        cef_calls = CEF.load_calls(os.path.join(rundir, "traces", f"trace_{t}.json"))
        if len(cef_calls) != len(calls):
            problems.append(f"{rid}: v082 call list length {len(cef_calls)} != v083b {len(calls)}")
        cases = {r["call_index"]: r for r in v82c if r["task"] == t}
        ep, ep_rec, chg_no = 0, None, 0
        for i, cl in enumerate(calls):
            charged = cl["fn"] not in V.FREE and cl["status"] in ("exec_ok", "exec_error", "unknown")
            chg_no += charged
            r = dict(rollout_id=rid, position=i, charged_position=chg_no if charged else "", tool=cl["fn"],
                     kind="free" if cl["fn"] in V.FREE else cl["kind"], status=cl["status"], charged=b(charged),
                     fail_case="false", fail_budget="", fail_cause="", fail_lacks_mandatory="", fail_only_filepath_new_string="",
                     fail_strict_resend="", fail_next_action="", fail_recovered="", fail_calls_until_recovery="",
                     episode_no="", episode_start="", episode_recovered="")
            cs = cases.get(i)
            if cs is not None:
                if cef_calls[i]["name"] != cl["fn"]:
                    problems.append(f"{rid}@{i}: v082 case tool {cef_calls[i]['name']} != {cl['fn']}")
                bud = FEF.is_budget(cs)
                keys = set(cef_calls[i]["args"])
                nxt = cef_calls[i + 1] if i + 1 < len(cef_calls) else None
                r.update(fail_case="true", fail_budget=b(bud), fail_cause=cs["cause"],
                         fail_next_action=cs["next_action"], fail_recovered=b(cs["recovered"] == "yes"),
                         fail_calls_until_recovery="" if cs["calls_until_recovery"] is None else cs["calls_until_recovery"],
                         episode_start=b(cs["episode_start"]))
                if not bud:
                    if cs["cause"] == "F":
                        lack = any(m not in keys for m in FEF.MANDATORY)
                        r["fail_lacks_mandatory"] = b(lack)
                        r["fail_only_filepath_new_string"] = b(lack and keys == {"filepath", "new_string"})
                    r["fail_strict_resend"] = b(nxt is not None and nxt["name"] == cef_calls[i]["name"] and nxt["args"] == cef_calls[i]["args"])
                    if cs["episode_start"]:
                        ep += 1; ep_rec = cs["recovered"] == "yes"
                    if ep:
                        r["episode_no"] = ep; r["episode_recovered"] = b(ep_rec)
            out_c.append(r)
        for ci in cases:
            if ci >= len(calls):
                problems.append(f"{rid}: v082 case index {ci} outside the call list")


def write_tsv(path, cols, rows):
    with open(path, "x", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow([c[0] for c in cols])
        for r in rows:
            w.writerow(["" if r.get(c[0]) is None else r.get(c[0]) for c in cols])


def write_schema(path, cols, hashes):
    with open(path, "x", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["column", "type", "meaning", "source", "source_sha256"])
        order = [("cap_corrected_a1", "cap_corrected_a1"), ("cap_sensitivity", "cap_sensitivity"),
                 ("cap_corrected", "cap_corrected"), ("call_kinds_v2", "call_kinds_v2"), ("budget_graph_v083b", "v083b"),
                 ("patch_class_v2", "patch_class_v2"), ("patch_class.py", "patch_class"),
                 ("failed_edit_features", "failed_edit_features"), ("classify_edit_failures", "v082_classifier"),
                 ("v082", "v082_classifier"), ("paper2_seed_analysis", "seed_analysis")]
        for name, typ, meaning, src in cols:
            key = next((k for kw, k in order if kw in src), "builder" if "builder" in src else None)
            w.writerow([name, typ, meaning, src, hashes.get(key, "") if key else "input file (hash in build_manifest.json)"])


def main(argv):
    cfg = json.load(open(argv[0])); out = argv[1]
    sys.path.insert(0, V086)
    import paper2_seed_analysis as P
    rows, calls, problems = [], [], []
    for s in cfg["sets"]:
        build_set(s, rows, calls, problems)
    tasks = {}
    for r in rows:
        if r["scope"] == "main":
            tasks.setdefault(r["task_id"], {})[r["decoding_seed"]] = r["resolved"] == "true"
    seeds = [x for x in ("1", "2", "7") if any(x in v for v in tasks.values())]
    trows, cls = [], {}
    if len(seeds) > 1:
        sd = {l: {"valid": {t: v[l] for t, v in tasks.items() if l in v}} for l in seeds}
        st = P.stability(sd, seeds)
        for t in tasks:
            vals = [tasks[t].get(l) for l in seeds]
            if any(v is None for v in vals): cls[t] = "incomplete"
            elif len(seeds) == 3: cls[t] = {3: "always", 0: "never"}.get(sum(vals), "sometimes")
            else: cls[t] = "both" if all(vals) else ("neither" if not any(vals) else "one")
    for t in sorted(tasks):
        trows.append(dict(task_id=t, repository=t.split("_", 1)[0],
                          **{f"resolved_s{l}": b(tasks[t].get(l)) for l in ("1", "2", "7")}, stability_class=cls.get(t, "")))
    os.makedirs(out)
    hashes = {k: sha(p) for k, p in SRC.items()}
    write_tsv(os.path.join(out, "rollouts.tsv"), ROLLOUT_COLS, rows)
    write_tsv(os.path.join(out, "calls.tsv"), CALL_COLS, calls)
    write_tsv(os.path.join(out, "tasks.tsv"), TASK_COLS, trows)
    for n, cols in (("rollouts", ROLLOUT_COLS), ("calls", CALL_COLS), ("tasks", TASK_COLS)):
        write_schema(os.path.join(out, f"{n}.schema.tsv"), cols, hashes)
    json.dump(dict(sources={k: dict(path=SRC[k], sha256=hashes[k]) for k in SRC}, config=cfg, problems=problems,
                   rows=dict(rollouts=len(rows), calls=len(calls), tasks=len(trows))),
              open(os.path.join(out, "build_manifest.json"), "x"), indent=1)
    print(json.dumps(dict(rollouts=len(rows), calls=len(calls), tasks=len(trows), problems=problems[:20], n_problems=len(problems))))


if __name__ == "__main__":
    main(sys.argv[1:])
