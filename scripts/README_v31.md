# Corpus tools version 3.1: stricter rule for the trace's own task

Python 3.10 or newer and the standard library only. No tool here contains a machine path. Nothing is sent anywhere. Versions 1 to 3 stay as they were (see `README.md` and `README_v2.md` and `README_v3.md`). Version 3.1 files are new files that import version 3. The placeholder format is the one of version 3 (tag `RDX3`), so `restore_traces_v3.py` and the single file `restore_traces_standalone.py` restore the output of version 3.1.

| file | purpose |
|---|---|
| `redact_traces_v31.py` | the redactor with the own task rule |
| `audit_corpus_v31.py` | decoded view audit with the own task rule |
| `audit_raw_v31.py` | raw view audit (second path) with the own task rule and the automatic classification of remaining rows |
| `restore_traces_standalone.py` | restore in one file without imports of the other tools (the trace dataset ships it as `restore_traces.py`) |
| `test_redaction_v31.py` and `test_restore_standalone.py` | unit tests with invented texts |
| `compare_v3_v31.py` | per trace comparison of the statement placeholders and characters removed under 20 characters (version 3.1) against 40 (version 3) |
| `run_phase_a31.py` | driver of the version 3.1 run on existing traces |

## Usage

```
python3 redact_traces_v31.py --tasks tasks.jsonl --in TRACE_DIR --out REDACTED_DIR --manifest manifest.tsv --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR [--path-rules FILE]
python3 audit_corpus_v31.py --tasks tasks.jsonl --traces REDACTED_DIR --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR --report audit.json
python3 audit_raw_v31.py --tasks tasks.jsonl --traces REDACTED_DIR --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR --out-tsv rows.tsv --out-json summary.json
python3 restore_traces_standalone.py --tasks tasks.jsonl --organiser ORGANISER_DIR --in REDACTED_DIR --out RESTORED_DIR --manifest manifest.tsv [--path-rules FILE]
```

## The rule

Rule of version 3 with these changes for the trace's OWN task:

| source | threshold | exemptions |
|---|---|---|
| problem statement and hints of the own task | 20 characters | none: not for text that occurs in the snapshot and not for paths |
| gold patch and test patch of the own task | 40 characters | own snapshot contents and own snapshot paths |
| all sources of other tasks and the organiser's files | 40 characters | own snapshot contents and own snapshot paths |

The own statement and hints are handled first. Their spans are replaced before the other sources are looked at. The other sources then treat the replaced characters as blocked. The audit uses the same thresholds. It skips the own statement and hints in its 40 character pass because its 20 character pass covers them.

## The task prompt step

The task prompt step of a trace has two parts.

| part | where it comes from | in the released trace | restore |
|---|---|---|---|
| the harness wrapper (the opening sentence with the repository name and the heading "Problem Statement:" and the budget and rule and instruction sections) | the competition harness builds it for each task from its prompt template and the run's budget settings. It is not a file of the organiser's sample submission (0 of 216 prompt steps hold an organiser placeholder) | readable as it is | nothing to restore |
| the statement (and the hints when a task has them) | the task file | in all 216 released traces the prompt step has one placeholder that covers the field from offset 0 to its full length (11 of the prompt steps also hold further placeholders of 20 to 25 characters for file paths that the statement mentions). A prompt with other line breaks or spacing gets the same placeholder with a DIFFS part | the placeholder is restored from `tasks.jsonl` |

Hints are empty for all 129 tasks of the task file, so no real prompt holds hints.

## Limits

The redaction and the audits compare strings. They do not detect paraphrase or changed wording. They do not compare fragments below the thresholds (20 characters for the own statement and hints and 40 for the other sources). A quote that was changed in ways other than whitespace and JSON escapes is not matched.
