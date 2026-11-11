# Corpus tools version 3: cross task protection

Python 3.10 or newer and the standard library only. No tool here contains a machine path. Nothing is sent anywhere. Versions 1 and 2 stay as they were. Version 3 files are new files beside them and import the helpers of versions 1 and 2.

| file | purpose |
|---|---|
| `redact_traces_v3.py` | replaces protected text in trace files by placeholders (tag `RDX3`) and leaves out traces that must not be released |
| `restore_traces_v3.py` | gives back the original bytes; needs the competition's task file and for organiser placeholders the organiser's sample submission folder |
| `audit_corpus_v3.py` | audit in the decoded view against all tasks and the organiser files |
| `audit_raw_v3.py` | second audit path in the raw view of the file text with an automatic classification of every remaining row |
| `test_redaction_v3.py` | 18 unit tests with invented texts |
| `run_phase_a3.py` | driver of the version 3 run on existing traces |

## Usage

```
python3 redact_traces_v3.py --tasks tasks.jsonl --in TRACE_DIR --out REDACTED_DIR --manifest manifest.tsv --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR [--path-rules FILE]
python3 restore_traces_v3.py --tasks tasks.jsonl --in REDACTED_DIR --out RESTORED_DIR --manifest manifest.tsv --organiser ORGANISER_DIR [--path-rules FILE]
python3 audit_corpus_v3.py --tasks tasks.jsonl --traces REDACTED_DIR --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR --report audit.json
python3 audit_raw_v3.py --tasks tasks.jsonl --traces REDACTED_DIR --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR --out-tsv rows.tsv --out-json summary.json
```

A trace file must be named `trace_<task id>.json`. The task file and the organiser folder are not part of any release.

## The rule

Protected sources are the problem statement and hints text and gold patch and test patch of every task of the task file (not only the task of the trace) and the text files of the organiser's sample submission. The text of a trace is compared after JSON decoding and whitespace normalisation, in two views (plain and escape aware).

1. A window of 40 characters that occurs in a protected source is a candidate.
2. A window that touches a path is ignored. A path is a file or folder name of the upstream snapshot tree of the trace's own task (at least 12 characters). A path may follow a longer token, for example the prefix of a directory in the file system, and a test node id such as `tests/x.py::test_name` counts for the part before `::`.
3. Consecutive candidate windows form a run. A run (edge spaces trimmed) that occurs in the file contents of the own task's snapshot is exempt. Nothing else is exempt. There is no list of boilerplate.
4. Every other run is replaced by placeholders. At each position the longest match wins. Equal lengths are decided by the following order. Sources of the own task come first. Within one task the order is problem statement, hints, gold patch, test patch. Other tasks follow in sorted task id order. Organiser files come last in sorted path order. A tail of fewer than 40 characters at the end of a run stays visible.

Without `--snapshots` nothing is exempt and every candidate is replaced.

## Placeholder format

A placeholder is the character U+27E6, then `RDX3:`, then a code, then U+27E7.

| code | meaning |
|---|---|
| `t:TASKID:F:J:L:H` | a span of the field `F` (`ps` problem statement or `ht` hints or `pa` gold patch or `tp` test patch) of the task `TASKID` (percent encoded). `J` is the offset in the normalised field and `L` the length and `H` the first six hex digits of the sha256 of the normalised field |
| `og:FILE:J:L:H` | the same for an organiser file (`FILE` is the percent encoded relative path) |
| any of them plus `:DIFFS` | `Q=RAW` items joined by `;` where the trace text differs from the source text. `RAW` is percent encoded |
| `P1` and so on | one configured string of a private path rules file |
| `L` and `R` | a literal U+27E6 or U+27E7 of the original text |

Restore checks `H` and fails when the task file or the organiser file differs from the one used for redaction.

## Left out traces

`left-out-email` (an e-mail address that is not of an example domain is left in the redacted text) and `left-out-graph` and `left-out-serialiser` and `no-task`. Nothing is written for them. The manifest says why.

## Audits

`audit_corpus_v3.py` (decoded view) forms the runs per protected source and applies the same path and snapshot exemptions. Target: 0 hits. `audit_raw_v3.py` reads the file text as it is stored. JSON escapes (`\n`) stay in the text there, so it sees runs that the decoded view cannot see. Every remaining row gets a class: shorter than 40 characters after decoding, or decoded text in the own snapshot, or decoded text touches a path (all three are artifacts of the raw view), or NOT artifact (listed in the summary).

## Limits

The matching sees only changes of whitespace and JSON escapes. A quote with other changes (a prefix on every line or other quotation marks) can pass both the redaction and the audits. Text shorter than 40 characters is not touched. A snapshot path that is shorter than 12 characters is not exempt.
