#!/usr/bin/env python3
"""Tests of redact_traces_v32.py and restore_traces_v32.py and audit_corpus_v32.py and audit_raw_v32.py and audit_payload_v32.py and
restore_traces_standalone_v32.py. All texts here are invented."""
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import unittest
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audit_corpus_v32 as AU  # noqa: E402
import audit_payload_v32 as AP  # noqa: E402
import audit_raw_v32 as AR  # noqa: E402
import redact_traces as R  # noqa: E402
import redact_traces_v2 as V2  # noqa: E402
import redact_traces_v3 as V3  # noqa: E402
import redact_traces_v32 as V  # noqa: E402
import restore_traces_standalone_v32 as S  # noqa: E402
import restore_traces_v32 as RS  # noqa: E402

OWN_STATEMENT = ("The frobnicator crashes when the widget list is empty and the tolerance flag is set to a negative value in strict mode.\r\n\r\n"
                 "Expected: a clear ValueError at the guard.")
OTHER = "Calling the sprocket exporter with a negative offset truncates the output buffer without any error and nobody notices."
SAME_SHAPE = OTHER.translate({ord(c): ord(c) + 1 for c in "abcdefghijklmnopqrstuvwxy"})          # same length and same spaces, other letters
TWO_PIECES = "The sprocket exporter drops frames\nwhen the offset is negative at all"                  # both pieces under 40 characters
GUILLEMETS = "Use «raw» strings or «bytes» here when the exporter reads offsets."
PATH_SHORT = "pkg/exporter/flush_core.py"                                                        # 26 characters, shorter than a window
PATH_LONG = "pkg/exporter/internal/flush_core_helpers_v2.py"                                      # 46 characters, longer than a window
LEFT30, RIGHT30 = "Remember to flush the sprocket", "buffer before the next export run"
PATCH_WITH_PATH = "%s\n%s\n%s\n" % (LEFT30, PATH_SHORT, RIGHT30)
TEST_PATCH_WITH_PATH = "--- a/%s\n+++ b/%s\n@@ -1,2 +1,3 @@\n" % (PATH_LONG, PATH_LONG)
TASKS = {
    "toy_1": {"instance_id": "toy_1", "problem_statement": OWN_STATEMENT, "hints_text": "", "patch": "", "test_patch": ""},
    "toy_2": {"instance_id": "toy_2", "problem_statement": OTHER, "hints_text": "", "patch": PATCH_WITH_PATH, "test_patch": TEST_PATCH_WITH_PATH},
    "toy_3": {"instance_id": "toy_3", "problem_statement": SAME_SHAPE, "hints_text": "", "patch": "", "test_patch": ""},
    "toy_4": {"instance_id": "toy_4", "problem_statement": TWO_PIECES, "hints_text": "", "patch": "", "test_patch": ""},
    "toy_5": {"instance_id": "toy_5", "problem_statement": GUILLEMETS, "hints_text": "", "patch": "", "test_patch": ""},
}
ORG_FILE = "You are a careful repository agent working inside a sandbox. Always read the failing test before you edit any source file."
RULES = R.PathRules([])


def trace(user="", agent_msg="", observation="", system="You are a toy agent."):
    return {"schema_version": "T-1", "steps": [
        {"step_id": 1, "source": "system", "message": system, "extra": {"k": 1}},
        {"step_id": 2, "source": "user", "message": user, "extra": {"k": 2}},
        {"step_id": 3, "source": "agent", "message": agent_msg, "tool_calls": [{"tool_call_id": "c1", "function_name": "run_command", "arguments": {"command": "ls"}}],
         "observation": {"content": observation}, "extra": {"k": 3}}], "final_metrics": {"total_steps": 3}}


def raw_of(obj):
    return json.dumps(obj, indent=2).encode("utf-8")


