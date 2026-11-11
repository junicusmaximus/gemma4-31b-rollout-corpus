# Figure script and data

Code and tables: https://github.com/junicusmaximus/gemma4-31b-rollout-corpus | Traces: https://www.kaggle.com/datasets/junicus/gemma4-31b-rollout-corpus | Paper: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/writeups/new-writeup-1794293663311

This folder holds the script that draws Figure 1 of the paper and the card image from the tables. The script reads `tables/rollouts.tsv` and `tables/calls.tsv` and checks the totals quoted in the paper before it draws.

## Files

1. `make_figures.py` is the script.
2. `fig1.png` is Figure 1.
3. `fig1_data.csv` lists every plotted number with the columns panel and series and category and count and share.
4. `card.png` and `card_2x.png` are the card image in two sizes.

## Command

Run this from the root of the code repository. The folder OUT_DIR is created if it is missing.

    python3 -B figures/make_figures.py tables OUT_DIR

## Requirement

Python 3 and matplotlib. The shipped files were drawn with Python 3.11.15 and matplotlib 3.9.2. A run with these versions gave a data file and three images that are byte identical to the shipped files. Other matplotlib versions may give an identical data file and images that differ in their bytes.

## Licence

The script is licensed under Apache-2.0 (`../LICENSE`). The images and the data file are licensed under CC BY 4.0 (`../LICENSE-CC-BY-4.0`). Copyright 2026 Jun Hyung Lee.
