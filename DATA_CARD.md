# Data card: Gemma 4 31B rollout corpus

Code and tables: https://github.com/junicusmaximus/gemma4-31b-rollout-corpus | Traces: https://www.kaggle.com/datasets/junicus/gemma4-31b-rollout-corpus | Paper: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/writeups/new-writeup-1794293663311

## Summary

The corpus describes 395 rollouts of a local Gemma 4 31B developer agent that ran under the competition harness. It has a rollout table and a call table and a task table in this repository and 201 redacted traces in the Kaggle dataset. The paper is "Where the Budget Goes: Labelled Rollouts of a Local Gemma 4 31B Developer Agent".

## Composition

Rollouts: 395 rows. 285 are main rollouts. They are baseline rollouts on the 95 public tasks in decoding seeds 1, 2 and 7 with 95 rows for each seed. 110 are development rollouts. The column `scope` holds main or dev and the column `arm` names the variant of the agent package (`baseline` or `M-CLOSE` or `S1` or `read-bundle`).

Calls: 10,109 rows. Each row is one tool call of a rollout. 530 rows are free status and submission calls that the paper does not count as attempted calls. The other 9,579 rows are attempted calls. The table records whether the harness charged each call and the status of each call and its kind (read or edit or test or graph or free). Failed edits carry labels.

Tasks: 95 rows. 58 are from fastapi and 37 from rich. The table holds the outcome in each decoding seed and the class of the task (solved in every seed or in some seeds or in none).

Traces: 201 redacted ATIF files in 20 sets. They cover 92 tasks (56 fastapi and 36 rich). The 190 rollouts of decoding seeds 2 and 7 and the four rollouts left out for an email address have no trace.

## Labels

The scripts in `labels/` made the labels of the call kinds and the cap classes and the patch classes and the edit failure classes. Columns with the suffix `_stamped` hold the label of the stamped rule or script. The other columns hold the corrected label. The schema files in `tables/` describe every column.

## Redaction of the traces

Text that equals a problem statement or a hint or a gold patch or a test patch of the competition is replaced by a placeholder when it has 40 or more characters. For the problem statement and the hints of the trace's own task the limit is 20 characters. Text of the organiser's sample submission files is replaced in the same way. A placeholder carries no character of the replaced text. Machine paths and account names are replaced by short placeholders and their strings are not published. A trace that holds an email address that is not of an example domain is left out.

Participants restore the traces with the competition files. 189 of the 201 traces restore byte for byte from public inputs. 12 restore only partly because the machine paths stay private. 154 of the 201 traces hold a placeholder of the own gold patch so a reader without the competition files does not see part of the agent's own fix there. Fragments below the limits and file paths of the upstream repositories remain visible.

The redaction was checked with the audits of the redaction tool (decoded views to a fixpoint and placeholder payloads and the raw view) and with an independent second implementation that included a planted control and with an independent review by a second agent. These checks compare strings. They do not find paraphrase and do not decide rights.

## Intended use

The corpus serves the analysis of how a tool using agent spends its call budget and the reproduction of the numbers of the paper. It does not serve the estimate of a score on hidden tests.

## Limitations

The data come from one local model and hardware stack and two repositories and a small fixed task panel. The three main seeds are repeat measurements. Tool categories do not prove useful testing or causal bottlenecks. A second AI reading checked the script labels. No independent human validated them. Gold file overlap is an offline diagnostic and not a lookup that a production agent could use. The full labels cannot be rebuilt from the 201 traces alone.

## Licences

Copyright 2026 Jun Hyung Lee. Own code is licensed under Apache-2.0. Own tables and documents and the compilation of the traces are licensed under CC BY 4.0. Upstream text inside the traces keeps its own licence (MIT for fastapi and rich). `NOTICE.md` lists the licences.

## Contact

Open an issue in the issue tracker of the GitHub repository: https://github.com/junicusmaximus/gemma4-31b-rollout-corpus/issues
