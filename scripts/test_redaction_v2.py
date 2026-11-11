#!/usr/bin/env python3
"""Tests of redact_traces_v2.py and restore_traces_v2.py and audit_corpus_v2.py. All texts here are invented."""
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audit_corpus as A  # noqa: E402
import audit_corpus_v2 as AU  # noqa: E402
import redact_traces as R  # noqa: E402
import redact_traces_v2 as V  # noqa: E402
import restore_traces_v2 as RS  # noqa: E402

STATEMENT = ("The frobnicator crashes when the widget list is empty and the tolerance flag is set to a negative value in strict mode. "
             "Expected: a clear ValueError at the guard.")
HINTS = "Maintainers note: the guard for an empty widget list was removed during the refactor of the tolerance module in release two."
SNAP_FILE = "def guard(widgets, tolerance=0, strict=False):\n    widgets = list(widgets)\n    validate_tolerance(tolerance, strict_mode=strict)\n    return widgets\n"
GOLD = ("--- a/toy/guard.py\n+++ b/toy/guard.py\n@@ -2,3 +2,5 @@ def guard(widgets, tolerance=0, strict=False):\n"
        "     widgets = list(widgets)\n     validate_tolerance(tolerance, strict_mode=strict)\n"
        "+    if len(widgets) == 0:\n+        raise ValueError('the widget list must not be empty in strict mode')\n     return widgets\n")
TEST_PATCH = ("--- a/tests/test_guard.py\n+++ b/tests/test_guard.py\n@@ -1,2 +1,6 @@\n"
              "+def test_guard_rejects_empty_widget_lists_in_strict_mode():\n+    with pytest.raises(ValueError):\n+        guard([], strict=True)\n")
TASK = {"instance_id": "toy_1", "repo": "toy/toy", "problem_statement": STATEMENT, "hints_text": HINTS, "patch": GOLD, "test_patch": TEST_PATCH}
ORG_FILE = "You are a careful repository agent working inside a sandbox. Always read the failing test before you edit any source file. Never print secrets."
OWN_ADDITION = "Our own addition: keep every note short and name the file you changed."
EDIT_LINE = "raise ValueError('the widget list must not be empty in strict mode')"
CONTEXT_LINES = "widgets = list(widgets)\nvalidate_tolerance(tolerance, strict_mode=strict)"
TEST_LINE = "def test_guard_rejects_empty_widget_lists_in_strict_mode():"
RULES = R.PathRules(["/home/alice/proj/root", "alice"])


def trace(user="", agent_msg="", observation="", args=None, system="You are a toy agent."):
    return {"schema_version": "T-1", "steps": [
        {"step_id": 1, "source": "system", "message": system, "extra": {"k": 1}},
        {"step_id": 2, "source": "user", "message": user, "extra": {"k": 2}},
        {"step_id": 3, "source": "agent", "message": agent_msg, "tool_calls": [{"tool_call_id": "c1", "function_name": "edit_file", "arguments": args or {"command": "ls"}}],
         "observation": {"content": observation}, "extra": {"k": 3}}], "final_metrics": {"total_steps": 3}}


def raw_of(obj):
    return json.dumps(obj, indent=2).encode("utf-8")


def slurp(path, mode="r"):
    with open(path, mode) as fh:
        return fh.read()


def common_40(text, source_text):
    norm = lambda s: " ".join(s.split())
    a, b = norm(text), norm(source_text)
    return any(b[i:i + 40] in a for i in range(0, max(0, len(b) - 39)))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.snap_dir = os.path.join(d, "snap"); os.makedirs(self.snap_dir)
        with tarfile.open(os.path.join(self.snap_dir, "toy_1.tgz"), "w:gz") as tf:
            data = SNAP_FILE.encode(); ti = tarfile.TarInfo("repo/guard.py"); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
        self.org_dir = os.path.join(d, "org"); os.makedirs(os.path.join(self.org_dir, "prompts"))
        with open(os.path.join(self.org_dir, "prompts", "system.md"), "w") as fh:
            fh.write(ORG_FILE)
        self.org = V.load_organiser(self.org_dir)
        self.org_map = V.organiser_map(self.org_dir)
        self.snap = A.Snapshots(self.snap_dir).text("toy_1")
        self.tasks = {"toy_1": TASK}

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, obj, snapshot=True, organiser=True, task=TASK):
        raw = raw_of(obj)
        red, st = V.redact_trace_bytes(raw, task, RULES, self.org if organiser else (), self.snap if snapshot else None)
        back = V.restore_trace_bytes(red, {task["instance_id"]: task}, task["instance_id"], RULES, self.org_map)
        self.assertEqual(back, raw, "restore(redact(x)) must be x")
        return raw, red, st


