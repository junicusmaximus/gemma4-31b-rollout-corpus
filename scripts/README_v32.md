# Corpus tools version 3.2 (release candidate rules)

Python 3.10 or newer and the standard library only. No tool here contains a machine path. Nothing is sent anywhere. Versions 1 to 3.1 stay as they were. Version 3.2 files are new files that import their helpers. The placeholder tag is `RDX4`, so version 3.2 output is restored only by the version 3.2 restore programs.

| file | purpose |
|---|---|
| `redact_traces_v32.py` | the redactor (rule text below) and the restore functions |
| `restore_traces_v32.py` | command line restore (needs the task file, the organiser folder and for machine paths the private path rules file) |
| `restore_traces_standalone_v32.py` | restore in one file without imports (the trace dataset ships it as `restore_traces.py`) |
| `audit_corpus_v32.py` | decoded audit to the fixpoint of the unescape pass |
| `audit_raw_v32.py` | raw view audit (second path) with the automatic classification of remaining rows |
| `audit_payload_v32.py` | payload audit: decodes every placeholder payload and fails on any character that is not whitespace |
| `test_redaction_v32.py` | 21 unit tests with invented texts |
| `run_phase_a32.py` | driver; writes one summary from the final outputs of its own run |

## Usage

```
python3 redact_traces_v32.py --tasks tasks.jsonl --in TRACE_DIR --out REDACTED_DIR --manifest manifest.tsv --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR [--path-rules FILE]
python3 restore_traces_v32.py --tasks tasks.jsonl --in REDACTED_DIR --out RESTORED_DIR --manifest manifest.tsv --organiser ORGANISER_DIR [--path-rules FILE]
python3 audit_corpus_v32.py --tasks tasks.jsonl --traces REDACTED_DIR --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR --report audit.json
python3 audit_payload_v32.py --traces REDACTED_DIR --out payload.json
python3 audit_raw_v32.py --tasks tasks.jsonl --traces REDACTED_DIR --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR --out-tsv rows.tsv --out-json summary.json
```

## The rule

Protected sources: the problem statement and the hints of every task of the task file (387 non empty fields of 129 tasks; all hints are empty), the gold patch and the test patch of every task, and the 8 text files of the organiser's sample submission (395 sources). Text is compared after JSON decoding and after whitespace is collapsed: every run of whitespace becomes one space, and a leading or trailing run is dropped from the index.

1. A WINDOW is 40 consecutive characters of the collapsed text of a trace string. For the problem statement and the hints of the trace's OWN task a window is 20 characters. A window is a candidate when it occurs in a protected source.
2. A window is ignored only when it lies wholly inside the path part of a token. A path part is a file or folder name of the upstream snapshot tree of the trace's own task of 12 or more characters (the whole token, or its tail after a slash). A window that straddles a path and the text next to it counts like any other window. The own statement and hints have no path exemption.
3. Consecutive candidate windows form a RUN. A run is measured after its two end spaces are dropped. A run of 40 or more characters (20 for the own statement and hints) is a HIT. A hit of the 40 character kind is exempt when the run occurs in the file contents of the own task's snapshot. There is no other exemption, and the own statement and hints have none. Shorter pieces therefore remain visible. This includes pieces next to a path and a run with a space at an end that is shorter than 40 characters once the end spaces are dropped.
4. Every hit is replaced by placeholders. The own statement and hints are replaced first. Then at each position the longest match wins. Equal lengths follow this order: own task before other tasks; within a task problem statement, hints, gold patch, test patch; other tasks in sorted task id order; organiser files last in sorted path order. A tail shorter than the threshold at the end of a run stays visible.
5. Views. The stored string (depth 0) and the string with JSON style escapes undone once (depth 1) are redacted. Then the redacted trace is audited in the views of depth 0 to the fixpoint of the unescape pass (at most 6 passes). A trace with any remaining hit, which means in practice a hit at depth 2 or deeper, is left out (`left-out-residual`). Covering deeper levels would need more payload codes; leaving the trace out is the smaller and safer change.
6. Placeholder: the character U+27E6, then `RDX4:`, then a code, then U+27E7. The code is `t:TASKID:F:J:L:H[:DIFFS]` or `og:FILE:J:L:H[:DIFFS]` or `P<n>` or `L` or `R`. `F` is `ps` or `ht` or `pa` or `tp`. `J` is the offset and `L` the length in the collapsed source text and `H` the first 6 hex digits of its sha256. `DIFFS` is a list of items separated by `;`. An item is `Q=w` followed by the percent encoded raw text of a collapsed space (whitespace and escape forms of whitespace only) or `Q=` followed by one letter of `e E u U`. A letter means that position `Q` of the span is written as a JSON escape. `e`: the short escape where one exists (quote, backslash, slash, backspace) and otherwise backslash u with 4 lower case hex digits. `E`: the same with upper case hex digits. `u` and `U`: backslash u with lower or upper case hex digits for any character. The payload never holds the character itself: the letters say how a character is written and the whitespace items hold whitespace only. A written form that none of these can express (for example mixed case hex digits) is not passed on silently: the trace is left out (`left-out-payload`).

Left out kinds: `left-out-email` (an address that is not of an example domain), `left-out-graph`, `left-out-serialiser`, `left-out-payload`, `left-out-residual`.

## Audits

`audit_corpus_v32.py` forms the runs per protected source in every view to the fixpoint and applies the same thresholds and the same exemptions. `audit_payload_v32.py` checks every placeholder: the form of the code, the items, and that every raw of a `w` item decodes (percent decoding, then JSON escapes to the fixpoint) to whitespace only. `audit_raw_v32.py` reads the stored file text and classifies the remaining rows by decoding each row's region again. Every candidate release gets its own complete set of these audits.

## Limits

The redaction and the audits compare strings. They do not detect paraphrase or changed wording. They do not compare fragments below the thresholds. A quote that was changed in ways other than whitespace and JSON escapes is not matched.
