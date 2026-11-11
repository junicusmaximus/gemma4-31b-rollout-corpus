"""verify_paper_numbers_r4.py: recomputes the register ids of paper 2 from the three released tables only.
Revision 4 (for register v0.3.2, 618b6d0c): revision 3 (67b08012) plus a column register_section (A, H or -) in
all_values.tsv; ids of section H ("no longer used by the body") are still computed but only listed in all_values.tsv.
m_eps_refusal = fail_case, fail_budget and episode_start in calls.tsv, the definition of the field
episodes_opened_by_budget_refusal of failed_edit_features.py (is_budget and episode_start). Revision 3 (for register v0.3.1, 46e819ee): revision 2 (678c029a) plus formulas for the new ids that the tables
define (patch class moves, the stamped "no gold file" stratum of seed 1, cap class changes and undecided under the
register names) and the source of every id taken from elsewhere. Revision 2 of verify_paper_numbers.py (69840510): runs with the Python standard library and numpy alone (no competition
harness). Imports only paper2_seed_analysis.py (8c92b263, harness free; found beside this file in this public copy).
n_half below mirrors failed_edit_features.n_half (36321db2) line for line, applied to rows with cause_detail "" (no
budget refusals are passed in). Everything else is unchanged from revision 1.
Usage: python3 -B verify_paper_numbers_r4.py TABLE_DIR REGISTER.md OUT_DIR   (OUT_DIR must not exist)"""
import csv, json, os, re, statistics, sys

import collections

V086 = os.path.dirname(os.path.abspath(__file__))  # public sibling-only import
sys.path.insert(0, V086)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # a copy beside this file wins
import paper2_seed_analysis as P   # noqa: E402


def is_budget(r):  # mirrors failed_edit_features.is_budget
    return r['cause_detail'].startswith('F-budget')


def n_half(rows):  # mirrors failed_edit_features.n_half
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


def T(x):
    return x == "true"


def load(d, n):
    return list(csv.DictReader(open(os.path.join(d, n)), delimiter="\t"))


def register_ids(path):
    ids, on = [], False
    for line in open(path, encoding="utf-8"):
        if line.startswith("## "):
            on = line.startswith("## A.")
            continue
        m = re.match(r"^\| ([a-z][a-z0-9_]*) \|", line)
        if on and m and m.group(1) != "id":
            ids.append(m.group(1))
    return ids


def register_section_ids(path, letter):
    ids, on = [], False
    for line in open(path, encoding="utf-8"):
        if line.startswith("## "):
            on = line.startswith(f"## {letter}.")
            continue
        m = re.match(r"^\| ([a-z][a-z0-9_]*) \|", line)
        if on and m and m.group(1) != "id":
            ids.append(m.group(1))
    return ids


def q50(xs):  # quantile helper of budget_graph_v083b: element round(0.5 * (n - 1)) of the sorted list
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.5 * (len(xs) - 1))))]