class Sources(Base):
    def test_gold_patch_span_in_edit_argument(self):
        raw, red, st = self.go(trace(args={"path": "toy/guard.py", "new_string": "    if len(widgets) == 0:\n        " + EDIT_LINE}))
        self.assertGreaterEqual(st["n_pa"], 1)
        self.assertFalse(common_40(red.decode(), GOLD))
        self.assertGreater(st["removed_pa"], 0)

    def test_test_patch_span_in_json_text_of_an_observation(self):
        obs = json.dumps({"stdout": TEST_LINE + "\n    with pytest.raises(ValueError):", "exit": 0})
        raw, red, st = self.go(trace(observation=obs))
        self.assertGreaterEqual(st["n_tp"], 1)
        self.assertFalse(common_40(red.decode(), TEST_PATCH))

    def test_span_in_the_snapshot_stays_visible(self):
        raw, red, st = self.go(trace(agent_msg="context: " + CONTEXT_LINES + " done"))
        self.assertEqual(st["n_pa"], 0)
        self.assertIn("validate_tolerance(tolerance, strict_mode=strict)", red.decode())

    def test_without_a_snapshot_everything_is_replaced(self):
        raw, red, st = self.go(trace(agent_msg="context: " + CONTEXT_LINES + " done"), snapshot=False)
        self.assertGreaterEqual(st["n_pa"], 1)
        self.assertNotIn("validate_tolerance(tolerance", red.decode())

    def test_scaffold_only_span_is_replaced(self):
        # diff header and hunk header and one context line: nothing of it is new code, yet the run as a whole is not in the snapshot
        text = "+++ b/toy/guard.py\n@@ -2,3 +2,5 @@ def guard(widgets, tolerance=0, strict=False):\n     widgets = list(widgets)\n"
        raw, red, st = self.go(trace(observation=text))
        self.assertGreaterEqual(st["n_pa"], 1)
        self.assertFalse(common_40(red.decode(), GOLD))

    def test_organiser_span_in_system_instruction(self):
        raw, red, st = self.go(trace(system=ORG_FILE + " " + OWN_ADDITION))
        self.assertEqual(st["n_og"], 1)
        self.assertIn(OWN_ADDITION, red.decode())
        self.assertNotIn("Always read the failing test", red.decode())
        self.assertIn("og:prompts%2Fsystem.md", red.decode())

    def test_restore_needs_the_organiser_folder_and_the_right_file(self):
        red, _ = V.redact_trace_bytes(raw_of(trace(system=ORG_FILE)), TASK, RULES, self.org, self.snap)
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, self.tasks, "toy_1", RULES, None)
        other = {"prompts/system.md": V.Source("og:prompts/system.md", "og", ORG_FILE + " changed", False, "prompts/system.md", False)}
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, self.tasks, "toy_1", RULES, other)
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, self.tasks, "toy_1", RULES, {})

    def test_two_sources_next_to_each_other(self):
        text = "Expected: a clear ValueError at the guard. " + TEST_LINE
        raw, red, st = self.go(trace(agent_msg=text))
        self.assertGreaterEqual(st["n_ps"], 1)
        self.assertGreaterEqual(st["n_tp"], 1)
        self.assertFalse(common_40(red.decode(), STATEMENT))
        self.assertFalse(common_40(red.decode(), TEST_PATCH))

    def test_span_shared_by_two_sources_gets_one_placeholder(self):
        task = dict(TASK, problem_statement="The fix is " + EDIT_LINE + " in the guard.")
        raw, red, st = self.go(trace(agent_msg="so: " + EDIT_LINE), task=task)
        self.assertEqual(st["n_ps"] + st["n_pa"], 1)

    def test_statement_and_hints_as_before(self):
        raw, red, st = self.go(trace(user=STATEMENT, agent_msg=HINTS))
        self.assertEqual((st["n_ps"], st["n_ht"]), (1, 1))

    def test_unknown_task_id_and_changed_task_file(self):
        red, _ = V.redact_trace_bytes(raw_of(trace(agent_msg="x " + EDIT_LINE)), TASK, RULES, self.org, self.snap)
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, self.tasks, "nope", RULES, self.org_map)
        changed = dict(TASK, patch=GOLD + "+    extra_line_added_later = 1\n")
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, {"toy_1": changed}, "toy_1", RULES, self.org_map)

    def test_brackets_and_paths_still_work(self):
        raw, red, st = self.go(trace(agent_msg="open ⟦ and ⟧ in /home/alice/proj/root/x by alice"))
        self.assertEqual(st["paths"], 2)


class EmailLeaveOut(Base):
    def test_real_looking_address_leaves_the_trace_out(self):
        with self.assertRaises(V.LeftOut) as cm:
            V.redact_trace_bytes(raw_of(trace(observation="Author-email: maintainer@acme-widgets.io")), TASK, RULES, self.org, self.snap)
        self.assertEqual(cm.exception.kind, "left-out-email")

    def test_address_of_an_example_domain_stays(self):
        raw, red, st = self.go(trace(observation="mail user@example.com or noreply@users.noreply.github.com"))
        self.assertEqual(red, raw)

    def test_address_inside_a_protected_span_does_not_count(self):
        task = dict(TASK, problem_statement="Please write to the person at help@acme-widgets.io about the frobnicator crash with empty lists.")
        raw, red, st = self.go(trace(user=task["problem_statement"]), task=task)
        self.assertEqual(st["n_ps"], 1)
        self.assertNotIn("acme-widgets", red.decode())

    def test_graph_tool_and_serialiser_cases_have_kinds(self):
        obj = trace()
        obj["steps"][2]["tool_calls"][0]["function_name"] = "get_code_neighbors"
        with self.assertRaises(V.LeftOut) as cm:
            V.redact_trace_bytes(raw_of(obj), TASK, RULES, self.org, self.snap)
        self.assertEqual(cm.exception.kind, "left-out-graph")
        with self.assertRaises(V.LeftOut) as cm:
            V.redact_trace_bytes(json.dumps(trace(), indent=4).encode(), TASK, RULES, self.org, self.snap)
        self.assertEqual(cm.exception.kind, "left-out-serialiser")


