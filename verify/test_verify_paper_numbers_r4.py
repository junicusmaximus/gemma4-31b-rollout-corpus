"""Unit tests for verify_paper_numbers_r4.py (the cases of r3, b3da939a, plus the section column) (same cases as test_verify_paper_numbers.py, 823d7266) with invented mini tables and hand-computed answers.
Usage: python -B test_verify_paper_numbers.py WORKDIR"""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_paper_numbers_r4 as VP
import paper2_seed_analysis as P

W = sys.argv[1]; os.makedirs(W)
RC = ["rollout_id", "scope", "run", "arm", "baseline_package", "decoding_seed", "task_id", "repository", "resolved", "error",
      "agent_patch_size", "duration_seconds", "tool_calls", "attempted_calls", "charged_calls", "parse_failed_calls",
      "att_read", "att_edit", "att_test", "att_graph", "chg_read", "chg_edit", "chg_test", "chg_graph", "n_graph_calls",
      "compaction_events", "proj_b28_30", "proj_b28_34", "proj_b28_40", "capped", "cap_class", "cap_class_stamped",
      "patch_class", "gold_file_hit", "patch_flags", "edit_file_calls", "patch_class_stamped"]
CC = ["rollout_id", "position", "charged", "fail_case", "fail_budget", "fail_cause", "fail_lacks_mandatory",
      "fail_only_filepath_new_string", "fail_strict_resend", "fail_next_action", "fail_recovered",
      "fail_calls_until_recovery", "episode_start", "episode_no"]


def R(rid, task, seed, res, tc, att, chg, capped="false", cls="", stamped="", pc="resolved", gh="true", flags="", ar=0, ae=0, at=0, cr=0, ce=0, ct=0):
    return dict(rollout_id=rid, scope="main", run=rid.split("/")[0], arm="baseline", baseline_package="true", decoding_seed=seed,
                task_id=task, repository=task.split("_")[0], resolved=res, error="", agent_patch_size="10", duration_seconds="100",
                tool_calls=tc, attempted_calls=att, charged_calls=chg, parse_failed_calls=str(int(att) - int(chg)),
                att_read=ar, att_edit=ae, att_test=at, att_graph=0, chg_read=cr, chg_edit=ce, chg_test=ct, chg_graph=0,
                n_graph_calls=0, compaction_events=1, proj_b28_30=500, proj_b28_34=400, proj_b28_40=300, capped=capped,
                cap_class=cls, cap_class_stamped=stamped, patch_class=pc, gold_file_hit=gh, patch_flags=flags, edit_file_calls=ae,
                patch_class_stamped=("no gold file" if task == "fastapi_1" and seed == "1" else pc))


def F(rid, pos, cause="F", lack="true", only="true", strict="true", nxt="identical resend", rec="false", cur="", start="false", budget="false"):
    return dict(rollout_id=rid, position=pos, charged="false", fail_case="true", fail_budget=budget, fail_cause=cause,
                fail_lacks_mandatory=lack, fail_only_filepath_new_string=only, fail_strict_resend=strict, fail_next_action=nxt,
                fail_recovered=rec, fail_calls_until_recovery=cur, episode_start=start, episode_no="")


rows = [
    # charged vs attempted: 30 attempted, 28 charged (2 parse failed), capped, calls not run; corrected class differs from stamped
    R("s1/fastapi_1", "fastapi_1", "1", "false", 28, 30, 28, "true", "cut_off_mid_work", "finished_and_padded", "gold file touched", "true",
      ar=20, ae=8, at=2, cr=20, ce=6, ct=2),
    R("s1/fastapi_2", "fastapi_2", "1", "true", 5, 5, 5, ar=4, ae=1, cr=4, ce=1),
    R("s1/rich_1", "rich_1", "1", "false", 3, 3, 3, pc="no patch", gh="false", flags="patch_not_stored", ar=3, cr=3),
    R("s2/fastapi_1", "fastapi_1", "2", "true", 4, 4, 4, ar=3, ae=1, cr=3, ce=1),
    R("s2/fastapi_2", "fastapi_2", "2", "true", 4, 4, 4, ar=4, cr=4),
    # rich_1 has no row in seed 2 (missing rollout)
    R("s7/fastapi_1", "fastapi_1", "7", "false", 4, 4, 4, ar=4, cr=4),
    R("s7/fastapi_2", "fastapi_2", "7", "true", 4, 4, 4, ar=4, cr=4),
    R("s7/rich_1", "rich_1", "7", "false", 4, 4, 4, ar=4, cr=4)]
calls = [  # s1/fastapi_1: three analysed failures, one episode recovered after 3 calls; one budget refusal
    F("s1/fastapi_1", 3, start="true", rec="true", cur="3"),
    F("s1/fastapi_1", 4, rec="false"),
    F("s1/fastapi_1", 5, cause="C", lack="", only="", strict="false", nxt="re-read then edit"),
    F("s1/fastapi_1", 29, budget="true", lack="", only="", strict="", nxt="", start="true"),
    # s1/fastapi_2: one analysed failure, episode not recovered
    F("s1/fastapi_2", 1, only="false", strict="false", nxt="changed resend without re-read", start="true")]
tasks = [dict(task_id="fastapi_1", repository="fastapi", resolved_s1="false", resolved_s2="true", resolved_s7="false", stability_class=""),
         dict(task_id="fastapi_2", repository="fastapi", resolved_s1="true", resolved_s2="true", resolved_s7="true", stability_class=""),
         dict(task_id="rich_1", repository="rich", resolved_s1="false", resolved_s2="", resolved_s7="false", stability_class="")]
