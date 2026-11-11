#!/usr/bin/env python3
"""Tests of redact_traces_v3.py and restore_traces_v3.py and audit_corpus_v3.py and audit_raw_v3.py. All texts here are invented."""
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audit_corpus_v3 as AU  # noqa: E402
import audit_raw_v3 as AR  # noqa: E402
import redact_traces as R  # noqa: E402
import redact_traces_v2 as V2  # noqa: E402
import redact_traces_v3 as V  # noqa: E402
import restore_traces_v3 as RS  # noqa: E402

SHARED_12 = "The exporter must raise an error whenever the offset argument is negative or larger than the buffer length."
SHARED_OWN_2 = "Callers expect a ValueError with the name of the argument in the message text."
OWN_STATEMENT = "The frobnicator crashes when the widget list is empty and the tolerance flag is set to a negative value in strict mode. " + SHARED_OWN_2
S2 = "Calling the sprocket exporter with a negative offset truncates the output buffer without any error. " + SHARED_12 + " " + SHARED_OWN_2
S3 = "Another report from the field says the following about the exporter. " + SHARED_12 + " Please add a regression test."
SNAP_FILE = "def guard(widgets, tolerance=0, strict=False):\n    widgets = list(widgets)\n    validate_tolerance(tolerance, strict_mode=strict)\n    return widgets\n"
TEST_PATH = "tests/test_toy_widgets/test_guard_strictness_cases.py"
GOLD1 = "--- a/toy/guard.py\n+++ b/toy/guard.py\n@@ -2,3 +2,4 @@\n     widgets = list(widgets)\n+    raise ValueError('the widget list must not be empty in strict mode')\n"
GOLD2 = ("--- a/toy/export.py\n+++ b/toy/export.py\n@@ -2,3 +2,5 @@ def guard(widgets, tolerance=0, strict=False):\n"
         "     widgets = list(widgets)\n     validate_tolerance(tolerance, strict_mode=strict)\n"
         "+    check_offset_is_inside_the_buffer(offset, buffer_length, name='offset')\n     return widgets\n")
TEST2 = "--- a/%s\n+++ b/%s\n@@ -1,2 +1,3 @@\n+def test_exporter_rejects_negative_offsets_in_every_mode():\n+    pass\n" % (TEST_PATH, TEST_PATH)
TASKS = {
    "toy_1": {"instance_id": "toy_1", "problem_statement": OWN_STATEMENT, "hints_text": "", "patch": GOLD1, "test_patch": ""},
    "toy_2": {"instance_id": "toy_2", "problem_statement": S2, "hints_text": "", "patch": GOLD2, "test_patch": TEST2},
    "toy_3": {"instance_id": "toy_3", "problem_statement": S3, "hints_text": "", "patch": "", "test_patch": ""},
}
ORG_FILE = "You are a careful repository agent working inside a sandbox. Always read the failing test before you edit any source file. Never print secrets."
RULES = R.PathRules(["/home/alice/proj/root", "alice"])


def trace(user="", agent_msg="", observation="", system="You are a toy agent."):
    return {"schema_version": "T-1", "steps": [
        {"step_id": 1, "source": "system", "message": system, "extra": {"k": 1}},
        {"step_id": 2, "source": "user", "message": user, "extra": {"k": 2}},
        {"step_id": 3, "source": "agent", "message": agent_msg, "tool_calls": [{"tool_call_id": "c1", "function_name": "run_command", "arguments": {"command": "ls"}}],
         "observation": {"content": observation}, "extra": {"k": 3}}], "final_metrics": {"total_steps": 3}}


def raw_of(obj):
    return json.dumps(obj, indent=2).encode("utf-8")


