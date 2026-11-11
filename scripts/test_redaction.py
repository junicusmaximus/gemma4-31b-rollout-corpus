#!/usr/bin/env python3
"""Tests of redact_traces.py and restore_traces.py. All task texts here are invented."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import redact_traces as R  # noqa: E402
import restore_traces as RS  # noqa: E402

STATEMENT = ("The frobnicator crashes when the widget list is empty and the tolerance flag is set to a negative value "
             "in strict mode.\n\nExpected: a clear ValueError. Actual: \"IndexError\" with path C:\\tmp\\x and a stray tab.")
HINTS = "Maintainers note: the guard for an empty widget list was removed during the refactor of the tolerance module in release two."
TASK = {"instance_id": "toy_1", "repo": "toy/toy", "base_commit": "0" * 40, "patch": "", "test_patch": "", "problem_statement": STATEMENT, "hints_text": HINTS}
TASK_NO_HINTS = dict(TASK, instance_id="toy_2", hints_text="")
LONG = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz"   # no spaces, 62 characters
TASK_LONG = dict(TASK, instance_id="toy_3", problem_statement=LONG, hints_text="")


def trace(user="", agent_msg="", observation="", args=None):
    return {"schema_version": "T-1", "agent": {"name": "toy", "version": "1"}, "steps": [
        {"step_id": 1, "source": "system", "message": "You are a toy agent.", "extra": {"k": 1}},
        {"step_id": 1, "source": "user", "message": user, "extra": {"k": 2}},
        {"step_id": 1, "source": "agent", "message": agent_msg, "tool_calls": [{"tool_call_id": "c1", "function_name": "run_command", "arguments": args or {"command": "ls"}}],
         "observation": {"content": observation}, "extra": {"k": 3}}],
        "final_metrics": {"total_steps": 3}}


RULES = R.PathRules(["/home/alice/proj/root", "/home/alice", "alice", "projx"])      # invented machine strings


def raw_of(obj):
    return json.dumps(obj, indent=2).encode("utf-8")


def common_40(redacted_text, field_text):
    """Independent check: does any 40-character window of the normalised field occur in the normalised text?"""
    norm = lambda s: " ".join(s.split())
    a, b = norm(redacted_text), norm(field_text)
    return any(b[i:i + 40] in a for i in range(0, max(0, len(b) - 39)))


class RoundTrip(unittest.TestCase):
    def go(self, obj, task=TASK):
        raw = raw_of(obj)
        red, st = R.redact_trace_bytes(raw, task, RULES)
        back = RS.restore_trace_bytes(red, {task["instance_id"]: task}, task["instance_id"], RULES)
        self.assertEqual(back, raw, "restore(redact(x)) must be x")
        return raw, red, st

    def test_exact_quote_in_prompt(self):
        raw, red, st = self.go(trace(user="Fix this issue:\n" + STATEMENT + "\nThanks."))
        self.assertFalse(common_40(red.decode(), STATEMENT))
        self.assertEqual(st["ps"], 1)

    def test_quote_split_by_line_break(self):
        quote = STATEMENT.replace("the widget list is empty", "the widget list\nis empty").replace("tolerance flag is set", "tolerance flag\n  is set")
        raw, red, st = self.go(trace(agent_msg="I read: " + quote))
        self.assertGreaterEqual(st["ps"], 1)
        self.assertFalse(common_40(red.decode(), STATEMENT))

    def test_quote_with_changed_spacing(self):
        quote = STATEMENT.replace(" ", "  ").replace("Expected:", "Expected:\t")
        raw, red, st = self.go(trace(agent_msg=quote))
        self.assertGreaterEqual(st["ps"], 1)
        self.assertFalse(common_40(red.decode(), STATEMENT))

    def test_quote_inside_json_escaped_string(self):
        inner = json.dumps({"status": "ok", "stdout": STATEMENT})            # quotes, backslashes and newlines escaped once
        outer_obs = json.dumps({"content": inner})                           # and once more
        raw, red, st = self.go(trace(observation=inner, args={"command": "echo " + json.dumps(STATEMENT)}))
        self.assertGreaterEqual(st["ps"], 2)
        self.assertNotIn("frobnicator crashes", red.decode())
        raw2, red2, st2 = self.go(trace(observation=outer_obs))
        self.assertNotIn("frobnicator crashes", red2.decode())

    def test_backslash_n_text_quoted_plain(self):
        task = dict(TASK, instance_id="toy_4", problem_statement="Use the literal text \\n inside the pattern string when the parser reads the escape table.", hints_text="")
        raw, red, st = self.go(trace(agent_msg="note: " + task["problem_statement"]), task)
        self.assertEqual(st["ps"], 1)

    def test_hints_are_redacted_with_their_own_code(self):
        raw, red, st = self.go(trace(agent_msg="hint was: " + HINTS))
        self.assertEqual((st["ps"], st["ht"]), (0, 1))
        self.assertIn(R.OPEN + R.TAG + ":ht:", red.decode().replace("\\u27e6", R.OPEN))

    def test_task_without_hints(self):
        raw, red, st = self.go(trace(user=STATEMENT), TASK_NO_HINTS)
        self.assertEqual((st["ps"], st["ht"]), (1, 0))

    def test_39_and_40_characters(self):
        t = TASK_LONG
        raw39, red39, st39 = self.go(trace(agent_msg="start " + LONG[:39] + " end"), t)
        self.assertEqual(st39["ps"], 0)
        raw40, red40, st40 = self.go(trace(agent_msg="start " + LONG[:40] + " end"), t)
        self.assertEqual(st40["ps"], 1)
        raw41, red41, st41 = self.go(trace(agent_msg="start " + LONG[:41] + " end"), t)
        self.assertEqual(st41["ps"], 1)

    def test_two_separate_quotes_and_unrelated_text(self):
        raw, red, st = self.go(trace(user="a " + LONG[:45] + " b unrelated text in between " + LONG[10:60] + " c"), TASK_LONG)
        self.assertEqual(st["ps"], 2)

    def test_literal_brackets_and_marker_text(self):
        text = "see " + R.OPEN + "RDX1:ps:0:5:abcdef" + R.CLOSE + " and " + R.OPEN + " lone " + R.CLOSE + " done"
        raw, red, st = self.go(trace(agent_msg=text))
        self.assertEqual(st["ps"], 0)

    def test_paths_and_host_names(self):
        text = "File \"/home/alice/envs/x/lib/a.py\", line 3 on host alice, dir /home/alice/proj/root/gemma4, user projx"
        raw, red, st = self.go(trace(observation=text))
        self.assertEqual(st["paths"], 4)
        self.assertNotIn("alice", red.decode())
        self.assertNotIn("projx", red.decode())

    def test_non_ascii_text_survives(self):
        raw, red, st = self.go(trace(user="caf\u00e9 \u4e2d\u6587 \U0001f600 " + STATEMENT))
        self.assertEqual(st["ps"], 1)


class Failures(unittest.TestCase):
    def test_unknown_task_id_fails_loudly(self):
        red, _ = R.redact_trace_bytes(raw_of(trace(user=STATEMENT)), TASK)
        with self.assertRaises(R.RedactionError):
            RS.restore_trace_bytes(red, {"other_1": TASK}, "toy_1")

    def test_path_placeholder_without_rules_fails(self):
        red, _ = R.redact_trace_bytes(raw_of(trace(observation="in /home/alice/x")), TASK, RULES)
        with self.assertRaises(R.RedactionError):
            RS.restore_trace_bytes(red, {"toy_1": TASK}, "toy_1")

    def test_changed_task_text_is_detected(self):
        red, _ = R.redact_trace_bytes(raw_of(trace(user=STATEMENT)), TASK)
        changed = dict(TASK, problem_statement=STATEMENT.replace("frobnicator", "gadgetizer"))
        with self.assertRaises(R.RedactionError):
            RS.restore_trace_bytes(red, {"toy_1": changed}, "toy_1")

    def test_graph_tool_trace_is_left_out(self):
        obj = trace()
        obj["steps"][2]["tool_calls"][0]["function_name"] = "get_code_neighbors"
        with self.assertRaises(R.RedactionError):
            R.redact_trace_bytes(raw_of(obj), TASK)
        with self.assertRaises(R.RedactionError):
            R.redact_trace_bytes(raw_of(trace(observation="reading /data/graphs/x.json now")), TASK)

    def test_file_not_reproduced_by_serialiser_is_left_out(self):
        with self.assertRaises(R.RedactionError):
            R.redact_trace_bytes(json.dumps(trace()).encode(), TASK)      # compact form, not indent=2

    def test_bad_file_name(self):
        with self.assertRaises(R.RedactionError):
            R.task_id_of("notatrace.json")


class CommandLine(unittest.TestCase):
    def test_cli_round_trip_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            tasks = os.path.join(d, "tasks.jsonl")
            with open(tasks, "w") as fh:
                for t in (TASK, TASK_NO_HINTS):
                    fh.write(json.dumps(t) + "\n")
            src, red, back = (os.path.join(d, x) for x in ("src", "red", "back"))
            os.makedirs(src)
            for tid, user in (("toy_1", STATEMENT), ("toy_2", "x " + STATEMENT)):
                open(os.path.join(src, "trace_%s.json" % tid), "wb").write(raw_of(trace(user=user)))
            man = os.path.join(d, "manifest.tsv")
            self.assertEqual(R.main(["--tasks", tasks, "--in", src, "--out", red, "--manifest", man]), 0)
            rows = open(man).read().strip().split("\n")
            self.assertEqual(len(rows), 3)
            self.assertEqual(RS.main(["--tasks", tasks, "--in", red, "--out", back, "--manifest", man]), 0)
            for f in os.listdir(src):
                self.assertEqual(open(os.path.join(src, f), "rb").read(), open(os.path.join(back, f), "rb").read())
            with self.assertRaises(SystemExit):        # refuses to overwrite
                R.main(["--tasks", tasks, "--in", src, "--out", red, "--manifest", man + "2"])

    def test_restore_cli_fails_on_unknown_task(self):
        with tempfile.TemporaryDirectory() as d:
            tasks = os.path.join(d, "tasks.jsonl")
            open(tasks, "w").write(json.dumps(TASK) + "\n")
            red = os.path.join(d, "red"); os.makedirs(red)
            r, _ = R.redact_trace_bytes(raw_of(trace(user=STATEMENT)), TASK)
            open(os.path.join(red, "trace_unknown_9.json"), "wb").write(r)
            self.assertNotEqual(RS.main(["--tasks", tasks, "--in", red, "--out", os.path.join(d, "back")]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
