#!/usr/bin/env python3
"""Restore trace files redacted by redact_traces_v32.py to the original bytes.

Needs the competition's public task file (tasks.jsonl, all tasks that the placeholders name) and, for organiser placeholders, the
organiser's sample submission folder. A task id that is not in the task file is an error. With --manifest the sha256 of each
restored file is compared with the recorded sha256 of the original.
Python 3.10+, standard library only. Usage:
  python3 restore_traces_v32.py --tasks tasks.jsonl --in REDACTED_DIR --out RESTORED_DIR [--manifest manifest.tsv] [--organiser DIR] [--path-rules FILE]
"""
import argparse
import os
import sys

import redact_traces as R
import redact_traces_v32 as V3


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--in", dest="inp", required=True, help="a redacted trace file or a folder of them")
    ap.add_argument("--out", required=True, help="output folder (existing files are not overwritten)")
    ap.add_argument("--manifest")
    ap.add_argument("--organiser", help="folder with the organiser's sample submission files")
    ap.add_argument("--path-rules", help="the private path rules file used for redaction (needed only for P placeholders)")
    a = ap.parse_args(argv)
    rules = R.load_path_rules(a.path_rules)
    tasks = R.load_tasks(a.tasks)
    rs = V3.V3.RestoreSources(tasks, a.organiser)
    expected = {}
    if a.manifest:
        with open(a.manifest, encoding="utf-8") as fh:
            for line in fh.read().split("\n")[1:]:
                if line:
                    p = line.split("\t")
                    expected[p[0]] = p[3]
    files = [a.inp] if os.path.isfile(a.inp) else sorted(os.path.join(a.inp, f) for f in os.listdir(a.inp) if f.endswith(".json"))
    os.makedirs(a.out, exist_ok=True)
    errors = 0
    for f in files:
        name = os.path.basename(f)
        try:
            tid = R.task_id_of(f)
            with open(f, "rb") as fh:
                restored = V3.restore_trace_bytes(fh.read(), tasks, tid, rules, None, rs)
            if name in expected and R.sha256(restored) != expected[name]:
                raise R.RedactionError("sha256 of the restored file differs from the manifest")
        except R.RedactionError as e:
            print("ERROR %s: %s" % (name, e), file=sys.stderr)
            errors += 1
            continue
        dst = os.path.join(a.out, name)
        if os.path.exists(dst):
            raise SystemExit("refusing to overwrite " + dst)
        with open(dst, "wb") as fh:
            fh.write(restored)
    print("restored %d files, %d errors" % (len(files) - errors, errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