def slurp(path, mode="r"):
    with open(path, mode) as fh:
        return fh.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.snap_dir = os.path.join(d, "snap"); os.makedirs(self.snap_dir)
        with tarfile.open(os.path.join(self.snap_dir, "toy_1.tgz"), "w:gz") as tf:
            for name, text in (("./toy/guard.py", SNAP_FILE), ("./" + TEST_PATH, "def test_placeholder():\n    pass\n")):
                data = text.encode(); ti = tarfile.TarInfo(name); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
        self.org_dir = os.path.join(d, "org"); os.makedirs(os.path.join(self.org_dir, "prompts"))
        with open(os.path.join(self.org_dir, "prompts", "system.md"), "w") as fh:
            fh.write(ORG_FILE)
        self.corpus = V.Corpus(TASKS, self.org_dir)
        self.snaps = V.SnapshotStore(self.snap_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, obj, snapshots=True, tid="toy_1"):
        raw = raw_of(obj)
        red, st = V.redact_trace_bytes(raw, tid, self.corpus, RULES, self.snaps if snapshots else None)
        back = V.restore_trace_bytes(red, TASKS, tid, RULES, self.org_dir)
        self.assertEqual(back, raw, "restore(redact(x)) must be x")
        return raw, red.decode(), st


class CrossTask(Base):
    def test_span_of_another_tasks_statement_in_test_output(self):
        raw, red, st = self.go(trace(observation="E   AssertionError: Calling the sprocket exporter with a negative offset truncates the output buffer without any error."))
        self.assertGreaterEqual(st["n_oth_ps"], 1)
        self.assertIn("t:toy_2:ps", red)
        self.assertNotIn("sprocket exporter", red)

    def test_span_of_another_tasks_patch_that_is_in_the_own_snapshot_stays(self):
        raw, red, st = self.go(trace(agent_msg="context: widgets = list(widgets)\nvalidate_tolerance(tolerance, strict_mode=strict) done"))
        self.assertEqual(sum(st["n_" + k] for k in V.STAT_KEYS), 0)
        self.assertIn("validate_tolerance(tolerance, strict_mode=strict)", red)

    def test_without_a_snapshot_the_same_span_is_masked(self):
        raw, red, st = self.go(trace(agent_msg="context: widgets = list(widgets)\nvalidate_tolerance(tolerance, strict_mode=strict) done"), snapshots=False)
        self.assertGreaterEqual(st["n_oth_pa"], 1)

    def test_path_of_a_snapshot_file_that_is_in_another_tasks_test_patch_stays(self):
        text = "FAILED %s::test_rejects - assertion failed" % TEST_PATH
        raw, red, st = self.go(trace(observation=text))
        self.assertEqual(sum(st["n_" + k] for k in V.STAT_KEYS), 0)
        self.assertIn(TEST_PATH, red)

    def test_the_same_path_without_a_snapshot_is_masked(self):
        raw, red, st = self.go(trace(observation="FAILED %s::test_rejects - assertion failed" % TEST_PATH), snapshots=False)
        self.assertGreaterEqual(st["n_oth_tp"], 1)

    def test_path_with_a_directory_prefix_stays(self):
        raw, red, st = self.go(trace(observation="/work/repo/" + TEST_PATH + ":12: in test_rejects"))
        self.assertEqual(sum(st["n_" + k] for k in V.STAT_KEYS), 0)

    def test_text_around_a_path_is_still_masked(self):
        # a long shared run on both sides of a path: the path stays and both sides are masked
        sentence_a = "Calling the sprocket exporter with a negative offset truncates the output buffer"
        sentence_b = "The exporter must raise an error whenever the offset argument is negative or larger"
        raw, red, st = self.go(trace(observation=sentence_a + " " + TEST_PATH + " " + sentence_b))
        self.assertIn(TEST_PATH, red)
        self.assertGreaterEqual(st["n_oth_ps"], 2)

    def test_span_shared_by_two_other_tasks_goes_to_the_smaller_task_id(self):
        sentence = "Remember: " + SHARED_12 + " Thanks."
        raw, red, st = self.go(trace(agent_msg=sentence.replace(" Thanks.", "")))
        self.assertIn("t:toy_2:ps", red)
        self.assertNotIn("t:toy_3:ps", red)

    def test_span_shared_by_the_own_task_and_another_goes_to_the_own_task(self):
        raw, red, st = self.go(trace(agent_msg="so " + SHARED_OWN_2))
        self.assertIn("t:toy_1:ps", red)
        self.assertNotIn("t:toy_2:ps", red)
        self.assertGreaterEqual(st["n_own_ps"], 1)

    def test_the_longest_match_wins_over_the_order(self):
        # the whole own statement is longer than the sentence that another task shares with it
        raw, red, st = self.go(trace(user=OWN_STATEMENT))
        self.assertEqual((st["n_own_ps"], st["n_oth_ps"]), (1, 0))

    def test_runs_that_overlap_in_characters_restore_exactly(self):
        # window w is in task A, window w+1 is in no source, window w+2 and the following ones are in task B: two runs overlap by 38 characters
        m = "mnopqrstuvwxyz0123456789ABCDEFGHIJKLMNO"            # 39 characters
        tail = "bcdefghijklmnopqrstuvwxyz-and-then-some-more-text"
        tasks = {"toy_1": {"instance_id": "toy_1", "problem_statement": "unrelated own statement of the task, long enough"},
                 "toy_4": {"instance_id": "toy_4", "problem_statement": "a" + m + "Q" + "-the-rest-of-the-first-source"},
                 "toy_5": {"instance_id": "toy_5", "problem_statement": m[1:] + tail}}
        corpus = V.Corpus(tasks)
        raw = raw_of(trace(agent_msg="x " + "a" + m + tail + " y"))
        red, st = V.redact_trace_bytes(raw, "toy_1", corpus)
        self.assertEqual(V.restore_trace_bytes(red, tasks, "toy_1"), raw)
        self.assertGreaterEqual(st["n_oth_ps"], 2)
        self.assertNotIn(m[:30], red.decode())

    def test_restore_fails_loudly(self):
        red, _ = V.redact_trace_bytes(raw_of(trace(agent_msg="x " + SHARED_12)), "toy_1", self.corpus, RULES, self.snaps)
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, {"toy_1": TASKS["toy_1"], "toy_3": TASKS["toy_3"]}, "toy_1", RULES, self.org_dir)     # toy_2 missing
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, {"toy_1": TASKS["toy_1"], "toy_2": dict(TASKS["toy_2"], problem_statement=S2 + " changed")}, "toy_1", RULES, self.org_dir)
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, TASKS, "nope", RULES, self.org_dir)

    def test_organiser_span_in_system_instruction(self):
        raw, red, st = self.go(trace(system=ORG_FILE + " Our own addition: keep every note short."))
        self.assertEqual(st["n_og"], 1)
        self.assertIn("Our own addition", red)
        red_b, _ = V.redact_trace_bytes(raw_of(trace(system=ORG_FILE)), "toy_1", self.corpus, RULES, self.snaps)
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red_b, TASKS, "toy_1", RULES, None)

    def test_real_looking_address_leaves_the_trace_out(self):
        with self.assertRaises(V2.LeftOut) as cm:
            V.redact_trace_bytes(raw_of(trace(observation="Author-email: maintainer@acme-widgets.io")), "toy_1", self.corpus, RULES, self.snaps)
        self.assertEqual(cm.exception.kind, "left-out-email")

    def test_brackets_and_paths_still_work(self):
        raw, red, st = self.go(trace(agent_msg="open ⟦ and ⟧ in /home/alice/proj/root/x by alice"))
        self.assertEqual(st["paths"], 2)


