# Corpus tools version 2: five protected sources and e-mail leave out

Python 3.10 or newer and the standard library only. No tool here contains a machine path. Nothing is sent anywhere. Version 1 (`README.md` and the three version 1 programs) stays as it was. Version 2 files are new files beside them and import the text helpers of version 1.

| file | purpose |
|---|---|
| `redact_traces_v2.py` | replaces protected text in trace files by placeholders (tag `RDX2`) and leaves out traces that must not be released |
| `restore_traces_v2.py` | gives back the original bytes; needs the competition's public task file and for organiser placeholders the organiser's sample submission folder |
| `audit_corpus_v2.py` | proves that no protected text is left (rules R1 to R3) |
| `audit_public_tree.py` | read only span audit of any folder of text files against all tasks and the organiser files (used for the public package of paper 1) |
| `test_redaction_v2.py` | 18 unit tests with invented texts (redaction and restore and audit) |
| `run_phase_a2.py` | driver of the version 2 run on existing traces |

## Usage

```
python3 redact_traces_v2.py --tasks tasks.jsonl --in TRACE_DIR --out REDACTED_DIR --manifest manifest.tsv --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR [--path-rules FILE]
python3 restore_traces_v2.py --tasks tasks.jsonl --in REDACTED_DIR --out RESTORED_DIR --manifest manifest.tsv --organiser ORGANISER_DIR [--path-rules FILE]
python3 audit_corpus_v2.py --tasks tasks.jsonl --traces REDACTED_DIR --snapshots SNAPSHOT_DIR --organiser ORGANISER_DIR --report audit.json
```

A trace file must be named `trace_<task id>.json`. The restore tool reads the task id from the file name. A task id that is not in the task file is an error. The task file and the organiser folder are not part of any release; people who accepted the competition rules have them.

## Protected sources

| code | source | rule |
|---|---|---|
| `ps` and `ht` | problem statement and hints text of the task | every span of 40 or more characters is replaced |
| `pa` and `tp` | gold patch and test patch of the task | a span is replaced unless the whole run that it belongs to occurs in the upstream snapshot of the task (the repository at the base commit). Diff headers and hunk headers and context lines that are not a snapshot run are replaced too. Without `--snapshots` every span is replaced |
| `og` | text files of the organiser's sample submission | every span is replaced. Text added by the study stays visible |

Spans are found after whitespace normalisation in two views (plain and JSON escape aware). At each position the longest match over all sources wins. A run of consecutive matches from two sources gives two placeholders.

## Placeholder format

A placeholder is the character U+27E6, then `RDX2:`, then a code, then U+27E7.

| code | meaning |
|---|---|
| `ps:J:L:H` and `ht:J:L:H` and `pa:J:L:H` and `tp:J:L:H` | a span of that task field. `J` is the offset in the normalised field and `L` the length and `H` the first six hex digits of the sha256 of the normalised field |
| `og:FILE:J:L:H` | the same for an organiser file. `FILE` is the percent encoded relative path inside the organiser folder |
| any of them plus `:DIFFS` | `Q=RAW` items joined by `;` where the trace text differs from the source text (other whitespace or a JSON escape). `RAW` is percent encoded |
| `P1` and `P2` and so on | one configured string of a private path rules file (`--path-rules`) |
| `L` and `R` | a literal U+27E6 or U+27E7 of the original text |

The restore tool checks `H` against the task file or the organiser file and fails when they differ.

## Left out traces

The manifest lists every input file. Status `redacted` means released. Other statuses (nothing is written for them):

| status | reason |
|---|---|
| `left-out-email` | the redacted text still holds an e-mail address that is not of an example domain (example.com and similar and users.noreply.github.com are kept) |
| `left-out-graph` | the trace calls an official graph tool or names the graph or embedding folders |
| `left-out-serialiser` | `json.dumps(indent=2)` does not reproduce the file byte for byte |
| `no-task` | the task id is not in the task file |

Every released trace restores to the original bytes. The manifest records the sha256 of the original and of the redacted file and for each source the number of placeholders and the number of characters removed.

## Audit rules

| rule | check |
|---|---|
| R1 | no span of 40 or more characters (decoded and whitespace normalised and both views) shared with the task's problem statement or hints or gold patch or test patch or with an organiser text file. A span of a task field that also occurs in the task's snapshot is exempt. Organiser spans are never exempt |
| R2 | secret shaped strings and e-mail addresses that are not of an example domain and `/home/` and the words of a private list given with `--forbidden`. Example domain addresses are counted and tolerated |
| R3 | file types and sizes of a tree and no file above 50 MB |

The exit status is 0 only when there are no R1 hits and no unchecked spans and no R2 hits and no R3 findings. A hit is a finding.

## Limits

The matching sees only changes of whitespace and JSON escapes. A quote with other changes (a prefix on every line or a different quotation mark) can pass both the redaction and the audit. Text shorter than 40 characters is not touched. The audit guarantees the own task of each trace only. Text of other tasks that appears by chance (common tracebacks and separator lines and shared repository code) is not part of the rule.
