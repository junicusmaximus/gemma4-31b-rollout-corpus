# Where the Budget Goes: Labelled Rollouts of a Local Gemma 4 31B Developer Agent

Code and tables: https://github.com/junicusmaximus/gemma4-31b-rollout-corpus | Traces: https://www.kaggle.com/datasets/junicus/gemma4-31b-rollout-corpus | Paper: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/writeups/new-writeup-1794293663311

This repository holds the tables and the code behind the paper. The tables describe rollouts of a local Gemma 4 31B developer agent that ran under the competition harness. The repository holds no model weights and no competition task text.

## What the tables hold

The rollout table has 395 rows. 285 are baseline rollouts on the 95 public tasks in decoding seeds 1, 2 and 7. 110 are development rollouts. The call table has 10,109 rows. Each row is one tool call of a rollout. 530 rows are free status and submission calls that the paper does not count as attempted calls. The other 9,579 rows are attempted calls. The table says whether the harness charged each call and what its status was and it carries the labels for failed edits. The task table has one row for each of the 95 tasks.

The three decoding seeds of the main screen resolved 36 and 36 and 39 of the 95 tasks. 26 tasks were solved in every seed and 47 in no seed. 22 varied. These are repeat measurements of one setup. They do not show an agent improvement or a hidden score.

## Files

1. `tables/` holds `rollouts.tsv` and `calls.tsv` and `tasks.tsv` with a schema file for each. It also holds `trace_index.tsv` which joins every `rollout_id` to the status of its trace and to the trace path in the Kaggle dataset.
2. `labels/` holds the scripts that made the labels in their stamped and corrected versions. In this public copy the machine paths of three scripts are replaced by `PROJECT_ROOT`. The hashes in the schema files and in the field `source_sha256` of the provenance file are those of the sealed originals. `provenance/public_copies.tsv` lists the sealed hash and the public hash of the three scripts. Some scripts need the competition harness. They document how the labels were made. They do not rebuild the tables on another machine.
3. `verify/` holds a script that recomputes the numbers of the paper from the tables with Python and numpy and the reference values that it is compared with.
4. `scripts/` holds the tools that redacted and audited and restored the traces. The notes in `scripts/` and the reports in `legacy_reports/` are working records kept as written.
5. `provenance/` holds the hashes that tie the tables and the scripts to the build that made them.
6. `figures/` holds the script that draws Figure 1 of the paper and the card image from the tables and the data file of every plotted number.

## Traces

The Kaggle dataset holds 201 redacted traces. They are the 110 development rollouts and the 95 rollouts of decoding seed 1 of the main screen. Four of these 205 rollouts are left out because their trace holds an email address. The 190 rollouts of decoding seeds 2 and 7 have table rows only. In `tables/trace_index.tsv` the status `included_redacted` marks a trace in the dataset and `excluded_email` marks a rollout that was left out for an email address and `not_audited` marks a rollout of seed 2 or 7 that has no trace.

Text that equals a problem statement or a hint or a gold patch or a test patch of the competition is replaced by a placeholder when it has 40 or more characters. For the problem statement and the hints of the trace's own task the limit is 20 characters. Text of the organiser's sample submission files is replaced in the same way. A placeholder carries no character of the text that it replaces. Participants restore a trace with the competition files and the tool `scripts/restore_traces_standalone_v32.py`. 189 of the 201 traces restore byte for byte from public inputs. 12 restore only partly because the machine paths in them stay private.

154 of the 201 traces hold a placeholder of the own gold patch. A reader without the competition files therefore does not see part of the agent's own fix in them. Fragments below the limits and file paths of the upstream repositories remain visible.

The redaction was checked with the audits of the redaction tool (decoded views to a fixpoint and placeholder payloads and the raw view) and with an independent second implementation that included a planted control and with an independent review by a second agent. These checks compare strings. They do not find paraphrase and do not decide rights.

## Limits

The data come from one local model and hardware stack and two repositories and a small fixed task panel. The three main seeds are repeat measurements. Tool categories do not prove useful testing or causal bottlenecks. A second AI reading checked the script labels. No independent human validated them. Gold file overlap is an offline diagnostic and not a lookup that a production agent could use. The full labels cannot be rebuilt from the 201 traces alone.

## Licences

Own code in `scripts/` and `labels/` and `verify/` is licensed under Apache-2.0 (`LICENSE`). Own tables and documents and the compilation of the traces are licensed under CC BY 4.0 (`LICENSE-CC-BY-4.0`). Upstream text inside the traces keeps its own licence. fastapi and rich are MIT. `NOTICE.md` lists the licences and the texts are in the folder `licences/` of the Kaggle dataset. Copyright 2026 Jun Hyung Lee.

## Contact

Open an issue in the issue tracker of the GitHub repository: https://github.com/junicusmaximus/gemma4-31b-rollout-corpus/issues