class CommandLineAndAudits(Base):
    def write_traces(self, name, objs):
        d = os.path.join(self.tmp.name, name); os.makedirs(d)
        for fn, obj in objs.items():
            with open(os.path.join(d, fn), "wb") as fh:
                fh.write(raw_of(obj))
        return d

    def tasks_file(self):
        p = os.path.join(self.tmp.name, "tasks.jsonl")
        with open(p, "w") as fh:
            for t in TASKS.values():
                fh.write(json.dumps(t) + "\n")
        return p

    def test_round_trip_manifest_and_both_audits(self):
        tf = self.tasks_file()
        src = self.write_traces("orig", {"trace_toy_1.json": trace(
            system=ORG_FILE + " Our own addition.", user=OWN_STATEMENT,
            agent_msg="E   AssertionError: Calling the sprocket exporter with a negative offset truncates the output buffer without any error.\n" + "FAILED %s::t" % TEST_PATH,
            observation="context: widgets = list(widgets)\nvalidate_tolerance(tolerance, strict_mode=strict) done; check_offset_is_inside_the_buffer(offset, buffer_length, name='offset')")})
        red, man = os.path.join(self.tmp.name, "red"), os.path.join(self.tmp.name, "man.tsv")
        self.assertEqual(V.main(["--tasks", tf, "--in", src, "--out", red, "--manifest", man, "--snapshots", self.snap_dir, "--organiser", self.org_dir]), 0)
        rows = [l.split("\t") for l in slurp(man).strip().split("\n")]
        self.assertEqual(len(rows[0]), len(rows[1]))
        rec = dict(zip(rows[0], rows[1]))
        self.assertEqual(rec["status"], "redacted")
        for c in ("n_own_ps", "n_oth_ps", "n_oth_pa", "n_og"):
            self.assertGreaterEqual(int(rec[c]), 1, c)
        back = os.path.join(self.tmp.name, "back")
        self.assertEqual(RS.main(["--tasks", tf, "--in", red, "--out", back, "--manifest", man, "--organiser", self.org_dir]), 0)
        self.assertEqual(slurp(os.path.join(back, "trace_toy_1.json"), "rb"), slurp(os.path.join(src, "trace_toy_1.json"), "rb"))
        self.assertEqual(RS.main(["--tasks", tf, "--in", red, "--out", os.path.join(self.tmp.name, "back2"), "--manifest", man]), 1)
        # decoded audit: hits in the original (own, other, organiser), none in the redacted trace
        rep_o, rep_r = os.path.join(self.tmp.name, "ro.json"), os.path.join(self.tmp.name, "rr.json")
        self.assertEqual(AU.main(["--tasks", tf, "--traces", src, "--snapshots", self.snap_dir, "--organiser", self.org_dir, "--report", rep_o]), 1)
        by = json.loads(slurp(rep_o))["r1"]["by_field"]
        for key in ("own:ps:hit", "other:ps:hit", "organiser:og:hit"):
            self.assertGreaterEqual(by.get(key, 0), 1, key)
        self.assertEqual(AU.main(["--tasks", tf, "--traces", red, "--snapshots", self.snap_dir, "--organiser", self.org_dir, "--report", rep_r]), 0)
        # raw audit: rows for the original, no rows of class NOT artifact for the redacted trace
        out_o, out_r = os.path.join(self.tmp.name, "rawo.json"), os.path.join(self.tmp.name, "rawr.json")
        AR.main(["--tasks", tf, "--traces", src, "--snapshots", self.snap_dir, "--organiser", self.org_dir, "--out-tsv", os.path.join(self.tmp.name, "o.tsv"), "--out-json", out_o])
        self.assertGreater(json.loads(slurp(out_o))["remaining_rows"], 0)
        AR.main(["--tasks", tf, "--traces", red, "--snapshots", self.snap_dir, "--organiser", self.org_dir, "--out-tsv", os.path.join(self.tmp.name, "r.tsv"), "--out-json", out_r])
        self.assertEqual(json.loads(slurp(out_r))["not_artifact"], [])
        self.assertEqual(json.loads(slurp(out_r))["remaining_rows"], 0)

    def test_audit_keeps_a_path_and_an_exempt_span(self):
        tf = self.tasks_file()
        d = self.write_traces("keep", {"trace_toy_1.json": trace(observation="FAILED %s::t\ncontext: widgets = list(widgets)\nvalidate_tolerance(tolerance, strict_mode=strict)" % TEST_PATH)})
        self.assertEqual(AU.main(["--tasks", tf, "--traces", d, "--snapshots", self.snap_dir, "--report", os.path.join(self.tmp.name, "k.json")]), 0)

    def test_audit_without_snapshots_reports_unchecked(self):
        tf = self.tasks_file()
        d = self.write_traces("nosnap", {"trace_toy_1.json": trace(agent_msg=SHARED_12)})
        self.assertEqual(AU.main(["--tasks", tf, "--traces", d, "--report", os.path.join(self.tmp.name, "n.json")]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