def slurp(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
        return fh.read()


def all_escaped(text, upper=False):
    return "".join(("\\u%04X" if upper else "\\u%04x") % ord(c) for c in text)


def payload_of(red_json):
    """The DIFFS parts of all span placeholders of a redacted trace (JSON text)."""
    pat = re.compile(V.OPEN + V.TAG + r":(?:t:[^:]+:[a-z]{2}|og:[^:]+):[0-9]+:[0-9]+:[0-9a-f]{6}(?::([^" + V.CLOSE + r"]*))?" + V.CLOSE)
    out = []
    for _, s in V2.A.strings_of(json.loads(red_json)):
        out += [m.group(1) for m in pat.finditer(s) if m.group(1)]
    return out


def decoded_payload_chars(diffs):
    """Characters that a reader gets from a DIFFS string without any source: percent decoding then the unescape fixpoint of the w items."""
    out = []
    for item in diffs.split(";"):
        val = item.split("=", 1)[1]
        if val.startswith("w"):
            out.append(V.views(unquote(val[1:]))[-1])
    return "".join(out)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.snap_dir = os.path.join(d, "snap"); os.makedirs(self.snap_dir)
        with tarfile.open(os.path.join(self.snap_dir, "toy_1.tgz"), "w:gz") as tf:
            for name, text in (("./toy/guard.py", "def guard(widgets):\n    return widgets\n"), ("./" + PATH_SHORT, "x = 1\n"), ("./" + PATH_LONG, "y = 2\n")):
                data = text.encode(); ti = tarfile.TarInfo(name); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
        self.org_dir = os.path.join(d, "org"); os.makedirs(os.path.join(self.org_dir, "prompts"))
        with open(os.path.join(self.org_dir, "prompts", "system.md"), "w") as fh:
            fh.write(ORG_FILE + "\n")
        self.corpus = V.Corpus(TASKS, self.org_dir)
        self.snaps = V3.SnapshotStore(self.snap_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, obj, tid="toy_1", snapshots=True):
        raw = raw_of(obj)
        red, st = V.redact_trace_bytes(raw, tid, self.corpus, RULES, self.snaps if snapshots else None)
        back = V.restore_trace_bytes(red, TASKS, tid, RULES, self.org_dir)
        self.assertEqual(back, raw, "restore(redact(x)) must be x")
        return raw, red.decode(), st

    def left_out(self, obj, kind, tid="toy_1"):
        with self.assertRaises(V2.LeftOut) as cm:
            V.redact_trace_bytes(raw_of(obj), tid, self.corpus, RULES, self.snaps)
        self.assertEqual(cm.exception.kind, kind)
        return str(cm.exception)


class Payload(Base):
    def test_a_span_written_entirely_as_unicode_escapes_leaks_no_character(self):
        raw, red, st = self.go(trace(agent_msg="x " + all_escaped(OTHER)))
        self.assertGreaterEqual(st["n_oth_ps"], 1)
        diffs = payload_of(red)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(decoded_payload_chars(diffs[0]).strip(), "")                  # whitespace only
        self.assertEqual(sum(1 for i in diffs[0].split(";") if i.split("=")[1] in "eEuU"), len(OTHER.replace(" ", "")))
        for word in ("sprocket", "exporter", "negative", "offset"):
            self.assertNotIn(word, red)

    def test_two_texts_of_the_same_shape_give_the_identical_payload(self):
        _, red_a, _ = self.go(trace(agent_msg="x " + all_escaped(OTHER)))
        _, red_b, _ = self.go(trace(agent_msg="x " + all_escaped(SAME_SHAPE)))
        self.assertEqual(payload_of(red_a), payload_of(red_b))
        self.assertNotEqual(re.findall(r":t:[^:]+:ps", red_a), re.findall(r":t:[^:]+:ps", red_b))      # the sources differ, the payloads do not

    def test_upper_case_hex_and_short_escapes_and_whitespace_forms(self):
        text = "Use \\u00abraw\\u00bb strings or \\u00abbytes\\u00bb here\\nwhen the exporter reads offsets."
        raw, red, st = self.go(trace(observation=text), tid="toy_1")
        # lower case « is the canonical form: letter e; the newline is a whitespace run
        d = payload_of(red)[0]
        self.assertIn("=e", d)
        self.assertIn("=w%5Cn", d)
        upper = text.replace("\\u00ab", "\\u00AB").replace("\\u00bb", "\\u00BB")
        raw, red, st = self.go(trace(observation=upper))
        self.assertIn("=E", payload_of(red)[0])

    def test_quote_and_backslash_are_written_with_the_letter_only(self):
        quoted = 'The "alpha" value and "beta" value and "gamma" value must be "valid" before the "export" starts here'
        text = quoted.replace('"', '\\"')                                                         # every quote is written as backslash quote
        task = dict(TASKS["toy_2"], problem_statement=quoted)
        tasks = dict(TASKS, toy_2=task)
        corpus = V.Corpus(tasks)
        raw = raw_of(trace(observation=text))
        red, st = V.redact_trace_bytes(raw, "toy_1", corpus, RULES, None)
        d = payload_of(red.decode())
        self.assertEqual(len(d), 1)
        self.assertEqual([i.split("=")[1] for i in d[0].split(";")], ["e"] * quoted.count('"'))
        self.assertEqual(V.restore_trace_bytes(red, tasks, "toy_1", RULES), raw)

    def test_mixed_case_hex_cannot_be_expressed_and_the_trace_is_left_out(self):
        text = "Use \\u00aB" + "raw\\u00bb strings or \\u00abbytes\\u00bb here when the exporter reads offsets."
        msg = self.left_out(trace(observation=text), "left-out-payload")
        self.assertNotIn("raw", msg)

    def test_a_non_whitespace_item_is_caught_by_the_payload_audit(self):
        good = os.path.join(self.tmp.name, "good"); os.makedirs(good)
        _, red, _ = self.go(trace(agent_msg="x " + all_escaped(OTHER)))
        with open(os.path.join(good, "trace_toy_1.json"), "w", encoding="utf-8") as fh:
            fh.write(red)
        out = os.path.join(self.tmp.name, "p.json")
        self.assertEqual(AP.main(["--traces", good, "--out", out]), 0)
        bad = os.path.join(self.tmp.name, "bad"); os.makedirs(bad)
        evil = red.replace("=w%5Cu0020", "=w%5Cu0041", 1)                                              # a raw that decodes to the letter A
        self.assertNotEqual(evil, red)
        with open(os.path.join(bad, "trace_toy_1.json"), "w", encoding="utf-8") as fh:
            fh.write(evil)
        self.assertEqual(AP.main(["--traces", bad, "--out", os.path.join(self.tmp.name, "q.json")]), 1)


class Depth(Base):
    def dumps_n(self, text, n):
        for _ in range(n):
            text = json.dumps(text)[1:-1]
        return text

    def test_once_escaped_is_redacted_and_restores(self):
        raw, red, st = self.go(trace(observation="log: " + self.dumps_n(TWO_PIECES, 1)))
        self.assertGreaterEqual(st["n_oth_ps"], 1)
        self.assertNotIn("sprocket", red)

    def test_twice_escaped_is_left_out(self):
        msg = self.left_out(trace(observation="log: " + self.dumps_n(TWO_PIECES, 2)), "left-out-residual")
        self.assertIn("depth", msg)
        self.assertNotIn("sprocket", msg)

    def test_three_times_escaped_is_left_out(self):
        self.left_out(trace(observation="log: " + self.dumps_n(TWO_PIECES, 3)), "left-out-residual")

    def test_the_audit_finds_depth_2_and_3_in_the_original(self):
        tf = os.path.join(self.tmp.name, "tasks.jsonl")
        with open(tf, "w") as fh:
            for t in TASKS.values():
                fh.write(json.dumps(t) + "\n")
        for n in (2, 3):
            d = os.path.join(self.tmp.name, "orig%d" % n); os.makedirs(d)
            with open(os.path.join(d, "trace_toy_1.json"), "wb") as fh:
                fh.write(raw_of(trace(observation="log: " + self.dumps_n(TWO_PIECES, n))))
            rep = os.path.join(self.tmp.name, "rep%d.json" % n)
            self.assertEqual(AU.main(["--tasks", tf, "--traces", d, "--snapshots", self.snap_dir, "--report", rep]), 1)
            self.assertGreaterEqual(json.loads(slurp(rep))["r1"]["by_depth"].get("depth %d:hit" % n, 0), 1)
        # the one pass audit of version 3.1 cannot see it
        import audit_corpus_v31 as AU31
        self.assertEqual(AU31.main(["--tasks", tf, "--traces", os.path.join(self.tmp.name, "orig2"), "--snapshots", self.snap_dir, "--report", os.path.join(self.tmp.name, "v31.json")]), 0)


class PathRule(Base):
    def test_text_path_text_is_replaced_as_one_run(self):
        raw, red, st = self.go(trace(observation="notes: " + LEFT30 + " " + PATH_SHORT + " " + RIGHT30 + " end"))
        self.assertEqual(st["n_oth_pa"], 1)
        self.assertNotIn(PATH_SHORT, red)
        self.assertNotIn("flush the sprocket", red)

    def test_the_rule_of_version_3_missed_it(self):
        raw = raw_of(trace(observation="notes: " + LEFT30 + " " + PATH_SHORT + " " + RIGHT30 + " end"))
        corpus3 = V3.Corpus(TASKS, self.org_dir)
        red, st = V3.redact_trace_bytes(raw, "toy_1", corpus3, RULES, self.snaps)
        self.assertEqual(st["n_oth_pa"], 0)

    def test_a_bare_path_of_40_or_more_characters_stays_visible(self):
        raw, red, st = self.go(trace(observation="FAILED %s::test_x failed" % PATH_LONG))
        self.assertEqual(sum(st["n_" + k] for k in V3.STAT_KEYS), 0)
        self.assertIn(PATH_LONG, red)

    def test_the_same_path_without_a_snapshot_is_replaced(self):
        raw, red, st = self.go(trace(observation="FAILED %s::test_x failed" % PATH_LONG), snapshots=False)
        self.assertGreaterEqual(st["n_oth_tp"], 1)


class IndexAndRules(Base):
    def test_no_window_uses_the_leading_or_trailing_space_of_a_source(self):
        src = [s for s in self.corpus.sources if s.task_id == "toy_2" and s.code == "pa"][0]
        self.assertTrue(src.nf.endswith(" "))
        self.assertNotIn(src.nf[-V.MIN_SPAN:], self.corpus.index)               # the window that ends in the trailing space
        self.assertIn(src.nf[-V.MIN_SPAN - 1:-1], self.corpus.index)            # the last window of the text itself
        lead = V.Corpus({"t": {"instance_id": "t", "problem_statement": "\n" + OTHER}})
        s0 = lead.sources[0]
        self.assertTrue(s0.nf.startswith(" "))
        self.assertNotIn(s0.nf[:V.MIN_SPAN], lead.index)
        self.assertIn(s0.nf[1:V.MIN_SPAN + 1], lead.index)

    def test_own_statement_20_characters_and_no_snapshot_exemption(self):
        raw, red, st = self.go(trace(agent_msg="I think the widget list is empty again."))
        self.assertEqual(st["n_own_ps"], 1)
        raw, red, st = self.go(trace(agent_msg="see the tolerance flag now and the widget list"))
        self.assertEqual(sum(st["n_" + k] for k in V3.STAT_KEYS), 0)

    def test_other_tasks_stay_at_40(self):
        text = "x sprocket exporter with a negative off"
        raw, red, st = self.go(trace(agent_msg=text))
        self.assertEqual(sum(st["n_" + k] for k in V3.STAT_KEYS), 0)

    def test_whole_field_in_the_prompt_is_one_placeholder(self):
        prompt = "You are evaluating a task.\n\nProblem Statement:\n" + OWN_STATEMENT + "\n\n## Task Budget\n- Time allowance: 8.0 minutes\n"
        raw, red, st = self.go(trace(user=prompt))
        self.assertEqual(st["n_own_ps"], 1)
        self.assertIn("RDX4:t:toy_1:ps:0:%d:" % len(" ".join(OWN_STATEMENT.split())), red)
        self.assertIn("Time allowance: 8.0 minutes", red)

    def test_organiser_span_and_email_and_brackets(self):
        raw, red, st = self.go(trace(system=ORG_FILE + " Our own line."))
        self.assertEqual(st["n_og"], 1)
        self.left_out(trace(observation="Author-email: maintainer@acme-widgets.io"), "left-out-email")
        raw, red, st = self.go(trace(agent_msg="open ⟦ and ⟧ here"))
        self.assertEqual(sum(st["n_" + k] for k in V3.STAT_KEYS), 0)

    def test_restore_errors(self):
        red, _ = V.redact_trace_bytes(raw_of(trace(agent_msg="x " + OTHER)), "toy_1", self.corpus, RULES, self.snaps)
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, {"toy_1": TASKS["toy_1"]}, "toy_1", RULES, self.org_dir)
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, dict(TASKS, toy_2=dict(TASKS["toy_2"], problem_statement=OTHER + " x")), "toy_1", RULES, self.org_dir)
        with self.assertRaises(R.RedactionError):
            V.restore_trace_bytes(red, TASKS, "nope", RULES, self.org_dir)


