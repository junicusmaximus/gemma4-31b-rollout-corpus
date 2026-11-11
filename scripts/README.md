# Corpus tools: redaction and restore of agent traces and the release audit

Python 3.10 or newer and the standard library only. No tool here contains a machine path. Nothing is sent anywhere.

| file | purpose |
|---|---|
| `redact_traces.py` | replaces competition task text in trace files by placeholders and normalises machine paths |
| `restore_traces.py` | gives back the original bytes; needs the competition's public task file |
| `audit_corpus.py` | proves that no protected text is left (rules R1 to R3 below) |
| `test_redaction.py` and `test_audit.py` | unit tests with invented task texts |
| `run_phase_a.py` and `summarise_phase_a.py` | driver and summary of the Phase A run on existing traces |
| `coverage_check.py` and `system_prompt_overlap.py` and `upstream_licences.py` | extra measurements used in the report |

Run the tests with `python3 test_redaction.py` and `python3 test_audit.py`.

## Usage

```
python3 redact_traces.py --tasks tasks.jsonl --in TRACE_DIR --out REDACTED_DIR --manifest manifest.tsv
python3 restore_traces.py --tasks tasks.jsonl --in REDACTED_DIR --out RESTORED_DIR --manifest manifest.tsv
python3 audit_corpus.py --tasks tasks.jsonl --traces REDACTED_DIR --snapshots SNAPSHOT_DIR --tree STAGING_DIR --report audit.json
```

`tasks.jsonl` is the competition's public task file. It is not part of any release. A trace file must be named `trace_<task id>.json`. The restore tool reads the task id from the file name. A task id that is not in the task file is an error and nothing is restored for it.

## What is redacted

A string of the trace JSON is a decoded value at any nesting level. Every span of 40 or more characters that such a string shares with the task's problem statement or hints is replaced. Whitespace is normalised before the comparison. Two views are compared: the plain text and a view in which JSON escape sequences (`\n` and `\"` and `\\` and `\uXXXX`) stand for their characters. The second view finds task text that sits inside JSON text inside JSON (tool output).

Gold patches and test patches are not replaced. The audit reports their shared spans (see below).

A trace is written back with `json.dumps(indent=2)`. A trace is processed only when that serialiser reproduces the original file byte for byte. The tool checks this for every file and leaves out the ones where it does not hold.

A trace that calls one of the three official graph tools (`get_code_neighbors` and `search_similar_code` and `get_code_subgraph`) or names the graph or embedding folders is left out and listed in the manifest with the status `left-out`.

## Placeholder format

A placeholder is the character U+27E6, then `RDX1:`, then a code, then U+27E7.

| code | meaning |
|---|---|
| `ps:J:L:H` or `ps:J:L:H:DIFFS` | a span of the problem statement. `J` is the offset in the normalised statement and `L` the length and `H` the first six hex digits of the sha256 of the normalised statement |
| `ht:J:L:H` | the same for the hints text |
| `DIFFS` | `Q=RAW` items joined by `;`. `Q` is a position inside the span where the trace text differs from the statement's own text (another whitespace run or a JSON escape sequence). `RAW` is the exact trace text and is percent encoded |
| `P1` and `P2` and `P3` and `P4` (the number is the position in the list) | one configured string of a private path rules file given with `--path-rules`. The file is a JSON list of strings, longest first. It is not part of any release |
| `L` and `R` | a literal U+27E6 or U+27E7 that was in the original text |

The restore tool checks `H` against the task file and fails when they differ. The manifest holds for each file the sha256 of the original and of the redacted file and the counts of placeholders and the number of characters removed.

## Audit rules

| rule | check |
|---|---|
| R1 | no span of 40 or more characters (decoded and whitespace normalised and both views) shared with the task's problem statement or hints or gold patch or test patch. A span that also occurs in the task's repository snapshot is exempt. A span with no snapshot to check is listed as unchecked. A hit in a patch field is marked `novel` when it contains an added line of the patch that is not in the snapshot (the solution text) and `scaffold` when it only holds diff headers or context |
| R2 | secret shaped strings and e-mail addresses and `/home/` and the words of a private list given with `--forbidden` (names and host and account strings). Every hit is a finding. A hit that also occurs in the snapshot (upstream text) is marked |
| R3 | file types and sizes of a tree and no file above 50 MB |

The exit status is 0 only when there are no R1 hits that need a decision and no R2 hits and no R3 findings. A hit is a finding. Nothing here tunes it away.

## Limits

The matching sees only changes of whitespace and JSON escapes. A quote with other changes (a prefix on every line or a different quotation mark) can pass both the redaction and the audit. Text shorter than 40 characters is not touched by design.
