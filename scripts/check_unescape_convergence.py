#!/usr/bin/env python3
"""Fail closed unless every JSON string reaches the v3.2 unescape fixed point.

Run before AND after any future corpus build. This separate gate does not fix
or replace the original redactor/auditor and does not audit protected content.
The unchanged v3.2 tools stop after six passes without proving convergence.
"""
import argparse
import json
from pathlib import Path

import redact_traces_v32 as V


def strings_of(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def converged(text):
    views = V.views(text)
    return bool(views) and V.unescape32(views[-1]) == views[-1]


def inspect(roots):
    report = {"files": 0, "strings": 0, "nonconverged_strings": 0,
              "max_changed_passes": 0, "errors": [], "ok": False}
    files = set()
    for root in roots:
        root = Path(root)
        if root.is_symlink() or not root.exists():
            report["errors"].append("missing-or-symlink-input")
            continue
        candidates = list(root.rglob("*")) if root.is_dir() else [root]
        root_files = set()
        for path in candidates:
            if path.is_symlink():
                report["errors"].append("symlink-input")
            elif path.is_file() and path.suffix == ".json":
                root_files.add(path)
        if not root_files:
            report["errors"].append("input-has-no-json-files")
        files.update(root_files)
    if not files:
        report["errors"].append("no-json-inputs")
    for path in sorted(files):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            report["errors"].append("unreadable-or-invalid-json")
            continue
        report["files"] += 1
        for text in strings_of(obj):
            report["strings"] += 1
            views = V.views(text)
            report["max_changed_passes"] = max(report["max_changed_passes"], len(views) - 1)
            if not views or V.unescape32(views[-1]) != views[-1]:
                report["nonconverged_strings"] += 1
    report["ok"] = not report["errors"] and report["nonconverged_strings"] == 0
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", action="append", required=True,
                        help="JSON trace file or directory; repeat for multiple inputs")
    parser.add_argument("--report", required=True, help="new output file; never overwritten")
    args = parser.parse_args(argv)
    report = inspect(args.traces)
    with open(args.report, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({key: report[key] for key in
                     ("files", "strings", "nonconverged_strings", "max_changed_passes", "ok")}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