class Tools(Base):
    def test_command_line_standalone_and_audits_agree(self):
        d = self.tmp.name
        tf = os.path.join(d, "tasks.jsonl")
        with open(tf, "w") as fh:
            for t in TASKS.values():
                fh.write(json.dumps(t) + "\n")
        src = os.path.join(d, "orig"); os.makedirs(src)
        obj = trace(system=ORG_FILE + " Our own line.", user="Problem Statement:\n" + OWN_STATEMENT + "\n## Budget\n",
                    agent_msg="x " + all_escaped(OTHER) + " then I think the widget list is empty again. " + LEFT30 + " " + PATH_SHORT + " " + RIGHT30,
                    observation="FAILED %s::t" % PATH_LONG)
        with open(os.path.join(src, "trace_toy_1.json"), "wb") as fh:
            fh.write(raw_of(obj))
        red, man = os.path.join(d, "red"), os.path.join(d, "man.tsv")
        self.assertEqual(V.main(["--tasks", tf, "--in", src, "--out", red, "--manifest", man, "--snapshots", self.snap_dir, "--organiser", self.org_dir]), 0)
        rows = [l.split("\t") for l in slurp(man).strip().split("\n")]
        self.assertEqual(rows[1][2], "redacted")
        back = os.path.join(d, "back")
        self.assertEqual(RS.main(["--tasks", tf, "--in", red, "--out", back, "--manifest", man, "--organiser", self.org_dir]), 0)
        self.assertEqual(slurp(os.path.join(back, "trace_toy_1.json"), "rb"), slurp(os.path.join(src, "trace_toy_1.json"), "rb"))
        back2 = os.path.join(d, "back2")
        self.assertEqual(S.main(["--tasks", tf, "--in", red, "--out", back2, "--manifest", man, "--organiser", self.org_dir]), 0)
        self.assertEqual(slurp(os.path.join(back2, "trace_toy_1.json"), "rb"), slurp(os.path.join(src, "trace_toy_1.json"), "rb"))
        rep = os.path.join(d, "rep.json")
        self.assertEqual(AU.main(["--tasks", tf, "--traces", red, "--snapshots", self.snap_dir, "--organiser", self.org_dir, "--report", rep]), 0)
        self.assertEqual(AP.main(["--traces", red, "--out", os.path.join(d, "pay.json")]), 0)
        raw_json = os.path.join(d, "raw.json")
        AR.main(["--tasks", tf, "--traces", red, "--snapshots", self.snap_dir, "--organiser", self.org_dir, "--out-tsv", os.path.join(d, "raw.tsv"), "--out-json", raw_json])
        self.assertEqual(json.loads(slurp(raw_json))["not_artifact"], [])
        self.assertEqual(AU.main(["--tasks", tf, "--traces", src, "--snapshots", self.snap_dir, "--organiser", self.org_dir, "--report", os.path.join(d, "rep_o.json")]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
