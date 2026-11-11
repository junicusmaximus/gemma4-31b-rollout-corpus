# Recompute the numbers of the paper from the tables

Code and tables: https://github.com/junicusmaximus/gemma4-31b-rollout-corpus | Traces: https://www.kaggle.com/datasets/junicus/gemma4-31b-rollout-corpus | Paper: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/writeups/new-writeup-1794293663311

Python 3 and numpy are required. The script uses the seed analysis module that sits next to it. From the root of the code repository run these commands with fresh output paths:

    python3 -B verify/verify_paper_numbers_r4.py tables verify/tables_phase_b_s7_register.md /tmp/paper2-verify-new
    python3 -B verify/test_paper2_seed_analysis.py /tmp/paper2-seed-fixtures-new
    python3 -B verify/test_verify_paper_numbers_r4.py /tmp/paper2-number-fixtures-new

The register file keeps the identifiers and the order of the number register and omits the private notes of the author. Only the import of the seed module and the explanatory docstring of the verifier differ from the internal file. The formulas are the same. The six table files are the sealed outputs of the table builder.

The reference outputs hold 102 registered quantities that the script computes and 31 that it does not compute from these tables. Those 31 need declared external evidence. The folder `reference/` holds the seed summaries and summaries of the second AI label check with the hashes of their sources. Simulation values are not competition scores. The three tables do not suffice to regenerate every raw label.

The isolated checks passed with the files of this folder: 37 seed fixtures and 39 number fixtures and the three recomputed outputs equal the reference outputs byte for byte (102 computed and 31 not computed).

Own code is licensed under Apache-2.0.
