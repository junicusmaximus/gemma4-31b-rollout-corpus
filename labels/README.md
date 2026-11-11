# Label scripts

Code and tables: https://github.com/junicusmaximus/gemma4-31b-rollout-corpus | Traces: https://www.kaggle.com/datasets/junicus/gemma4-31b-rollout-corpus | Paper: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/writeups/new-writeup-1794293663311

These scripts made the labels of the tables in their stamped and corrected versions. They document the cap definitions and the patch class definitions.

In this public copy the machine paths of `build_release_tables.py` and `classify_edit_failures.py` and `budget_graph_v083b.py` are replaced by `PROJECT_ROOT`. Nothing else in these three scripts changed. The other scripts here are byte identical to the sealed originals. `../provenance/public_copies.tsv` lists the sealed hash and the public hash of the three changed scripts.

The scripts are not a portable rebuild of the full labels. Some wrappers read input files that are not part of this repository and some need the official competition harness (`adk_eval_core.editing`). The 190 rollouts of decoding seeds 2 and 7 have no trace in the dataset. Obtain the competition resources through authorized channels. No kit is vendored. Use `../verify/` to recompute the numbers from the tables. Own code is licensed under Apache-2.0 (`../LICENSE`).