class CommandLineAndAudit(Base):
    def write_traces(self, name, objs):
        d = os.path.join(self.tmp.name, name); os.makedirs(d)
        for fn, obj in objs.items():
            with open(os.path.join(d, fn), "wb") as fh:
                fh.write(raw_of(obj))
        return d

    def tasks_file(self):
        p = os.path.join(self.tmp.name, "tasks.jsonl")
        with open(p, "w") as fh:
            fh.write(json.dumps(TASK) + "\n")
        return p

    def test_cli_round_trip_manifest_and_audit(self):
        tf = self.tasks_file()
        src = self.write_traces("orig", {"trace_toy_1.json": trace(system=ORG_FILE + " " + OWN_ADDITION, user=STATEMENT + "\n" + HINTS,
                                                                     agent_msg="fix: " + EDIT_LINE + " " + TEST_LINE + " context: " + CONTEXT_LINES,
                                                                     observation="user@example.com")})
        leaked = self.write_traces("mail", {"trace_toy_1.json": trace(observation="Author-email: maintainer@acme-widgets.io")})
        red, man = os.path.join(self.tmp.name, "red"), os.path.join(self.tmp.name, "man.tsv")
        self.assertEqual(V.main(["--tasks", tf, "--in", src, "--out", red, "--manifest", man, "--snapshots", self.snap_dir, "--organiser", self.org_dir]), 0)
        rows = [l.split("\t") for l in slurp(man).strip().split("\n")]
        self.assertEqual(len(rows[0]), len(rows[1]))
        rec = dict(zip(rows[0], rows[1]))
        self.assertEqual(rec["status"], "redacted")
        for c in ("n_ps", "n_ht", "n_pa", "n_tp", "n_og"):
            self.assertGreaterEqual(int(rec[c]), 1, c)
        # restore through the command line, with and without the organiser folder
        back = os.path.join(self.tmp.name, "back")
        self.assertEqual(RS.main(["--tasks", tf, "--in", red, "--out", back, "--manifest", man, "--organiser", self.org_dir]), 0)
        self.assertEqual(slurp(os.path.join(back, "trace_toy_1.json"), "rb"), slurp(os.path.join(src, "trace_toy_1.json"), "rb"))
        self.assertEqual(RS.main(["--tasks", tf, "--in", red, "--out", os.path.join(self.tmp.name, "back2"), "--manifest", man]), 1)
        # audit of the redacted trace: zero hits; audit of the original: hits for all five sources
        rep = os.path.join(self.tmp.name, "rep.json")
        self.assertEqual(AU.main(["--tasks", tf, "--traces", red, "--snapshots", self.snap_dir, "--organiser", self.org_dir, "--report", rep]), 0)
        rep_orig = os.path.join(self.tmp.name, "rep_orig.json")
        self.assertEqual(AU.main(["--tasks", tf, "--traces", src, "--snapshots", self.snap_dir, "--organiser", self.org_dir, "--report", rep_orig]), 1)
        by = json.loads(slurp(rep_orig))["r1"]["by_field"]
        for f in ("problem_statement", "hints_text", "patch", "test_patch", "organiser"):
            self.assertGreaterEqual(by.get(f + ":hit", 0), 1, f)
        # a trace with a real looking address is left out and listed
        man2 = os.path.join(self.tmp.name, "man2.tsv")
        V.main(["--tasks", tf, "--in", leaked, "--out", os.path.join(self.tmp.name, "red2"), "--manifest", man2, "--snapshots", self.snap_dir, "--organiser", self.org_dir])
        row = slurp(man2).strip().split("\n")[1].split("\t")
        self.assertEqual(row[2], "left-out-email")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "red2", "trace_toy_1.json")))

    def test_audit_flags_a_real_looking_address_and_tolerates_example_domains(self):
        tf = self.tasks_file()
        bad = self.write_traces("bad", {"trace_toy_1.json": trace(observation="Author-email: maintainer@acme-widgets.io")})
        ok = self.write_traces("ok", {"trace_toy_1.json": trace(observation="user@example.com")})
        self.assertEqual(AU.main(["--tasks", tf, "--traces", bad, "--report", os.path.join(self.tmp.name, "a.json"), "--snapshots", self.snap_dir]), 1)
        self.assertEqual(AU.main(["--tasks", tf, "--traces", ok, "--report", os.path.join(self.tmp.name, "b.json"), "--snapshots", self.snap_dir]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
