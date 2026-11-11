#!/usr/bin/env python3
"""Tests of audit_corpus.py. All texts are invented."""
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

STATEMENT = "The frobnicator crashes when the widget list is empty and the tolerance flag is set to a negative value in strict mode."
GOLD = "def guard(widgets):\n    if not widgets:\n        raise ValueError('widget list must not be empty here')\n    return widgets\n"
TASK = {"instance_id": "toy_1", "problem_statement": STATEMENT, "hints_text": "", "patch": GOLD, "test_patch": "def test_guard():\n    assert guard([1]) == [1]  # invented line for the test\n"}


def trace(**kw):
    return {"steps": [{"step_id": 1, "source": "user", "message": kw.get("user", "hello"), "extra": {}},
                      {"step_id": 2, "source": "agent", "message": kw.get("agent", "ok"), "observation": {"content": kw.get("obs", "fine")}, "extra": {}}]}


class Audit(unittest.TestCase):
    def run_audit(self, obj, snapshot_text=None, tree=None, task=TASK, forbidden=None):
        with tempfile.TemporaryDirectory() as d:
            tasks = os.path.join(d, "tasks.jsonl"); open(tasks, "w").write(json.dumps(task) + "\n")
            tdir = os.path.join(d, "t"); os.makedirs(tdir)
            with open(os.path.join(tdir, "trace_toy_1.json"), "w") as fh:
                json.dump(obj, fh, indent=2)
            args = ["--tasks", tasks, "--traces", tdir, "--report", os.path.join(d, "r.json")]
            if snapshot_text is not None:
                sd = os.path.join(d, "snap"); os.makedirs(sd)
                with tarfile.open(os.path.join(sd, "toy_1.tgz"), "w:gz") as tf:
                    data = snapshot_text.encode(); ti = tarfile.TarInfo("repo/mod.py"); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
                args += ["--snapshots", sd]
            if tree:
                args += ["--tree", tree]
            if forbidden:
                fp = os.path.join(d, "forbidden.json"); json.dump(forbidden, open(fp, "w"))
                args += ["--forbidden", fp]
            rc = A.main(args)
            return rc, json.load(open(os.path.join(d, "r.json")))

    def test_clean_trace_passes(self):
        rc, rep = self.run_audit(trace(user="Fix <ISSUE> please", agent="reading files"), snapshot_text="x = 1")
        self.assertEqual(rc, 0)
        self.assertEqual((rep["r1"]["hit"], rep["r1"]["unchecked"]), (0, 0))

    def test_leaked_statement_is_a_hit_with_first_60_characters(self):
        rc, rep = self.run_audit(trace(agent="as the issue says: " + STATEMENT), snapshot_text="x = 1")
        self.assertEqual(rc, 1)
        self.assertEqual(rep["r1"]["hit"], 1)
        h = rep["r1"]["list"][0]
        self.assertEqual((h["field"], h["first60"]), ("problem_statement", STATEMENT[:60]))

    def test_39_and_40_character_leaks(self):
        quote = STATEMENT[4:]
        rc39, rep39 = self.run_audit(trace(agent="q: " + quote[:39] + " end"), snapshot_text="x")
        rc40, rep40 = self.run_audit(trace(agent="q: " + quote[:40] + " end"), snapshot_text="x")
        self.assertEqual((rep39["r1"]["hit"], rep40["r1"]["hit"]), (0, 1))

    def test_changed_spacing_and_line_break_leak(self):
        rc, rep = self.run_audit(trace(agent=STATEMENT.replace(" the widget", "\n\n  the   widget")), snapshot_text="x")
        self.assertEqual(rep["r1"]["hit"], 1)

    def test_leak_inside_json_escaped_text(self):
        rc, rep = self.run_audit(trace(obs=json.dumps({"stdout": GOLD})), snapshot_text="x")
        self.assertGreaterEqual(rep["r1"]["hit"], 1)
        self.assertEqual(rep["r1"]["list"][0]["field"], "patch")

    def test_span_in_upstream_snapshot_is_exempt(self):
        rc, rep = self.run_audit(trace(agent="see " + GOLD.split("\n")[2].strip()), snapshot_text=GOLD)
        self.assertEqual((rep["r1"]["hit"], rep["r1"]["exempt"]), (0, 1))
        self.assertEqual(rc, 0)

    def test_no_snapshot_means_unchecked(self):
        rc, rep = self.run_audit(trace(agent="see " + GOLD.split("\n")[2].strip()))
        self.assertEqual((rep["r1"]["unchecked"], rc), (1, 1))

    def test_rule_two_hits(self):
        text = "mail me at someone@real-company.io and user@example.com, key sk-abcdefghijklmnopqrstuvwx, path /home/alice/x, Jane Doe, host zorbix"
        rc, rep = self.run_audit(trace(agent=text), snapshot_text="x", forbidden=["Jane Doe", "zorbix"])
        r2 = rep["r2"]
        self.assertEqual(rc, 1)
        for k in ("email", "email:example-domain", "secret:sk-", "/home/", "forbidden word 1", "forbidden word 2"):
            self.assertEqual(r2[k]["hits"], 1, k)

    def test_upstream_email_is_marked(self):
        rc, rep = self.run_audit(trace(agent="contact: dev@project.example.org for help with the build"), snapshot_text="contact: dev@project.example.org for help with the build")
        self.assertEqual(rep["r2"]["email:example-domain"]["upstream"] if "email:example-domain" in rep["r2"] else rep["r2"]["email"]["upstream"], 1)

    def test_escaped_newline_before_decorator_is_not_an_email(self):
        rc, rep = self.run_audit(trace(obs="line one\\n@app.get('/x')\\nline two"), snapshot_text="x")
        self.assertNotIn("email", rep["r2"])

    def test_added_gold_line_is_classified_as_novel(self):
        gold = dict(TASK, patch="--- a/m.py\n+++ b/m.py\n@@ -1,1 +1,2 @@\n def guard(widgets):\n+    raise ValueError('widget list must not be empty here')\n")
        rc, rep = self.run_audit(trace(agent="my fix: raise ValueError('widget list must not be empty here')"), snapshot_text="def guard(widgets):", task=gold)
        self.assertEqual((rep["r1"]["novel"], rep["r1"]["scaffold_only"]), (1, 0))

    def test_scaffold_only_hit_is_not_novel(self):
        snapshot = "def guard(widgets):\n    return widgets\n"
        diff = "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,3 @@\n def guard(widgets):\n+    # short\n     return widgets\n"
        gold = dict(TASK, patch=diff)
        with tempfile.TemporaryDirectory() as d:
            tasks = os.path.join(d, "tasks.jsonl"); open(tasks, "w").write(json.dumps(gold) + "\n")
            tdir = os.path.join(d, "t"); os.makedirs(tdir)
            json.dump(trace(obs=diff), open(os.path.join(tdir, "trace_toy_1.json"), "w"), indent=2)
            sd = os.path.join(d, "snap"); os.makedirs(sd)
            with tarfile.open(os.path.join(sd, "toy_1.tgz"), "w:gz") as tf:
                data = snapshot.encode(); ti = tarfile.TarInfo("repo/m.py"); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
            A.main(["--tasks", tasks, "--traces", tdir, "--snapshots", sd, "--report", os.path.join(d, "r.json")])
            rep = json.load(open(os.path.join(d, "r.json")))
        self.assertEqual(rep["r1"]["novel"], 0)

    def test_tree_size_limit(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "a.json"), "w").write("{}")
            old = A.MAX_FILE; A.MAX_FILE = 1
            try:
                rc, rep = self.run_audit(trace(), snapshot_text="x", tree=d)
            finally:
                A.MAX_FILE = old
            self.assertEqual(len(rep["r3"]["over_50MB"]), 1)
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