def scope_values(s, rows, C, by, put):
    ids = {r["rollout_id"] for r in rows}
    cs = [c for c in C if c["rollout_id"] in ids]
    fails = [c for c in cs if T(c["fail_case"]) and not T(c["fail_budget"])]
    eps = [c for c in fails if T(c["episode_start"])]
    capped = [r for r in rows if T(r["capped"])]
    unres = [r for r in rows if not T(r["resolved"])]
    put(f"{s}_rows", len(rows), f"rows, scope {s}")
    put(f"{s}_resolved", sum(T(r["resolved"]) for r in rows), "resolved rows")
    put(f"{s}_unresolved", len(unres), "rows minus resolved")
    put(f"{s}_cap", len(capped), "capped (tool_calls >= 28)")
    put(f"{s}_cut", sum(r["cap_class"] == "cut_off_mid_work" for r in capped), "capped, corrected class cut_off_mid_work")
    put(f"{s}_padded", sum(r["cap_class"] == "finished_and_padded" for r in capped), "capped, corrected class finished_and_padded")
    put(f"{s}_undecided", sum(r["cap_class"] == "undecided" for r in capped), "capped, corrected class undecided")
    put(f"{s}_cut_stamped", sum(r["cap_class_stamped"] == "cut_off_mid_work" for r in capped), "capped, stamped class cut_off_mid_work")
    put(f"{s}_cut_changed", sum(r["cap_class"] != r["cap_class_stamped"] for r in capped), "capped, corrected != stamped")
    put(f"{s}_cut_unres", sum(r["cap_class"] == "cut_off_mid_work" for r in capped if not T(r["resolved"])), "unresolved and corrected cut_off_mid_work")
    att28 = [r for r in rows if int(r["attempted_calls"]) >= 28 and int(r["charged_calls"]) < 28]
    put(f"{s}_att28", len(att28), "attempted >= 28 and charged < 28")
    a28 = {r["rollout_id"] for r in att28}
    put(f"{s}_att28_parse", sum(T(c["fail_lacks_mandatory"]) for c in fails if c["rollout_id"] in a28), "failed edits lacking a mandatory argument in those rollouts")
    put(f"{s}_graph_calls", sum(int(r["n_graph_calls"]) for r in rows), "sum n_graph_calls")
    put(f"{s}_edit_calls", sum(int(r["edit_file_calls"]) for r in rows), "sum edit_file_calls")
    put(f"{s}_edit_failed", len(fails), "failed edit cases, budget refusals left out")
    put(f"{s}_edit_refused", sum(T(c["fail_case"]) and T(c["fail_budget"]) for c in cs), "failed edit cases refused by budget")
    put(f"{s}_edit_recovered", sum(T(c["fail_recovered"]) for c in fails), "analysed failures recovered")
    put(f"{s}_cause_f", sum(c["fail_cause"] == "F" for c in fails), "cause F among analysed failures")
    put(f"{s}_parse_fail", sum(T(c["fail_lacks_mandatory"]) for c in fails), "cause F lacking a mandatory argument")
    put(f"{s}_parse_exact", sum(T(c["fail_only_filepath_new_string"]) for c in fails), "cause F with exactly filepath and new_string")
    put(f"{s}_resend_identical", sum(c["fail_next_action"] == "identical resend" for c in fails), "v082 next action identical resend")
    put(f"{s}_resend_strict", sum(T(c["fail_strict_resend"]) for c in fails), "next call same tool and identical arguments")
    put(f"{s}_episodes", len(eps), "episode openers among analysed failures")
    put(f"{s}_episodes_recovered", sum(T(c["fail_recovered"]) for c in eps), "recovered episode openers")
    put(f"{s}_eps_refusal", sum(T(c["fail_case"]) and T(c["fail_budget"]) and T(c["episode_start"]) for c in cs), "episode openers refused by budget")
    rc = [int(c["fail_calls_until_recovery"]) for c in eps if T(c["fail_recovered"]) and c["fail_calls_until_recovery"] != ""]
    put(f"{s}_rec_calls_median", statistics.median(rc) if rc else "", "median calls until recovery, recovered episodes")
    fr = {c["rollout_id"] for c in fails}
    put(f"{s}_fail_rollouts", len(fr), "rollouts with an analysed failure")
    put(f"{s}_fail_rollouts_resolved", sum(T(by[x]["resolved"]) for x in fr), "resolved among them")
    unrec = {c["rollout_id"] for c in eps if not T(c["fail_recovered"])}
    put(f"{s}_unrec_unres", sum(1 for r in unres if r["rollout_id"] in unrec), "unresolved with an unrecovered episode")
    pseudo = [dict(task=by[c["rollout_id"]]["task_id"], seed=by[c["rollout_id"]]["decoding_seed"],
                   run=by[c["rollout_id"]]["run"], cause_detail="") for c in fails]
    nh = n_half(pseudo)
    put(f"{s}_fail_half_n", nh["n_half"], "failed_edit_features.n_half over the analysed failures")
    put(f"{s}_fail_half_held", nh["n_half_hold"], "failures held by those rollouts")
    put(f"{s}_fail_top4", " ".join(str(x["failed"]) for x in nh["top4"]), "failures of the four rollouts with most failures")
    for cls, key in (("gold file touched", "gold"), ("no gold file", "nogold"), ("scratch only", "scratch"), ("no patch", "nopatch")):
        put(f"{s}_pc_{key}", sum(r["patch_class"] == cls for r in unres), f"unresolved with patch class {cls}")
    put(f"{s}_pc_resolved", sum(r["patch_class"] == "resolved" for r in rows), "patch class resolved")
    put(f"{s}_pc_moved", sum(r["patch_class"] != r["patch_class_stamped"] for r in rows), "patch class (patch_class_v2) != patch_class_stamped")
    put(f"{s}_cut_undecided", sum(r["cap_class"] == "undecided" for r in capped), "capped with corrected class undecided (CLAR6A)")
    put(f"{s}_gold_hit", sum(T(r["gold_file_hit"]) for r in rows), "gold_file_hit true, all rows")
    put(f"{s}_patch_missing", sum("patch_not_stored" in r["patch_flags"] for r in rows), "flag patch_not_stored")
    put(f"{s}_patch_conflict", sum(("size_field_nonzero_but_empty" in r["patch_flags"]) or
                                   ("patch_not_stored" in r["patch_flags"] and int(r["agent_patch_size"] or 0) > 0) for r in rows),
        "flag size_field_nonzero_but_empty, or missing file with size > 0")
    if rows:
        put(f"{s}_wall_median", q50([float(r["duration_seconds"]) for r in rows]), "duration_seconds, v083b quantile rule")
        put(f"{s}_compaction_mean", P.pct(statistics.mean(int(r["compaction_events"]) for r in rows) / 100), "mean compaction_events, one decimal half up")
    for rate, idk in ((30, "_30"), (34, ""), (40, "_40")):
        put(f"{s}_proj_over{idk}", sum(float(r[f"proj_b28_{rate}"]) > 480 for r in rows), f"proj_b28_{rate} > 480")
    for pre, name in (("chg", "kind"), ("att", "att")):
        tot = sum(int(r[f"{pre}_{k}"]) for r in rows for k in ("read", "edit", "test", "graph"))
        put(f"{s}_{pre}_total", tot, f"sum of {pre}_* columns")
        for k in ("read", "edit", "test", "graph"):
            n = sum(int(r[f"{pre}_{k}"]) for r in rows)
            put(f"{s}_{name}_{k}_pct", P.pct(n / tot) if tot else "", f"{pre}_{k} / {pre} total, half up")
            put(f"{s}_{pre}_{k}_n", n, f"sum {pre}_{k}")
    put(f"{s}_err_rows", sum(r["error"] != "" for r in rows), "rows with a non empty error")
    for rp in ("fastapi", "rich"):
        put(f"{s}_res_{rp}", sum(T(r["resolved"]) for r in rows if r["repository"] == rp), f"resolved, {rp}")
        put(f"{s}_rows_{rp}", sum(r["repository"] == rp for r in rows), f"rows, {rp}")


