# Sealed analysis tables and trace linkage

Code and tables: https://github.com/junicusmaximus/gemma4-31b-rollout-corpus | Traces: https://www.kaggle.com/datasets/junicus/gemma4-31b-rollout-corpus | Paper: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/writeups/new-writeup-1794293663311

The six table files `rollouts.tsv` and `calls.tsv` and `tasks.tsv` and their three schema files are final and their bytes do not change. They hold 395 rollout rows (285 main rollouts on 95 tasks in decoding seeds 1, 2 and 7 and 110 development rollouts) and 10,109 call rows and 95 task rows. The call rows hold 9,579 attempted calls in the sense of the paper and 530 free calls (`submit_patch` and `get_status`). Numerical and label fields did not change.

The five trace columns of `rollouts.tsv` are empty so that its sealed hash is kept. Join the companion file `trace_index.tsv` by `rollout_id`. It holds 201 rows `included_redacted` and 4 rows `excluded_email` and 190 rows `not_audited`. The status `not_audited` marks the rollouts of decoding seeds 2 and 7 which have no trace. The `trace_file` paths are relative to the root of the Kaggle dataset. A row that is excluded or has no trace carries no path and no redacted hash. The four excluded rows keep the hash of their source trace only.

The schema files give hashes of the sealed label implementations. See `../provenance/release_provenance.json` and `../verify/README.md`. The recomputation of the numbers differs from a full regeneration of the labels.
