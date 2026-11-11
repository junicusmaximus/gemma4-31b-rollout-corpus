# Notice: licences and what is not included

Copyright 2026 Jun Hyung Lee.

Own code (`scripts/`, `labels/` and `verify/`) is licensed under the Apache License 2.0 (`LICENSE`). Own tables and documents and the compilation of redacted traces are licensed under Creative Commons Attribution 4.0 International (`LICENSE-CC-BY-4.0`). Third party material keeps its own licence and attribution and nothing in this folder relicenses it.

## Upstream repositories that appear in traces

Traces contain code and text of the repositories below because the agent read and edited their files. Only repositories with a released trace are listed. The licence texts are in the trace dataset (`licences/`); each is the repository's own licence file copied verbatim from a task snapshot.

| repository | licence | copyright line | source of the licence text |
|---|---|---|---|
| Textualize/rich | MIT | Copyright (c) 2020 Will McGugan | snapshot of task rich_2725, path `./LICENSE`, sha256 deed7c17a4318158190a3ea239cc879a5a50271cebb98ae7025f48fbe58dca15 (the same file in all 36 rich tasks of the release tree) |
| fastapi/fastapi | MIT | Copyright (c) 2018 Sebastián Ramírez | snapshot of task fastapi_11194, path `./LICENSE`, sha256 4ec89ffc81485b97fec584b2d4a961032eeffe834453894fd9c1274906cc744e (the same file in all 56 fastapi tasks of the release tree) |

The other repositories of the competition's task file (psf/requests and encode/httpx) have no released trace and are not listed.

Traces that contain an email address that is not of an example domain are left out of the trace release. Their rows stay in the table.

## Not included

1. the competition's task text (problem statements and hints of all tasks), which is replaced by placeholders (see `scripts/README_v32.md`)
2. gold patches and test patches of all tasks (spans of traces that equal them and are not upstream repository text of the trace's own task are replaced by placeholders)
3. the official graph and embedding data and the traces of any run that used the official graph tools
4. model weights and adapters
5. the organiser's sample submission files. Spans of traces that equal organiser text (mostly the system instruction) are replaced by placeholders. The restore tool needs the organiser's folder

## Machines and accounts

Machine paths and account names in traces are replaced by short placeholders (`P1` and so on). The strings behind them are not published.