def seed_values(K, put):
    seeds = [l for l in ("1", "2", "7") if any(k[f"resolved_s{l}"] != "" for k in K)]
    if len(seeds) < 2:
        return seeds
    sd = {l: {"valid": {k["task_id"]: T(k[f"resolved_s{l}"]) for k in K if k[f"resolved_s{l}"] != ""}} for l in seeds}
    pairs = {}
    for i, a in enumerate(seeds):
        for b in seeds[i + 1:]:
            pt = P.pair_table(sd[a]["valid"], sd[b]["valid"]); pairs[(a, b)] = pt
            for key, col in (("disc", "discordant"), ("n", "n"), ("both", "both"), ("neither", "neither")):
                put(f"p{a}{b}_{key}", pt[col], f"pair table of seeds {a} and {b}, {col}")
    tn = sum(p["n"] for p in pairs.values()); td = sum(p["discordant"] for p in pairs.values())
    d0 = td / tn if tn else None
    put("d0_disc", td, "discordant summed over pairs"); put("d0_pairs", tn, "tasks summed over pairs")
    put("d0_pct", P.pct(d0), "d0 percent, half up")
    put("rule5a_pairs", len(pairs), "seed pairs")
    put("rule5a_triggered", sum(p["costly_rule"]["triggered"] for p in pairs.values()), "pairs where rule 5a triggers")
    st = P.stability(sd, seeds)
    if "three_seed" in st:
        for k in ("always", "sometimes", "never", "incomplete"):
            put(f"cls_{k}", st["three_seed"][k], "rule 3 three seed class")
    dr = P.draw_sim(sd, seeds)
    for key, col in (("mean", "mean_pct"), ("sd", "sd_pct"), ("lo", "p2_5_pct"), ("hi", "p97_5_pct")):
        put(f"draw_{key}_pct", dr[col], f"draw simulation {col}")
    for m, v in P.false_trigger(sd, seeds).items():
        put(f"ft_{m}_pct", v["share_pct"], f"false trigger share m={m} (m_used {v['m_used']})")
    for m, v in (P.g_min(d0) or {}).items():
        put(f"gmin_{m}", v["g_min"], f"g_min at d0, m={m}")
    return seeds


