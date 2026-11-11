#!/usr/bin/env python3
"""Tests of restore_traces_standalone.py (invented texts). The standalone restore must agree with restore_traces_v3.py."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import redact_traces as R  # noqa: E402
import redact_traces_v3 as V3  # noqa: E402
import redact_traces_v31 as V  # noqa: E402
import restore_traces_standalone as S  # noqa: E402

STATEMENT = "The frobnicator crashes when the widget list is empty and the tolerance flag is set to a negative value in strict mode.\r\n\r\nExpected: a clear ValueError."
OTHER = "Calling the sprocket exporter with a negative offset truncates the output buffer without any error and nobody notices."
ORG = "You are a careful repository agent working inside a sandbox. Always read the failing test before you edit any source file."
TASKS = {"toy_1": {"instance_id": "toy_1", "problem_statement": STATEMENT, "hints_text": "", "patch": "", "test_patch": ""},
         "toy_2": {"instance_id": "toy_2", "problem_statement": OTHER, "hints_text": "", "patch": "", "test_patch": ""}}


def trace(system, user, agent):
    return {"steps": [{"step_id": 1, "source": "system", "message": system}, {"step_id": 2, "source": "user", "message": user},
                      {"step_id": 3, "source": "agent", "message": agent}]}


class Standalone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.org = os.path.join(self.tmp.name, "org"); os.makedirs(os.path.join(self.org, "prompts"))
        with open(os.path.join(self.org, "prompts", "system.md"), "w") as fh:
            fh.write(ORG)
        self.rules = R.PathRules(["/home/alice/proj", "alice"])
        self.corpus = V3.Corpus(TASKS, self.org)
        obj = trace(ORG + " Our own line.", "Problem Statement:\n" + STATEMENT + "\n## Budget", "open \u27e6 and \u27e7 in /home/alice/proj/x then " + OTHER)
        self.raw = json.dumps(obj, indent=2).encode()
        self.red, _ = V.redact_trace_bytes(self.raw, "toy_1", self.corpus, self.rules, None)
        self.srcs = S.Sources(TASKS, self.org)

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_restore_with_the_path_rules_and_agreement_with_version_3(self):
        restored, left = S.restore_bytes(self.red, TASKS, "toy_1", self.srcs, {"P1": "/home/alice/proj", "P2": "alice"})
        self.assertEqual((restored, left), (self.raw, []))
        self.assertEqual(restored, V3.restore_trace_bytes(self.red, TASKS, "toy_1", self.rules, self.org))

    def test_without_the_path_rules_machine_paths_stay_and_everything_else_is_restored(self):
        restored, left = S.restore_bytes(self.red, TASKS, "toy_1", self.srcs, None)
        self.assertEqual(left, ["P1"])
        self.assertIn("\u27e6RDX3:P1\u27e7", json.loads(restored.decode())["steps"][2]["message"])
        text = json.loads(restored.decode())["steps"][1]["message"]
        self.assertIn("The frobnicator crashes", text)

    def test_errors_are_loud(self):
        with self.assertRaises(S.RestoreError):
            S.restore_bytes(self.red, TASKS, "nope", self.srcs, None)
        with self.assertRaises(S.RestoreError):
            S.restore_bytes(self.red, TASKS, "toy_1", S.Sources(TASKS, None), None)                       # no organiser folder
        changed = dict(TASKS, toy_2=dict(TASKS["toy_2"], problem_statement=OTHER + " changed"))
        with self.assertRaises(S.RestoreError):
            S.restore_bytes(self.red, changed, "toy_1", S.Sources(changed, self.org), None)

    def test_command_line_manifest_check_and_partly_restored_files(self):
        d = self.tmp.name
        tf = os.path.join(d, "tasks.jsonl")
        with open(tf, "w") as fh:
            for t in TASKS.values():
                fh.write(json.dumps(t) + "\n")
        red_dir = os.path.join(d, "red"); os.makedirs(red_dir)
        with open(os.path.join(red_dir, "trace_toy_1.json"), "wb") as fh:
            fh.write(self.red)
        import hashlib
        man = os.path.join(d, "man.tsv")
        with open(man, "w") as fh:
            fh.write("file\ttask_id\tstatus\tsha256_original\n" + "trace_toy_1.json\ttoy_1\tredacted\t" + hashlib.sha256(self.raw).hexdigest() + "\n")
        pr = os.path.join(d, "rules.json")
        with open(pr, "w") as fh:
            json.dump(["/home/alice/proj", "alice"], fh)
        self.assertEqual(S.main(["--tasks", tf, "--in", red_dir, "--out", os.path.join(d, "o1"), "--manifest", man, "--organiser", self.org, "--path-rules", pr]), 0)
        with open(os.path.join(d, "o1", "trace_toy_1.json"), "rb") as fh:
            self.assertEqual(fh.read(), self.raw)
        self.assertEqual(S.main(["--tasks", tf, "--in", red_dir, "--out", os.path.join(d, "o2"), "--manifest", man, "--organiser", self.org]), 0)    # partly restored
        self.assertEqual(S.main(["--tasks", tf, "--in", red_dir, "--out", os.path.join(d, "o3"), "--manifest", man]), 1)                               # no organiser


if __name__ == "__main__":
    unittest.main(verbosity=2)
