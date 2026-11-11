# Release notes: release 1

Code and tables: https://github.com/junicusmaximus/gemma4-31b-rollout-corpus | Traces: https://www.kaggle.com/datasets/junicus/gemma4-31b-rollout-corpus | Paper: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/writeups/new-writeup-1794293663311

Release 1 holds the tables of 395 rollouts and 10,109 calls and the code that labelled them and recomputes the numbers of the paper. The 201 redacted traces are in the Kaggle dataset. It also includes the script and the data of the figure of the paper in `figures/`.

## Tables

`rollouts.tsv` and `calls.tsv` and `tasks.tsv` and their three schema files are final. Their bytes and numerical labels do not change. The five trace columns of `rollouts.tsv` are empty. `trace_index.tsv` holds the join keyed by `rollout_id`: 201 rows `included_redacted` and 4 rows `excluded_email` and 190 rows `not_audited`.

## Traces

The 201 traces are unchanged traces of an earlier cohort of 205 rows. The placeholder tag is `RDX4` (tools of version 3.2). The 190 rollouts of decoding seeds 2 and 7 have table rows only.

## Files derived from internal files

1. `verify/verify_paper_numbers_r4.py` differs from the internal file in its import path and its docstring. The formulas are the same.
2. `verify/tables_phase_b_s7_register.md` keeps the identifiers and the order of the number register and omits the private notes of the author.
3. `verify/reference/seed_summary.json` has no input paths.
4. `verify/reference/ai_label_check_summary.json` has no task specific notes.
5. The test fixture `test_redaction_v31.py` is omitted because it contained protected task text.
6. `labels/build_release_tables.py` and `labels/classify_edit_failures.py` and `labels/budget_graph_v083b.py` differ from the internal files only in their machine paths.

## Documents

The documents describe what the release holds. `provenance/release_provenance.json` lists the source and the hash of every file that comes from the build.