def compute(R, C, K):
    out = {}
    def put(k, v, note): out[k] = (v, note)
    by = {r["rollout_id"]: r for r in R}
    scopes = dict(d=[r for r in R if r["scope"] == "dev"],
                  b=[r for r in R if r["scope"] == "dev" and T(r["baseline_package"])],
                  m=[r for r in R if r["scope"] == "main"])
    put("rows_total", len(R), "rows of rollouts.tsv")
    put("d_tasks", len({r["task_id"] for r in scopes["d"]}), "distinct task_id, scope dev")
    put("charged_mismatch", sum(r["charged_calls"] != r["tool_calls"] for r in R), "rollouts with charged_calls != tool_calls")
    for s, rows in scopes.items():
        scope_values(s, rows, C, by, put)
    for l in ("1", "2", "7"):
        rr = [r for r in scopes["m"] if r["decoding_seed"] == l]
        if rr:
            put(f"s{l}_valid", len(rr), f"main rows of seed {l}")
            put(f"s{l}_resolved", sum(T(r["resolved"]) for r in rr), f"resolved, seed {l}")
    put("err_rows", out["m_err_rows"][0], "main rows with a non empty error")
    s1 = [r for r in scopes["m"] if r["decoding_seed"] == "1"]
    put("s1_nogold_stamped", sum(r["patch_class_stamped"] == "no gold file" for r in s1), "seed 1 rows with patch_class_stamped no gold file")
    put("s1_nogold_moved", sum(r["patch_class_stamped"] == "no gold file" and r["patch_class"] == "gold file touched" for r in s1),
        "seed 1 rows stamped no gold file and corrected gold file touched")
    return out, seed_values(K, put)


REASONS = [(r"^lc_", "from the label check comparison outputs (analysis/paper2-label-audit-boss-v090/compare_output_v2/, compare_output_v2_patchclass_v2/, compare_output_corrected/), not in the tables"),
           (r"^rf_", "from the stamp files of the rule files (briefing rules folder), not in the tables"),
           (r"^rd_", "from the reader's notes released with the label check, not in the tables"),
           (r"^(red_|tr_)", "from the release tool's manifests (redaction report), not in the tables"),
           (r"^(t_rollouts|t_events|t_excess_s|mclose_compliance|screen_rollouts|s1_stack_compliance|rb_adoption)$",
            "quoted from a sealed report"),
           (r"^(p\d\d_|d0_|cls_|draw_|ft_|gmin_|rule5a_|s2_|s7_)", "needs seed 2 or seed 7 in tasks.tsv")]


def main(argv):
    d, reg, out = argv
    R, C, K = load(d, "rollouts.tsv"), load(d, "calls.tsv"), load(d, "tasks.tsv")
    vals, seeds = compute(R, C, K)
    ids = register_ids(reg)
    os.makedirs(out)
    done = [(i, *vals[i]) for i in ids if i in vals]
    nd = [(i, next((w for p, w in REASONS if re.search(p, i)), "no formula from the three tables in this script")) for i in ids if i not in vals]
    with open(os.path.join(out, "register_values.tsv"), "x") as f:
        f.write("id\tvalue\tformula\n")
        f.writelines(f"{i}\t{v}\t{n}\n" for i, v, n in done)
    with open(os.path.join(out, "not_computed.tsv"), "x") as f:
        f.write("id\treason\n")
        f.writelines(f"{i}\t{w}\n" for i, w in nd)
    hids = set(register_section_ids(reg, "H"))
    sec = lambda k: "A" if k in ids else ("H" if k in hids else "-")
    with open(os.path.join(out, "all_values.tsv"), "x") as f:
        f.write("key\tvalue\tformula\tregister_section\n")
        f.writelines(f"{k}\t{vals[k][0]}\t{vals[k][1]}\t{sec(k)}\n" for k in sorted(vals))
    print(json.dumps(dict(register_ids=len(ids), computed=len(done), not_computed=len(nd), seeds_in_tasks=seeds)))
    return vals


if __name__ == "__main__":
    main(sys.argv[1:])