for name, cols, data in (("rollouts.tsv", RC, rows), ("calls.tsv", CC, calls),
                         ("tasks.tsv", ["task_id", "repository", "resolved_s1", "resolved_s2", "resolved_s7", "stability_class"], tasks)):
    with open(os.path.join(W, name), "x", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", lineterminator="\n"); w.writeheader(); w.writerows(data)
open(os.path.join(W, "reg.md"), "x").write("## A. Placeholders\n| id | x |\n|---|---|\n| m_cap | a |\n| lc_cap_a | b |\n| t_events | c |\n| m_unknown_thing | d |\n## H. old\n| id | m |\n|---|---|\n| m_parse_exact | x |\n## B. x\n| m_rows | z |\n")
vals = VP.main([W, os.path.join(W, "reg.md"), os.path.join(W, "out")])
v = {k: x[0] for k, x in vals.items()}
ok = fail = 0
def check(n, got, want):
    global ok, fail
    if got == want: ok += 1
    else: fail += 1; print("FAIL", n, "got", got, "want", want)

check("rows", v["m_rows"], 8); check("cap", v["m_cap"], 1); check("cut", v["m_cut"], 1); check("cut_changed", v["m_cut_changed"], 1)
check("att28", v["m_att28"], 0); check("att28_parse", v["m_att28_parse"], 0)
check("charged mismatch", v["charged_mismatch"], 0)
check("chg total", v["m_chg_total"], 56); check("att total", v["m_att_total"], 58)
check("kind edit pct", v["m_kind_edit_pct"], 14.3)    # 8/56 = 14.29
check("att edit pct", v["m_att_edit_pct"], 17.2)      # 10/58 = 17.24
check("failed", v["m_edit_failed"], 4); check("refused", v["m_edit_refused"], 1); check("recovered", v["m_edit_recovered"], 1)
check("episodes", (v["m_episodes"], v["m_episodes_recovered"]), (2, 1)); check("eps refusal", v["m_eps_refusal"], 1)
check("rec median", v["m_rec_calls_median"], 3)
check("cause F / lack / exact", (v["m_cause_f"], v["m_parse_fail"], v["m_parse_exact"]), (3, 3, 2))
check("resend", (v["m_resend_identical"], v["m_resend_strict"]), (2, 2))
check("N_half", (v["m_fail_half_n"], v["m_fail_half_held"], v["m_fail_top4"]), (1, 3, "3 1"))
check("fail rollouts", (v["m_fail_rollouts"], v["m_fail_rollouts_resolved"]), (2, 1))
check("unrec unres", v["m_unrec_unres"], 0)   # the unrecovered episode is in the resolved rollout s1/fastapi_2
check("patch", (v["m_pc_gold"], v["m_pc_nopatch"], v["m_patch_missing"], v["m_patch_conflict"]), (1, 1, 1, 1))
check("seed rows", (v["s1_valid"], v["s2_valid"], v["s7_valid"]), (3, 2, 3))
check("classes", (v["cls_always"], v["cls_sometimes"], v["cls_never"], v["cls_incomplete"]), (1, 1, 0, 1))
check("pairs", (v["p12_n"], v["p12_disc"], v["p17_n"], v["p17_disc"], v["p27_n"], v["p27_disc"]), (2, 1, 3, 0, 2, 1))
check("d0", (v["d0_disc"], v["d0_pairs"], v["d0_pct"]), (2, 7, 28.6))
check("proj", (v["m_proj_over_30"], v["m_proj_over"], v["m_proj_over_40"]), (8, 0, 0))
nc = {l.split("\t")[0]: l.strip().split("\t")[1] for l in open(os.path.join(W, "out", "not_computed.tsv")).readlines()[1:]}
check("register parse", sorted(nc), ["lc_cap_a", "m_unknown_thing", "t_events"])
# exact agreement of the seed statistics with paper2_seed_analysis.analyse on the same outcomes
paths = []
for l in ("1", "2", "7"):
    p = os.path.join(W, f"seed{l}.jsonl"); paths.append(p)
    with open(p, "x") as f:
        for t in tasks:
            if t[f"resolved_s{l}"] != "":
                f.write(json.dumps(dict(instance_id=t["task_id"], resolved=t[f"resolved_s{l}"] == "true")) + "\n")
ref = P.analyse(["1", "2", "7"], paths)
check("draws equal", [v[f"draw_{k}_pct"] for k in ("mean", "sd", "lo", "hi")], [ref["draws"][k] for k in ("mean_pct", "sd_pct", "p2_5_pct", "p97_5_pct")])
check("false trigger equal", [v[f"ft_{m}_pct"] for m in ("8", "16", "18", "36", "95")], [ref["false_trigger"][m]["share_pct"] for m in ("8", "16", "18", "36", "95")])
check("gmin equal", [v[f"gmin_{m}"] for m in ("8", "16", "18", "36", "95")], [ref["g_min"][m]["g_min"] for m in ("8", "16", "18", "36", "95")])
check("d0 equal", v["d0_pct"], ref["d0"]["d0_pct"])
check("pc moved", (v["m_pc_moved"], v["s1_nogold_stamped"], v["s1_nogold_moved"]), (1, 1, 1))
check("cut undecided", v["m_cut_undecided"], 0)
check("reasons", (nc["lc_cap_a"].startswith("from the label check"), nc["t_events"]), (True, "quoted from a sealed report"))
secs = {l.split("\t")[0]: l.rstrip("\n").split("\t")[3] for l in open(os.path.join(W, "out", "all_values.tsv")).readlines()[1:]}
check("sections", (secs["m_cap"], secs["m_parse_exact"], secs["m_rows"]), ("A", "H", "-"))
check("H not in register_values", "m_parse_exact" in open(os.path.join(W, "out", "register_values.tsv")).read(), False)
check("eps refusal", v["m_eps_refusal"], 1)
print(f"tests passed {ok}, failed {fail}")
sys.exit(1 if fail else 0)
